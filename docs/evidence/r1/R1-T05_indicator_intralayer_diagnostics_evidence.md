# R1-T05 Indicator Intralayer Diagnostics Evidence

`task_id`: R1-T05
`task_class`: formal_experiment
`status`: completed
`run_id`: R1-T05-20260710T0959Z
`code_commit`: 5a9de4d94f294e849fd9be87238917558d55ce54

`engineering_validator_status`: passed
`result_artifact_status`: passed
`author_result_analysis_status`: passed
`scientific_review_status`: passed
`anomaly_resolution_status`: passed
`review_phase`: independent_review_complete

`supersedes_run_id`: R1-T05-20260710T0918Z
`supersession_reason`: scientific review found incorrect individual hit denominator, joint segment gap handling, missing percentile bucket artifact, and ambiguous validity reason denominator. The superseded run package is marked `superseded=true`.

`experiment_summary_path`: data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_experiment_summary.json
`experiment_summary_sha256`: 70276a55f7409674994bba9ddb3061c38b0c3f2dfc7834e42b1490de9c000028
`primary_result_artifacts`:
- data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_indicator_raw_distribution.csv / a3996867d2a8ed5d29e55065fc2f40fef83d80e3af3c9dfed973dd6ec19e0c09 / 8 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_indicator_score_distribution.csv / 45a2a7256fb0651f44c4b9e6091bcf2012dc95c393dced4f2d5b96d2e6be9f37 / 24 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_indicator_percentile_bucket_distribution.csv / 0b7b4b4e46f7025fee4cb5323efce24cad0ee81644b857eceb0d011ddd1c29ae / 240 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_indicator_hit_duration.csv / 54ab887c02369799491fae044bb866c4fa912e7ecd82c525435375ede6eaa2a8 / 72 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_intralayer_correlation.csv / 85bd32d34c12fed94bf83d7fb7423661495d8f416a6c3a728770c9e3465860d5 / 12 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_intralayer_threshold_structure.csv / 0d31862d6b42fe67d5d31fcd7c8fda627e90aa0c285861efdaed9d60509d06e3 / 36 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_intralayer_diagnostic_summary.csv / 4d57094d86d510551159ad3a2ac9f3b6881d10186533ba4512ca2a6fa55c5252 / 12 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_validity_reason_profile.csv / b9710d5f1145fe2163900b5009f7d21924643feb94c6ab67af473248e027b7be / 146 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_r0_t06_reconciliation.csv / 3b9725b6401af777e9ba400d4356def558a540646d782e509aa7e6c387ebf776 / 72 rows
`diagnostic_summary_path`: data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_diagnostic_summary.json
`diagnostic_summary_sha256`: be374b1efb2f4e4f825476de08aebca5ffc98eb7a045caf7dbc37fd2982bbfff
`engineering_validation_result_path`: data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_engineering_validation_result.json
`engineering_validation_result_sha256`: e87616c3b97403d6838d6e26bd246d14205dd82b625302f6006d9c12cf2dd364
`result_analysis_path`: docs/experiments/r1/R1-T05_indicator_intralayer_diagnostics_result_analysis.md
`result_analysis_sha256`: 5c9b930359e35724b55c9cb49f465065844da85ca3caa9fb5c923b2b2f220ab6
`anomaly_scan_path`: data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_anomaly_scan.json
`anomaly_scan_sha256`: 1561e287d0d813c17b1acf5efde3abf980cac0acc815e9b1e72b4bfe3d1ab80b
`formal_evidence_path`: docs/evidence/r1/R1-T05_indicator_intralayer_diagnostics_evidence.md
`formal_evidence_sha256`: computed in result package
`scientific_review_path`: data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_scientific_review.json
`scientific_review_sha256`: 3cb54ff8fe7892b9686f7f7a0c487d9fd2d4ad40470c2e36d0265c149a4aa0e6
`scientific_review_md_path`: docs/reviews/r1/R1-T05_indicator_intralayer_diagnostics_scientific_review.md
`scientific_review_md_sha256`: c1faddb78311c53615f39fd754e74d39971f756c13cb7cb2081348acb4a93d46
`readme_path`: docs/tasks/README.md
`readme_sha256`: 03288e409b594e7474fbb3a44740ec4b0e909423eb0c3df5e4075ae6d69d4371
`expected_current_stage`: R1
`expected_current_task`: R1-T06 层间同期留存、关联 Lift 与嵌套增量
`expected_next_planned_task`: R1-T07 S_PCT/S_PCVT 预注册配置的同步性零模型
`expected_downstream_gate_marker`: R1-T06_allowed_to_start: true

`superseded`: false
`superseded_by`: null
`downstream_gate_allowed`: true

## Formal Run

Command:

```bash
python -m src.r1.r1_t05_indicator_intralayer_diagnostics_cli --output-dir data/generated/r1/r1_t05/R1-T05-20260710T0959Z --run-id R1-T05-20260710T0959Z --code-commit 5a9de4d94f294e849fd9be87238917558d55ce54
```

Task-specific validation:

```bash
python -m src.r1.r1_t05_indicator_intralayer_diagnostics_validator_cli --summary data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_experiment_summary.json --output data/generated/r1/r1_t05/R1-T05-20260710T0959Z/r1_t05_engineering_validation_result.json
```

## Gate Notes

R1-T04 final gate passed before this run. Repaired R0-T10-01/T10-02/T10-03 input hashes, row counts, security counts and date ranges matched the locked config. Independent scientific review passed, downstream gate is allowed, and README has advanced to R1-T06.

The previous run `R1-T05-20260710T0918Z` is superseded and must not be used as current R1-T05 evidence.
