# Independent review packet — 24 October 2026

This packet combines the frozen sprint manuscript and message review with the
derived tables, configurations, test evidence, and provenance indexes needed to
review the work. The manuscript and message review are copied from
`output/evidence_freeze_20261024_v1`; `derived_checksums.json` records the
original SHA-256 values. Supplemental Lambda and paired-probe tables are copied
verbatim from their saved outputs. They are not silently folded into the frozen
manuscript's findings.

## Scope and status

- `PAPER_DRAFT.md` is an exploratory draft, not a submission-ready paper.
- `MESSAGE_REVIEW.md` records mechanical matches and selected manual review;
  exhaustive independent semantic coding remains open.
- `market_outcomes.csv` and `paired_contrasts.csv` summarize the four-seed,
  16-market information-by-communication study. The evidence inventory retains
  the failed seed-24 full-visibility cell alongside completed cells.
- `lambda_distortion_market_outcomes.csv` and
  `lambda_truthful_controls.csv` are separate supplementary results. The latter
  has four completed Lambda control markets; it is not yet incorporated into
  the manuscript's provider-confounded distortion comparison.
- `paired_quote_plan.json` is the saved intervention plan;
  `paired_quote_decisions.csv` contains 48 accepted live decisions. The saved
  run status records 49/49 requests and host exit code 0.

## Validation record

`../../VALIDATION.md` is the historical 23 October offline validation report; it
records 25 passing tests and explicitly distinguishes synthetic checks from
live inference. `mock_validation/` preserves the paired-probe mocked execution
record: 49 requests, 48 decision rows, all accepted. The paired probe's live
result is separate from that mock. No tests were run as part of this packaging
step.

## Full raw evidence

The full original run directories remain on the research machine under
`G:\collusion_hackathon\output\`. They are not included in this GitHub commit:
they contain raw prompts, model responses, source snapshots, and verbose server
logs. The local raw evidence index is in `RAW_EVIDENCE_INDEX.md`; the main study
cell seal hashes are in `evidence_inventory.json`. A reviewer needs a separately
shared copy of those directories to inspect raw prompts and responses. The
committed tables and hashes do not substitute for access to the raw evidence.

The paired-probe root manifest is retained as generated. Its final bundle-level
verification has a known packaging limitation: `host.log` differs from the
recorded hash and `host_exit.json` is not listed in that manifest. The recorded
decision table and status are included, and the manuscript discloses this
limitation; no raw file or manifest was repaired or rewritten here.

`publication_checksums.json` hashes every file in this packet except itself.
