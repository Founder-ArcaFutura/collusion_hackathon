# Communication, Visibility and Corrupted Information in LLM Double Auctions

Research sprint manuscript draft, 24 October 2026. Complete prose draft of available results; not submission-ready. Truthful Lambda controls are pending in this local freeze. Exhaustive message coding, verified literature references, author details and venue formatting remain to be completed.

## Abstract

We study how communication interacts with market information in repeated double auctions populated by Qwen2.5-7B-Instruct agents. Four matched seed blocks cross seller communication with full versus partially masked rival-ask visibility, yielding 16 completed ten-round markets and 1,600 accepted decisions. Communication's effect on trade count is more positive under partial visibility in every block: interactions are +1, +7, +3 and +13 trades. Price interactions vary in direction, and no completed market passes the implemented sustained-high-price criterion. An exploratory corruption pilot produces divergent market trajectories. A paired decision test yields 48 valid responses, showing sensitivity to quote interventions in some states and invariant asks in another. Messages include accurate self-price reports reaching recipients whose direct histories omit those orders; this does not establish informational novelty or causal mediation. Results motivate treating information availability and integrity as important conditions of agent communication, while small samples and technical failures limit generalization.

## 1. Introduction

Communication can report prices, recommend competitive adjustments or sustain common price references. Consequently, enabling a channel does not determine whether its effects will be competitive or anticompetitive. Public information may make messages redundant; missing or misleading information may change their role.

This sprint began with sustained high pricing and possible collusion as its motivating question. Completed runs did not establish the intended high-price positive control. Subsequent experiments varied the information environment. These follow-ups are exploratory, motivated by earlier observations, and not a prospectively confirmatory programme. We ask whether communication's effect depends on visibility, and whether changing quote content changes immediate seller actions. We do not test whether LLMs integrate more information than humans.

## 2. Methods

### Market and inference

Each main market has five unit-capacity sellers with cost $80 and five buyers with value $100. Over ten disclosed rounds, agents propose orders using market history, own memory and realized trades. Public inputs are frozen before a round's decisions are collected. Genuine crossing orders clear at midpoint prices. Enabled seller messages arrive the following round; buyer communication is disabled.

The main runs use Qwen/Qwen2.5-7B-Instruct, temperature 0.7, a 1,200-token budget, guided JSON, vLLM 0.6.6, Outlines 0.1.11 and XGrammar 0.1.13. Sampling seeds are paired across cells by market seed, role and round; paired seeds do not guarantee numerical determinism across executions. A maximum of two attempts allows bounded recovery from malformed or length-truncated output. Semantic violations and transport failures are not silently repaired. Raw prompts, responses and failures are retained.

### Factorial design and outcomes

Four cells cross full/partial rival-ask visibility with communication ON/OFF. Partial visibility deterministically omits approximately half of rival seller quotes from current and historical displays, using a hash of market seed, observer, owner and quote-origin round. Own quotes, buyer bids and realized trades remain available. True matching is unchanged. Both visibility conditions carry the same disclosure about possible omissions. Run order reverses in alternating seed blocks.

Seeds 20–23 complete all four cells. These constitute four matched seed blocks, not 1,600 independent treatment observations. The trade-count interaction is (partial ON minus partial OFF) minus (full ON minus full OFF). We report per-seed contrasts without trade-level significance tests or equivalence claims. Executed price is conditional on which orders trade, so it is distinguished from submitted asks.

The high-price gate uses the implemented symmetric-market competitive reference interval [$80,$100], its midpoint $90 as a reporting convention, and joint-profit reference $100. All seller asks and mean executed price must strictly exceed $95 with at least one trade in each of the final five rounds. This is a price/trade proxy, not a sufficient definition of cartel conduct. The midpoint is not a unique competitive-equilibrium prediction.

### Extensions

The Lambda distortion pilot runs seeds 20/21 with communication ON/OFF, inflating selected rival asks by exactly $10 in current and historical displays. Current displays are sorted by shown price. Own quotes, buyer views and genuine matching are unchanged; values are not clipped. Four markets complete 400 decisions without recovery. Historical truthful controls ran on Modal; new Lambda truthful controls have been launched but are not yet incorporated here. Provider/hardware differences remain confounded with treatment in the initial comparison.

The paired probe selects four saved truthful communication-ON seller states: seeds 20/21 at rounds 2/5, taking the alphabetically first seller with a rival quote, then the lowest-priced rival quote. Each state is shown truthfully, masked, $10 higher or $10 lower under three matched sampling seeds: 48 decisions plus one separate warmup. History, messages, memory and other entries remain fixed. Current-book ordering is fixed too, so altered values can conflict with ordering. The probe tests a current-entry perturbation, not consistent corruption of an entire history or representative sensitivity across all sellers.

### Message analysis and evidence

All nonempty seller messages are extracted from completed communication-enabled markets. Explicit dollar amounts are matched to actual quotes hidden from each recipient's next-round historical display. Final-round messages have no measured subsequent response. Numerical matches are candidates for semantic review, not confirmed factual transfers. Referent, accuracy, prior knowledge and recipient action must be considered separately.

Original market bundles are checksum-verified and unchanged. Derived evidence is stored separately. In the paired test, the worker sealed the directory before the host log closed. All sealed decision/response files still match; host.log changed and host_exit.json was added. This packaging limitation is disclosed rather than treating the initial root seal as valid.

## 3. Results

### Trading activity

| Seed | Full ON trades | Full OFF | Partial ON | Partial OFF | Interaction |
|---|---:|---:|---:|---:|---:|
| 20 | 26 | 27 | 18 | 18 | +1 |
| 21 | 35 | 34 | 33 | 25 | +7 |
| 22 | 28 | 30 | 26 | 25 | +3 |
| 23 | 22 | 29 | 30 | 24 | +13 |

Communication changes full-visibility trade counts by −1, +1, −2 and −7, versus 0, +8, +1 and +6 under partial visibility. The interaction averages +6 trades per ten-round market, or 12 percentage points of the 50-trade maximum. This is an equal-seed descriptive mean with substantial heterogeneity, not a precise population estimate.

Full ON/OFF markets total 111/120 trades; partial ON/OFF total 107/92. Masking does not always reduce liquidity: seed 23 ON executes 30 trades under partial visibility versus 22 under full visibility. The communication interaction is more consistent than a universal masking penalty.

### Prices and gates

Price interactions are approximately −$3.07, +$2.95, +$0.03 and −$3.17. Equal-seed mean market prices are $85.85 full ON, $85.04 full OFF, $84.15 partial ON and $84.15 partial OFF. These are not trade-weighted pooled prices. None of the 16 completed factorial markets passes the sustained-high-price gate. The data support a descriptive trade-volume interaction more clearly than a stable price-raising effect.

### Message evidence

The eight communication-enabled markets contain 374 nonempty messages: 183 full and 191 partial. Explicit dollar amounts appear in 135 and 155 respectively. In partial visibility, 124 messages yield 302 recipient/quote matches to hidden asks. Of these, 106 messages yield 221 rows matching the sender's own order. These counts do not establish 106 factual relays: recommendations, coincidental amounts and multiple recipients generate matches. Full visibility has no masked-quote matches by construction.

Reviewed examples establish that accurate recipient-relevant reports exist. In seed 20 partial ON round 1, Jin reports his actual $84 ask, omitted from Kit and Nia's next-round histories. Leo likewise reports his actual $82 ask, omitted from Jin and Nia's histories. This demonstrates communication carrying information absent from direct quote displays. It does not establish global novelty or causal uptake. Other messages recommend coordinated reductions or narrate orders inconsistently with actual submissions. Factual reports, recommendations and action discrepancies must remain distinct. Exhaustive independently reviewed semantic coding remains pending.

### Distortion trajectories

Against historical Modal truthful controls, seed 20 ON increases mean executed price by $6.96 and adds two trades; OFF changes price by +$0.23 and loses one trade. Seed 21 ON changes price by −$2.96 and loses 15 trades; OFF changes price by −$1.25 and loses ten trades. These contrasts remain provider-confounded pending truthful Lambda results.

In corrupted seed 20 ON, mean seller ask declines from $93.52 to $88.37 while mean buyer bid rises from $85.98 to $96.91. High- and low-ask groups coexist; repeated messages invoke genuine standing quotes around $96.90. The outcome is not uniform imitation of fabricated high values. Seed 21 ON instead approaches cost: mean asks decline from $88.95 to $81.26 and final-round mean trade price is $81.56, accompanied by repeated recommendations to lower prices. Buyers receive no directly corrupted views but can respond endogenously to real orders and trades. All four distortion markets fail the high-price gate.

### Paired decisions

All 48 probe responses are valid. Seed 21 round 5 returns $82 in every condition and sampling seed: twelve identical asks. Seed 20 round 2 remains around $82.50–$82.83; round 5 numeric asks remain around $82.40–$82.65, with one truthful withdrawal.

Seed 21 round 2 is more sensitive. With sampling seed 901, truthful returns $92, masking and lowering return $85, and increasing produces withdrawal. With seed 902, truthful returns $90, masked $85, increased $89.99 and lowered $90. The remaining sampling seed includes a truthful withdrawal. Withdrawals are separate actions, not artificial numeric prices. The test shows heterogeneous responses without monotonic upward matching. It lacks repeated identical-prompt controls to separately estimate residual generation nondeterminism.

### Technical failures

Original-protocol seed 24 fails after three requests on an overlong scratchpad; a subsequent seed-25 attempt exhausts its two length-recovery attempts before accepting an action. Seed 26 is not attempted in those batches. Separate bounded-scratchpad repair attempts fail on request timeouts before completing a round. These attempts are retained and excluded from completed-market contrasts. Failures may select against verbose or unusual trajectories; they are not evidence of ordinary economic withdrawal.

## 4. Discussion

Communication is more favourable to trade volume under partial visibility in each observed seed block. It is not a uniform trigger for anticompetitive prices. Candidate explanations include relaying missing facts, competitive recommendations, reassurance or shared interpretations of market demand. Accurate messages containing recipient-masked self-prices establish the existence of an information channel, but do not identify the mechanism behind the interaction.

Distortion and paired probes qualify a simple price-imitation account. Individual quote interventions sometimes change actions substantially and sometimes leave them invariant. This is consistent with dependence on surrounding state, but does not prove competent information integration, establish the dominant source or demonstrate superiority to humans. These are behavioural interventions, not internal mechanistic explanations.

Coordination language also needs outcome context. Agents can explicitly coordinate price reductions, and their narratives can disagree with their orders. Neither cooperative language nor high mean prices alone establishes a cartel.

A proposed 2×5 extension was deferred after benchmark review. With two unit-capacity $80 sellers and five $100 buyers, the implemented competitive and joint-profit reference prices both equal $100. The existing index cannot separate supply scarcity from coordinated restraint there. Concentration studies require a benchmark-separated design rather than interpreting ordinary excess demand as collusion.

## 5. Limitations

There are four main seed blocks, two distortion seeds, one model and a short horizon. Failed runs may induce selection bias. Repairs change output constraints and cannot be silently pooled with original results. The analysis is exploratory, without a preregistered significance claim, equivalence conclusion or mediation estimate. Paired seeds do not guarantee deterministic outputs. Historical distortion controls use another provider; fresh controls are pending. Message extraction is complete but semantic coding is not exhaustive. Fixed history and ordering may contradict probe perturbations. No human comparison or model-internal intervention is attempted. External literature positioning and independent review are still needed before submission.

## 6. Conclusion

Across four matched LLM auction seeds, communication's trade-volume effect is more positive under partial visibility, while price effects remain heterogeneous and the sustained-high-price criterion is never met. Corruption and paired probes reveal state-dependent responses rather than automatic price imitation. The informational environment merits attention when evaluating agent coordination; these results do not establish a general theory of collusion or superior LLM information breadth.

## Evidence and remaining completion work

Main tables: market_outcomes.csv and paired_contrasts.csv. Source seals: evidence_inventory.json. Message evidence: messages.csv, recipient_hidden_price_candidates.csv and MESSAGE_REVIEW.md. Distortion review: ../distortion_trajectory_review_20261024/REVIEW.md. Paired results: ../paired_quote_e819adc5cf/. Remaining: incorporate verified Lambda controls, complete semantic review, add verified literature and author/venue details. No new paid inference was launched for this analysis.
