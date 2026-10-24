"""Bring a Modal-hosted model UP for the duration of an experiment, then tear it DOWN.

This wraps the manual "deploy a model, paste its URL into compute.env, remember to stop it" flow into
one lifecycle. It runs `modal_serve` as an **ephemeral** Modal app (`app.run()`), points
`llm_config` at the temporary endpoint, waits until the model is ready, runs your experiment, and
stops the app on exit — so you never leave a GPU (and credits) running.

Use when an experiment can't use Nebius inference and you want a model on Modal just for this run.

----------------------------------------------------------------------------------------------------
CLI — wrap any command:
    poseidon-host --model Qwen/Qwen2.5-7B-Instruct --gpu A10G -- \
        bash -c "cd llm-trust-breaking && python experiments/run_endogenous.py --game diners ..."

In your own Python:
    from poseidon_compute import hosted_model
    with hosted_model(model="Qwen/Qwen2.5-7B-Instruct"):
        ...  # llm_config now points at the Modal endpoint; run your code
    # endpoint is torn down here

Prereqs: `pip install modal` + `modal setup` (browser auth). Gated models need a HF token secret.
Scaffolding ahead of live credits — validate once your Modal account is funded.
"""
import os
import sys
import time
import json
import argparse
import contextlib
import signal
import subprocess
import urllib.request
import urllib.error
import pathlib

from .runtime_metadata import RUNTIME_HEADER, validate_serving_runtime


class ModelAccessError(RuntimeError):
    """Raised when a model can't be hosted because we don't have access to it on Hugging Face
    (gated repo without an approved token). Carries a human-readable, actionable message."""


def _hf_token():
    """Best-effort local HF token: env first, then the CLI-cached token."""
    for var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        v = os.environ.get(var)
        if v:
            return v.strip()
    try:
        return (pathlib.Path.home() / ".cache" / "huggingface" / "token").read_text().strip() or None
    except Exception:
        return None


def _check_hf_access(model):
    """Preflight: confirm we can actually download this model from Hugging Face before spending time
    (and credits) booting Modal. Gated repos without an approved token fail here with a clear pointer
    to the model's access page — instead of a mysterious vLLM cold-start timeout later.

    Checks with the LOCAL token; the actual download on Modal uses the `huggingface` Modal secret, so if
    your local account differs from that secret this is only a best-effort hint (it never blocks on a
    network hiccup — only on a definitive 401/403).
    """
    token = _hf_token()
    url = f"https://huggingface.co/{model}/resolve/main/config.json"
    req = urllib.request.Request(url, method="HEAD")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20):
            return  # 200 -> readable, we have access
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ModelAccessError(
                f"'{model}' is GATED on Hugging Face and your token doesn't have access, so it can't be "
                f"hosted on Modal. To fix:\n"
                f"  1. Request access (sign in, click 'Agree and access'):\n"
                f"        https://huggingface.co/{model}\n"
                f"  2. Create an HF access token:\n"
                f"        https://huggingface.co/settings/tokens\n"
                f"  3. Give that token to Modal so the server can download the weights:\n"
                f"        modal secret create huggingface HF_TOKEN=hf_xxx\n"
                f"     (and export HF_TOKEN=hf_xxx locally so this check passes too).\n"
                f"Not substituting another model."
            ) from None
        return  # 404/5xx etc. — not an access problem; let the Modal boot surface the real error
    except Exception:
        return  # network hiccup — don't block; the Modal boot will surface real errors


def _wait_ready(url, api_key, timeout):
    """Poll the endpoint until vLLM has loaded the model (first hit triggers the cold start)."""
    deadline = time.time() + timeout
    req = urllib.request.Request(url.rstrip("/") + "/v1/models")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    raw_runtime = r.headers.get(RUNTIME_HEADER)
                    if not raw_runtime:
                        raise RuntimeError(
                            "Modal endpoint is ready but did not report serving dependency versions"
                        )
                    try:
                        runtime = json.loads(raw_runtime)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(
                            "Modal endpoint returned invalid serving dependency metadata"
                        ) from exc
                    return validate_serving_runtime(runtime)
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001 - cold start returns connection errors / 503s
            last = e
        time.sleep(5)
    raise TimeoutError(
        f"Modal model endpoint not ready after {timeout}s (last: {last}). If this is a GATED model, "
        f"make sure the Modal `huggingface` secret holds a token WITH access "
        f"(modal secret create huggingface HF_TOKEN=hf_xxx) and that you've accepted the model's "
        f"license on its Hugging Face page."
    )


@contextlib.contextmanager
def hosted_model(model=None, gpu=None, api_key=None, ready_timeout=900):
    """Context manager: ephemeral Modal model up -> llm_config pointed at it -> torn down on exit."""
    # modal_serve reads these at import, so set them before importing it.
    if model:
        os.environ["MODAL_SERVE_MODEL"] = model
    if gpu:
        os.environ["MODAL_SERVE_GPU"] = gpu
    if api_key:
        os.environ["MODAL_SERVE_API_KEY"] = api_key

    import modal
    from . import modal_serve

    served_model = os.environ.get("MODAL_SERVE_MODEL", modal_serve.MODEL)
    # Fail fast with an actionable message if the model is gated and we lack access, before booting Modal.
    _check_hf_access(served_model)
    saved = {
        k: os.environ.get(k)
        for k in (
            "LLM_BASE_URL",
            "LLM_API_KEY",
            "LLM_MODEL",
            "MODAL_SERVING_RUNTIME",
        )
    }
    with modal.enable_output(), modal_serve.app.run():
        url = modal_serve.serve.get_web_url()
        os.environ["LLM_BASE_URL"] = url.rstrip("/") + "/v1"
        os.environ["LLM_API_KEY"] = modal_serve.ENDPOINT_API_KEY
        os.environ["LLM_MODEL"] = served_model
        print(f"[hosted_model] up: {os.environ['LLM_BASE_URL']}  (model {served_model}) — warming up...", flush=True)
        try:
            runtime = _wait_ready(url, modal_serve.ENDPOINT_API_KEY, ready_timeout)
            os.environ["MODAL_SERVING_RUNTIME"] = json.dumps(
                runtime, sort_keys=True, separators=(",", ":")
            )
            print(
                "[hosted_model] ready; serving runtime "
                + json.dumps(runtime, sort_keys=True),
                flush=True,
            )
            yield url
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            print("[hosted_model] torn down.", flush=True)  # app.run() exit stops the ephemeral app


def main():
    ap = argparse.ArgumentParser(description="Run a command with a Modal-hosted model up for its duration.")
    ap.add_argument("--model", default=None, help="model id to serve (default: modal_serve.py's default)")
    ap.add_argument("--gpu", default=None, help="Modal GPU, e.g. A10G / A100-40GB / H100")
    ap.add_argument("--api-key", default=None, help="bearer key to require on the endpoint (optional)")
    ap.add_argument("--ready-timeout", type=int, default=900)
    ap.add_argument(
        "--run-timeout",
        type=int,
        default=7200,
        help="maximum seconds for the wrapped command after model readiness (default: 7200)",
    )
    ap.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="the experiment command, after `--` (e.g. -- bash -c '...')")
    args = ap.parse_args()
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        ap.error("provide a command after `--`, e.g.  -- bash -c 'cd proj && python ...'")
    if args.ready_timeout <= 0 or args.run_timeout <= 0:
        ap.error("--ready-timeout and --run-timeout must be positive")
    try:
        with hosted_model(model=args.model, gpu=args.gpu, api_key=args.api_key, ready_timeout=args.ready_timeout):
            process = subprocess.Popen(
                cmd,
                env=os.environ,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            try:
                rc = process.wait(timeout=args.run_timeout)
            except subprocess.TimeoutExpired:
                # Give the experiment a chance to run its failure/finally path and
                # seal its partial evidence bundle before forcing it to exit.
                interrupt = (
                    signal.CTRL_BREAK_EVENT
                    if os.name == "nt"
                    else signal.SIGINT
                )
                process.send_signal(interrupt)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise
    except subprocess.TimeoutExpired:
        print(
            f"[poseidon-host] wrapped command exceeded {args.run_timeout}s; stopped it and the Modal app",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(124)
    sys.exit(rc)


if __name__ == "__main__":
    main()
