# Modal overnight replication

Run from `G:\collusion_hackathon`. Preparation and status are offline:

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m research.lambda_smoke.message_channel_overnight `
  --stage plan --out output\message_channel_modal_v2 --state-limit 40 --max-sessions 8

& .\.venv\Scripts\python.exe -X utf8 -m research.lambda_smoke.message_channel_overnight `
  --stage status --out output\message_channel_modal_v2
```

Review the generated `plan.json` before running. The selector requests up to 40
distinct recipient decision states across the existing eligible saved states; it may
find fewer. It never invents states or relaxes the existing eligibility checks.
Repeated sender/recipient pairs at distinct rounds or markets are allowed; they
remain correlated observations. The default two sampling seeds produce `states × 20` decisions; the maximum
request count is that number plus eight schema warmups. Each new session may
require a fresh warmup, which consumes inference time. GPU startup, CPU, memory,
and all session execution also incur provider charges. These are request/time
limits, not a guaranteed dollar cap.

The schema warmup uses a frozen minimal JSON template, temperature zero, and a
512-token ceiling. Warmup failures report their phase, finish reason, and token
usage when available; HTTP 200 alone does not establish a complete response.

For the known initial 128-token warmup truncation, a verified pre-decision
recovery is available. It requires preserved checksums, a completed failed host,
exactly one truncated warmup request, and zero decision attempts. It leaves the
old directory intact, preserves the treatment queue and controller deadline,
and subtracts the spent session from the new budget:

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m research.lambda_smoke.message_channel_overnight `
  --stage recover-warmup --from-run output\message_channel_modal_v2 `
  --out output\message_channel_modal_v2_warmup_fix
```

Use the recovered directory as `-Out` for subsequent batch/controller commands.

Validate a small live batch first (this command starts paid Modal compute):

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m research.lambda_smoke.message_channel_overnight `
  --stage batch --out output\message_channel_modal_v2 --max-decisions 2 --max-session-seconds 1200
```

Then start the controller. The smoke batch counts against the same eight-session
budget; accepted decisions will not be repeated:

```powershell
.\research\lambda_smoke\run_message_channel_overnight.ps1 `
  -Out output\message_channel_modal_v2 -Hours 8 -KeepAwake
```

The controller uses the existing authenticated ephemeral Modal host and pinned
Qwen2.5-7B/vLLM/Outlines stack on A10G. Sessions run attached and synchronously.
After the host exits, the controller pauses locally for 30 seconds, then starts
the next batch. Default batch limits are 100 decisions or 5,400 seconds after
readiness. It reserves 600 seconds for readiness and 60 seconds for cleanup when
checking the deadline. Infrastructure delays or teardown can exceed those
reserves; this is not a guaranteed wall-clock cancellation service. The existing
host interrupts a worker exceeding its timeout and exits its ephemeral app.

`-KeepAwake` temporarily requests Windows system wakefulness for this process;
it restores ordinary behavior on exit, without changing the saved power plan.
It cannot prevent updates, restarts, power loss, or network outages.

The first controller deadline is persisted in `controller.json`; rerunning the
same command resumes the same deadline and remaining session budget. Normal
completed batches resume automatically. Source or manifest changes fail before
compute starts. All prompt variants and the counterbalanced queue are frozen
before execution. Original/hidden prompts remain byte exact. Source snapshots,
runtime metadata, requests, raw responses, response hashes, and decision rows
remain local throughout execution. `decisions.csv` and `checksums.json` can be
used with `analyze_message_channel`; keep analysis output outside the run folder.

An attempt marker is flushed **before** HTTP dispatch, and accepted results are
atomically saved immediately after validation. A crash between these steps is
ambiguous: the remote request may have completed. The controller therefore
stops on an unresolved marker, rejected response, failed host, or interrupted
session instead of retrying. Inspect preserved session evidence before any
manual recovery; never delete an attempt marker simply to make it run again.
The OS lock prevents overlapping batch controllers on the same directory and
releases on process death. It does not promise exactly-once remote HTTP delivery.

This is a separate decision-level replication, not a new market simulation.
Report independent source markets and messages separately from sampling draws.
Use recorded provider labels for earlier evidence: the current v1 README records
its archived 200-decision probe as Modal-hosted, while Lambda pilot bundles are
separate. No provider-equivalence experiment is required or performed here.

Modal lifecycle reference: https://modal.com/docs/guide/apps
