"""Local-only regression checks: no Modal app.run(), account lookup or image build."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_serve(monkeypatch, hf_secret=None):
    calls = []
    image_calls = []

    class Image:
        @classmethod
        def debian_slim(cls, **kwargs):
            return cls()

        def pip_install(self, *args):
            image_calls.append(("pip_install", args))
            return self

        def add_local_python_source(self, *args):
            image_calls.append(("add_local_python_source", args))
            return self

        def env(self, *args):
            image_calls.append(("env", args))
            return self

    class Secret:
        @staticmethod
        def from_dict(values):
            calls.append(("inline", values))
            return values

        @staticmethod
        def from_name(name, **kwargs):
            calls.append(("named", name, kwargs))
            return name

    fake = SimpleNamespace(Image=Image, Secret=Secret,
        App=lambda *args: SimpleNamespace(function=lambda **kwargs: lambda f: f),
        web_server=lambda **kwargs: lambda f: f)
    monkeypatch.setitem(__import__("sys").modules, "modal", fake)
    monkeypatch.delenv("MODAL_SERVE_API_KEY", raising=False)
    monkeypatch.delenv("MODAL_HF_SECRET", raising=False)
    if hf_secret:
        monkeypatch.setenv("MODAL_HF_SECRET", hf_secret)
    path = Path(__file__).resolve().parents[1] / "poseidon_compute/modal_serve.py"
    spec = importlib.util.spec_from_file_location("modal_serve_local_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, calls, image_calls


def test_public_model_has_no_named_secret_dependency(monkeypatch):
    module, calls, image_calls = load_serve(monkeypatch)
    assert len(calls) == 1 and calls[0][0] == "inline"
    assert len(module.ENDPOINT_API_KEY) >= 32
    assert calls[0][1]["MODAL_SERVE_API_KEY"] == module.ENDPOINT_API_KEY
    pip_args = next(value for name, value in image_calls if name == "pip_install")
    assert "vllm==0.6.6" in pip_args
    assert "xgrammar==0.1.13" in pip_args
    assert "outlines==0.1.11" in pip_args
    assert ("add_local_python_source", ("poseidon_compute",)) in image_calls
    assert image_calls[-1][0] == "add_local_python_source"


def test_hf_secret_opt_in_checks_expected_variable(monkeypatch):
    _, calls, _ = load_serve(monkeypatch, "huggingface")
    assert ("named", "huggingface", {"required_keys": ["HF_TOKEN"]}) in calls
    assert all(c[1] != "modal-serve" for c in calls if c[0] == "named")


def test_server_caps_context_and_surfaces_engine_failure(monkeypatch):
    monkeypatch.delenv("MODAL_MAX_MODEL_LEN", raising=False)
    monkeypatch.delenv("MODAL_MAX_NUM_SEQS", raising=False)
    module, _, _ = load_serve(monkeypatch)
    seen = []
    monkeypatch.setattr(
        module,
        "collect_serving_runtime",
        lambda: {
            "vllm": "0.6.6.post1",
            "xgrammar": "0.1.13",
            "outlines": "0.1.11",
            "guided_decoding_backend": "outlines",
            "required_api": "vllm guided_json via outlines backend",
            "required_api_available": True,
        },
    )

    def start(cmd, **kwargs):
        seen.append((cmd, kwargs))
        return SimpleNamespace(poll=lambda: 1, stdout=io.StringIO())

    monkeypatch.setattr(module.subprocess, "Popen", start)
    with pytest.raises(RuntimeError, match="vLLM exited during startup"):
        module.serve()
    cmd, options = seen[0]
    assert cmd[cmd.index("--max-model-len") + 1] == "8192"
    assert cmd[cmd.index("--max-num-seqs") + 1] == "1"
    assert options["stdout"] == module.subprocess.PIPE
    assert options["stderr"] == module.subprocess.STDOUT
    assert options["text"] is True
    assert cmd[cmd.index("--guided-decoding-backend") + 1] == "outlines"
    assert cmd[cmd.index("--middleware") + 1] == (
        "poseidon_compute.runtime_metadata.runtime_metadata_middleware"
    )


def test_runtime_preflight_failure_fails_before_server_process(monkeypatch):
    module, _, _ = load_serve(monkeypatch)
    started = []
    monkeypatch.setattr(
        module,
        "collect_serving_runtime",
        lambda: (_ for _ in ()).throw(RuntimeError("required Outlines package missing")),
    )
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: started.append(a))
    with pytest.raises(RuntimeError, match="required Outlines package missing"):
        module.serve()
    assert started == []


def test_vllm_log_relay_redacts_generated_api_key(monkeypatch, capsys):
    module, _, _ = load_serve(monkeypatch)
    key = "generated-local-bearer-secret"
    module._relay_redacted_logs(
        io.StringIO(f"vLLM api key: {key}\nstartup complete\n"), key
    )
    output = capsys.readouterr().out
    assert key not in output
    assert "[REDACTED]" in output
    assert "startup complete" in output


def test_serving_runtime_versions_and_backend_are_strictly_validated(monkeypatch):
    from poseidon_compute.runtime_metadata import (
        collect_serving_runtime,
        validate_serving_runtime,
    )

    versions = {"vllm": "0.6.6.post1", "xgrammar": "0.1.13", "outlines": "0.1.11"}
    runtime = collect_serving_runtime(
        package_version=lambda name: versions[name],
    )
    assert runtime["guided_decoding_backend"] == "outlines"
    assert runtime["xgrammar"] == "0.1.13"
    assert runtime["outlines"] == "0.1.11"
    assert validate_serving_runtime(runtime) == runtime
    with pytest.raises(RuntimeError, match="not running Outlines"):
        validate_serving_runtime({**runtime, "outlines": "0.1.12"})
    with pytest.raises(RuntimeError, match="backend is not outlines"):
        validate_serving_runtime({**runtime, "guided_decoding_backend": "xgrammar"})
    with pytest.raises(RuntimeError, match="Expected Outlines"):
        collect_serving_runtime(package_version=lambda name: {**versions, "outlines": "0.1.12"}[name])
    from research.endogenous_defection.io import serving_runtime_metadata

    metadata = {**runtime, "actual_runtime_marker": "recorded"}
    monkeypatch.setenv("MODAL_SERVING_RUNTIME", json.dumps(metadata))
    assert serving_runtime_metadata() == metadata


def test_readiness_requires_and_returns_actual_serving_runtime(monkeypatch):
    import importlib

    from poseidon_compute.runtime_metadata import RUNTIME_HEADER

    host = importlib.import_module("poseidon_compute.hosted_model")
    runtime = {
        "vllm": "0.6.6.post1",
        "xgrammar": "0.1.13",
        "outlines": "0.1.11",
        "guided_decoding_backend": "outlines",
        "required_api": "vllm guided_json via outlines backend",
        "required_api_available": True,
    }

    class Response:
        status = 200
        headers = {RUNTIME_HEADER: json.dumps(runtime)}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(host.urllib.request, "urlopen", lambda *a, **k: Response())
    assert host._wait_ready("https://example.invalid", "key", 1) == runtime

    Response.headers = {}
    with pytest.raises(RuntimeError, match="did not report serving dependency"):
        host._wait_ready("https://example.invalid", "key", 1)


def test_readiness_failure_restores_client_environment(monkeypatch):
    import poseidon_compute
    from poseidon_compute import hosted_model as host_context
    import importlib

    host = importlib.import_module("poseidon_compute.hosted_model")
    key = "local-test-only-bearer"
    fake_serve = SimpleNamespace(MODEL="test-model", ENDPOINT_API_KEY=key,
        app=SimpleNamespace(run=contextlib.nullcontext),
        serve=SimpleNamespace(get_web_url=lambda: "https://example.invalid"))
    monkeypatch.setattr(poseidon_compute, "modal_serve", fake_serve, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "modal", SimpleNamespace(enable_output=contextlib.nullcontext))
    monkeypatch.setattr(host, "_check_hf_access", lambda model: None)
    monkeypatch.setenv("LLM_API_KEY", "previous-local-value")
    monkeypatch.setenv("MODAL_SERVING_RUNTIME", "previous-runtime")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    def fail(url, bearer, timeout):
        assert bearer == key and os.environ["LLM_API_KEY"] == key
        raise TimeoutError("simulated startup failure")

    monkeypatch.setattr(host, "_wait_ready", fail)
    with pytest.raises(TimeoutError):
        with host_context(model="test-model"):
            pytest.fail("Readiness failed; body must not execute")
    assert os.environ["LLM_API_KEY"] == "previous-local-value"
    assert os.environ["MODAL_SERVING_RUNTIME"] == "previous-runtime"
    assert "LLM_BASE_URL" not in os.environ and "LLM_MODEL" not in os.environ
