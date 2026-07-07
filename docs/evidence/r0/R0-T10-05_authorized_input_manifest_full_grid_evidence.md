# R0-T10-05 Authorized Input Manifest And Full-Grid Evidence

This evidence records the local formal R0-T10-05 authorized input manifest generation and 27-config artifact-backed full-grid materialization. It records only commands, paths, hashes, counts, coverage, validation status, and gates; it does not embed row-level payloads or copy generated DuckDB / Parquet contents.

## Run Record

`task_id`: R0-T10-05
`status`: completed
`run_id`: R0-T10-05-20260707T1845Z
`code_commit`: 3bef6cab84f15771e24b3db903e8fa1c2726ad81

`authorized_input_manifest_path`: `data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t10_05_authorized_input_manifest.json`
`authorized_input_manifest_sha256`: `77d92279e55ea8bb012390c033d4f4f1ada9cee2f284532cd4be733689d4a40e`
`authorized_r0_input`: true

## Source Evidence Hashes

`R0-T04_evidence_path`: `docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md`
`R0-T04_evidence_sha256`: `4a145e4363be47220e0cca55cdd92142bd422b2ee8f341a6c5ed7a114af59c31`
`R0-T05_evidence_path`: `docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md`
`R0-T05_evidence_sha256`: `6c4f14fa819b82f43e2a751a894f7f659d330edced57f26914cca8627d95a526`
`R0-T06_evidence_path`: `docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md`
`R0-T06_evidence_sha256`: `3996ede8d0f5df5f3084792e961e5e77c43e457ad2bfefc7d9b2192ac132c6f9`
`R0-T07_evidence_path`: `docs/evidence/r0/R0-T10-04_r0_t07_confirmation_interval_materialization_evidence.md`
`R0-T07_evidence_sha256`: `da5ab8cab732dd4fac7bd873b9569fa60dcd7fd6f0ad0be36518a9dccf0a5fd5`

## Input Artifacts

`r0_t04_raw_metric_duckdb`: `data/generated/r0/r0_t10/R0-T10-01-20260707T1345Z/r0_t04/r0_t04_raw_metric_results.duckdb`
`r0_t04_raw_metric_sha256`: `100f515de8e337c82e86e3f3760648df4229860dd83c16ac767065c4f2e16fc7`
`r0_t04_raw_metric_row_count`: 13,846,152

`r0_t05_indicator_score_duckdb`: `data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_indicator_score_results.duckdb`
`r0_t05_indicator_score_sha256`: `3061c07c0ab5074e54e1bbf83780c4fd3b2b065700314f1c1ca2f3524e83f944`
`r0_t05_indicator_score_row_count`: 41,538,456
`r0_t05_dimension_score_duckdb`: `data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_dimension_score_results.duckdb`
`r0_t05_dimension_score_sha256`: `8e371f1245933f763ea6328568a5d0025c0f17752d8c9f0c6c401f5ccc707942`
`r0_t05_dimension_score_row_count`: 20,769,228
`r0_t05_common_eligible_duckdb`: `data/generated/r0/r0_t10/R0-T10-02-20260707T1500Z/r0_t05/r0_t05_common_eligible_sample_results.duckdb`
`r0_t05_common_eligible_sha256`: `47cafa631016b24830cd600ed53f6cf96818fec06641fb92621b1f23f6f56c88`
`r0_t05_common_eligible_row_count`: 1,730,769

`r0_t06_indicator_state_duckdb`: `data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/r0_t06_indicator_state_results.duckdb`
`r0_t06_indicator_state_sha256`: `102aa8f912e4d006d716e1bd8148ac0daf2823b467beabc262875d9afaab4904`
`r0_t06_indicator_state_row_count`: 124,615,368
`r0_t06_dimension_state_duckdb`: `data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/r0_t06_dimension_state_results.duckdb`
`r0_t06_dimension_state_sha256`: `9f3707e92e8410919609a356b8532a80d992f4078f9e966aaa358b44bbcafc52`
`r0_t06_dimension_state_row_count`: 62,307,684
`r0_t06_nested_daily_state_duckdb`: `data/generated/r0/r0_t10/R0-T10-03-20260707T1630Z/r0_t06/r0_t06_nested_daily_state_results.duckdb`
`r0_t06_nested_daily_state_sha256`: `1a5aa1375a46e5909f16d64353908dd7ad1d0754078079136b0aae06263be9d4`
`r0_t06_nested_daily_state_row_count`: 15,576,921

`r0_t07_daily_confirmation_duckdb`: `data/generated/r0/r0_t10/R0-T10-04-20260707T1711Z/r0_t07/r0_t07_daily_confirmation_results.duckdb`
`r0_t07_daily_confirmation_sha256`: `643b988359823d89ca5d38b58716f6c5880aa0b45e0c81fe21bfe9faa991ae29`
`r0_t07_daily_confirmation_row_count`: 186,923,052
`r0_t07_confirmed_interval_duckdb`: `data/generated/r0/r0_t10/R0-T10-04-20260707T1711Z/r0_t07/r0_t07_confirmed_interval_results.duckdb`
`r0_t07_confirmed_interval_sha256`: `f6d662e7be4a8adb009aeee6c23edc849fc2dec9b7babbec004546dd108e81ea`
`r0_t07_confirmed_interval_row_count`: 0

`input_security_count`: 800
`input_date_min`: 20160104
`input_date_max`: 20260630

## Grid And Coverage

`grid_W_coverage`: 120 / 250 / 500
`grid_q_coverage`: 0.10 / 0.20 / 0.30
`grid_K_coverage`: 2 / 3 / 5
`weak_delta`: 0.10
`dimension_rule`: weak
`selected_config_count`: 27
`completed_config_count`: 27
`skipped_config_count`: 0
`failed_config_count`: 0
`baseline_config_id`: R0_W250_Q20_K3_WEAK_D010
`config_id_list_hash`: `eaac435ef84eb9a13eb2d32114c5ced6e6f0a9309e2c4e6fbb5bbe2c937eee67`

## Output Summary

`output_dir`: `data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t09_full_grid/`
`global_manifest_path`: `data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t09_full_grid/r0_t10_05_full_grid_manifest.json`
`global_manifest_sha256`: `a30d5bc7d1613637dbdfaa0f889f1f58719335bbf9831d95c079c6ba33ac1a96`
`summary_path`: `data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t09_full_grid/r0_t10_05_execution_summary.json`
`summary_sha256`: `d85a05619ae88371d5998c3733409dfee4f2813673935ae17dcae08d896cd398`
`validation_result_path`: `data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t09_full_grid/r0_t10_05_validation_result.json`
`validation_result_sha256`: `3344c707d4c1e830f4d67250db45bd6cc5f47a8ebb76b196b7b4d28d3cc1c022`

`daily_candidate_row_count_total`: 186,923,052
`confirmed_interval_row_count_total`: 0
`confirmed_interval_zero_config_count`: 27
`daily_confirmed_true_count_total`: 0
`zero_interval_reason_if_any`: no_confirmed_segments_in_r0_t07_input
`confirmed_interval_row_count_by_config`: all 27 configs = 0
`daily_confirmed_true_count_by_config`: all 27 configs = 0
`max_raw_streak_summary`: all sampled config/state max raw streak values = 0

## Execution Parameters

`max_workers`: 16
`duckdb_threads`: 1
`duckdb_memory_limit_per_worker`: 2GB
`process_pool_context`: spawn
`artifact_backed_streaming_input`: true
`monolithic_json_payload_mode`: false
`parent_receives_row_payload`: false
`resume_status`: initial formal run completed without skipped configs
`DONE_marker_count`: 27
`FAILED_marker_count`: 0
`partial_artifact_used_as_completed`: false

## Commands

`authorized_manifest_command`: `python -m src.r0.r0_t10_authorized_input_manifest_builder_cli --output-dir data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z --run-id R0-T10-05-20260707T1845Z --code-commit 3bef6cab84f15771e24b3db903e8fa1c2726ad81`

`full_grid_materialization_command`: `python -m src.r0.r0_t10_full_grid_materializer_cli --authorized-input-manifest data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t10_05_authorized_input_manifest.json --output-dir data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t09_full_grid --run-id R0-T10-05-20260707T1845Z --code-commit 3bef6cab84f15771e24b3db903e8fa1c2726ad81 --max-workers 16 --duckdb-threads 1 --duckdb-memory-limit-per-worker 2GB --resume`

`validator_command`: `python -m src.r0.r0_t10_full_grid_validator_cli --authorized-input-manifest data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t10_05_authorized_input_manifest.json --output-dir data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t09_full_grid`

`wrapper_validator_command`: `python scripts/r0/validate_r0_t10_05_full_grid.py --authorized-input-manifest data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t10_05_authorized_input_manifest.json --output-dir data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t09_full_grid`

## Validation And Gates

`validator_status`: passed
`forbidden_field_check`: passed
`legacy_v1_check`: passed
`synthetic_input_check`: passed
`raw_external_source_check`: passed
`full_code_commit_check`: passed
`manifest_contains_row_payload`: false
`summary_contains_row_payload`: false
`authorized_manifest_contains_row_payload`: false
`downstream_gate_allowed`: true
`R0-T11_allowed_to_start`: true
