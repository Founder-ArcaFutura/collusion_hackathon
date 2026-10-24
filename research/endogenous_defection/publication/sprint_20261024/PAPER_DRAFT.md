# Communication, Visibility, and Corrupted Information in LLM Double Auctions

**Authors:** [Add author names and affiliations before PDF export]

## Abstract

We study how seller communication interacts with public quote visibility in repeated LLM double auctions. Four matched seed blocks cross communication ON/OFF with full/partial visibility of rival asks, producing 16 completed ten-round markets and 1,600 accepted decisions. Communication’s trade-count interaction (partial-minus-full visibility difference in the ON-minus-OFF effect) is +1, +7, +3, and +13 trades; the mean is +6.0 (sample SD 5.29; illustrative 95% t interval −2.4 to +14.4). This exploratory estimate is imprecise and does not establish a population effect. Communication ON also changes the prompt and required output fields, so this is a communication-enabled protocol contrast, not an isolated information-channel intervention. The synchronous, batch-updated CDA-style markets did not meet the specified sustained-high-price gate. Verified examples show one self-price report hidden from recipients’ current and historical displays; they do not establish reliance or causal mediation. Four supplemental Lambda truthful controls now permit same-provider comparisons with quote-distortion runs, though host instances differ. Corruption and paired quote probes show heterogeneous responses. Results motivate studying information conditions in agent markets, but do not establish collusion or a general propensity to collude.

## 1. Introduction

Communication can transmit price observations, recommend competitive adjustments, or help sustain common price references. The effect of a message therefore depends on what recipients already observe and on how the communication treatment changes their decision context. Prior work finds that direct seller communication can increase collusive tendencies in double auctions [1], studies how asymmetric data access can make AI-agent collusion fragile [2], and tests cheap talk in AI-agent prediction markets where information aggregation is the outcome [3]. These settings and outcomes differ from the liquidity interaction studied here.

This sprint began from a high-price collusion question. A completed live exploratory baseline using Qwen2.5-7B-Instruct made 200 requests across two seeds but passed the specified sustained-high-price gate in 0 of 2 seeds. That is a failed positive-control gate for this model and setup, not evidence that collusion is absent generally. The information-by-communication experiment and subsequent corruption/probe analyses are exploratory follow-ups. They ask whether the observed communication effect on trade completion varies with rival-ask visibility, and whether selected seller actions respond to quote perturbations.

Our contribution is narrow: a factorial intervention on quote visibility and a communication-enabled protocol, with trade count as a liquidity outcome, plus selected evidence about message availability and quote sensitivity. We do not test whether LLMs possess broader information than humans or whether messages caused the observed market interaction.

## 2. Methods

### Market and protocol

Each market has five unit-capacity sellers with a fixed cost of $80 and five buyers with a fixed value of $100. Markets run for ten rounds. In each round, all ten agents submit decisions against the same pre-round market state; only after the full batch is collected are orders applied and crossing orders cleared. We therefore describe the mechanism as a synchronous, batch-updated double auction with CDA-style matching, not as continuous asynchronous decision-making. Executed trades clear at the midpoint under the unchanged matching engine. Agents observe market histories, their own memory, and realized transactions.

The main runs use Qwen/Qwen2.5-7B-Instruct, temperature 0.7, a 1,200-token output budget, guided JSON, vLLM 0.6.6, Outlines 0.1.11, and XGrammar 0.1.13. Sampling seeds are paired across cells by market seed, role, and round. Paired seeds do not ensure identical outputs across executions. The runner permits at most two bounded recovery attempts for malformed or length-truncated output; semantic violations and transport failures are not silently repaired. Prompts, responses, and failed attempts are retained in the raw bundles.

### Factorial visibility and communication study

The design crosses seller communication ON/OFF with full/partial visibility of rival seller asks. Buyers do not communicate. In partial visibility, a deterministic hash of market seed, observer, quote owner, and quote-origin round omits approximately half of rival seller quotes from the observer’s current and historical displays. Own quotes, buyer bids, realized trades, and true matching remain unchanged. Both visibility conditions disclose that displayed quote lists may omit rival asks.

Communication ON enables next-round seller messages and also changes the prompt and required output fields. Thus the estimand is the effect of the communication-enabled protocol, including those prompt/output differences; it does not isolate message receipt as the sole causal component. Messages sent in round t become available in round t+1.

Seeds 20–23 completed all four cells, giving four matched seed blocks and 16 markets. Seed 24’s full-visibility/communication-on cell failed before completing a round; its remaining cells and later planned seeds were not attempted. The failed cell remains in the evidence inventory and is excluded from completed-market contrasts. The per-seed interaction for a metric is (partial ON − partial OFF) − (full ON − full OFF). We report seed-level descriptive contrasts rather than treating 1,600 decisions as independent treatment units.

### Outcomes and high-price gate

The primary outcome is number of trades per ten-round market. We also report mean executed trade price, submitted asks, seller profit, buyer surplus, and total realized welfare. With fixed seller cost $80 and buyer value $100, each trade contributes exactly $20 of realized surplus, so total welfare equals $20 multiplied by trade count and is not independent corroborating evidence.

The sustained-high-price gate requires all active sellers’ asks to exceed $95, mean executed price to exceed $95, and at least one trade in each of the final five rounds. This is an operational threshold for this experiment, not a comprehensive definition or detector of collusion. Failure to pass means only that the specified gate was not met.

### Quote distortion and paired decision probe

A supplemental Lambda pilot uses seeds 20/21 with communication ON/OFF. In distortion-on cells, selected rival asks are displayed $10 higher in current and historical views; own quotes, buyer views, and true matching are unchanged. Four distortion markets each complete ten rounds and 100 accepted decisions. Four truthful full-visibility controls for the same seeds and communication conditions also completed on Lambda. The runs use the same provider, GPU class, model, and serving/software versions, but distinct host instances; residual instance-level variation remains possible.

The paired quote probe selects four saved truthful communication-on seller states: seeds 20/21 at rounds 2/5, choosing the alphabetically first seller with a rival quote and then the lowest-priced rival quote. At each state, it varies the current quote entry (truthful, masked, $10 higher, or $10 lower) under three matched sampling seeds, for 48 decisions plus one warmup. History, messages, memory, and other entries remain fixed. Current-book ordering is fixed, so perturbed values can conflict with ordering. These selected states are not representative samples of all sellers or market states.

## 3. Results

### Communication and visibility

The trade-count interactions by seed are +1, +7, +3, and +13. Their equal-seed mean is +6.0 trades per ten-round market, with sample SD 5.29. An illustrative two-sided 95% t interval using four blocks is approximately −2.4 to +14.4 trades. Given the small number of blocks and exploratory, data-informed hypothesis, this interval is descriptive and does not support a formal population-effect claim.

Communication ON/OFF markets total 111/120 trades under full visibility and 107/92 under partial visibility. Partial visibility did not uniformly reduce liquidity: in seed 23 communication-on markets, partial visibility produced 30 trades versus 22 with full visibility. The interaction’s direction is consistent across the four completed seed blocks, while its magnitude is uncertain.

Price interactions are approximately −$3.07, +$2.95, +$0.03, and −$3.17. Equal-seed mean prices are $85.85 (full ON), $85.04 (full OFF), $84.15 (partial ON), and $84.15 (partial OFF). These are means of market means, not trade-weighted pooled prices. None of the 16 completed factorial markets passed the specified sustained-high-price gate. This does not establish that no collusive behavior occurred under other definitions or in other settings.

### Positive control and quote distortion

The earlier live high-price baseline completed 200/200 requests over two seeds but passed the gate in 0/2 seeds. Every active ask in the evaluated final windows was below $95; the price criteria failed while the final-window trade-count criterion passed. This is a completed but unsuccessful positive control for the intended high-price outcome. Separately, scripted synthetic controls validate software plumbing only and are not behavioral evidence.

The four completed Lambda truthful controls and four distortion markets are summarized below. Values are mean executed prices and trade counts. Distortion-minus-truthful differences vary substantially across the two seeds and do not show a consistent directional response.

| Seed | Communication | Truthful price / trades | Distorted price / trades | Price difference | Trade difference |
|---|---|---:|---:|---:|---:|
| 20 | ON | $85.35 / 26 | $92.31 / 28 | +$6.96 | +2 |
| 20 | OFF | $82.85 / 27 | $83.08 / 26 | +$0.23 | −1 |
| 21 | ON | $86.62 / 35 | $83.66 / 20 | −$2.96 | −15 |
| 21 | OFF | $88.91 / 34 | $87.66 / 24 | −$1.25 | −10 |

These are small, seed-specific supplementary comparisons, not a powered estimate of a general corruption effect. Because the runs used distinct host instances, shared provider/model/runtime does not remove all possible system-level differences.

### Message evidence

The mechanical inventory contains 374 nonempty messages (183 full-visibility and 191 partial-visibility). It finds 124 partial-visibility messages with dollar amounts matching quotes omitted from at least one recipient’s next-round historical display, across 302 recipient/quote candidate rows; 221 rows from 106 messages match the sender’s own quote. These are candidate matches, not verified factual relays: numeric agreement can be a proposal or coincidence, and historical omission alone does not establish that information was globally unavailable.

Selected recipient-level review distinguishes two examples. In seed 20, partial ON, round 1, Jin accurately reports his $84 ask to Kit and Nia. That quote is marked hidden from both recipients’ current and historical quote displays at receipt. This establishes an opportunity for the message to convey otherwise unavailable direct-display information; it does not show that either recipient relied on the message or that it caused a later action. Leo’s truthful $82 report to Jin and Nia has a different status: the quote is omitted from their historical display, but remains visible in the current order book. It is not evidence that the message supplied information unavailable in the recipients’ direct displays. Other reviewed messages include recommendations, coordination requests, and discrepancies between narrated intentions and recorded actions. Exhaustive semantic coding remains incomplete.

### Paired quote probe and failures

All 48 paired-probe responses were accepted. In seed 21 round 5, the seller returned an $82 ask in all four quote conditions under each sampling seed (12 identical outcomes). Seed 20 round 2 remained around $82.50–$82.83; seed 20 round 5 numeric asks remained around $82.40–$82.65, with one truthful withdrawal. Seed 21 round 2 showed larger condition- and sampling-dependent changes, including withdrawals. This selected probe demonstrates heterogeneous responses to current quote perturbations, not a monotonic price-copying rule or a general information-integration capability. It has no repeated identical-prompt controls to estimate residual generation variability separately.

The original seed-24 factorial attempt failed after three requests because of an overlong scratchpad; a later seed-25 attempt exhausted its two length-recovery attempts before accepting an action. Seed 26 was not attempted in those batches. Separate bounded-scratchpad repairs timed out before completing a round. All failures remain retained and excluded from completed-market contrasts. Failure-related selection bias is possible.

## 4. Discussion

Across four completed matched seed blocks, the communication-enabled protocol had a more favourable effect on trade counts under partial rival-ask visibility than under full visibility. Verified message evidence shows that at least one accurate self-price report reached recipients whose current and historical quote displays both omitted the price. That establishes a plausible information-recovery opportunity, not causal mediation of the trade-count interaction. Because communication ON also changes prompt wording and required output fields, the factorial result should not be attributed solely to message content or information relay.

The primary study does not establish sustained high pricing under either visibility condition, and none of its markets passed the pre-specified gate. The supplementary distortion and paired-probe results are heterogeneous. They motivate more careful tests of information integrity and availability but do not establish that LLM sellers systematically imitate altered quotes, coordinate on supra-competitive prices, or possess superior information breadth.

## 5. Limitations

The primary factorial estimate has four completed seed blocks, one model, ten rounds, and an exploratory analysis plan. Its illustrative interval is wide. Seeds are paired design blocks, not independent replications of the broader population of models, prompts, or markets. The communication treatment bundles received messages with changes to prompts and output requirements. Message counts are mechanical candidates, not exhaustive semantic labels; manual review is selective. Hidden from a display does not imply globally novel, remembered, or causally influential.

The corruption comparison has only two seeds and distinct host instances. The paired probe uses four selected states, fixed histories and ordering, and no identical-prompt repetition controls. Neither identifies internal mechanisms. Technical failures can select which trajectories complete. The paired-probe bundle’s generated root manifest has a known limitation: its recorded host.log hash does not match the current file, and host_exit.json is unlisted. We preserve and disclose this condition rather than repairing the original manifest. No new tests or inference runs were conducted for this manuscript revision.

## 6. Conclusion

In sixteen completed Qwen2.5-7B-Instruct double-auction markets, the communication-enabled protocol had a more favourable effect on trade completion under restricted rival-price visibility than under full visibility in each of four matched seed blocks. The mean interaction was +6.0 trades, with substantial uncertainty. A selected verified message conveyed a price absent from recipients’ current and historical displays, but message reliance and mediation were not established. Neither communication condition reliably met the sustained-high-price criterion. Supplemental quote-distortion and paired-decision probes show heterogeneous, state-dependent responses. These findings motivate further study of public information and communication as interacting features of agent markets; they do not establish a general effect or prove collusion.

## Acknowledgment of pre-sprint work

The underlying auction environment, agent framework, and initial endogenous-defection apparatus predate the sprint. Sprint-period work added the rival-quote visibility intervention, communication-by-visibility study, quote-distortion pilot, paired quote probe, analyses, and evidence package reported here. The repository README identifies the pre-existing components. No claim is made that the underlying auction implementation originated in the sprint.

## Appendix: Limitations and Dual-Use / Ethical Considerations

This work studies simulated seller agents in a bounded toy market. It does not establish collusion, intent, cartel membership, real-world market impact, or a general propensity for LLMs to collude. The primary result is an exploratory interaction in trade counts with four matched seed blocks; the high-price gate failed in the positive-control baseline and all completed factorial markets. Message matching does not prove information uptake or causal influence. Distortion and probe results are limited, heterogeneous observations.

Research on message-mediated coordination could inform both monitoring and attempts to coordinate market behavior. We therefore report aggregate results, selected evidence needed to substantiate the claims, and reproducibility metadata while keeping full raw prompts/responses and verbose logs in a separately retained local evidence archive. We do not provide guidance for deploying price-coordination agents in real markets. Any real-world use of such systems would require legal, economic, and safety review, independent monitoring, and controls on private communications and order visibility. The experiments used simulated agents and did not interact with real buyers, sellers, or financial markets.

## References

[1] K. Agrawal, V. Teo, J. J. Vazquez, S. Kunnavakkam, V. Srikanth, and A. Liu. “Evaluating LLM Agent Collusion in Double Auctions.” arXiv:2507.01413, 2025. https://arxiv.org/abs/2507.01413

[2] J. Keppo, Y. Li, G. Tsoukalas, and N. Yuan. “On the Fragility of AI Agent Collusion.” arXiv:2603.20281, 2026. https://arxiv.org/abs/2603.20281

[3] S. Galanis. “Information Aggregation with AI Agents.” arXiv:2604.20050, 2026. https://arxiv.org/abs/2604.20050
