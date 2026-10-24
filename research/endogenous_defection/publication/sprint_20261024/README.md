# Independent review packet — revised 24 October 2026

This packet combines the frozen sprint evidence with a revised manuscript and message review, derived tables, configurations, test evidence, and provenance indexes. The manuscript and message-review revisions respond to independent feedback against the committed code and tables. derived_checksums.json remains the original freeze manifest to preserve provenance. publication_checksums.json records current packet file hashes (except itself).

## Scope and status

- PAPER_DRAFT.md is a revised, still-unsubmitted manuscript draft. It includes the four completed Lambda truthful controls, references, an uncertainty summary, positive-control result, pre-sprint-work disclosure, and the required limitations/dual-use/ethics appendix.
- Author names and affiliations remain placeholders. The official template is linked from the [Apart sprint page](https://apartresearch.com/sprints/ai-collusion-research-sprint-2026-10-23-to-2026-10-25); opening its Google Docs copy redirected to sign-in in this environment. This packet is not represented as using that template, and no final PDF is included.
- MESSAGE_REVIEW.md separates historically omitted quotes from quotes also hidden in current displays. It records selected examples; exhaustive semantic coding remains open.
- market_outcomes.csv and paired_contrasts.csv summarize the four-seed, 16-market information-by-communication study. The evidence inventory retains the failed seed-24 full-visibility cell alongside completed cells.
- lambda_distortion_market_outcomes.csv and lambda_truthful_controls.csv are separate supplemental results; the revised manuscript compares them descriptively. Runs used the same provider/model/runtime and GPU class on distinct host instances.
- paired_quote_plan.json is the saved intervention plan; paired_quote_decisions.csv contains 48 accepted live decisions. The saved run status records 49/49 requests and host exit code 0.

## Validation record

../../VALIDATION.md is the historical 23 October offline validation report; it records 25 passing tests and distinguishes synthetic checks from live inference. mock_validation/ preserves the paired-probe mocked execution record: 49 requests, 48 decision rows, all accepted. The paired probe’s live result is separate from that mock. No tests were run as part of this manuscript revision.

## Full raw evidence and provenance

The full original run directories remain on the research machine under G:\collusion_hackathon\output\ and are excluded from this GitHub branch. They contain raw prompts, model responses, source snapshots, and verbose server logs. RAW_EVIDENCE_INDEX.md identifies each raw bundle and its SHA-256 seal/checksum-manifest hashes; the main study’s per-cell hashes and statuses are retained in evidence_inventory.json. The raw bundle files themselves were not edited during this revision. A reviewer needs a separately shared copy of those directories to inspect raw prompts and responses; committed tables and hashes do not substitute for raw access.

The paired-probe root manifest is retained as generated. Its final bundle-level verification has a known limitation: host.log differs from its recorded hash and host_exit.json is not listed in that manifest. The decision table, status, plan, host-exit record, and original checksum file remain included; neither raw file nor manifest was repaired or rewritten.

The original freeze hashes remain in derived_checksums.json. Editorial changes to PAPER_DRAFT.md, MESSAGE_REVIEW.md, and this README are identified by the current publication_checksums.json. The unchanged raw-evidence seals remain the source-of-record for the underlying observations.
