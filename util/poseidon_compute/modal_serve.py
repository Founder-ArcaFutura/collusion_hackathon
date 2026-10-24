"""vLLM model server on Modal — an OpenAI-compatible endpoint for experiments Nebius can't serve.

You don't run this directly. `poseidon_compute.hosted_model` runs it ephemerally around an experiment (boots a
model, wires the endpoint into `llm_config`, tears it down):

    poseidon-host --model Qwen/Qwen2.5-7B-Instruct --gpu A10G -- <your experiment command>

SETUP (one-time): `pip install modal && modal setup` (browser auth). Gated models (e.g. Llama) need a
secret named `huggingface` containing HF_TOKEN and local MODAL_HF_SECRET=huggingface.
Public Qwen weights do not require it. No named modal-serve secret is needed.
Pick a GPU that fits the model: A10G (24GB)
~ up to 8B · A100-40GB ~ up to 32B · H100 for 70B (pass `--gpu` to hosted_model).

Advanced: `modal deploy poseidon_compute.modal_serve` gives a persistent shared endpoint; most teams won't need
it (the ephemeral hosted_model flow is simpler and leaves nothing running). Scaffolding ahead of live
credits — validate once your Modal account is funded.
"""
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import json

import modal
from poseidon_compute.runtime_metadata import (
    GUIDED_DECODING_BACKEND,
    OUTLINES_VERSION,
    XGRAMMAR_VERSION,
    collect_serving_runtime,
)

# ---- config (override via env at deploy time) ----------------------------------------------------
MODEL = os.environ.get("MODAL_SERVE_MODEL", "Qwen/Qwen2.5-7B-Instruct")  # open by default (no HF gate)
GPU = os.environ.get("MODAL_SERVE_GPU", "A10G")
VLLM_PORT = 8000
MAX_MODEL_LEN = int(os.environ.get("MODAL_MAX_MODEL_LEN", "8192"))
MAX_NUM_SEQS = int(os.environ.get("MODAL_MAX_NUM_SEQS", "1"))
if MAX_MODEL_LEN <= 0 or MAX_NUM_SEQS <= 0:
    raise ValueError("Modal context and sequence limits must be positive")

app = modal.App("hackathon-serve")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "vllm==0.6.6",
        f"xgrammar=={XGRAMMAR_VERSION}",
        f"outlines=={OUTLINES_VERSION}",
        "huggingface_hub[hf_transfer]==0.26.2",
    )
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1", "MODAL_MAX_MODEL_LEN": str(MAX_MODEL_LEN),
          "MODAL_MAX_NUM_SEQS": str(MAX_NUM_SEQS),
          "MODAL_GUIDED_DECODING_BACKEND": GUIDED_DECODING_BACKEND})
    # Modal requires local source mounts to be the final image layer unless
    # copied into the image. Keep this last so app startup does not fail before
    # the web server (and without provisioning a GPU).
    .add_local_python_source("poseidon_compute")
)

# Named handles are lazy: from_name() does not check existence until app.run().
# Use a per-process bearer secret directly, so no named 'modal-serve' is required.
# The client uses this same value via hosted_model; never print it.
ENDPOINT_API_KEY = os.environ.get("MODAL_SERVE_API_KEY") or secrets.token_urlsafe(32)
_secrets = [modal.Secret.from_dict({"MODAL_SERVE_API_KEY": ENDPOINT_API_KEY})]
# Public Qwen weights need no HF credential. Explicitly opt in for gated models:
# MODAL_HF_SECRET=huggingface, whose variable must be HF_TOKEN (not 'huggingface').
if hf_secret := os.environ.get("MODAL_HF_SECRET"):
    _secrets.insert(0, modal.Secret.from_name(hf_secret, required_keys=["HF_TOKEN"]))


def _relay_redacted_logs(pipe, secret):
    """Forward child output while removing the generated endpoint bearer key."""
    try:
        for line in iter(pipe.readline, ""):
            safe_line = line.replace(secret, "[REDACTED]") if secret else line
            sys.stdout.write(safe_line)
            sys.stdout.flush()
    finally:
        pipe.close()


@app.function(
    image=image,
    gpu=GPU,
    timeout=24 * 3600,
    scaledown_window=300,            # spin down after 5 min idle to save credits
    secrets=_secrets,
    max_containers=1,               # smoke test: prevent parallel GPU startups
)
# (for higher throughput on one GPU, add `@modal.concurrent(max_inputs=N)` above web_server)
@modal.web_server(port=VLLM_PORT, startup_timeout=900)
def serve():
    """Launch vLLM's OpenAI-compatible server; Modal proxies it to a public URL."""
    # Run before starting vLLM's listener so a resolver/API mismatch cannot accept
    # any live inference requests.
    runtime = collect_serving_runtime()
    print("SERVING_RUNTIME " + json.dumps(runtime, sort_keys=True), flush=True)
    cmd = [
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--model", MODEL,
        "--host", "0.0.0.0",
        "--port", str(VLLM_PORT),
        "--served-model-name", MODEL,
        "--max-model-len", str(MAX_MODEL_LEN),
        "--max-num-seqs", str(MAX_NUM_SEQS),
        "--guided-decoding-backend", GUIDED_DECODING_BACKEND,
        "--middleware", "poseidon_compute.runtime_metadata.runtime_metadata_middleware",
    ]
    api_key = os.environ.get("MODAL_SERVE_API_KEY")
    if api_key:
        cmd += ["--api-key", api_key]   # clients must send this as their key
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    # vLLM echoes its --api-key argument during startup. Relay its combined
    # output through a secret filter so Modal research logs never contain it.
    threading.Thread(
        target=_relay_redacted_logs,
        args=(process.stdout, api_key),
        name="vllm-redacted-log-relay",
        daemon=True,
    ).start()
    # Surface a dead engine promptly rather than keep the outer readiness loop
    # polling a dead child until its 15-minute timeout. Never log argv (bearer).
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(f"vLLM exited during startup (exit code {exit_code}); inspect engine logs")
        try:
            with socket.create_connection(("127.0.0.1", VLLM_PORT), timeout=1):
                return
        except OSError:
            time.sleep(1)
    process.terminate()
    raise TimeoutError("vLLM did not open its server port within 900 seconds")
