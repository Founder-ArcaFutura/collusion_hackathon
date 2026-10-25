"""Resource-capped ephemeral host for the separate v3 source acquisition."""
import argparse
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time

import modal
from . import modal_serve as original
from .hosted_model import _wait_ready
from .runtime_metadata import collect_serving_runtime

RESOURCE_SPEC = {"gpu": "A10G", "gpu_count": 1, "cpu_request": 2, "cpu_limit": 4,
                 "memory_request_mib": 16384, "memory_limit_mib": 32768,
                 "worker_seconds": 4000, "ready_seconds": 600,
                 "container_watchdog_seconds": 4660, "scaledown_seconds": 30}
app = modal.App("message-source-v3")


def watchdog(process, seconds):
    """Also bound the remote process when the workstation disconnects."""
    time.sleep(seconds)
    process.kill()
    os._exit(124)


@app.function(image=original.image, gpu=RESOURCE_SPEC["gpu"],
              cpu=(RESOURCE_SPEC["cpu_request"], RESOURCE_SPEC["cpu_limit"]),
              memory=(RESOURCE_SPEC["memory_request_mib"], RESOURCE_SPEC["memory_limit_mib"]),
              timeout=RESOURCE_SPEC["container_watchdog_seconds"],
              scaledown_window=RESOURCE_SPEC["scaledown_seconds"],
              max_containers=1, secrets=original._secrets)
@modal.web_server(port=8000, startup_timeout=600)
def serve():
    runtime = collect_serving_runtime()
    print("SERVING_RUNTIME " + json.dumps(runtime, sort_keys=True), flush=True)
    command = ["python", "-m", "vllm.entrypoints.openai.api_server", "--model", original.MODEL,
               "--host", "0.0.0.0", "--port", "8000", "--served-model-name", original.MODEL,
               "--max-model-len", str(original.MAX_MODEL_LEN), "--max-num-seqs", "1",
               "--guided-decoding-backend", "outlines", "--middleware",
               "poseidon_compute.runtime_metadata.runtime_metadata_middleware"]
    key = os.environ.get("MODAL_SERVE_API_KEY")
    if key:
        command += ["--api-key", key]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)
    threading.Thread(target=original._relay_redacted_logs, args=(process.stdout, key), daemon=True).start()
    threading.Thread(target=watchdog, args=(process, RESOURCE_SPEC["container_watchdog_seconds"]), daemon=True).start()
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("vLLM exited before readiness; inspect redacted server logs")
        try:
            with socket.create_connection(("127.0.0.1", 8000), timeout=1):
                return
        except OSError:
            time.sleep(1)
    process.terminate()
    raise TimeoutError("vLLM startup exceeded 600 seconds")


@contextlib.contextmanager
def hosted():
    names = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "MODAL_SERVING_RUNTIME")
    saved = {name: os.environ.get(name) for name in names}
    try:
        with modal.enable_output(), app.run():
            url = serve.get_web_url()
            os.environ["LLM_BASE_URL"] = url.rstrip("/") + "/v1"
            os.environ["LLM_API_KEY"] = original.ENDPOINT_API_KEY
            os.environ["LLM_MODEL"] = original.MODEL
            runtime = _wait_ready(url, original.ENDPOINT_API_KEY, 600)
            os.environ["MODAL_SERVING_RUNTIME"] = json.dumps(runtime, sort_keys=True)
            print("RESOURCE_CAPPED_HOST_READY " + json.dumps(RESOURCE_SPEC), flush=True)
            yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        print("Resource-capped Modal host exited.", flush=True)


def run_command(command):
    with hosted():
        process = subprocess.Popen(command, env=os.environ,
                                   creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        try:
            return process.wait(timeout=RESOURCE_SPEC["worker_seconds"])
        except BaseException:
            if process.poll() is None:
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
                    process.wait(timeout=30)
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait()
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Provide the worker command after --")
    raise SystemExit(run_command(command))
