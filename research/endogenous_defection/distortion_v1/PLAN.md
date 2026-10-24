# Observation corruption: prepared exploratory pilot

Status: implemented and locally tested; no live pilot launched. Existing replication code and configurations are untouched. The live command refuses to start while an information-study host lacks a recorded exit. Do not run this in parallel with the five-seed replication.

## Question

Does upward falsification of rival seller quotes change sellers' asks, completed trades or communication? Truthful, omitted and false quote observations test different aspects of information use. Sensitivity to false values alone would not establish broad information integration, collusion, or a human–LLM difference.

## Fixed design

- Same 5 sellers, 5 buyers, Qwen model, ten rounds, temperature, response schema, sampling seeds, token ceiling and bounded format recovery as the completed information-v1 controls.
- Seeds 20 and 21; communication ON and OFF: four new markets, **400 decisions, at most 800 inference requests**.
- Select the same observer/quote-owner/quote-origin-round combinations that the existing 50% mask would omit. Preserve every quote identity and quote count; display selected rival asks **exactly $10 higher**.
- No clipping: an actual ask of 98.50 becomes 108.50 when selected. This deliberate rule prevents clipping from changing the direction or dose. It does not guarantee every displayed price looks economically sensible; above-valuation displayed quotes must be recorded and considered in interpretation.
- Keep the fake value consistent in current book and historical quote displays. Re-sort the displayed current queue by displayed price, preserving a plausible ordering. Both displayed numeric values and their resulting ranks can change; this is not a pure numeral-only perturbation.
- Preserve own quotes, buyer bids, costs, valuations, true order queues, matching and realized trades. Memories are not rewritten. Agents can detect contradictions through legitimate observations or messages; that is part of the response being studied.
- Reuse the exact existing disclosure text in every comparison: it warns that quote lists may omit information, but adds no misinformation warning. There is no new treatment-specific instruction telling agents that quotes are false.
- Compare against the sealed full and partial cells for seeds 20/21 from `information_study_20261024_095806_35d3842f`. These are exploratory matched comparisons with historical controls, not independent confirmation. Shared scientific code and serving package versions must match the controls.

## Commands

Local plan only, safe while the replication runs:

```powershell
Set-Location G:\collusion_hackathon
& G:\collusion_hackathon\.venv\Scripts\python.exe -X utf8 -m research.endogenous_defection.distortion_v1 --stage plan
```

After the replication host exits, this starts the paid pilot:

```powershell
& G:\collusion_hackathon\.venv\Scripts\python.exe -X utf8 -m research.endogenous_defection.distortion_v1 --stage run
```

One ephemeral A10G host, ten-minute readiness limit, two-hour experiment limit. Roughly 70–90 minutes at the previous study's observed pace, with no completion or dollar guarantee. There is no automatic restart. The same filename/encoding safeguards as the working study launcher are used. A technical cell failure stops the batch, with failed/unattempted cells retained.

## Evidence and analysis

The output directory is fresh: `output/distortion_pilot_<timestamp>_<id>`. Each market bundle records raw prompts/responses, true and displayed observations, selected quotes, original/displayed values and offsets, plus a snapshot and hashes of this isolated pilot package. The original sealed control paths and checksum hashes are pinned in the pilot plan.

The automatic analysis writes market outcomes, matched price/ask/trade contrasts, and an exposure–decision table linking visible corruption to that round's own ask and outgoing message. Mean executed prices remain conditional on which trades occur; seller asks and trade counts must be examined separately. The first sample is for discovery, not equivalence or significance claims.

Possible outcomes include upward ask following, contradictory messages, price resistance, or lost liquidity with little price change. None is a guaranteed outcome. A downward distortion, a disclosure treatment or a pivotal-quote treatment would each need its own versioned follow-up; they are not silently added here.

## Prior art

Wang, Hoang, Vorobeychik and Wellman, *Spoofing the Limit Order Book: A Strategic Agent-Based Analysis*, Games 12(2), 46 (2021), concerns deceptive submitted orders and non-LLM agent strategies. It establishes adjacent precedent for useful market information also creating manipulation vulnerability; it does not establish the outcome or novelty of this LLM observation-corruption experiment. Author source: https://strategicreasoning.org/spoofing-the-limit-order-book-a-strategic-agent-based-analysis/

The Federal Reserve's November 2025 Financial Stability Report also discusses AI-related market-manipulation risks in its asset-valuations section. This is contextual motivation, not experimental evidence for our mechanism: https://www.federalreserve.gov/publications/november-2025-financial-stability-report-asset-valuations.htm

Our intervention changes displayed observations, not executable orders, so describe it as observation corruption rather than a market-spoofing experiment.
