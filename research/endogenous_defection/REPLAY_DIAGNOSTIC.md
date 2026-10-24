# Four-request failed-prompt diagnostic

Run this from PowerShell:

```powershell
Set-Location G:\collusion_hackathon
& .\research\endogenous_defection\run_replay_diagnostic.ps1
```

This command starts paid Modal compute. It checks the saved bundle locally first, then starts one ephemeral A10G host using the existing Qwen model and serving runtime. It makes **at most four inference requests**, each with a 2,048-completion-token ceiling and a 90-second client timeout. SDK retries are disabled. The host has a 600-second readiness limit and a 480-second experiment limit, then follows the existing teardown path. Startup/warmup charges are additional to inference; this is a request/token/time bound, not a dollar guarantee.

It does not launch a full market experiment or change its configuration.

The launcher explicitly enables Python UTF-8 for planning, hosting and replay, including redirected output captured by PowerShell. This fixes the Windows `cp1252` failure when Modal/Rich prints a checkmark. The host CLI is imported directly to avoid the duplicate-module `runpy` warning. These changes affect logging/entry-point invocation only; the four-case plan and scientific source bundle are unchanged. The failed startup at `output/replay_diagnostic_20261024_084506_8054915c` contains no probe summary and made no diagnostic requests.

## Fixed diagnostic design

The source is the preserved `results/factorial_3x5_comms_off_v4_guided_2048` bundle. Its checksum seal and the current request/schema implementation against the sealed snapshot are verified before any Modal startup. Before inference, the actual serving package versions and decoding backend must also match the source runtime. The replay extracts the exact Seller Theo prompt from the failed seventh request, plus the successful Buyer Ana prompt from the first request in the same seed and round. Whitespace is preserved, and each prompt's SHA-256 is recorded.

| Order | Prompt | Guided JSON |
| ---: | --- | --- |
| 1 | Original failing seller prompt | On, original role schema |
| 2 | Original successful buyer prompt | On, original role schema |
| 3 | Same seller prompt | Off |
| 4 | Same buyer prompt | Off |

The model remains `Qwen/Qwen2.5-7B-Instruct`, temperature 0.7, maximum output 2,048 tokens. As in the source run, no sampling seed is sent. Turning guidance off is the sole request-parameter contrast for each prompt pair; the prompt still asks for the original JSON format. Application response validation remains strict in every case.

All four cases are attempted even if an earlier response is rejected. These are fixed diagnostic cases, not retries until success. No ask or bid is applied, and no market round or collusion gate is evaluated. A one-sample contrast can suggest the next investigation; stochastic output and fixed execution order prevent a definitive causal conclusion.

## Where the evidence goes

The script prints a fresh directory such as:

```text
G:\collusion_hackathon\output\replay_diagnostic_<timestamp>_<unique-id>\
    preflight.json
    host.log
    probe\
        plan.json
        source_protocol.json
        provenance.json
        replay_diagnostic.py
        01_seller_guided_request.json
        02_buyer_guided_request.json
        03_seller_unguided_request.json
        04_buyer_unguided_request.json
        events.jsonl
        case_results.jsonl
        diagnostic_summary.json
        checksums.json
```

`host.log` captures the streamed Modal startup/server/client/teardown output. The existing host redacts its bearer key. Each request body is recorded without credentials. `events.jsonl` retains raw responses, finish reasons, usage and safe provider error metadata. The summary adds elapsed time and validation outcomes per case. The probe directory is sealed; `host.log` remains outside that seal so final shutdown logs can still be appended. If startup fails, the host log and local preflight remain available even though no probe summary exists.

Exit code **0** means all four diagnostic responses passed validation. Exit code **2** means at least one case was rejected or had a transport failure; this is a useful recorded diagnostic result and is not permission to restart a full experiment. Other nonzero codes indicate startup, preflight, interruption or execution failure; **124** is the host experiment timeout. The console prints the summary and log paths. Preserve the entire output directory.

## Reading the result

- Seller repetition with guidance on but a coherent response with guidance off suggests investigating the decoder/model interaction. It does not establish that the decoder alone caused the original failure.
- Repetition in both seller cases suggests the problem is not limited to guided decoding.
- Buyer failures as well as seller failures suggest a broader serving/output issue.
- All four passing means the original failure was not reproduced. It does not demonstrate that a 160-request cell is reliable.
- A timeout is distinct from a truncated response. Inspect the server log around that case before choosing another change.

Do not repair or accept truncated JSON, change the model silently, or combine these diagnostic calls with market results. Any subsequent serving or prompt change needs a versioned and tested follow-up before a full-cell retry.

## Optional local-only preview

This prints the full replay plan, including exact prompts, and starts no GPU or inference:

```powershell
& .\.venv\Scripts\python.exe -m research.endogenous_defection.replay_diagnostic --stage plan --out output/replay_preview_unused/probe
```

The output path must not already exist; planning does not create it.

Implementation validation: exact source-bundle local preflight and PowerShell syntax parsing passed. Offline regression tests cover exact prompt reuse, request-parameter contrasts, the four-call limit, continuation through truncation/timeouts, safe error recording, model-identity rejection, checksum verification and blocking changed source evidence or existing output. No live replay was launched while implementing this diagnostic.
