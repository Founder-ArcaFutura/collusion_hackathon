# Exploratory market-structure and communication comparison

**Sprint execution path:** use [Run the missing cell and inspect results](RUN_EXPERIMENT.md). The v5 protocol permits one logged regeneration only for truncated/malformed output, with a 320-request worst-case ceiling for 160 decisions. It runs the actual ten-round/two-seed cell and automatically produces analysis and a descriptive comparison. The prior no-retry cells and every failed attempt remain preserved.

**Latest communication-off attempt:** v4 also failed on Seller Theo's seventh request, with scratchpad repetition through 2,048 tokens and zero completed rounds. Do not repeat the full-cell commands below as a repair. Use the [four-request failed-prompt diagnostic](REPLAY_DIAGNOSTIC.md) to capture the exact seller/buyer prompts with and without guided decoding before choosing a versioned follow-up. The three completed cells passed the offline audit at `output/troubleshooting_20261024/README.md`; the 3/5 communication-off cell remains missing.

This is an exploratory 2x2 comparison, not a replication or a robust test of cartel persistence. Every cell uses Qwen2.5-7B-Instruct, seeds 10 and 11, ten rounds, the existing guided JSON response protocol, temperature 0.7, 1,200 maximum generated tokens, and unchanged initial-order ranges and decision thresholds.

| Sellers / buyers | Seller communication | Configuration or evidence | Calls |
| --- | --- | --- | ---: |
| 5 / 5 | On | Reuse `results/baseline_A_v2_full_001` | 200 already completed |
| 5 / 5 | Off | `configs/factorial_5x5_comms_off_v1.json` | 200 |
| 3 / 5 | On | `configs/factorial_3x5_comms_on_v1.json` | 160 |
| 3 / 5 | Off | `configs/factorial_3x5_comms_off_v1.json` | 160 |

The new inference total is 520 calls; all four cells represent 720 calls including the completed 5/5 communication-on bundle. The completed positive-control bundle is preserved as-is, including its recorded gate result. It is reused as a measurement, not rerun or relabeled.

Communication-off sets the upstream seller communication parameter to false. Seller prompts omit received-message instructions and message-planning/output fields, the guided seller schema excludes message fields, the runner drops prior seller-message maps even if a malformed prior round contains one, and the auction stores no seller messages. Buyer communication remains off in all four cells.

The 3/5 configurations set `initialization_seller_slots` to five: the initializer draws the two unused seller asks before generating buyer bids. This preserves the existing RNG sequence for 5/5 and matches the first three seller ask values and all five buyer bid values by role/index across market sizes. The 5/5 ON/OFF cells also have identical identities and initial orders. Agent names and company identities are not fully matched across 5/5 and 3/5 because the upstream identity sampler draws a different population size; the randomly selected target seller index also depends on seller count. Those identity differences are retained rather than rewriting upstream identity behavior.

With three sellers and five buyers at costs $80 and values $100, the existing competitive midpoint and joint-profit-maximizing price coincide at $100, leaving a zero reference-price gap. Price-index and positive-control gate results are therefore reported as not evaluable for 3/5. Direct metrics remain available: mean/median asks, ask markups over seller costs, mean/median executed prices and seller markups, trade count, buyer surplus, seller profit, total welfare, and per-buyer/per-seller profit or surplus. The 5/5 gate formula and archived values are unchanged.

The completed 5/5 ON run took about 39 minutes for 200 requests including Modal startup and shutdown. Linear scaling at that observed rate gives about 31 minutes per 160-request cell, or roughly 102 minutes for the three new hosted runs. This is a planning estimate; request length and serving variance can change it. Each command below retains a two-hour host timeout and an explicit request ceiling.

## Bounded-text retry for the failed 3/5 communication-off cell

The original `factorial_3x5_comms_off_v1` bundle remains preserved as a failed technical attempt: seed 10, round 1, call 7 (Seller Theo), `finish_reason="length"`, 1,200 completion tokens, zero completed rounds. Its saved partial response has a coherent reflection, plan, ask, and memory, followed by a runaway scratchpad repeating the same escaped `\\(\\)` fragment until JSON truncation. This is not a market outcome and is not evidence about either communication treatment.

The separate v2 retry, `factorial_3x5_comms_off_v2_bounded_text`, failed technically before completing a round. Its first buyer request did not return within the configured 90-second client timeout (`APITimeoutError`); no response body was received. The Modal server trace was not available, so the evidence cannot distinguish slow guided-schema compilation from slow generation. The v2 schema bounded six prose fields, including the scratchpad at 1,200 characters.

The v3 retry used just one schema length bound (1,000 characters on `scratch_pad_update`) but failed in the same way: its first buyer request timed out at 90 seconds, with no response or completed round. Together with the v2 timeout, this makes bounded strings the common changed schema feature and the likely trigger, though the missing Modal-side trace prevents proving causality.

`factorial_3x5_comms_off_v4_guided_2048.json` removes `maxLength` from guided generation and reuses the known v1 role schema, which previously served live responses. It keeps the 2,048-token ceiling and all scientific settings. The existing strict application validator still rejects scratchpads longer than 250 words, without altering a model response. Both v2 and v3 failed bundles remain preserved and contain no market outcomes. The v4 first request must be checked on the live backend before interpreting any trajectory.

  The v4 retry plans 160 calls. Using the observed rate for the earlier 160-call cell gives an approximate 31-minute hosted runtime; actual time may vary. Use a new results directory. The preflight is local and starts no Modal container.

```powershell
& .\.venv\Scripts\python.exe -m research.endogenous_defection.run_experiment --config research/endogenous_defection/configs/factorial_3x5_comms_off_v4_guided_2048.json --stage preflight --backend live --model Qwen/Qwen2.5-7B-Instruct --max-calls 160 --out research/endogenous_defection/results/factorial_3x5_comms_off_v4_guided_2048
if ($LASTEXITCODE -ne 0) { throw "3/5 communication-off v4 local preflight failed; no Modal process started." }
& .\.venv\Scripts\poseidon-host.exe --model Qwen/Qwen2.5-7B-Instruct --gpu A10G --ready-timeout 900 --run-timeout 7200 -- .\.venv\Scripts\python.exe -m research.endogenous_defection.run_experiment --config research/endogenous_defection/configs/factorial_3x5_comms_off_v4_guided_2048.json --stage control --backend live --model Qwen/Qwen2.5-7B-Instruct --max-calls 160 --out research/endogenous_defection/results/factorial_3x5_comms_off_v4_guided_2048
if ($LASTEXITCODE -ne 0) { throw "3/5 communication-off v4 host run failed." }
```

## PowerShell launch commands

Run only when ready. These commands do not include the already completed 5/5 ON cell. Each creates a new sealed result bundle; do not reuse an existing output path.

```powershell
& .\.venv\Scripts\python.exe -m research.endogenous_defection.run_experiment --config research/endogenous_defection/configs/factorial_5x5_comms_off_v1.json --stage preflight --backend live --model Qwen/Qwen2.5-7B-Instruct --max-calls 200 --out research/endogenous_defection/results/factorial_5x5_comms_off_v1
if ($LASTEXITCODE -ne 0) { throw "5/5 communication-off local preflight failed; no Modal process started." }
& .\.venv\Scripts\poseidon-host.exe --model Qwen/Qwen2.5-7B-Instruct --gpu A10G --ready-timeout 900 --run-timeout 7200 -- .\.venv\Scripts\python.exe -m research.endogenous_defection.run_experiment --config research/endogenous_defection/configs/factorial_5x5_comms_off_v1.json --stage control --backend live --model Qwen/Qwen2.5-7B-Instruct --max-calls 200 --out research/endogenous_defection/results/factorial_5x5_comms_off_v1
if ($LASTEXITCODE -ne 0) { throw "5/5 communication-off host run failed." }
& .\.venv\Scripts\python.exe -m research.endogenous_defection.run_experiment --config research/endogenous_defection/configs/factorial_3x5_comms_on_v1.json --stage preflight --backend live --model Qwen/Qwen2.5-7B-Instruct --max-calls 160 --out research/endogenous_defection/results/factorial_3x5_comms_on_v1
if ($LASTEXITCODE -ne 0) { throw "3/5 communication-on local preflight failed; no Modal process started." }
& .\.venv\Scripts\poseidon-host.exe --model Qwen/Qwen2.5-7B-Instruct --gpu A10G --ready-timeout 900 --run-timeout 7200 -- .\.venv\Scripts\python.exe -m research.endogenous_defection.run_experiment --config research/endogenous_defection/configs/factorial_3x5_comms_on_v1.json --stage control --backend live --model Qwen/Qwen2.5-7B-Instruct --max-calls 160 --out research/endogenous_defection/results/factorial_3x5_comms_on_v1
if ($LASTEXITCODE -ne 0) { throw "3/5 communication-on host run failed." }
& .\.venv\Scripts\python.exe -m research.endogenous_defection.run_experiment --config research/endogenous_defection/configs/factorial_3x5_comms_off_v1.json --stage preflight --backend live --model Qwen/Qwen2.5-7B-Instruct --max-calls 160 --out research/endogenous_defection/results/factorial_3x5_comms_off_v1
if ($LASTEXITCODE -ne 0) { throw "3/5 communication-off local preflight failed; no Modal process started." }
& .\.venv\Scripts\poseidon-host.exe --model Qwen/Qwen2.5-7B-Instruct --gpu A10G --ready-timeout 900 --run-timeout 7200 -- .\.venv\Scripts\python.exe -m research.endogenous_defection.run_experiment --config research/endogenous_defection/configs/factorial_3x5_comms_off_v1.json --stage control --backend live --model Qwen/Qwen2.5-7B-Instruct --max-calls 160 --out research/endogenous_defection/results/factorial_3x5_comms_off_v1
if ($LASTEXITCODE -ne 0) { throw "3/5 communication-off host run failed." }
```

Run the existing analyzer once per bundle, with a distinct fresh output directory. For the completed baseline and new results, for example:

```powershell
# This baseline analysis has already been generated at analysis_outputs/factorial_5x5_comms_on.
& .\.venv\Scripts\python.exe -m research.endogenous_defection.analyze research/endogenous_defection/results/factorial_5x5_comms_off_v1 --out research/endogenous_defection/analysis_outputs/factorial_5x5_comms_off
& .\.venv\Scripts\python.exe -m research.endogenous_defection.analyze research/endogenous_defection/results/factorial_3x5_comms_on_v1 --out research/endogenous_defection/analysis_outputs/factorial_3x5_comms_on
& .\.venv\Scripts\python.exe -m research.endogenous_defection.analyze research/endogenous_defection/results/factorial_3x5_comms_off_v1 --out research/endogenous_defection/analysis_outputs/factorial_3x5_comms_off
```
