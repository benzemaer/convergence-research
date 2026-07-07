# R0-T10-03 R0-T06 Nested State Materialization Evidence

This evidence records a local formal R0-T06 materialization from PR #70 evidence-bound R0-T05 score artifacts. It records only commands, paths, hashes, counts, coverage, validation status, and gates; it does not embed row-level payloads or copy generated DuckDB / shard contents.

## Run Record

`task_id`: R0-T10-03
`status`: completed
`run_id`: R0-T10-03-20260707T1630Z
`code_commit`: 92dcceefd710de40a65daa7d0e414bd7708f5353

`input_r0_t05_evidence_path`: `docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md`
`input_indicator_score_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_indicator_score_results.duckdb`
`input_indicator_score_duckdb_sha256`: `3061c07c0ab5074e54e1bbf83780c4fd3b2b065700314f1c1ca2f3524e83f944`
`input_dimension_score_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_dimension_score_results.duckdb`
`input_dimension_score_duckdb_sha256`: `8e371f1245933f763ea6328568a5d0025c0f17752d8c9f0c6c401f5ccc707942`
`input_common_eligible_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_common_eligible_sample_results.duckdb`
`input_common_eligible_duckdb_sha256`: `47cafa631016b24830cd600ed53f6cf96818fec06641fb92621b1f23f6f56c88`
`input_indicator_score_row_count`: 41,538,456
`input_dimension_score_row_count`: 20,769,228
`input_common_eligible_row_count`: 1,730,769
`input_security_count`: 800
`input_date_min`: 20160104
`input_date_max`: 20260630

`output_dir`: `data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/`
`indicator_state_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/r0_t06_indicator_state_results.duckdb`
`indicator_state_duckdb_sha256`: `102aa8f912e4d006d716e1bd8148ac0daf2823b467beabc262875d9afaab4904`
`dimension_state_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/r0_t06_dimension_state_results.duckdb`
`dimension_state_duckdb_sha256`: `9f3707e92e8410919609a356b8532a80d992f4078f9e966aaa358b44bbcafc52`
`nested_daily_state_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/r0_t06_nested_daily_state_results.duckdb`
`nested_daily_state_duckdb_sha256`: `1a5aa1375a46e5909f16d64353908dd7ad1d0754078079136b0aae06263be9d4`
`manifest_path`: `data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/r0_t06_nested_state_results_manifest.json`
`manifest_sha256`: `214ff8e33432d7892e6d59b2a498893f772c6603a92ed71090d15ce8b7162f48`
`summary_path`: `data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/r0_t06_execution_summary.json`
`summary_sha256`: `d9b32bb9d5f0d0bd1066b30e0d144a352a7d9253692466072a702760daeb1989`

## Counts And Coverage

`indicator_state_row_count`: 124,615,368
`dimension_state_row_count`: 62,307,684
`nested_daily_state_row_count`: 15,576,921
`security_count`: 800
`date_min`: 20160104
`date_max`: 20260630
`W_coverage`: 120 / 250 / 500
`q_coverage`: 0.10 / 0.20 / 0.30
`weak_delta`: 0.10
`indicator_coverage`: P1_NATR14, P2_LogRange20, C1_LogMASpread_5_60, C2_AdjVWAPSpread_5_60, T1_ER20, T2_AbsTrendT20, V1_TurnoverShrink20_60, V2_AmountLevel20Pct
`dimension_coverage`: P / C / T / V
`exclusive_state_layer_distribution`: BLOCKED=10,894; NONE=10,674,548; UNKNOWN=4,891,479
`nested_state_true_distribution`: S_P_raw=2,690,161; S_PC_raw=0; S_PCT_raw=0; S_PCVT_raw=0
`unknown_distribution`: nested_daily_state validity_status unknown=4,891,479
`blocked_distribution`: nested_daily_state validity_status blocked=10,894
`diagnostic_distribution`: nested_daily_state validity_status diagnostic_required=0

## Execution Parameters

`materialization_command`: `python -m src.r0.r0_t10_nested_state_materializer_cli --r0-t05-evidence docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md --indicator-score-duckdb data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_indicator_score_results.duckdb --dimension-score-duckdb data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_dimension_score_results.duckdb --common-eligible-duckdb data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_common_eligible_sample_results.duckdb --output-dir data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06 --run-id R0-T10-03-20260707T1630Z --code-commit 92dccee --max-workers 16 --duckdb-threads 1 --duckdb-memory-limit-per-worker 2GB --chunk-size-securities 1 --resume`
`max_workers`: 16
`duckdb_threads`: 1
`duckdb_memory_limit_per_worker`: 2GB
`chunk_size_securities`: 1
`process_pool_context`: spawn
`duckdb_write_strategy`: Parquet shards per security chunk; final authoritative DuckDB tables built with DuckDB `CREATE TABLE AS SELECT * FROM read_parquet(...)`; no Python row-by-row insert path; no custom WAL autocheckpoint setting.

## Resume And Markers

`resume_status`: initial formal run completed without skipped chunks
`completed_chunk_count`: 800
`skipped_chunk_count`: 0
`failed_chunk_count`: 0
`DONE_marker_count`: 800
`FAILED_marker_count`: 0
`partial_artifact_used_as_completed`: false
`manifest_contains_row_payload`: false
`summary_contains_row_payload`: false

## Validation

`validator_command`: `python -m src.r0.r0_t10_nested_state_materialization_validator_cli --output-dir data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06 --r0-t05-evidence docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md --indicator-score-duckdb data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_indicator_score_results.duckdb --dimension-score-duckdb data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_dimension_score_results.duckdb --common-eligible-duckdb data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_common_eligible_sample_results.duckdb`
`wrapper_validator_command`: `python scripts/r0/validate_r0_t10_03_materialization.py --output-dir data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06 --r0-t05-evidence docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md --indicator-score-duckdb data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_indicator_score_results.duckdb --dimension-score-duckdb data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_dimension_score_results.duckdb --common-eligible-duckdb data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_common_eligible_sample_results.duckdb`
`validator_status`: passed
`nested_recompute_sample_count`: 10
`nested_recompute_mismatch_count`: 0
`nested_recompute_W_coverage`: 120 / 250 / 500
`nested_recompute_q_coverage`: 0.10 / 0.20 / 0.30
`nested_recompute_dimension_coverage`: P / C / T / V
`nested_recompute_check`: passed
`nested_invariant_check`: passed
`exclusive_layer_recompute_check`: passed
`exclusive_layer_uniqueness_check`: passed
`forbidden_field_check`: passed
`legacy_v1_check`: passed
`confirmation_field_absence_check`: passed
`K_absence_check`: passed

`downstream_gate_allowed`: true
`R0-T07_allowed_to_start`: true
