# R1-T05 Indicator Intralayer Diagnostics Evidence

`task_id`: R1-T05
`task_class`: formal_experiment
`status`: author_analysis_complete
`run_id`: R1-T05-20260710T0918Z
`code_commit`: c6899a9a3e840f749291dc57fb70f22e58e082e5

`engineering_validator_status`: passed
`result_artifact_status`: passed
`author_result_analysis_status`: passed
`scientific_review_status`: pending
`anomaly_resolution_status`: passed
`review_phase`: author_analysis_complete

`experiment_summary_path`: data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_experiment_summary.json
`experiment_summary_sha256`: 4938ed1391fd6c482f995c14e2a3cdd61405f5c3df9217d5606bb5c9138e82cb
`primary_result_artifacts`:
- data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_indicator_raw_distribution.csv / a3996867d2a8ed5d29e55065fc2f40fef83d80e3af3c9dfed973dd6ec19e0c09 / 8 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_indicator_score_distribution.csv / 45a2a7256fb0651f44c4b9e6091bcf2012dc95c393dced4f2d5b96d2e6be9f37 / 24 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_indicator_hit_duration.csv / 7eceb10ccc9bf0d7747936ec187cf891da3c10d65a159c431a1436d12d891d63 / 72 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_intralayer_correlation.csv / 80bb612b98ad6770c77eb7930f18ea0a2739489f953c4348b44be145849c3d6c / 12 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_intralayer_threshold_structure.csv / ae6a897a0c09e2c29567de534260e041510b69c18d02bd9d7a0746100796e91f / 36 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_intralayer_diagnostic_summary.csv / a6879852a4627118e6a89c16574bb811d21f707db77affb28be64d8d2c73ed1f / 12 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_validity_reason_profile.csv / 0d839dafca445fa10d9997bfad33e3535327c8cf7a7c7edcfd91161a6b1f62c2 / 146 rows
- data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_r0_t06_reconciliation.csv / 3b9725b6401af777e9ba400d4356def558a540646d782e509aa7e6c387ebf776 / 72 rows
`diagnostic_summary_path`: data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_diagnostic_summary.json
`diagnostic_summary_sha256`: 4e21a27c31c0713024de30bfa22c4fde57fff6f144299cf866395c7ec4aa7edf
`engineering_validation_result_path`: data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_engineering_validation_result.json
`engineering_validation_result_sha256`: 62621c9bd3f78e17bfd76488c983e6dc3f884141fac59cf47a52422709e7972f
`result_analysis_path`: docs/experiments/r1/R1-T05_indicator_intralayer_diagnostics_result_analysis.md
`result_analysis_sha256`: 662f9c6bb30204b9364bd00ada8dbf0de22ad4605f154e5849b39c2fee9cc15d
`anomaly_scan_path`: data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_anomaly_scan.json
`anomaly_scan_sha256`: af0023d4c42ab24b2f3b5e669127870263301f4ecc4af0080ff9b73b7b1e2768
`formal_evidence_path`: docs/evidence/r1/R1-T05_indicator_intralayer_diagnostics_evidence.md
`formal_evidence_sha256`: computed in result package
`scientific_review_path`: null
`scientific_review_sha256`: null
`scientific_review_md_path`: null
`scientific_review_md_sha256`: null
`readme_path`: docs/tasks/README.md
`readme_sha256`: cbf15eefd58bd28223db83a4fbd0a657056afd8dd30b3dc98c4c5826b7786104
`expected_current_stage`: R1
`expected_current_task`: R1-T05 单指标诊断与层内互补性分析
`expected_next_planned_task`: R1-T06 层间同期留存、关联 Lift 与嵌套增量
`expected_downstream_gate_marker`: R1-T06_allowed_to_start: false

`superseded`: false
`superseded_by`: null
`downstream_gate_allowed`: false

## Formal Run

Command:

```bash
python -m src.r1.r1_t05_indicator_intralayer_diagnostics_cli --output-dir data/generated/r1/r1_t05/R1-T05-20260710T0918Z --run-id R1-T05-20260710T0918Z --code-commit c6899a9a3e840f749291dc57fb70f22e58e082e5
```

Task-specific validation:

```bash
python -m src.r1.r1_t05_indicator_intralayer_diagnostics_validator_cli --summary data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_experiment_summary.json --output data/generated/r1/r1_t05/R1-T05-20260710T0918Z/r1_t05_engineering_validation_result.json
```

## Gate Notes

R1-T04 final gate passed before this run. Repaired R0-T10-01/T10-02/T10-03 input hashes, row counts, security counts and date ranges matched the locked config. Author-draft stops with `scientific_review_status=pending`, `downstream_gate_allowed=false`, and README still on R1-T05.
