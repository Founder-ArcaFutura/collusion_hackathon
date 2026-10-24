#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
test "$(uname -m)" = x86_64 || { echo 'This smoke requires an x86_64 GPU instance.'; exit 1; }
nvidia-smi
docker build -t collusion-lambda-smoke .
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
RESULTS="$PWD/results/$RUN_ID"
mkdir -p "$RESULTS"
NAME="collusion-smoke-$RUN_ID"
cleanup() {
  docker logs "$NAME" > "$RESULTS/server.log" 2>&1 || true
  docker rm -f "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM
# No public listener: client executes inside this container against loopback.
docker run -d --name "$NAME" --gpus 'device=0' --shm-size=2g \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  -v "$RESULTS:/results" collusion-lambda-smoke \
  python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct --served-model-name Qwen/Qwen2.5-7B-Instruct \
  --host 127.0.0.1 --port 8000 --max-model-len 8192 --max-num-seqs 1 \
  --guided-decoding-backend outlines --middleware runtime_metadata.runtime_metadata_middleware
docker exec "$NAME" python smoke.py --out /results
echo "Smoke passed. Evidence: $RESULTS"
echo 'Container removed on exit. The Lambda VM must be terminated separately to stop VM billing.'
