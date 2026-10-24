# Lambda infrastructure smoke

Uses an existing x86_64 Linux NVIDIA GPU instance with at least 24 GB VRAM, Docker and NVIDIA Container Toolkit configured. This script does not provision or terminate the VM. Lambda connection instructions: https://docs.lambda.ai/public-cloud/on-demand/connecting-instance/

The exported bundle includes copies of the existing runtime checks and action schemas, with hashes. It contains no credentials, results or private configuration. It uses the same pinned serving packages, model, context size and single-sequence limit as Modal. The Docker base and transitive dependencies are not an exact image clone. A different GPU can change numerical outputs.

From Windows, create the bundle:

```powershell
& G:\collusion_hackathon\.venv\Scripts\python.exe -X utf8 G:\collusion_hackathon\research\lambda_smoke\prepare.py
```

Copy the printed archive to your existing instance (replace the example paths and IP):

```powershell
scp -i C:\path\lambda-key.pem G:\collusion_hackathon\output\lambda_smoke_TIMESTAMP_ID.tar.gz ubuntu@INSTANCE_IP:~/
ssh -i C:\path\lambda-key.pem ubuntu@INSTANCE_IP
```

On the instance:

```bash
tar -xzf lambda_smoke_TIMESTAMP_ID.tar.gz
cd lambda_smoke_TIMESTAMP_ID
bash run.sh
```

This builds a separate image, starts a GPU container with no published port, waits at most 15 minutes for readiness, and sends at most two completion requests without retries. The requests exercise seller communication ON and buyer communication OFF schemas; they are simple fixtures, not full auction prompts or market decisions. Responses, requests, runtime versions and server logs remain under `results/`. The container is removed when the script exits. Interrupting a Docker build may leave build cache; a forced process kill can bypass cleanup. Terminate the VM through Lambda when finished to stop instance billing.

Success establishes serving and JSON contract compatibility only. Before launching any study on Lambda, run a separate end-to-end market smoke, record GPU/driver/image provenance, verify budgets and keep provider-labelled evidence separate from Modal controls. The existing distortion command still targets Modal; this bundle does not change that command or remove its guard.
