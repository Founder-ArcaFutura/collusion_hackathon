# Completed run, review scripts and the next factorial

The missing 3/5 communication-off run completed all 20 rounds with 160 accepted decisions, 162 total requests and two retained format recoveries. Its host exited with code 0. The sealed bundle was checksum-verified and an independent offline review is at:

`G:\collusion_hackathon\output\missing_cell_20261024_091424_3ce6ae12\review_verified_v1\RESULTS.md`

The new cell's executed-price means were 83.17 and 82.42 for seeds 10 and 11, with 17 and 18 trades. No bid above the buyer's value was recorded in either new trajectory. The three older cells remain descriptive references because their recovery/sampling policies differ. The 3/5 normalized gate remains not evaluated.

## Reusable review command — no inference

```powershell
Set-Location G:\collusion_hackathon
& G:\collusion_hackathon\.venv\Scripts\python.exe -X utf8 -m research.endogenous_defection.review_run G:\collusion_hackathon\output\missing_cell_20261024_091424_3ce6ae12 --wait-seconds 1800
```

This waits for a sealed bundle if needed, refuses to analyze a live/partial write, verifies its checksums and creates a fresh review directory. The review includes the existing round-level analysis and plot, a comparison against the three earlier cells, recorded rejection counts, bid-value checks and a surplus-accounting check. It does not change the source bundle or overwrite an earlier review.

## Next run — two fresh seeds across all four cells

The next executable study crosses full/partial seller quote visibility with communication ON/OFF, using the same 5-seller/5-buyer market, ten rounds, Qwen model, 1,200-token ceiling, two-attempt recovery policy and request sampling seed rule in every cell. Seeds 20 and 21 provide eight markets total. Cell order reverses in the second seed block. The historical seeds are excluded.

Preview the plan locally:

```powershell
& G:\collusion_hackathon\.venv\Scripts\python.exe -X utf8 -m research.endogenous_defection.information_study --stage plan --seeds 20 21
```

Run it on Modal:

```powershell
& G:\collusion_hackathon\.venv\Scripts\python.exe -X utf8 -m research.endogenous_defection.information_study --stage run --seeds 20 21
```

The live command starts paid compute: **800 decisions, at most 1,600 requests**, on one ephemeral A10G host. The host experiment limit is four hours, readiness limit ten minutes; startup and shutdown add overhead. At the observed earlier baseline's rate this is a multi-hour batch, not a short diagnostic. The time limit can stop an incomplete batch; request/token/time ceilings are not a dollar guarantee. Do not run concurrently with another hosted experiment. There is no automatic batch restart, and execution stops on a cell's technical failure, retaining failed/unattempted cells in the report. A failed collusion gate does not exclude a completed market.

The command prints a fresh `output/information_study_<timestamp>_<id>` directory. It creates sealed per-cell bundles and automatically writes:

- `analysis/RESULTS.md`: each market's completion status, trades and executed price.
- `analysis/market_outcomes.csv`: market-level price, liquidity, profits, surplus, welfare and failure counts.
- `analysis/paired_contrasts.csv`: ON minus OFF for each visibility condition and their interaction, by seed.
- `analysis/observation_checks.csv`: available/hidden rival quote counts, including history.
- `analysis/messages_for_coding.csv`: messages with UNREVIEWED mechanism labels for manual coding.
- `host.log`, `host_exit.json`, `study_plan.json`, `study_status.json`, and executable-source hashes.

Unattempted cells have missing outcomes, not invented zero outcomes. Zero-trade completed markets have undefined mean trade prices. With two seed blocks the analysis makes no significance or equivalence claim. All uncertainty is at market/block level; individual trades are not treated as independent replication.

## Observation contract

For partial visibility, each observer/quote-owner/quote-origin-round/market-seed combination has a deterministic 50% omission draw. A quote's visibility does not change as it moves from current book to displayed history. Own quotes remain visible. The mask is independent of quote price, display order and communication content. ON and OFF use the same mask rule, while realized book contents can diverge through behaviour.

Only seller observations change. Buyers' inputs, true order queues, trade matching and realized trade history are preserved. The same disclosure text appears in every study seller prompt: missing quotes are unobserved, not withdrawals. Current and historical rival quotes are filtered; previously learned memories are not erased, and received messages may legitimately relay hidden facts. Past trades can still permit inference; the study does not claim to eliminate all inference about quotes. True and rendered observations are saved separately in each bundle's `observations.jsonl`. Observation metadata is never passed as an extra model input.

The new observation and study modules were implemented after the prior run completed. Default market behavior remains full information; the earlier bundle and running-code snapshot are preserved. The old review-only configurations remain disabled as design records; the new explicit `--stage run` command creates the actual frozen per-cell configurations and records them.

## Offline analysis rerun

To regenerate study analysis into a new directory, use the real study directory printed by the runner:

```powershell
& G:\collusion_hackathon\.venv\Scripts\python.exe -X utf8 -m research.endogenous_defection.study_analysis G:\collusion_hackathon\output\information_study_TIMESTAMP_ID --out G:\collusion_hackathon\output\information_analysis_NEW_ID
```

Both names above are placeholders. The output directory must be new. The analyzer verifies every attempted cell's seal and refuses running/unsealed cells.

For offline plumbing validation only, replace `--stage run` with `--stage run --backend synthetic` in the study command. Synthetic outcomes are programmed fixtures, explicitly labelled, and provide no evidence about information effects or LLM behaviour.
