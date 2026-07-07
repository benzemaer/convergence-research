# R0-T10-01 R0-T04 Raw Metrics Materialization Evidence

## Summary

`task_id`: R0-T10-01

`status`: completed

`run_id`: R0-T10-01-20260707T1345Z

`code_commit`: 7ea2e649f0c9f0d04614cbbe7240747b98adec39

This evidence records a local real-data R0-T04 raw metrics materialization from the canonical D3-T11 candidate observation artifact. It records only paths, hashes, counts, parameter values, and validation results. It does not embed row-level payloads and does not commit generated DuckDB or JSONL.gz shard contents.

## Input

`input_source`: `data/generated/d3/d3_t11_volume_amount_share_turnover_candidate/d3_t11_volume_amount_share_turnover_candidate.duckdb`

`source_table`: `d3_t11_volume_amount_share_turnover_candidate`

`input_artifact_hash`: `57707f6ed5e821bd837029e3f0a8f42c1e1a0ecc432002df959a71064177f103`

`input_row_count`: 1,730,769

`input_security_count`: 800

`input_source_status`: D3-T11 candidate generated with warnings; D3 formal data version remains unpublished and downstream R-stage consumer readiness is evaluated by R0 tasks.

## Command

```powershell
python scripts/r0/run_r0_t10_01_materialize_raw_metrics.py `
  --d3-duckdb data/generated/d3/d3_t11_volume_amount_share_turnover_candidate/d3_t11_volume_amount_share_turnover_candidate.duckdb `
  --source-table d3_t11_volume_amount_share_turnover_candidate `
  --output-dir data/generated/r0/r0_t10/R0-T10-01-20260707T1345Z/r0_t04 `
  --run-id R0-T10-01-20260707T1345Z `
  --code-commit 7ea2e649f0c9f0d04614cbbe7240747b98adec39 `
  --max-workers 6 `
  --duckdb-threads 1 `
  --duckdb-memory-limit-per-worker 2GB `
  --chunk-size-securities 1 `
  --resume
```

## Output

`output_dir`: `data/generated/r0/r0_t10/R0-T10-01-20260707T1345Z/r0_t04/`

`output_duckdb`: `data/generated/r0/r0_t10/R0-T10-01-20260707T1345Z/r0_t04/r0_t04_raw_metric_results.duckdb`

`output_duckdb_sha256`: `100f515de8e337c82e86e3f3760648df4229860dd83c16ac767065c4f2e16fc7`

`manifest_path`: `data/generated/r0/r0_t10/R0-T10-01-20260707T1345Z/r0_t04/r0_t04_raw_metric_results_manifest.json`

`manifest_sha256`: `820c741ba69a7b4d2657f8a79c94fa22c45e78f599be5466c05c40acd67cce65`

`summary_path`: `data/generated/r0/r0_t10/R0-T10-01-20260707T1345Z/r0_t04/r0_t04_execution_summary.json`

`summary_sha256`: `2dd20ac270a012e8c8ceb5e9bb4ced7ce335d1e3fe9a4f0c61ab7a330ef4cf36`

`row_count`: 13,846,152

`security_count`: 800

`date_min`: 20160104

`date_max`: 20260630

`shard_count`: 800

`global_content_hash`: `09def86cffcd7c5a1bbe062f64aecea9ccba934aeb9b127ff28ba0d1d6a9b318`

## Worker And Memory Boundary

`max_workers`: 6

`duckdb_threads`: 1

`duckdb_memory_limit_per_worker`: 2GB

`chunk_size_securities`: 1

`parent_holds_all_securities`: false

`parent_holds_all_dates`: false

`parent_holds_upstream_rows`: false

`worker_returns_rows`: false

`duckdb_written_by_stream_append`: true

## Validation

```powershell
python scripts/r0/validate_r0_t10_01_materialization.py `
  --output-dir data/generated/r0/r0_t10/R0-T10-01-20260707T1345Z/r0_t04
```

Validation result:

`status`: passed

`DuckDB table exists`: true

`DuckDB row count`: 13,846,152

`manifest row count`: 13,846,152

`shard row count sum`: 13,846,152

`security_count`: 800

`date_min`: 20160104

`date_max`: 20260630

`forbidden_field_check`: passed

`legacy_v1_check`: passed

`indicator_id_coverage`: `C1_LogMASpread_5_60`, `C2_AdjVWAPSpread_5_60`, `P1_NATR14`, `P2_LogRange20`, `T1_ER20`, `T2_AbsTrendT20`, `V1_TurnoverShrink20_60`, `V2_LogAmount20_base`

`manifest_contains_row_payload`: false

`summary_contains_row_payload`: false

## Downstream Gate

`R0-T05_allowed_to_start`: true

R0-T05 is allowed to start only because this evidence shows completed R0-T04 materialization and validator-passed row count, security count, date range, output hash, shard consistency, forbidden field checks, legacy V1 checks, and manifest/summary no-row-payload checks. This evidence does not authorize R0-T09 full-grid execution and does not create an R0-T09 authorized input manifest.
