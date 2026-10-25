# Message-content × public-quote decision probe

This is a bounded decision-level probe over saved seller prompts from the frozen
partial-visibility, communication-on markets (seeds 20–23). It selects at most
ten cases with an exact, supported seller self-ask report, a matching standing
quote hidden from both direct displays, and no duplicate of that price elsewhere
in the recipient prompt. Selection is deterministic and the full prompt variants
are frozen in `plan.json` before any inference.

The current sealed evidence yields ten eligible recipient states from seeds 20
and 23, representing four unique outgoing messages. This is 200 target decisions
plus one warmup (201 total). The selector rejects cases where the same sender's
true or fabricated ±$10 ask is already asserted elsewhere in the prompt. Several
recipients share a source message, so the ten decisions are not ten independent
messages or markets.

The factors are public quote visibility (`hidden`, `restored`) and message
condition (`original`, `redacted`, `up10`, `down10`, `absent`). The restored
condition adds only the true quote to the current/historical display locations
where it existed in the saved true observation. No quote is invented or changed
in the auction engine. All other prompt content remains fixed. Each state gets
two matched sampling seeds, for at most 200 target decisions. One seller-schema
warmup request makes the maximum total 201 requests. There are no retries.

The probe uses Qwen2.5-7B-Instruct through vLLM 0.6.6 / Outlines 0.1.11 /
XGrammar 0.1.13, one sequence at a time. Provider, GPU model, driver, image and
dependency metadata are recorded with results. The worker supports both the
existing Lambda loopback server and the repository's `poseidon-host` Modal
endpoint. The archived paired-current-quote live probe was launched via
`poseidon-host` on Modal; the repository's Lambda smoke and market-pilot exports
are separate Lambda evidence. Keep provider/GPU labels explicit and do not pool
decision outputs with market-level outcomes or claim identical execution
stacks.

## Local preparation and offline checks

Run from PowerShell at the repo root. These stages read sealed evidence and make
no GPU or inference calls.

```powershell
Set-Location G:\collusion_hackathon

# Select and freeze eligible states; writes a new output directory.
& .\.venv\Scripts\python.exe -X utf8 -m research.lambda_smoke.message_channel_probe `
  --stage plan --out output\message_channel_probe_v1_approved4

# Re-verify source seals, the original prompt, each factorial transformation,
# and the 200-decision ceiling against the current source evidence.
& .\.venv\Scripts\python.exe -X utf8 -m research.lambda_smoke.message_channel_probe `
  --stage validate --out output\message_channel_probe_v1_approved4

# Deterministic mock/schema plumbing only; no model behavior evidence.
& .\.venv\Scripts\python.exe -X utf8 -m research.lambda_smoke.message_channel_probe `
  --stage mock --out output\message_channel_probe_v1_approved4

# Package the validated frozen plan and self-contained Lambda worker.
& .\.venv\Scripts\python.exe -X utf8 -m research.lambda_smoke.message_channel_probe `
  --stage package --plan output\message_channel_probe_v1_approved4\plan.json `
  --out output\lambda_message_probe_v1_approved4
```

`plan` deliberately stops if the target output path already exists. Keep each
generated plan and archive; do not overwrite a prior plan or result directory.
If fewer than ten clean states meet the criteria, the decision count falls to
`eligible states × 20` and the plan reports the smaller number.

## Launch on Modal (recommended for this probe)

This uses the existing `poseidon-host` wrapper to start an ephemeral Modal A10G
vLLM endpoint, run the worker locally against it, and tear the endpoint down
when the worker exits. It avoids building/transferring the Lambda archive. The
worker keeps all prompt/response artifacts in the local output directory. The
run is still bounded at 201 requests and has no retries.

First validate the frozen plan locally. Then pick a new output path for every
run; the worker refuses to overwrite one. Example PowerShell command:

```powershell
Set-Location G:\collusion_hackathon
$Python = (Resolve-Path '.venv\Scripts\python.exe').Path
$Out = 'output\modal_message_probe_20261024_001'

& $Python -X utf8 -m research.lambda_smoke.message_channel_probe `
  --stage validate --out output\message_channel_probe_v1_approved4
if ($LASTEXITCODE -ne 0) { throw 'Frozen plan validation failed; no model was started.' }

& $Python -X utf8 -c 'from poseidon_compute.hosted_model import main; main()' `
  --model Qwen/Qwen2.5-7B-Instruct --gpu A10G `
  --ready-timeout 900 --run-timeout 14400 -- `
  $Python -X utf8 -m research.lambda_smoke.message_channel_worker `
  --plan output\message_channel_probe_v1_approved4\plan.json --out $Out
if ($LASTEXITCODE -ne 0) { throw "Modal probe failed or stopped; inspect $Out and the host logs." }
```

`--run-timeout 14400` is a four-hour cap for the worker after the model is ready;
the Modal readiness cap is 15 minutes. The worker itself has a four-hour wall
clock cap. `poseidon-host` supplies the authenticated endpoint and serving
runtime metadata to the worker. The wrapper tears down the ephemeral Modal app
after the command finishes or fails. Keep the console output as the host log.

Modal's current A10 rate is **US$0.000306 per GPU-second** (about **US$1.10 per
GPU-hour**), so four hours of GPU allocation is about **US$4.41**, with up to
another **US$0.28** if startup uses the full 15-minute readiness allowance.
Container CPU and memory are metered separately, so this is a GPU-only estimate,
not a total bill. Modal currently lists $30/month in included Starter compute credits;
check your workspace usage page to confirm what your stated $69 balance
represents. The probe calls a self-hosted model endpoint, so it does not incur a
separate per-token model-provider charge. [Modal pricing](https://modal.com/pricing)
and [GPU requirements](https://modal.com/docs/guide/gpu).

After completion, review `$Out\summary.json`, `decisions.csv`, `runtime.json`,
`requests\`, `responses\`, and `checksums.json`; verify checksums before
analysis. Keep the Modal-labelled output separate from Lambda results.

## Transfer and launch on the existing Lambda A10

The package command prints the archive path. Replace the example SSH key, IP,
and archive path with the values for the already-running instance. This does
not provision or terminate a VM.

```powershell
$Archive = (Resolve-Path 'output\lambda_message_probe_v1_approved4.tar.gz').Path
scp -i 'C:\path\lambda-key.pem' $Archive ubuntu@INSTANCE_IP:~/
ssh -i 'C:\path\lambda-key.pem' ubuntu@INSTANCE_IP
```

On the instance, substitute the archive's actual basename:

```bash
tar -xzf lambda_message_probe_v1_approved4.tar.gz
cd lambda_message_probe_v1_approved4
bash run_message_channel.sh
```

The runner pins the served model and guided-decoding versions, limits the worker
to four hours, caps inference at 201 requests (200 decisions plus one warmup),
and disables retries. A timeout/transport failure retains partial evidence and
stops. The four-hour worker timeout covers model readiness and inference;
Docker build and final VM termination time are additional billed time.

## Retrieve and review evidence

The launch prints a remote path ending in `results/<UTC-run-id>/probe`. After
the worker exits, copy that directory back from a second local PowerShell
window. Replace the run ID and destination with the printed values:

```powershell
scp -r -i 'C:\path\lambda-key.pem' `
  'ubuntu@INSTANCE_IP:~/lambda_message_probe_v1_approved4/results/UTC-RUN-ID/probe' `
  'G:\collusion_hackathon\output\lambda_message_probe_results_v1'
```

`server.log` is included in the probe directory. Review `summary.json`,
`decisions.csv`, `runtime.json`, `requests/`, `responses/`, and `checksums.json`.
Verify the checksums before analysis. Keep original source seals and the provider-
labelled Lambda output separate from the Modal market results. The decision-level
probe cannot establish that messages mediated the earlier market-level liquidity
interaction.

Run the local descriptive analysis after retrieving the evidence. Use a fresh
output path:

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m research.lambda_smoke.analyze_message_channel `
  output\lambda_message_probe_results_v1\probe `
  --plan output\message_channel_probe_v1_approved4\plan.json `
  --out output\message_channel_probe_analysis_v1
```

## Request and cost bound

At ten eligible states: 200 planned decision requests plus one warmup, each
limited to 1,200 completion tokens (warmup 128). At fewer than ten states, the
decision ceiling scales down by 20 per excluded state. Invalid generations are
recorded and not retried.

The current Lambda public price table lists a single A10 at **US$1.29/GPU-hour**
before applicable sales taxes. At the four-hour worker cap, that is about
**US$5.16**, plus the Docker build and final termination time; if capped
generation takes two hours, GPU time would be about US$2.58 plus that overhead.
Lambda bills while the instance is running, including idle time. Check the
account's current price/availability before starting, keep the live run bounded,
and terminate the instance after evidence retrieval. This estimate is not a
guaranteed bill or an authorization to launch.
