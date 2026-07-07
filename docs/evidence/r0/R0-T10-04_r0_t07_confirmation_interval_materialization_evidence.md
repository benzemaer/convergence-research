# R0-T10-04 R0-T07 Confirmation Interval Materialization Evidence

This evidence records a local formal R0-T07 materialization from PR #71 evidence-bound R0-T06 nested daily state artifacts. It records only commands, paths, hashes, counts, coverage, validation status, and gates; it does not embed row-level payloads or copy generated DuckDB / shard contents.

## Run Record

`task_id`: R0-T10-04
`status`: completed
`run_id`: R0-T10-04-20260707T1711Z
`code_commit`: 99a914d59b6563b5bd685d09ee5e7804a325c397

`input_r0_t06_evidence_path`: `docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md`
`input_nested_daily_state_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/r0_t06_nested_daily_state_results.duckdb`
`input_nested_daily_state_duckdb_sha256`: `1a5aa1375a46e5909f16d64353908dd7ad1d0754078079136b0aae06263be9d4`
`input_nested_daily_state_row_count`: 15,576,921
`input_security_count`: 800
`input_date_min`: 20160104
`input_date_max`: 20260630

`output_dir`: `data/generated/r0/r0_t10/R0-T10-04-20260707T1711Z/r0_t07/`
`daily_confirmation_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-04-20260707T1711Z/r0_t07/r0_t07_daily_confirmation_results.duckdb`
`daily_confirmation_duckdb_sha256`: `643b988359823d89ca5d38b58716f6c5880aa0b45e0c81fe21bfe9faa991ae29`
`confirmed_interval_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-04-20260707T1711Z/r0_t07/r0_t07_confirmed_interval_results.duckdb`
`confirmed_interval_duckdb_sha256`: `f6d662e7be4a8adb009aeee6c23edc849fc2dec9b7babbec004546dd108e81ea`
`manifest_path`: `data/generated/r0/r0_t10/R0-T10-04-20260707T1711Z/r0_t07/r0_t07_confirmation_interval_results_manifest.json`
`manifest_sha256`: `21d75966acc084ade48ebe2d6435f0da2e4f79422501016b7bfe1c4cd89a69bd`
`summary_path`: `data/generated/r0/r0_t10/R0-T10-04-20260707T1711Z/r0_t07/r0_t07_execution_summary.json`
`summary_sha256`: `5aa95a4586bb7662460946261e5a736bd8a9031bf9e5dc7d42caabe7fc82421b`

## Counts And Coverage

`daily_confirmation_row_count`: 186,923,052
`confirmed_interval_row_count`: 0
`security_count`: 800
`date_min`: 20160104
`date_max`: 20260630
`W_coverage`: 120 / 250 / 500
`q_coverage`: 0.10 / 0.20 / 0.30
`weak_delta`: 0.10
`K_coverage`: 2 / 3 / 5
`state_name_coverage`: S_P / S_PC / S_PCT / S_PCVT
`confirmed_state_distribution`: false=128,094,576; NULL=58,828,476
`raw_state_distribution`: false=128,094,576; true=8,070,483; NULL=50,757,993
`validity_status_distribution`: valid=128,094,576; unknown=58,697,748; blocked=130,728
`termination_reason_distribution`: none; no confirmed intervals in this R0-T07 artifact
`open_interval_count`: 0
`closed_interval_count`: 0

## Execution Parameters

`materialization_command`: `python -m src.r0.r0_t10_confirmation_interval_materializer_cli --r0-t06-evidence docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md --nested-daily-state-duckdb data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/r0_t06_nested_daily_state_results.duckdb --output-dir data/generated/r0/r0_t10/R0-T10-04-20260707T1711Z/r0_t07 --run-id R0-T10-04-20260707T1711Z --code-commit 99a914d59b6563b5bd685d09ee5e7804a325c397 --max-workers 16 --duckdb-threads 1 --duckdb-memory-limit-per-worker 2GB --chunk-size-securities 1 --resume`
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

`validator_command`: `python -m src.r0.r0_t10_confirmation_interval_materialization_validator_cli --output-dir data/generated/r0/r0_t10/R0-T10-04-20260707T1711Z/r0_t07 --r0-t06-evidence docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md --nested-daily-state-duckdb data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/r0_t06_nested_daily_state_results.duckdb`
`wrapper_validator_command`: `python scripts/r0/validate_r0_t10_04_materialization.py --output-dir data/generated/r0/r0_t10/R0-T10-04-20260707T1711Z/r0_t07 --r0-t06-evidence docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md --nested-daily-state-duckdb data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/r0_t06_nested_daily_state_results.duckdb`
`validator_status`: passed
`daily_recompute_sample_count`: 111
`daily_recompute_mismatch_count`: 0
`daily_recompute_W_coverage`: 120 / 250 / 500
`daily_recompute_q_coverage`: 0.10 / 0.20 / 0.30
`daily_recompute_K_coverage`: 2 / 3 / 5
`daily_recompute_state_name_coverage`: S_P / S_PC / S_PCT / S_PCVT
`confirmed_true_sample_count`: 0
`confirmed_true_sample_status`: skipped; confirmed_true_absent in real artifact
`raw_false_sample_count`: 3
`raw_non_ready_sample_count`: 108
`interval_recompute_sample_count`: 0
`interval_recompute_mismatch_count`: 0
`interval_recompute_skipped_reasons`: open_interval_absent / closed_interval_absent / false_termination_absent / non_ready_termination_absent
`open_interval_sample_count`: 0
`closed_interval_sample_count`: 0
`false_termination_sample_count`: 0
`non_ready_termination_sample_count`: 0
`confirmed_nested_invariant_check`: passed
`no_backfill_check`: passed
`forbidden_field_check`: passed
`legacy_v1_check`: passed
`future_return_absence_check`: passed
`full_code_commit_check`: passed

`downstream_gate_allowed`: true
`R0-T10-05_allowed_to_start`: true
