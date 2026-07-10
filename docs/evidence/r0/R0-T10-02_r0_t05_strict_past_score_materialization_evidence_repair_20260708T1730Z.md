# R0-T10-02 R0-T05 Strict-Past Score Materialization Evidence Repair 20260708T1730Z

## Summary

`task_id`: R0-T10-02

`status`: completed

`run_id`: R0-T10-02-20260708T1730Z

`code_commit`: 9195dfebebe71802c582d4094fbaec2427c46d27

This evidence records the repaired R0-T05 strict-past score materialization from the repaired R0-T04 raw metrics artifact. It records only paths, hashes, counts, coverage, parameter values, and validation results. It does not embed row-level payloads and does not commit generated DuckDB or JSONL.gz shard contents.

## Input

`input_evidence`: `docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence_repair_20260708T1715Z.md`

`input_artifact`: `data/generated/r0/r0_t10/R0-T10-01-20260708T1715Z/r0_t04/r0_t04_raw_metric_results.duckdb`

`input_artifact_hash`: `89ff2979f8e151c1611c0c61b1b547783f76a4ad94953c9252b0ecef98ed56a0`

`input_row_count`: 13,846,152

`input_security_count`: 800

`input_date_min`: 20160104

`input_date_max`: 20260630

## Command

```powershell
python scripts/r0/run_r0_t10_02_materialize_scores.py `
  --r0-t04-evidence docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence_repair_20260708T1715Z.md `
  --r0-t04-duckdb data/generated/r0/r0_t10/R0-T10-01-20260708T1715Z/r0_t04/r0_t04_raw_metric_results.duckdb `
  --output-dir data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05 `
  --run-id R0-T10-02-20260708T1730Z `
  --code-commit 9195dfebebe71802c582d4094fbaec2427c46d27 `
  --max-workers 16 `
  --duckdb-threads 1 `
  --duckdb-memory-limit-per-worker 2GB `
  --chunk-size-securities 1 `
  --resume
```

## Output

`output_dir`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/`

`indicator_score_duckdb`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_indicator_score_results.duckdb`

`indicator_score_duckdb_sha256`: `6da065875c8270e321910083409f4dba5c1ee63bc6328e56aff3a1d489924447`

`dimension_score_duckdb`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_dimension_score_results.duckdb`

`dimension_score_duckdb_sha256`: `4a04fbada9ecac15936e3ab5d968cba8f1205db5dbe66a0491c7141e6fc5b8a5`

`common_eligible_duckdb`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_common_eligible_sample_results.duckdb`

`common_eligible_duckdb_sha256`: `fa3f7bf59956339ae667c6e8680bb6c67a896bd344029d9c002c3eb394a96de1`

`manifest_path`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_score_results_manifest.json`

`manifest_sha256`: `6b99afcc236d81734c42dd4acfbfdc684762cb0de232185c65ae0a87e141daaa`

`summary_path`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_execution_summary.json`

`summary_sha256`: `9e1836716b2d56f05d0f68529c15e09b5a136be248dfb957b832cd1a6336d32c`

`indicator_score_row_count`: 41,538,456

`dimension_score_row_count`: 20,769,228

`common_eligible_row_count`: 1,730,769

`security_count`: 800

`date_min`: 20160104

`date_max`: 20260630

`shard_count`: 800

`completed_chunk_count`: 800

`failed_chunk_count`: 0

## C-Layer Repair Check

`C2_AdjVWAPSpread_5_60_score_valid_count`: 4,287,463

`C2_AdjVWAPSpread_5_60_score_unknown_count`: 807,329

`C2_AdjVWAPSpread_5_60_score_blocked_count`: 97,515

`C_dimension_valid_count`: 4,287,463

`C_dimension_unknown_count`: 807,329

`C_dimension_blocked_count`: 97,515

## Validation

```powershell
python scripts/r0/validate_r0_t10_02_materialization.py `
  --output-dir data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05 `
  --r0-t04-duckdb data/generated/r0/r0_t10/R0-T10-01-20260708T1715Z/r0_t04/r0_t04_raw_metric_results.duckdb
```

`validator_status`: passed

`strict_past_validator_status`: passed

`future_leakage_check`: passed

`current_value_in_reference_set_check`: passed

`midrank_tie_check`: passed

`amount_level_repeated_percentile_check`: passed

`forbidden_field_check`: passed

`legacy_v1_check`: passed

`manifest_contains_row_payload`: false

`summary_contains_row_payload`: false

## Downstream Gate

`R0-T06_allowed_to_start`: true

R0-T06 is allowed to start because this evidence shows completed repaired R0-T05 materialization and validator-passed row count, security count, date range, output hashes, shard consistency, strict-past checks, coverage checks, forbidden field checks, legacy V1 checks, and manifest/summary no-row-payload checks.
