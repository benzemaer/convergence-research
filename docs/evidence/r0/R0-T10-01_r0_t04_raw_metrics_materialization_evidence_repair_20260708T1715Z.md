# R0-T10-01 R0-T04 Raw Metrics Materialization Evidence Repair 20260708T1715Z

## Summary

`task_id`: R0-T10-01

`status`: completed

`run_id`: R0-T10-01-20260708T1715Z

`code_commit`: 9195dfebebe71802c582d4094fbaec2427c46d27

This evidence records the repaired R0-T04 raw metrics materialization after restoring C2 readiness aliases and policy propagation. It records only paths, hashes, counts, parameter values, and validation results. It does not embed row-level payloads and does not commit generated DuckDB or JSONL.gz shard contents.

## Input

`input_source`: `data/generated/d3/d3_t11_volume_amount_share_turnover_candidate/d3_t11_volume_amount_share_turnover_candidate.duckdb`

`source_table`: `d3_t11_volume_amount_share_turnover_candidate`

`input_artifact_hash`: `57707f6ed5e821bd837029e3f0a8f42c1e1a0ecc432002df959a71064177f103`

`input_row_count`: 1,730,769

`input_security_count`: 800

`input_date_min`: 20160104

`input_date_max`: 20260630

## Command

```powershell
python scripts/r0/run_r0_t10_01_materialize_raw_metrics.py `
  --d3-duckdb data/generated/d3/d3_t11_volume_amount_share_turnover_candidate/d3_t11_volume_amount_share_turnover_candidate.duckdb `
  --source-table d3_t11_volume_amount_share_turnover_candidate `
  --output-dir data/generated/r0/r0_t10/R0-T10-01-20260708T1715Z/r0_t04 `
  --run-id R0-T10-01-20260708T1715Z `
  --code-commit 9195dfebebe71802c582d4094fbaec2427c46d27 `
  --max-workers 6 `
  --duckdb-threads 1 `
  --duckdb-memory-limit-per-worker 2GB `
  --chunk-size-securities 1 `
  --resume
```

## Output

`output_dir`: `data/generated/r0/r0_t10/R0-T10-01-20260708T1715Z/r0_t04/`

`output_duckdb`: `data/generated/r0/r0_t10/R0-T10-01-20260708T1715Z/r0_t04/r0_t04_raw_metric_results.duckdb`

`output_duckdb_sha256`: `89ff2979f8e151c1611c0c61b1b547783f76a4ad94953c9252b0ecef98ed56a0`

`manifest_path`: `data/generated/r0/r0_t10/R0-T10-01-20260708T1715Z/r0_t04/r0_t04_raw_metric_results_manifest.json`

`manifest_sha256`: `1380d87ffe99215983c026c6a2027ab7b53ce84334b7d7c82ec19a92612d2e1c`

`summary_path`: `data/generated/r0/r0_t10/R0-T10-01-20260708T1715Z/r0_t04/r0_t04_execution_summary.json`

`summary_sha256`: `57a05a9a0c61cfe78c86de26452a55a330d435d681a3290479f05b39b3af9f4a`

`row_count`: 13,846,152

`security_count`: 800

`date_min`: 20160104

`date_max`: 20260630

`shard_count`: 800

`completed_chunk_count`: 800

`failed_chunk_count`: 0

## C2 Readiness Repair Check

`C2_AdjVWAPSpread_5_60_valid_count`: 1,659,385

`C2_AdjVWAPSpread_5_60_unknown_count`: 38,879

`C2_AdjVWAPSpread_5_60_blocked_count`: 32,505

The repaired run uses D3 `high/low` as raw high/low aliases, `amount_yuan/volume_shares` as amount/volume aliases, and upstream VWAP policy fields. It does not use close as a VWAP substitute.

## Validation

```powershell
python scripts/r0/validate_r0_t10_01_materialization.py `
  --output-dir data/generated/r0/r0_t10/R0-T10-01-20260708T1715Z/r0_t04
```

`validator_status`: passed

`DuckDB row count`: 13,846,152

`manifest row count`: 13,846,152

`shard row count sum`: 13,846,152

`security_count`: 800

`date_min`: 20160104

`date_max`: 20260630

`forbidden_field_check`: passed

`legacy_v1_check`: passed

`manifest_contains_row_payload`: false

`summary_contains_row_payload`: false

## Downstream Gate

`R0-T05_allowed_to_start`: true

R0-T05 is allowed to start because this evidence shows completed repaired R0-T04 materialization and validator-passed row count, security count, date range, output hash, shard consistency, forbidden field checks, legacy V1 checks, and manifest/summary no-row-payload checks.
