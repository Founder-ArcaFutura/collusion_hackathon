"""Offline lifecycle tests against real frozen source prompts; no paid inference."""
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from research.lambda_smoke import message_channel_overnight as overnight
from research.lambda_smoke import message_channel_worker as worker


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("plan") / "run"
    overnight.prepare(root, state_limit=1, seeds=(901,), max_sessions=8)
    return root


@pytest.fixture
def run_root(prepared, tmp_path):
    root = tmp_path / "run"
    shutil.copytree(prepared, root)
    return root


@pytest.fixture
def endpoint(monkeypatch):
    calls = []
    fail = {"at": None, "length_at": None}
    monkeypatch.setattr(worker, "wait_ready", lambda *a: overnight.probe.EXPECTED_SOURCE_RUNTIME)

    def open_request(request, timeout):
        payload = json.loads(request.data)
        calls.append(payload)
        if len(calls) == fail["at"]:
            raise TimeoutError("simulated transport failure")
        action = {"reflection": "mock", "plan_for_this_hour": "mock", "ask": 85,
                  "new_memory": "mock", "plan_for_message": "mock",
                  "message_to_sellers": None, "scratch_pad_update": "mock"}
        finish = "length" if len(calls) == fail["length_at"] else "stop"
        response = {"model": payload["model"], "choices": [{"finish_reason": finish,
                     "message": {"content": json.dumps(action)}}]}
        return io.BytesIO(json.dumps(response).encode())

    monkeypatch.setattr(worker.urllib.request, "urlopen", open_request)
    return calls, fail


def session(root, number):
    path = root / "sessions" / f"session-{number:03d}"
    path.mkdir()
    return path


def test_multi_session_resume_never_repeats_decisions(run_root, endpoint):
    calls, _ = endpoint
    for number in range(1, 5):
        path = session(run_root, number)
        assert overnight.worker(run_root, path, 3, 1200) == 0
        overnight.save(path / "host_exit.json", {"exit_code": 0})
    state = overnight.status(run_root)
    assert state["complete"] and state["accepted_decisions"] == 10
    decisions = [call for call in calls if call["max_tokens"] != 512]
    assert len(decisions) == 10
    assert len({call["messages"][0]["content"] for call in decisions}) == 10
    from research.lambda_smoke.analyze_message_channel import analyze
    overnight.export(run_root, overnight.load(run_root))
    analyze(run_root, run_root / "plan.json", run_root.parent / "analysis")


def test_transport_failure_stops_and_cannot_retry(run_root, endpoint):
    calls, fail = endpoint
    fail["at"] = 4  # warmup, two accepted decisions, failed third decision
    path = session(run_root, 1)
    assert overnight.worker(run_root, path, 10, 1200) == 2
    overnight.save(path / "host_exit.json", {"exit_code": 2})
    state = overnight.status(run_root)
    assert state["accepted_decisions"] == 2 and len(state["blocked_decisions"]) == 1
    with pytest.raises(RuntimeError):
        overnight.batch(run_root)
    assert len(calls) == 4


def test_ambiguous_attempt_blocks_restart(run_root):
    manifest = overnight.load(run_root)
    item = manifest["queue"][0]
    overnight.save(run_root / "attempts" / (item["key"] + ".json"),
                   {**item, "manifest_sha256": manifest["sha256"], "status": "in_flight"})
    with pytest.raises(RuntimeError):
        overnight.batch(run_root)


def test_tampered_manifest_or_response_rejected(run_root, endpoint):
    path = session(run_root, 1)
    assert overnight.worker(run_root, path, 1, 1200) == 0
    (path / "responses/001.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        overnight.status(run_root)
    manifest = overnight.read(run_root / "manifest.json")
    manifest["plan"]["temperature"] = 1
    overnight.save(run_root / "manifest.json", manifest)
    with pytest.raises(ValueError, match="manifest changed"):
        overnight.status(run_root)


def test_batch_uses_attached_host_and_only_returns_after_exit(run_root, endpoint, monkeypatch):
    def host(cmd, cwd):
        assert "poseidon_compute.hosted_model" in cmd and "--detach" not in cmd
        path = Path(cmd[cmd.index("--session") + 1])
        assert not (path / "host_exit.json").exists()
        code = overnight.worker(run_root, path, 2, 1200)
        return SimpleNamespace(returncode=code)
    monkeypatch.setattr(overnight.subprocess, "run", host)
    assert overnight.batch(run_root, 2, 1200) == 0
    assert overnight.status(run_root)["accepted_decisions"] == 2
    assert overnight.status(run_root)["failed_or_active_sessions"] == []


def test_frozen_queue_and_byte_exact_original(run_root):
    manifest = overnight.load(run_root)
    assert len({item["key"] for item in manifest["queue"]}) == 10
    state = manifest["plan"]["states"][0]
    assert state["conditions"]["hidden_original"]["prompt"].encode() == state["prompt"].encode()
    assert manifest["plan"]["maximum_requests"] == 18


def test_os_lock_rejects_overlapping_batch(run_root):
    with overnight.lock(run_root):
        with pytest.raises(OSError):
            with overnight.lock(run_root):
                pass
    with overnight.lock(run_root):
        pass


def test_warmup_uses_minimal_template_and_larger_budget(run_root, endpoint):
    calls, _ = endpoint
    path = session(run_root, 1)
    assert overnight.worker(run_root, path, 1, 1200) == 0
    assert calls[0]["max_tokens"] == 512 and calls[0]["temperature"] == 0
    template = json.loads(calls[0]["messages"][0]["content"].split(": ", 1)[1])
    assert template["message_to_sellers"] is None and template["ask"] == 85


def test_truncated_warmup_reports_phase_without_decision_attempt(run_root, endpoint):
    _, fail = endpoint
    fail["length_at"] = 1
    path = session(run_root, 1)
    assert overnight.worker(run_root, path, 1, 1200) == 2
    failure = overnight.read(path / "worker_failure.json")
    assert failure["phase"] == "schema_warmup" and failure["finish_reason"] == "length"
    assert not list((run_root / "attempts").iterdir())


def test_recover_only_proven_predecision_failure(run_root, tmp_path):
    path = session(run_root, 1)
    (path / "requests").mkdir()
    (path / "responses").mkdir()
    overnight.save(path / "requests/000.json", {"max_tokens": 128})
    overnight.save(path / "responses/000.json", {"choices": [{"finish_reason": "length"}]})
    overnight.save(path / "host_exit.json", {"exit_code": 2})
    overnight.export(run_root, overnight.load(run_root))
    destination = tmp_path / "recovered"
    recovered = overnight.recover_warmup_only(run_root, destination)
    assert recovered["sessions_remaining"] == 7 and recovered["maximum_requests"] == 17
    assert overnight.load(destination)["queue"] == overnight.load(run_root)["queue"]
    item = overnight.load(run_root)["queue"][0]
    overnight.save(run_root / "attempts" / (item["key"] + ".json"), {"status": "in_flight"})
    overnight.export(run_root, overnight.load(run_root))
    with pytest.raises(ValueError, match="before any experimental"):
        overnight.recover_warmup_only(run_root, tmp_path / "disallowed")
