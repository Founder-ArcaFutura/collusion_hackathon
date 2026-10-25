# New source markets for the v3 message probe

The previous 200-decision run is complete and remains unchanged. This launcher
generates new market trajectories before attempting a larger saved-state probe.
It does not merely add draws of the existing four messages.

From PowerShell at `G:\collusion_hackathon`, start the source phase:

```powershell
.\research\lambda_smoke\run_message_source_expansion.ps1 `
  -Out output\message_channel_v3_sources -Phase sources -KeepAwake
```

This is a **paid Modal command**. If the output directory does not exist, the
script first creates and displays its immutable acquisition plan. It runs four
new independent market seeds, 40–43, each with ten rounds, five sellers and five
buyers. Each market has its own ephemeral attached Modal session, followed by a
30-second local pause. Scientific configuration is copied exactly from the
original seed-20 partial-visibility, seller-communication-on source, changing only
the market seed. No message is forced to contain a factual price report.

There are **400 market decisions**, at most **800 market inference requests**
under the original two-attempt format-recovery policy, and **eight schema warmups**
(512-token ceiling, minimal JSON, temperature zero): **808 requests maximum**.
Network/transport retries remain disabled. Technical failures stop the
controller; incomplete source markets are preserved and never rerun automatically.
Completed market keys are skipped when restarting the same command.

Source generation is estimated at roughly 2–3 hours including startup, using the
completed v2 run's observed 13.12-second inter-request interval as a rough
reference. Buyer/seller full-market generation and format recoveries may take
longer. That is an estimate, not a performance guarantee.

## Resource and execution limits

The separate `poseidon_compute.message_source_host` uses the same pinned
Qwen2.5-7B/vLLM 0.6.6/Outlines serving image. It explicitly requests two physical
CPU cores and 16 GiB host RAM, with limits of four cores and 32 GiB; GPU count is
one A10G, and concurrent sequences are fixed at one. The worker timeout is 4,000
seconds after readiness, readiness is limited to 600 seconds, a local watchdog
bounds the entire host operation at 4,660 seconds, and a remote watchdog kills
the serving process after 4,660 seconds from engine startup. Idle scaledown is
30 seconds. Normal completion exits the ephemeral app before another session.

The source phase reserves **$10 USD** from the user-reported **$67.10** balance;
the proposed probe phase has a separate **$10** resource budget, for at most $20
of combined allocations. The reported balance has not been independently read
from Modal billing.

Verified public rates: A10 $0.000306/second, CPU $0.0000131/physical-core/second,
RAM $0.00000222/GiB/second. At the configured limits, the upper resource-rate
estimate is $1.545984/hour. Each session requires a full reservation of
$2.40142848 including a 20% reserve; four full source-session reservations are
$9.60571392. A successful, fully exited session is charged its observed local
elapsed-time estimate plus reserve, releasing unused reservation. Failure keeps
the full reservation and stops. Restarting never resets this ledger.

These are enforced resource/time reservations using public pricing, **not a
provider-enforced invoice cap**. Taxes, storage, network egress, concurrent
workspace usage, provider price changes and infrastructure anomalies are outside
this calculation. A shared eight-hour controller deadline persists across both
phases and restarts. `-KeepAwake` is a temporary Windows execution-state request;
it does not change the saved power plan or prevent reboot/network failure.

Pricing: https://modal.com/pricing
Resource limits: https://modal.com/docs/guide/resources

## Audit and actual expanded plan

After all four new markets complete, the source command audits all eight source
markets directly from their sealed events, submitted asks, observations and
message delivery timing. Eligibility is unchanged: rounds 2–6, one accurate
explicit own-ask price, matching standing quote hidden in both current and
historical displays, exact next-hour message receipt, and no duplicate factual
or fabricated claim elsewhere in the prompt. Original/hidden prompts must match
the saved source prompt byte-for-byte.

The deterministic selector rotates markets and prefers distinct factual messages,
then selects at most 30 unique states. It freezes/displays the actual states,
markets, distinct messages, seeds, sessions and requests in `probe/`. The proposed
probe uses three fresh sampling seeds (1001–1003) and the existing 2 × 5 factorial,
with balanced treatment order across sessions. Repeated recipients of a source
message remain correlated observations.

The probe is ready only with **at least 20 states, 8 distinct messages and 4 source
markets**. It does not relax eligibility to meet these targets. If generation
does not yield sufficient diversity, it stops with the audit and a held plan;
there is no automatic purchase of more source markets.

Review the displayed audit first. If it says `READY_FOR_SEPARATE_PROBE_COMMAND`,
the exact subsequent launch command is:

```powershell
.\research\lambda_smoke\run_message_source_expansion.ps1 `
  -Out output\message_channel_v3_sources -Phase probe -KeepAwake
```

At 20 states this runs 600 decisions in six batches (606 requests including
warmups). At 30 states it runs 900 decisions in nine batches (909 requests).
Every experimental decision is durably checkpointed before/after HTTP dispatch.
Accepted keys are never repeated; failed or ambiguous keys stop for review.
The new capped host is used for both phases. The source phase never starts probe
inference automatically. Deadline or budget exhaustion may leave a partial
factorial, which must be reported as incomplete.

Offline preparation and status, with no paid execution:

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m research.lambda_smoke.message_source_expansion `
  --stage plan --out output\message_channel_v3_sources

& .\.venv\Scripts\python.exe -X utf8 -m research.lambda_smoke.message_source_expansion `
  --stage status --out output\message_channel_v3_sources
```

Only run `--stage plan` for a new directory. The PowerShell launcher performs
this step automatically when needed. The earlier sprint freeze, manuscript,
source bundles, completed v2 run and held v3 proposal are never edited.
