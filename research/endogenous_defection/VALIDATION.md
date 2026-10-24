# Local validation — October 23, 2026

Historical offline validation record. A subsequent user-launched live attempt
successfully hosted the model and made seven requests, then failed strict action
validation. See [LIVE_ATTEMPT_002.md](LIVE_ATTEMPT_002.md). Initial offline checks
below must not be confused with that later paid host attempt.

**Synthetic execution and software checks only. No live LLM results.**
No provider inference or Modal compute was launched: **0 requests, $0 API/compute
expenditure attributable to this work**. The $75 value is a simulated seller cost
($80 minus a $5 treatment), not expenditure. No account-wide spend or available
credit balance has been queried or inferred.

Working branch: `experiment/endogenous-cartel-defection`. Parent HEAD:
`d585a7b3be50366cc2bdf5789bf8add5890b2abd`. Research additions are currently
uncommitted and unpushed. Each bundle records that dirty state and snapshots the
actual source files with hashes, so the parent SHA is not misrepresented as the
commit containing this implementation.

## Completed checks

- **25 tests passed** against the actual upstream `LMSeller`, `LMBuyer`, prompt,
  memory and clearing stack, with synthetic or explicitly mocked inference.
- Ruff lint, format check and `git diff --check` passed.
- CLI planning confirmed the first live control has a maximum of **20 requests**:
  seed 0, three sellers, two buyers, four hours, maximum 800 output tokens per call.
  The live-smoke config contains only unchanged costs and no shock conditions.
- A two-seed synthetic pilot completed with eight continuation branches and
  generated sealed evidence, per-seed analysis tables and a labelled plot in
  `results/reviewed_synthetic_v2/` and `analysis_outputs/reviewed_synthetic_v2/`.
  These are ignored local artifacts, not findings about LLM behavior.

Tests verify all four continuations (control plus three treatment branches)
inherit the complete checkpoint: agent identities, parameters, memories,
scratchpads, private information, public histories, order book and current hour.
Canonical hashes must match before the intervention. An additional runtime
audit permits changes only to the target cost, private notice and scripted-policy
flag. First post-checkpoint prompts for uninformed peers are byte-identical
across all four conditions. Subsequent action-driven divergence is allowed.

Integer-valued JSON prices are normalized to the checkpoint's float schema
before storage, preserving identical history formatting after restoration.
Continuation tests verify full-run and split-run trajectories agree. Modified
bundles, protocols, source/environment/provider changes are refused.

Pre-existing cheaper prices cannot count as a new undercut. Cost pass-through
without markup compression cannot count as an excess-pass-through undercut.
A target-only cut cannot count as sustained peer price decline. Price-only
indicators never set a confirmed cartel-breakdown outcome: every automatic
assessment remains `UNREVIEWED`, even when prices fall across the market.
Failures, no-trade rounds, right censoring, negative results, private-cost privacy,
historical profit accounting and stopping before nonqualified continuations are
also covered.

Tests used `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` to isolate unrelated globally
installed plugins and a workspace-local `MPLCONFIGDIR`. Four deprecation warnings
originate from unchanged upstream Pydantic class configuration. They did not
fail the checks.

## Remaining validity and operational limits

- Sustained high prices, especially from high initial asks, do not establish
  active coordination. Review messages and behavior before calling it a cartel.
- A private cost reduction can induce ordinary rational repricing and need not
  strengthen the marginal incentive to undercut. Even markup compression does
  not identify intent or establish loss of coordination. Matched comparisons and
  transcript review remain necessary; a later no-communication comparison would
  strengthen the study.
- The static competitive interval is a reference, not a solved equilibrium of
  the repeated double auction. The scripted benchmark changes target messaging
  as well as action policy. Cost reductions mechanically affect available welfare.
- Small samples, selection on the pricing gate, provider drift and limited
  horizons restrict inference. The preliminary four-hour smoke cannot replace
  the research protocol's longer multi-seed positive control.
- No inference config/key/model setting was present in the inspected workspace.
  Modal authentication, credit redemption/balance, candidate-model access,
  startup and GPU/context fit have not been verified. GPU startup charges are
  outside a request-count cap. The shared host is inherited infrastructure,
  not a tested deployment of this study.

The exact first live smoke command and prerequisites are in
[README.md](README.md#first-live-smoke-control-only-at-most-20-requests). It uses
the existing Modal wrapper with `Qwen/Qwen2.5-7B-Instruct`, the upstream default
candidate, and runs only the four-hour control. It has **not** been executed.
The full paid experimental matrix remains unlaunched.
