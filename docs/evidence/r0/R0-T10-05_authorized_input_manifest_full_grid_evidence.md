# R0-T10-05 Authorized Input Manifest And Full-Grid Evidence

This evidence records the repaired local formal R0-T10-05 authorized input manifest generation and 27-config artifact-backed full-grid materialization. It records only commands, paths, hashes, counts, coverage, validation status, and gates; it does not embed row-level payloads or copy generated DuckDB / Parquet contents.

## Run Record

`task_id`: R0-T10-05
`status`: completed
`run_id`: R0-T10-05-20260708T1754Z
`code_commit`: e97ce154b174d661f0628c19014485509c022547

`authorized_input_manifest_path`: `data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t10_05_authorized_input_manifest.json`
`authorized_input_manifest_sha256`: `d18d4841476abb80da804635d15d9b9b853e5fb9e40545288c445be27af713f9`
`authorized_r0_input`: true

## Source Evidence Hashes

`R0-T04_evidence_path`: `docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence_repair_20260708T1715Z.md`
`R0-T04_evidence_sha256`: `732a0fb622d1bc78d80383a35dd1a142a32626935e9b156216517f1291bc1df9`
`R0-T05_evidence_path`: `docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence_repair_20260708T1730Z.md`
`R0-T05_evidence_sha256`: `1ff5674690dad654d3f6f731e953748b90d5710ee65cb132e4b45177115d1a2f`
`R0-T06_evidence_path`: `docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence_repair_20260708T1740Z.md`
`R0-T06_evidence_sha256`: `255d3419be61bdb54a1c47696e416135ccbddaa7f6130da577f61cffc900e71a`
`R0-T07_evidence_path`: `docs/evidence/r0/R0-T10-04_r0_t07_confirmation_interval_materialization_evidence_repair_20260708T1746Z.md`
`R0-T07_evidence_sha256`: `1029c22daf3819db9cba12010c43f065e06a8deac8a880f67387d6175c0ee59e`

## Input Artifacts

`r0_t04_raw_metric_duckdb`: `data/generated/r0/r0_t10/R0-T10-01-20260708T1715Z/r0_t04/r0_t04_raw_metric_results.duckdb`
`r0_t04_raw_metric_sha256`: `89ff2979f8e151c1611c0c61b1b547783f76a4ad94953c9252b0ecef98ed56a0`
`r0_t04_raw_metric_row_count`: 13,846,152

`r0_t05_indicator_score_duckdb`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_indicator_score_results.duckdb`
`r0_t05_indicator_score_sha256`: `6da065875c8270e321910083409f4dba5c1ee63bc6328e56aff3a1d489924447`
`r0_t05_indicator_score_row_count`: 41,538,456
`r0_t05_dimension_score_duckdb`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_dimension_score_results.duckdb`
`r0_t05_dimension_score_sha256`: `4a04fbada9ecac15936e3ab5d968cba8f1205db5dbe66a0491c7141e6fc5b8a5`
`r0_t05_dimension_score_row_count`: 20,769,228
`r0_t05_common_eligible_duckdb`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_common_eligible_sample_results.duckdb`
`r0_t05_common_eligible_sha256`: `fa3f7bf59956339ae667c6e8680bb6c67a896bd344029d9c002c3eb394a96de1`
`r0_t05_common_eligible_row_count`: 1,730,769

`r0_t06_indicator_state_duckdb`: `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_indicator_state_results.duckdb`
`r0_t06_indicator_state_sha256`: `c82fda0c89265ed9b8d5fbbb4f4fec9ca64acfd8b0d2954b856841a72ef7cc2e`
`r0_t06_indicator_state_row_count`: 124,615,368
`r0_t06_dimension_state_duckdb`: `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_dimension_state_results.duckdb`
`r0_t06_dimension_state_sha256`: `bbbb49ea2056bf6f257c1821236eb2b657eb1490153dfc9e56acee8f33264e08`
`r0_t06_dimension_state_row_count`: 62,307,684
`r0_t06_nested_daily_state_duckdb`: `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_nested_daily_state_results.duckdb`
`r0_t06_nested_daily_state_sha256`: `0c07f4897d76c0a729963118c2e75581bd71521a25245d6d3b650b4f32e68995`
`r0_t06_nested_daily_state_row_count`: 15,576,921

`r0_t07_daily_confirmation_duckdb`: `data/generated/r0/r0_t10/R0-T10-04-20260708T1746Z/r0_t07/r0_t07_daily_confirmation_results.duckdb`
`r0_t07_daily_confirmation_sha256`: `e9bcaafbd60229b6d9e01967cedb2739efb3407159a66d1ef47b3d779689b4e3`
`r0_t07_daily_confirmation_row_count`: 186,923,052
`r0_t07_confirmed_interval_duckdb`: `data/generated/r0/r0_t10/R0-T10-04-20260708T1746Z/r0_t07/r0_t07_confirmed_interval_results.duckdb`
`r0_t07_confirmed_interval_sha256`: `583187e213edc7b9796d5db5ef0b5484ad4b3fb17624212796ea1b9a721208ad`
`r0_t07_confirmed_interval_row_count`: 1,012,396

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

`output_dir`: `data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t09_full_grid/`
`global_manifest_path`: `data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t09_full_grid/r0_t10_05_full_grid_manifest.json`
`global_manifest_sha256`: `b031ae22a3cf396961bcefcf6479c18870b8206a348372cf87d4b9f73c1fd96b`
`summary_path`: `data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t09_full_grid/r0_t10_05_execution_summary.json`
`summary_sha256`: `6a6d7e537d06a2418094bc24b42aa3da16cc7e324aeeb3fdf40e3dc9edefd646`
`validation_result_path`: `data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t09_full_grid/r0_t10_05_validation_result.json`
`validation_result_sha256`: `92642af2c275fed0d3d53aba0d38cc172864dea6508c8db77034d6aec4a08f86`

`daily_candidate_row_count_total`: 186,923,052
`confirmed_interval_row_count_total`: 1,012,396
`confirmed_interval_zero_config_count`: 0
`daily_confirmed_true_count_total`: 10,206,649
`zero_interval_reason_if_any`: null

`confirmed_interval_row_count_by_config`: R0_W120_Q10_K2=31,245; R0_W120_Q10_K3=24,889; R0_W120_Q10_K5=17,712; R0_W120_Q20_K2=56,694; R0_W120_Q20_K3=44,804; R0_W120_Q20_K5=31,388; R0_W120_Q30_K2=85,436; R0_W120_Q30_K3=68,715; R0_W120_Q30_K5=47,941; R0_W250_Q10_K2=23,452; R0_W250_Q10_K3=19,061; R0_W250_Q10_K5=14,029; R0_W250_Q20_K2=45,654; R0_W250_Q20_K3=36,064; R0_W250_Q20_K5=25,544; R0_W250_Q30_K2=70,797; R0_W250_Q30_K3=57,739; R0_W250_Q30_K5=40,775; R0_W500_Q10_K2=18,329; R0_W500_Q10_K3=14,954; R0_W500_Q10_K5=11,312; R0_W500_Q20_K2=37,089; R0_W500_Q20_K3=29,532; R0_W500_Q20_K5=20,917; R0_W500_Q30_K2=57,582; R0_W500_Q30_K3=47,211; R0_W500_Q30_K5=33,531
`daily_confirmed_true_count_by_config`: R0_W120_Q10_K2=217,073; R0_W120_Q10_K3=185,828; R0_W120_Q10_K5=140,174; R0_W120_Q20_K2=455,004; R0_W120_Q20_K3=398,310; R0_W120_Q20_K5=316,642; R0_W120_Q30_K2=754,709; R0_W120_Q30_K3=669,273; R0_W120_Q30_K5=543,637; R0_W250_Q10_K2=194,145; R0_W250_Q10_K3=170,693; R0_W250_Q10_K5=135,396; R0_W250_Q20_K2=414,005; R0_W250_Q20_K3=368,351; R0_W250_Q20_K5=302,434; R0_W250_Q30_K2=693,012; R0_W250_Q30_K3=622,215; R0_W250_Q30_K5=516,412; R0_W500_Q10_K2=170,226; R0_W500_Q10_K3=151,897; R0_W500_Q10_K5=124,124; R0_W500_Q20_K2=373,809; R0_W500_Q20_K3=336,720; R0_W500_Q20_K5=282,804; R0_W500_Q30_K2=623,865; R0_W500_Q30_K3=566,283; R0_W500_Q30_K5=479,608

## Execution Parameters

`max_workers`: 16
`duckdb_threads`: 1
`duckdb_memory_limit_per_worker`: 2GB
`process_pool_context`: spawn
`artifact_backed_streaming_input`: true
`monolithic_json_payload_mode`: false
`parent_receives_row_payload`: false
`resume_status`: initial repaired formal run completed without skipped configs
`DONE_marker_count`: 27
`FAILED_marker_count`: 0
`partial_artifact_used_as_completed`: false

## Commands

`authorized_manifest_command`: `python -m src.r0.r0_t10_authorized_input_manifest_builder_cli --output-dir data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z --run-id R0-T10-05-20260708T1754Z --code-commit e97ce154b174d661f0628c19014485509c022547`

`full_grid_materialization_command`: `python scripts/r0/run_r0_t10_05_full_grid.py --authorized-input-manifest data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t10_05_authorized_input_manifest.json --output-dir data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t09_full_grid --run-id R0-T10-05-20260708T1754Z --code-commit e97ce154b174d661f0628c19014485509c022547 --max-workers 16 --duckdb-threads 1 --duckdb-memory-limit-per-worker 2GB --resume`

`validator_command`: `python -m src.r0.r0_t10_full_grid_validator_cli --authorized-input-manifest data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t10_05_authorized_input_manifest.json --output-dir data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t09_full_grid`

`wrapper_validator_command`: `python scripts/r0/validate_r0_t10_05_full_grid.py --authorized-input-manifest data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t10_05_authorized_input_manifest.json --output-dir data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t09_full_grid`

## Validation And Gates

`validator_status`: passed
`source_evidence_check`: passed
`input_artifact_hash_check`: passed
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
