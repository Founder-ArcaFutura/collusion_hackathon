# Live smoke 002 — October 23, 2026

**Real hosted LLM inference; failed/partial control. Not synthetic.**

Read-only inspection of `results/live_smoke_002` confirmed:

- Model requested and returned: `Qwen/Qwen2.5-7B-Instruct`, hosted on Modal.
- Stage: control only, seed 0; three $80-cost sellers, two $100-value buyers.
- Budget: maximum 20 requests, maximum 800 output tokens each.
- Actual requests: **7**, all returning HTTP success and `finish_reason=stop`.
- Completed hours: one; the second hour failed before all actions were collected.
- Qualification: no completed positive-control gate; no treatments/continuations.
- Modal log reports local entrypoint completion and app shutdown.
- GPU/account dollar expenditure: **not queried; not assumed zero**.

Request 7, Buyer 1 in hour 2, returned its action as `"bid": "81.00"`.
The original parser required a JSON numeric action and correctly stopped under
its declared strict policy. This was neither model truncation nor a GPU/cache
failure. The raw output, prompts, usage, manifest, source snapshot and checksums
remain in the original failed bundle. No action or trajectory was repaired there.

The bundle records its parent Git SHA and dirty source state. Runtime context
limit 8,192 and single-sequence settings were confirmed in the user-provided host
log. That startup succeeded; earlier failed-startup logs should not be read as
evidence that this later app failed to initialize.

For a new attempt, `configs/live_smoke_v2.json` explicitly enables conversion of
an exact decimal string into the same numeric amount. Conversions are audited,
with original raw response preserved. Currency text, extra precision, scientific
notation, NaN, ambiguous values and explanations still fail. There are no retries
and no inferred actions. The original pilot and v1 smoke stay strict by default.
Use a new bundle directory and fresh warmup. No paid retry has been started by
the coding agent, and this parser change establishes no collusion finding.
