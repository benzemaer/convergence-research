# R0-T10-02 R0-T05 Strict-Past Score Materialization Evidence

## Summary

`task_id`: R0-T10-02

`status`: completed

`run_id`: R0-T10-02-20260707T1500Z

`code_commit`: bc0920f811bf683ecffbb81a5ce9119cb4858256

This evidence records a local real-data R0-T05 strict-past score materialization from the PR #69 R0-T04 evidence-bound DuckDB artifact. It records only paths, hashes, counts, coverage, parameter values, and validation results. It does not embed row-level payloads and does not commit generated DuckDB or JSONL.gz shard contents.

## Input

`input_evidence`: `docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md`

`input_artifact`: `data/generated/r0/r0_t10/R0-T10-01-20260707T1345Z/r0_t04/r0_t04_raw_metric_results.duckdb`

`input_artifact_hash`: `100f515de8e337c82e86e3f3760648df4229860dd83c16ac767065c4f2e16fc7`

`input_row_count`: 13,846,152

`input_security_count`: 800

`input_date_min`: 20160104

`input_date_max`: 20260630

`input_source_status`: R0-T04 consumed a D3-T11 candidate generated with warnings; D3 formal data version remains unpublished. This R0-T05 run is an R-stage consumer-readiness materialization from the authorized R0-T04 candidate artifact, not a D3 formal release.

## Command

```powershell
python scripts/r0/run_r0_t10_02_materialize_scores.py `
  --r0-t04-evidence docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md `
  --r0-t04-duckdb data/generated/r0/r0_t10/R0-T10-01-20260707T1345Z/r0_t04/r0_t04_raw_metric_results.duckdb `
  --output-dir data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05 `
  --run-id R0-T10-02-20260707T1500Z `
  --code-commit bc0920f811bf683ecffbb81a5ce9119cb4858256 `
  --max-workers 16 `
  --duckdb-threads 1 `
  --duckdb-memory-limit-per-worker 2GB `
  --chunk-size-securities 1 `
  --resume
```

## Output

`output_dir`: `data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/`

`indicator_score_duckdb`: `data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_indicator_score_results.duckdb`

`indicator_score_duckdb_sha256`: `3061c07c0ab5074e54e1bbf83780c4fd3b2b065700314f1c1ca2f3524e83f944`

`dimension_score_duckdb`: `data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_dimension_score_results.duckdb`

`dimension_score_duckdb_sha256`: `8e371f1245933f763ea6328568a5d0025c0f17752d8c9f0c6c401f5ccc707942`

`common_eligible_duckdb`: `data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_common_eligible_sample_results.duckdb`

`common_eligible_duckdb_sha256`: `47cafa631016b24830cd600ed53f6cf96818fec06641fb92621b1f23f6f56c88`

`manifest_path`: `data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_score_results_manifest.json`

`manifest_sha256`: `8dcbbd1a5fce9ad4e4ec6b71631065aadf14ae7820fbf766889b7c75c0dca4ec`

`summary_path`: `data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_execution_summary.json`

`summary_sha256`: `fb7f9ebd0bd2bf83b5b8cd678658a008861608cdd0d106ef3e1f58655140a15d`

`indicator_score_row_count`: 41,538,456

`dimension_score_row_count`: 20,769,228

`common_eligible_row_count`: 1,730,769

`security_count`: 800

`date_min`: 20160104

`date_max`: 20260630

`shard_count`: 800

## Worker And Memory Boundary

`max_workers`: 16

`duckdb_threads`: 1

`duckdb_memory_limit_per_worker`: 2GB

`chunk_size_securities`: 1

`parent_holds_upstream_rows`: false

`parent_summary_only`: true

`worker_returns_rows`: false

`duckdb_written_by_native_bulk_read`: true

`process_pool_context`: spawn

## Coverage And Distribution

`W_coverage`: 120, 250, 500

`indicator_coverage`: `C1_LogMASpread_5_60`, `C2_AdjVWAPSpread_5_60`, `P1_NATR14`, `P2_LogRange20`, `T1_ER20`, `T2_AbsTrendT20`, `V1_TurnoverShrink20_60`, `V2_AmountLevel20Pct`

`dimension_coverage`: `C`, `P`, `T`, `V`

`indicator_validity_distribution`: `valid=30,942,351`, `unknown=10,494,864`, `blocked=101,241`

`indicator_eligible_distribution`: `true=30,942,351`, `false=10,596,105`

`dimension_validity_distribution`: `valid=13,205,780`, `unknown=7,462,207`, `blocked=101,241`

`dimension_eligible_distribution`: `true=13,205,780`, `false=7,563,448`

`common_eligible_distribution`: `true=0`, `false=1,730,769`

## Resume And Marker Status

`completed_chunk_count`: 0

`skipped_chunk_count`: 800

`failed_chunk_count`: 0

`DONE_marker_count`: 800

`FAILED_marker_count`: 0

`partial_artifact_used_as_completed`: false

The initial materialization populated all 800 chunk shards. The recorded command above was the final resume run after the marker-path validation fix; it skipped all completed chunks by DONE marker and rebuilt the authoritative DuckDB outputs, manifest, and execution summary.

## Validation

```powershell
python scripts/r0/validate_r0_t10_02_materialization.py `
  --output-dir data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05
```

Validation result:

`validator_status`: passed

`strict_past_validator_status`: passed

`future_leakage_check`: passed

`current_value_in_reference_set_check`: passed

`midrank_tie_check`: passed

`amount_level_repeated_percentile_check`: passed

`forbidden_field_check`: passed

`legacy_v1_check`: passed

`DuckDB table exists`: true

`DuckDB row count equals manifest row count`: true

`shard row count sum equals manifest row count`: true

`manifest output hash reproducible`: true

`security_count matches distinct security_id`: true

`date_min/date_max matches actual data`: true

`manifest_contains_row_payload`: false

`summary_contains_row_payload`: false

## Downstream Gate

`R0-T06_allowed_to_start`: true

R0-T06 is allowed to start only because this evidence shows completed R0-T05 materialization and validator-passed row count, security count, date range, output hashes, shard consistency, strict-past checks, coverage checks, forbidden field checks, legacy V1 checks, resume marker checks, and manifest/summary no-row-payload checks. This evidence does not authorize R0-T09 full-grid execution and does not create an R0-T09 authorized input manifest.
