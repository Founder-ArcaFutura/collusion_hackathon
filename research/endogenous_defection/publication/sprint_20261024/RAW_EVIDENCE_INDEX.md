# Raw evidence locations and seal hashes

All paths below are relative to the local repository root unless marked
otherwise. Full raw bundles remain at `G:\collusion_hackathon\output\` and are
excluded from this publication commit. A cell's `checksums.json` is the bundle
file manifest; the SHA-256 values below identify those manifest files. For the
main information study, per-cell seal hashes and statuses are recorded in
`evidence_inventory.json`.

## Main information-by-communication study

| Raw evidence | Status coverage | Checksum record |
|---|---|---|
| `output/information_study_20261024_095806_35d3842f/cells/` | Seeds 20–21; all four conditions per seed complete | Per-cell SHA-256 of `checksums.json` in `evidence_inventory.json` |
| `output/information_study_20261024_122407_31b6457e/cells/` | Seeds 22–23 complete; seed 24 full-on failed and retained | Per-cell SHA-256 of `checksums.json` in `evidence_inventory.json` |

The frozen inventory file's SHA-256 is
`40afa4d097dd39be5301c37c7810db52ebe2a215d59410a550063f733d164735`.
It lists all 17 relevant cells, including the failed seed-24 cell, with their
original source paths and seal hashes.

## Supplemental live runs

| Raw evidence | Status | SHA-256 of `checksums.json` |
|---|---|---|
| `output/lambda_distortion_results_20261024/pilot/cells/seed_20_distort_off` | Complete | `239c1ab6624e7bc7b33b550ab46ddcb40ae229e0a723cb813a4ff5ff11b377fc` |
| `output/lambda_distortion_results_20261024/pilot/cells/seed_20_distort_on` | Complete | `88a662eb0324a73d42487fd18da85f87e8abdbd8a3fcc46f0f94ae274981f5e2` |
| `output/lambda_distortion_results_20261024/pilot/cells/seed_21_distort_off` | Complete | `39df0ea9b6333f25bf96e7df3547144d3bfa2e51aebea1e25c22523ad6b7e463` |
| `output/lambda_distortion_results_20261024/pilot/cells/seed_21_distort_on` | Complete | `a2c291d2a44d56fbd4014e261359ef78ca2874889c267157e57947a602738d8f` |
| `output/lambda_truthful_recovered_20261024/controls/seed_20_full_off` | Complete | `c280e7622b6a6f516c755fd336887762ab9c226090b7d1a40260206a22d94bde` |
| `output/lambda_truthful_recovered_20261024/controls/seed_20_full_on` | Complete | `b94710e5276c78a4f2573d4cd1888899070f1986e1cf2939a3f8c77aae0dcc33` |
| `output/lambda_truthful_recovered_20261024/controls/seed_21_full_off` | Complete | `e3564372422dc4cc6b3e89bfe7b1463bd37fc6a46a633389ebc2a66930d5d88c` |
| `output/lambda_truthful_recovered_20261024/controls/seed_21_full_on` | Complete | `8983998439c097b8048f39e4cc503e2801ebe7b138b6a141c3129dacae7c28de` |

The recovered truthful-control batch has `control_status.json` status
`complete`. Its GPU/runtime metadata and four saved cell manifests remain in
the raw directory. The separate `lambda_truthful_20261024_160803_0bc9e63d`
source export corresponds to the Docker-permission startup failure; that
attempt stopped before inference and is not counted as a control result.

## Paired quote probe and validation

| Raw evidence | Status | SHA-256 of `checksums.json` |
|---|---|---|
| `output/paired_quote_e819adc5cf/` | Live run complete; 49 requests, 48 accepted decisions, host exit 0 | `9765d2dbe387ff4efaaea84637246e179a1f77cea6f3b2ead0b20ee6c0932fde` |
| `output/paired_quote_mock_validation_v2/` | Mock run complete; 49 requests, 48 accepted decisions | `f53bde42f65ed22c7346fc46aece893843762a617b892ef3618a68306e5b55ba` |

The live paired-probe manifest is preserved as generated but does not validate
as a complete root seal: the recorded `host.log` hash differs from the current
file, and `host_exit.json` is unlisted. The live decision CSV, status, plan,
host-exit record, and original checksum file are included in this packet. This
does not repair the raw bundle or upgrade its root seal to verified.

## Earlier technical failures

Versioned failed baseline and smoke attempts remain documented in
`research/endogenous_defection/LIVE_ATTEMPT_002.md`,
`research/endogenous_defection/LIVE_ATTEMPT_003.md`, and
`research/endogenous_defection/BASELINE_REVIEW.md`. Their complete raw
directories remain under `output/`; they were not deleted or overwritten for
this publication step.
