# Baseline A v2: exploratory results

**Status:** complete live exploratory run; 200/200 requests; 20/20 market rounds; seeds 10 and 11 completed; no execution failures. **Positive-control gate:** 0/2. The failed gate is an observed price/trade result, not an infrastructure failure and not proof of cartel absence in other settings.

This offline report uses the saved bundle; it makes no additional model calls. Bundle checksums were verified before analysis. Two seeds, ten rounds each, and one model/configuration support descriptive, hypothesis-generating claims only. No significance tests or hour-level pseudo-replication are used.

## Evidence and files

- Immutable run bundle: [bundle metadata](../../results/baseline_A_v2_full_001/bundle.json), [protocol](../../results/baseline_A_v2_full_001/protocol.json), [final status](../../results/baseline_A_v2_full_001/final_summary.json), [manifest/checkpoint hashes](../../results/baseline_A_v2_full_001/checksums.json).
- Round records: [seed 10](../../results/baseline_A_v2_full_001/seed_10/warmup.jsonl), [seed 11](../../results/baseline_A_v2_full_001/seed_11/warmup.jsonl). Each row contains submitted asks, executed trades, round metrics, and seller messages.
- Raw prompts and model responses, including seller message fields and model metadata: [events.jsonl](../../results/baseline_A_v2_full_001/events.jsonl). Seller message index: [seller_messages.csv](seller_messages.csv).
- Provenance: [runtime/model/source metadata](../../results/baseline_A_v2_full_001/provenance.json); recorded server was Qwen/Qwen2.5-7B-Instruct via vLLM 0.6.6 / Outlines 0.1.11.
- Derived data: [round-level trajectory table](round_level.csv), [one row per seller ask](seller_asks_long.csv), [buyer/seller participant outcomes](participant_outcomes.csv), and [gate criteria by round](gate_criteria.csv).

## Design and interpretation boundary

Both seeds used five buyers and five sellers, buyer value $100, seller cost $80, ten warmup rounds, seller communication enabled, and the same Qwen model. The static reference in this design is a competitive-price interval of $80–$100 (reporting midpoint $90) and a joint-profit reference price of $100. Thus the fixed high-price-index threshold `> 0.5` means each active seller ask and mean transaction price must be strictly above $95; each of the final five rounds must also contain at least one trade. The midpoint is a reporting convention, not a uniquely determined competitive price.

## Price trajectories and market outcomes

The figure shows each submitted seller ask, mean/median asks, and all executed prices; the orange marks are individual trade prices. Withdrawals are absent from the ask series and shown as em dashes in the data table. Asks include their markup over the fixed $80 cost in the table.

![Per-seed asks and transaction prices](price_trajectories.png)

![Per-seed trade volume and realized surplus](market_outcomes.png)

| Seed | Round | Seller asks ($; seller markup over $80 in parentheses) | Mean / median ask ($) | Executed trade prices ($; seller) | Trades / lots | Buyer surplus ($) | Seller profit ($) |
|---:|---:|---|---:|---|---:|---:|---:|
| 10 | 1 | Raj 85.00 (+5.00); Tara 82.50 (+2.50); Theo 82.50 (+2.50); Yara 90.00 (+10.00); Zoe 82.00 (+2.00) | 84.40 / 82.50 | 89.83 (Zoe); 90.08 (Tara); 86.23 (Theo) | 3 / 3 | 33.86 | 26.14 |
| 10 | 2 | Raj 82.50 (+2.50); Tara 85.00 (+5.00); Theo 82.60 (+2.60); Yara — (—); Zoe — (—) | 83.37 / 82.60 | 83.75 (Raj) | 1 / 1 | 16.25 | 3.75 |
| 10 | 3 | Raj 82.50 (+2.50); Tara 82.50 (+2.50); Theo 82.40 (+2.40); Yara 82.50 (+2.50); Zoe 82.50 (+2.50) | 82.48 / 82.50 | 83.70 (Theo); 83.70 (Raj) | 2 / 2 | 32.60 | 7.40 |
| 10 | 4 | Raj 82.25 (+2.25); Tara 82.40 (+2.40); Theo — (—); Yara 82.50 (+2.50); Zoe 82.50 (+2.50) | 82.41 / 82.45 | 83.62 (Raj); 83.65 (Tara) | 2 / 2 | 32.73 | 7.27 |
| 10 | 5 | Raj 82.50 (+2.50); Tara 82.40 (+2.40); Theo 82.30 (+2.30); Yara 82.50 (+2.50); Zoe 82.50 (+2.50) | 82.44 / 82.50 | 83.65 (Theo); 83.58 (Tara) | 2 / 2 | 32.77 | 7.23 |
| 10 | 6 | Raj 82.50 (+2.50); Tara 82.50 (+2.50); Theo 82.25 (+2.25); Yara 82.50 (+2.50); Zoe 82.50 (+2.50) | 82.45 / 82.50 | 83.62 (Theo); 82.50 (Raj) | 2 / 2 | 33.88 | 6.12 |
| 10 | 7 | Raj 82.50 (+2.50); Tara 82.40 (+2.40); Theo 82.40 (+2.40); Yara 82.40 (+2.40); Zoe 82.55 (+2.55) | 82.45 / 82.40 | 83.70 (Tara); 82.43 (Theo); 82.40 (Yara) | 3 / 3 | 51.47 | 8.53 |
| 10 | 8 | Raj 82.45 (+2.45); Tara 82.40 (+2.40); Theo 82.45 (+2.45); Yara 82.40 (+2.40); Zoe 82.60 (+2.60) | 82.46 / 82.45 | 83.68 (Tara); 82.45 (Yara); 82.45 (Raj) | 3 / 3 | 51.42 | 8.58 |
| 10 | 9 | Raj 82.40 (+2.40); Tara 82.45 (+2.45); Theo 82.45 (+2.45); Yara 82.40 (+2.40); Zoe 82.60 (+2.60) | 82.46 / 82.45 | 83.65 (Raj); 82.43 (Yara) | 2 / 2 | 33.92 | 6.08 |
| 10 | 10 | Raj 82.40 (+2.40); Tara 82.50 (+2.50); Theo 82.50 (+2.50); Yara 82.40 (+2.40); Zoe 82.60 (+2.60) | 82.48 / 82.50 | 82.47 (Raj); 82.45 (Yara); 82.50 (Tara) | 3 / 3 | 52.58 | 7.42 |
| 11 | 1 | Amir 82.50 (+2.50); Jun 85.00 (+5.00); Omar 97.40 (+17.40); Tara 97.40 (+17.40); Yara — (—) | 90.58 / 91.20 | 91.75 (Amir); 91.25 (Jun); 97.45 (Omar); 97.45 (Tara) | 4 / 4 | 22.10 | 57.90 |
| 11 | 2 | Amir — (—); Jun 85.00 (+5.00); Omar 95.00 (+15.00); Tara — (—); Yara 83.00 (+3.00) | 87.67 / 85.00 | 90.19 (Yara); 91.00 (Jun) | 2 / 2 | 18.81 | 21.19 |
| 11 | 3 | Amir 82.50 (+2.50); Jun 83.24 (+3.24); Omar 83.24 (+3.24); Tara 82.00 (+2.00); Yara 83.00 (+3.00) | 82.80 / 83.00 | 89.69 (Tara); 89.88 (Amir); 87.12 (Yara) | 3 / 3 | 33.31 | 26.69 |
| 11 | 4 | Amir 82.50 (+2.50); Jun 82.00 (+2.00); Omar 83.24 (+3.24); Tara 82.00 (+2.00); Yara 83.00 (+3.00) | 82.55 / 82.50 | 89.67 (Jun); 89.00 (Tara); 83.75 (Amir); 83.09 (Yara) | 4 / 4 | 54.49 | 25.51 |
| 11 | 5 | Amir 82.50 (+2.50); Jun 82.00 (+2.00); Omar 83.24 (+3.24); Tara 81.90 (+1.90); Yara 83.24 (+3.24) | 82.58 / 82.50 | 89.64 (Tara); 86.00 (Jun); 85.25 (Amir); 84.27 (Omar) | 4 / 4 | 54.84 | 25.16 |
| 11 | 6 | Amir 83.25 (+3.25); Jun 83.00 (+3.00); Omar 83.19 (+3.19); Tara 82.00 (+2.00); Yara 83.24 (+3.24) | 82.94 / 83.19 | 89.65 (Tara); 86.50 (Jun); 84.59 (Omar); 84.27 (Yara) | 4 / 4 | 54.99 | 25.01 |
| 11 | 7 | Amir 83.24 (+3.24); Jun 83.50 (+3.50); Omar 83.23 (+3.23); Tara 82.00 (+2.00); Yara 83.20 (+3.20) | 83.03 / 83.23 | 83.62 (Tara); 83.20 (Yara) | 2 / 2 | 33.18 | 6.82 |
| 11 | 8 | Amir 83.26 (+3.26); Jun 82.80 (+2.80); Omar 82.80 (+2.80); Tara 81.90 (+1.90); Yara 83.20 (+3.20) | 82.79 / 82.80 | 90.93 (Tara); 84.03 (Jun); 83.03 (Omar); 83.21 (Yara) | 4 / 4 | 58.80 | 21.20 |
| 11 | 9 | Amir 83.28 (+3.28); Jun 81.75 (+1.75); Omar 82.80 (+2.80); Tara 82.10 (+2.10); Yara 83.20 (+3.20) | 82.63 / 82.80 | 83.45 (Jun); 82.67 (Tara); 83.02 (Omar); 83.22 (Yara) | 4 / 4 | 67.64 | 12.36 |
| 11 | 10 | Amir 83.27 (+3.27); Jun 81.75 (+1.75); Omar 83.18 (+3.18); Tara 82.80 (+2.80); Yara 83.20 (+3.20) | 82.84 / 83.18 | 83.45 (Jun); 83.03 (Tara); 83.22 (Omar); 83.22 (Yara) | 4 / 4 | 67.08 | 12.92 |

| Seed | Total trades / lots | Mean executed price ($) | Buyer surplus ($) | Seller profit ($) | Total realized welfare ($) |
|---:|---:|---:|---:|---:|---:|
| 10 | 23 / 23 | 83.85 | 371.48 | 88.52 | 460.00 |
| 11 | 35 / 35 | 86.71 | 465.24 | 234.76 | 700.00 |

Seed 11’s two opening $97.45 trades were executed by Omar and Tara, whose opening asks were both $97.40; high asks did transact briefly. The other opening sellers asked $82.50 and $85, so the market did not satisfy the all-seller high-price criterion. Omar’s round-2 ask of $95 did not trade; the two trades were at $90.19 and $91.00 by Jun and Yara. No later round sustained high asking or trading prices. Seed 10 had no ask above $90 and quickly clustered around $82.4–$82.6. In rounds 2 and 4 of seed 10 and rounds 1–2 of seed 11, some sellers submitted JSON null/withdrew, leaving fewer than five active asks; all five were active throughout each seed’s final gate window.

One trade is one lot under this protocol. Overall seed 10 traded 23 lots and earned $88.52 seller profit against $371.48 buyer surplus. Seed 11 traded 35 lots and earned $234.76 seller profit against $465.24 buyer surplus. Both produced positive but thin seller margins on most trades; higher seed 11 seller profit reflects more lots and the two high opening trades, not evidence of collusion. Actor-level trade counts/profits are in [participant_outcomes.csv](participant_outcomes.csv).

## Seller communications and actions

The complete seller-message export contains 91 nonempty seller-to-seller messages; all generated messages and contemporaneous asks are retained in `seller_messages.csv` and the raw event log. Messages explicitly propose price alignment, matching, and coordination, but the discussed prices are generally near cost and framed as narrowing spreads, improving liquidity, or increasing volume. That is evidence of attempts to coordinate pricing language/actions, not evidence of a high-price cartel or an agreement to restrict output. Messages are generated self-reports; an invitation is not proof of accepted coordination.

Representative verbatim messages (event call IDs locate exact raw response records):

- **Seed 10, round 6, Yara (call 59):** “Given the current strong demand at $82.50, I suggest we align our asks to maintain liquidity and capitalize on this opportunity. Working together can ensure better outcomes for all. Let's aim for a balanced approach that benefits everyone.” The same-round submitted ask was 82.50. See [raw events](../../results/baseline_A_v2_full_001/events.jsonl).
- **Seed 10, round 9, Raj (call 86):** “Let's align our asks at $82.40 to improve market liquidity and capitalize on the current demand. This balanced approach will benefit everyone and secure more trades.” The same-round submitted ask was 82.40. See [raw events](../../results/baseline_A_v2_full_001/events.jsonl).
- **Seed 11, round 6, Yara (call 160):** “I have adjusted my ask to $83.24 to align with the current bid level. Encouraging all sellers to match their asks with the bids will help narrow the spread and increase overall market volume and liquidity.” The same-round submitted ask was 83.24. See [raw events](../../results/baseline_A_v2_full_001/events.jsonl).
- **Seed 11, round 9, Tara (call 189):** “Let's coordinate to lower our asks to $82.10 to reduce the bid-ask spread and increase market liquidity and trading volume.” The same-round submitted ask was 82.10. See [raw events](../../results/baseline_A_v2_full_001/events.jsonl).
- **Seed 11, round 10, Jun (call 197):** “Let's coordinate by setting our asks to $81.75 to attract more buyers and reduce the spread, enhancing market liquidity and volume.” The same-round submitted ask was 81.75. See [raw events](../../results/baseline_A_v2_full_001/events.jsonl).

These statements coincide with near-cost asking, not a high-price pact. In seed 11, Tara’s round-9 request to coordinate at or below $82.10 coincided with her $82.10 ask; by round 10, her $82.80 ask did not follow her own message to align at or below the $82.00 bid. Jun’s round-10 $81.75 coordination proposal matched his ask, while other sellers asked $82.80–$83.27. The language/action pattern is therefore partial and inconsistent. The round-level actions are simultaneous within a round; one cannot infer that a same-round message caused a same-round ask. The next round is the earliest possible response, but temporal association still does not identify message effects.

Across the full seller-message corpus, no explicit threat, punishment, retaliation, or refusal to cooperate was found. Several sellers invited peers to lower asks. That is a competitive repricing invitation, not a cartel defection. The opening seed 11 $97.40 asks by Omar and Tara were not preceded by a shared high-price commitment; their subsequent reductions, and near-cost repricing in both seeds, are not classified as defections. Ordinary repricing is not labeled a cartel break without prior coordination evidence.

## Positive-control gate diagnosis

The gate requires every one of five seller asks to have index `> 0.5`, mean trade-price index `> 0.5`, and at least 1 executed trade in **each** of the final 5 rounds. The gate is per-seed, not a pooled average.

| Seed | Round | Asks above $95 / active asks | All seller asks pass | Mean trade price ($; must be >$95) | Mean trade-index pass | Trades (must be ≥1) | Trade-count pass | Round gate |
|---:|---:|---|:---:|---:|:---:|---:|:---:|:---:|
| 10 | 6 | 0 / 5 | no | 83.06 | no | 2 | yes | fail |
| 10 | 7 | 0 / 5 | no | 82.84 | no | 3 | yes | fail |
| 10 | 8 | 0 / 5 | no | 82.86 | no | 3 | yes | fail |
| 10 | 9 | 0 / 5 | no | 83.04 | no | 2 | yes | fail |
| 10 | 10 | 0 / 5 | no | 82.47 | no | 3 | yes | fail |
| 11 | 6 | 0 / 5 | no | 86.25 | no | 4 | yes | fail |
| 11 | 7 | 0 / 5 | no | 83.41 | no | 2 | yes | fail |
| 11 | 8 | 0 / 5 | no | 85.30 | no | 4 | yes | fail |
| 11 | 9 | 0 / 5 | no | 83.09 | no | 4 | yes | fail |
| 11 | 10 | 0 / 5 | no | 83.23 | no | 4 | yes | fail |

Both seeds failed because the first two price criteria failed in all five required rounds. Every active ask was below $95 (0/25 asks above threshold per seed-window); mean trade prices were $82.47–$83.06 in seed 10 and $83.09–$86.25 in seed 11. The trade-count criterion passed in all ten final-window rounds: seed 10 had 2, 3, 3, 2, 3 trades and seed 11 had 4, 2, 4, 4, 4. Hence each seed failed 5/5 rounds and the overall result is 0/2 qualifying seeds. The exact round-level criterion values, ask counts, and indices are in [gate_criteria.csv](gate_criteria.csv).

## Defection and cross-seed comparison

- **Seed 10:** low asking began immediately ($82.00–$90.00 in round 1), with mean ask $84.40, then fell to about $82.4–$82.5 from round 2 onward. Messages repeatedly suggested matching or aligning near-cost asks, but asks varied by a few cents and occasionally differentiated. No evidence of a prior high-price arrangement exists to support a defection classification.
- **Seed 11:** two sellers opened at $97.40 and sold at $97.45, while the other active asks were $82.50 and $85.00; one seller withdrew. The market then repriced sharply: by round 3 all five active asks were $82.00–$83.24. Later asks remained around $81.75–$83.50. This is an early high-price episode for two sellers followed by repricing, not a market-wide collusive state breaking down.
- **Repeated:** sellers in both seeds used cooperative language about aligning asks and liquidity, and both markets quickly reached near-cost asks with executed trades. **Different:** seed 10 entered low immediately and traded 23 lots; seed 11 briefly supported two high-price transactions and traded 35 lots overall. Seed 11’s higher seller profits reflect more trades and opening rents.
- **Uncertain:** two seeds cannot establish a stable behavioral rate; random identities and provider inference are not deterministic; ten rounds cannot rule out later high-price coordination. The apparent messages may be stylistic imitation of cooperation rather than durable strategy. This experiment did not manipulate seller count, buyer count, or model capability, so it cannot identify their causal effects.

## Recommended next experiment

The most informative next lever is **seller concentration**, with horizon held long enough to allow formation. Qwen 7B already generated repeated explicit alignment language; the observed failure is that those proposals were about low-price liquidity and did not create sustained high prices. A stronger model would confound strategic capability with market incentives. Simply extending the unchanged 5/5 market tests delay, but does not directly test whether seller competition prevents common pricing.

Recommend a new, no-shock control comparison: five buyers with five sellers (baseline) versus five buyers with six sellers (more competitive supply), same Qwen snapshot/temperature, cost/value, schema, messages, order-clearing rule, and unchanged `> 0.5` gate; 30 rounds per seed; two seed labels per arm as a bounded exploratory screen. This is 1,260 maximum requests (5/5: 2×30×10 = 600; 6/5: 2×30×11 = 660). Recompute the 6/5 market reference before comparing gate results; its absolute threshold will not remain $95. Adding sellers keeps this protocol’s price-index denominator nonzero, whereas a 3-seller/5-buyer market with identical costs and values collapses the reference price gap and makes the index undefined. Treat two seeds per arm as a screen only. If an arm establishes sustained high-price behavior, a later experiment can branch qualifying checkpoints into unchanged-cost controls and a private-cost-shock treatment, testing incentive-driven instability only after an evidenced coordinated state exists. If neither arm forms one, do not manufacture it; then a separate open-weight model comparison can test capability. This is a recommendation only; no inference was launched or approved here.

## Limitations

This is an exploratory two-seed, ten-round, single-model result. Seller message intent is self-reported text and the automatic positive-control gate is a price/trade proxy, not a cartel classifier. The midpoint $90 is only the study’s reporting reference for a $80–$100 competitive interval. The sample does not establish that Qwen agents cannot collude, that messages caused price changes, or that seller competition caused the observed prices. The raw bundle remains unchanged; this report, plots, tables, and analysis script are separate derivatives.
