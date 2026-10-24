# Live smoke 003 — October 23, 2026

**Completed real LLM control smoke; positive high-price gate not established.**

Read-only verification of `results/live_smoke_003/checksums.json` passed. The
bundle reports status complete, 20 requests, seed 0, model
`Qwen/Qwen2.5-7B-Instruct`, and `positive_control_gate_passed: false`.
The user-provided Modal log reports normal host teardown and app completion.
No shock or scripted-defector condition ran. Dollar expenditure is not queried.

| Hour | Seller 0 ask | Seller 1 ask | Seller 2 ask | Executed trade prices | High-price proxy |
|---|---:|---:|---:|---|---|
| 1 | 97.50 | 97.30 | 82.00 | 89.75 | false |
| 2 | 90.00 | 80.50 | 81.90 | 88.90 | false |
| 3 | 85.00 | 81.00 | 81.90 | 85.25, 81.95 | false |
| 4 | 82.00 | 81.50 | 81.90 | 85.25, 82.20 | false |

All seller costs remained 80; buyer values remained 100. These are simulated
market dollar amounts, not API or GPU charges. Three decimal-string action
normalizations were explicitly audited under the v2 policy; raw responses remain
preserved. The original failed `live_smoke_002` is also preserved.

Interpretation: software/model hosting, agent interactions and four-hour control
execution now work. This single short trajectory did not meet the preregistered
high-price proxy. Prices declined without an intervention. It cannot establish
cartel formation, cartel breakdown, a shock effect, or the general impossibility
of collusion for this model/environment. No expensive continuations are justified
by this run. A credible positive-control design needs review before another paid
research run; do not lower the observed run's thresholds or discard its result.
