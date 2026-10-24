# Information and communication: next research tranche

Status update: the 3/5 run has completed and been analyzed. The partial-observation layer, four-cell runner and paired analysis are now implemented and locally tested; no live information-study batch has been launched. See [the executable next-run instructions](../../NEXT_RUN.md). The two JSON configurations here remain review-only (`execution_enabled=false`). The optional shuffled-order observation mode is implemented for local tests but is not included as a live factorial arm.

## Research decision

Follow the information-by-communication hypothesis. Finish the active concentration screen, then concentrate the next study on 5 sellers and 5 buyers. Do not expand market size, model family, horizon and observation policy simultaneously. Existing data motivate the new question; seeds 10 and 11 remain exploratory references.

Prepare six fresh paired market blocks, seeds 20–25, as a practical first tranche. This is neither a power calculation nor a claim that six markets establish equivalence. Pair initialization and request sampling seeds by role/round across cells. Use `provider_seed=true` in every new cell; identical request seeds do not produce identical outputs after prompts diverge or guarantee reproducibility across hardware/runtime changes. All cells share model, temperature, token ceiling, two-attempt format-recovery policy, horizon, matching rules and initial-order ranges.

## Sequence

1. Let the running cell finish and inspect its automatically generated results, recovery counts and technical exclusions.
2. Freeze the next experiment's observation contract, serving configuration and analysis plan. The full-visibility ON/OFF review configurations establish the common new protocol.
3. Expand along one axis: full versus privately censored seller-quote information, crossed with communication ON/OFF. Implement and test the observation layer before launching that factorial. A first small tranche should include all four cells, rather than exhaust the budget replicating only full visibility before testing the new hypothesis.
4. Run matched seed blocks in balanced order. A two-seed four-cell tranche costs 800 decisions, at most 1,600 requests. Expand to six blocks under the same frozen protocol if the manipulation and execution are usable. Expansion must not depend on obtaining the preferred effect direction or crossing a significance threshold. Log any pilot-driven redesign and use fresh seeds after redesign.
5. Reserve seeds 100–111 as candidates for later confirmation; choose the replication count from precision requirements and available budget before looking at those outcomes. These are unused candidates, not an approved sample-size commitment.

The full-visibility pair alone is 1,200 decisions / at most 2,400 requests for six seeds. The complete four-cell factorial is 2,400 decisions / at most 4,800 requests. An optional quote-order placebo crossed with ON/OFF for two seeds adds 400 decisions / at most 800 requests. Counts assume 10 rounds, 10 agents and at most two generations per decision. These are request budgets, not dollar estimates or authorizations to spend them.

## Controls with direct interpretive value

- **Matched full visibility:** separates changes associated with communication from changes induced by information restriction under one execution policy.
- **Matched mask schedules:** index masks by market seed, observer identity, quote-owner identity and observation time; do not tie missingness to price, display position or communication outputs. Save actual realized visibility because book contents can diverge across treatments even under a matched random mask rule.
- **Observation isolation:** preserve the true matching state, buyers' original observations, sellers' own information and actual trades. Apply the declared visibility rule to history as well as the current book where intended. Do not erase information agents previously learned. Log enough to establish what facts are still inferable.
- **Stable presentation:** use the same observation format and missing-data disclosure in both communication conditions. Make unknown quotes distinct from absent orders.
- **Order placebo:** shuffle the same visible quotes, preserving information, to detect presentation sensitivity. Allocate this as a limited control rather than another large research axis.
- **Sampling and execution controls:** balance cell order and fix model/runtime/recovery settings across cells. Retain every rejected response and failed trajectory; report failure rates by cell alongside economic outcomes. A failed market is not a zero-trade completed market.
- **Message-delivery control, if needed later:** the current communication switch also changes prompt/output fields and message planning. A compose-but-do-not-deliver arm can separate those changes from actually receiving peers' messages. It is an additional arm requiring an explicit delivery/expectation specification, not something silently added to this 2x2.
- **Mechanism extension, if needed later:** a mechanical truthful relay of permitted observations can distinguish information delivery from strategic free-form communication. This is a follow-up to a usable visibility manipulation, not another gate before collecting the first factorial outcomes.

## Measurement and decision rules

The independent unit is the complete market trajectory; matched seeds are blocks. Report each market's mean transaction price, trade rate relative to feasible capacity, seller profit per seller, buyer surplus, welfare and technical failure rate. Pooling trades across markets changes weights and must not replace the market-level analysis. Prespecify treatment of zero-trade markets: their mean trade price is undefined, while trade count, surplus and welfare remain measurable.

Estimate the communication contrast within each visibility condition and their interaction. Show individual paired contrasts, including disagreements between seeds. Six blocks may still leave wide intervals; a null estimate does not establish irrelevance or equivalence. Choose any equivalence margin from an economically motivated criterion before confirmation.

Audit whether messages contain accurate facts not available in the recipient's own view and whether later decisions are consistent with using them. Separate factual relays, price proposals and threats. Use a fixed coding rubric and, where practicable, code content without access to final market outcomes. An interaction is an outcome of interest even before the mechanism is settled.

Unexpected outcomes remain valuable: communication could reduce prices, increase volume without increasing prices, enable monitoring, or become less useful when observations are censored. The study is not contingent on finding stronger collusion or confirming the original cartel-defection framing.

## Preparation validation

Both review configurations were parsed through the actual `Protocol` model. They differ only in their communication flag and protocol identifier. All budget calculations use the runner's real worst-case request estimator. No implementation or configuration used by the active run was changed in this preparation.
