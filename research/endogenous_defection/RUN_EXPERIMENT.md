# Run the missing experimental cell and inspect results

The completed live cells already contain 560 accepted responses and 60 completed market rounds. The missing 3-seller/5-buyer communication-off cell stopped on truncated scratchpad generation. The four-request replay passed, but changed request order and did not reproduce the original model sampling state. It establishes that the exact prompt can complete, not a root cause or full-run reliability.

## One command

```powershell
Set-Location G:\collusion_hackathon
& G:\collusion_hackathon\.venv\Scripts\python.exe -X utf8 -m research.endogenous_defection.run_missing_cell --run
```

This starts paid Modal compute. The command performs local preflight, runs the actual missing cell, tears down the ephemeral host, analyzes the sealed result, and writes a comparison against the three completed cells. It does not pause for another diagnostic probe. Without `--run`, it only prints the local plan.

The output path is fresh and printed before startup: `G:\collusion_hackathon\output\missing_cell_<timestamp>_<id>`. It contains `host.log`, the sealed `bundle/`, `analysis/`, `RESULTS.md`, `comparison.csv`, `comparison.json`, and `host_exit.json`. If the model run fails, completed rounds are retained and labelled partial; if hosting fails before the runner starts, inspect `host.log`.

## Explicit v5 execution policy

The new configuration changes only `protocol_version` and `max_action_attempts` from the original 3/5 communication-off v1 cell. The model, 1,200-token ceiling, prompts, temperature, market structure, initial conditions, ten rounds and seeds 10/11 are unchanged. First attempts keep the original sampling settings. Only a truncated response (`finish_reason=length`) or malformed JSON permits one fresh generation from the identical prompt. That second attempt uses the existing agent/round seed formula plus a fixed offset of 104729. Raw rejected and accepted responses and every request count remain visible. No JSON is repaired and no action is inferred from a rejected response.

Other validation failures, provider errors and timeouts stop execution. A second format failure stops execution. Existing protocols default to one attempt and retain their old fail-fast behavior. SDK retries remain disabled.

There are **160 decisions**, at most **320 inference requests**, at most **1,200 output tokens per request**, a **600-second host readiness limit**, and a **7,200-second experiment limit**. These bounds include no dollar guarantee; GPU startup/warmup is billable too. The entire cell is launched once; there is no automatic full-run restart.

The summary explicitly counts rejected responses and scheduled recoveries. This is a versioned recovery protocol, not a proven correction of the model/decoder's underlying repetition. Comparison with the older no-retry cells is descriptive: do not claim a clean causal communication effect across different response-admission policies. No cost shock or intervention is launched, and the undefined 3/5 price index remains not evaluated.

## Existing measurements

`output/experiment_results_current/RESULTS.md` and `comparison.csv` summarize the current saved evidence, including the missing cell's failed status. Mean executed prices are weighted by the recorded transactions; profits and surplus are totals over completed rounds. The new live command creates its own fresh comparison after it finishes.

## Local verification

The original test suite passes with the default one-attempt policy. Additional recovery tests check the two-attempt bound, identical prompts, explicit second-attempt seed, retained raw failures, no retry on provider or semantic errors, request-budget exhaustion, and a recovered action flowing through the real eight-agent market round. No new paid run is established by those local checks.
