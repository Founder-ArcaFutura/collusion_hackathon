#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
test "$(uname -m)" = x86_64 || { echo 'This bundle requires an x86_64 GPU instance.'; exit 1; }
nvidia-smi
docker build -t collusion-lambda-message-channel .
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
RESULTS="$PWD/results/$RUN_ID"
mkdir -p "$RESULTS"
NAME="collusion-message-channel-$RUN_ID"
cleanup() {
  mkdir -p "$RESULTS/probe"
  docker logs "$NAME" > "$RESULTS/probe/server.log" 2>&1 || true
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  python3 -c 'import hashlib,json,pathlib,sys; root=pathlib.Path(sys.argv[1]); files=sorted(p for p in root.rglob("*") if p.is_file() and p.name!="checksums.json"); (root/"checksums.json").write_text(json.dumps({str(p.relative_to(root)).replace(chr(92),"/"):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},indent=2,sort_keys=True)+chr(10),encoding="utf-8")' "$RESULTS/probe"
}
trap cleanup EXIT INT TERM
docker run -d --name "$NAME" --gpus 'device=0' --shm-size=2g \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  -v "$RESULTS:/results" collusion-lambda-message-channel \
  python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct --served-model-name Qwen/Qwen2.5-7B-Instruct \
  --host 127.0.0.1 --port 8000 --max-model-len 8192 --max-num-seqs 1 \
  --guided-decoding-backend outlines --middleware runtime_metadata.runtime_metadata_middleware
set +e
docker exec "$NAME" timeout --signal=INT --kill-after=30s 14400 \
  python message_channel_worker.py --plan /app/plan.json --out "/results/probe"
WORKER_CODE=$?
set -e
echo "WORKER_EXIT $WORKER_CODE"
echo "EVIDENCE $RESULTS/probe"
echo 'Container removed on exit. Terminate the Lambda VM separately to stop instance billing.'
exit "$WORKER_CODE"
