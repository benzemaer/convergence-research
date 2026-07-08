# R1-T01 Validation Protocol Manifest Lock Evidence

This evidence records only paths, hashes, validator results, and gate values for R1-T01. It does not embed row-level payloads and does not copy generated DuckDB, Parquet, CSV, or JSONL contents.

## Run Record

`task_id`: R1-T01
`status`: completed
`run_id`: R1-T01-20260708T1815Z
`code_commit`: e97ce154b174d661f0628c19014485509c022547
`evidence_record_commit_note`: this evidence record is finalized in the following commit and records the validated code tree commit above

## Locked Inputs

`config_path`: configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json
`config_sha256`: e91b679b1d0c3fc6054a144ad3dd02a81a9a745bb4251beeb8cafa1a10408fa0
`schema_path`: schemas/r1/r1_t01_validation_protocol_manifest_lock.schema.json
`schema_sha256`: a79b9d7a4f2df35349615899e53a32e133f1dfd44f3cdc8f712b6400a091e731
`task_doc_path`: docs/tasks/R1-T01_验证协议状态线假设与manifest锁定.md
`task_doc_sha256`: 0aa0f06b643925f5f16f006e1258aedaa9c44dbcd1f3e72c0f4aa51d0d60a764
`stage_doc_path`: docs/stages/R1_状态存在性、结构关系、稳定性与零模型检验.md
`stage_doc_sha256`: f4697440b107b4d81716928006e058f20aae201a2ceac5e20cff0e44073ec15c

## R0 Input Package Lock

`r0_t10_05_run_id`: R0-T10-05-20260708T1754Z
`r0_t10_05_evidence_path`: docs/evidence/r0/R0-T10-05_authorized_input_manifest_full_grid_evidence.md
`r0_t10_05_evidence_sha256`: 25b6176de27add5532bb0a3809b6b7e0fd8403ef350f82685faa9cb5a0a52dab
`r0_t11_evidence_path`: docs/evidence/r0/R0-T11_r0_audit_report_r1_handoff_evidence.md
`r0_t11_evidence_sha256`: f6e16acb25b929ff3f96dbadec10b0253a9031e47943de6646a4b564a0eac65c
`authorized_input_manifest_path`: data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t10_05_authorized_input_manifest.json
`authorized_input_manifest_sha256`: d18d4841476abb80da804635d15d9b9b853e5fb9e40545288c445be27af713f9
`full_grid_manifest_path`: data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t09_full_grid/r0_t10_05_full_grid_manifest.json
`full_grid_manifest_sha256`: b031ae22a3cf396961bcefcf6479c18870b8206a348372cf87d4b9f73c1fd96b
`daily_candidate_row_count_total`: 186923052
`confirmed_interval_row_count_total`: 1012396
`daily_confirmed_true_count_total`: 10206649
`zero_interval_reason_if_any`: null
`selected_config_count`: 27
`completed_config_count`: 27
`failed_config_count`: 0
`baseline_config_id`: R0_W250_Q20_K3_WEAK_D010
`W_coverage`: [120,250,500]
`q_coverage`: [0.1,0.2,0.3]
`K_coverage`: [2,3,5]
`weak_delta`: 0.1
`dimension_rule`: weak

## Validation

`validator_command`: python -m src.r1.r1_t01_manifest_lock_validator_cli
`wrapper_validator_command`: python scripts/r1/validate_r1_t01_manifest_lock.py
`validator_status`: passed

## Protocol Values

`state_lines_registered`: S_PCT,S_PCVT
`reference_config`: W250_q20_K3 reference_baseline
`all_27_configs_light_profile`: true
`raw_confirmed_mode`: dual_line
`r2_decision_basis`: confirmed_state
`primary_null_model`: P_fixed_independent_CTV_circular_shift
`N_perm`: 2000
`lag_set`: [1,3,5,10,20]
`year_stability_required`: true
`future_labels_forbidden`: true
`decision_status_enum_registered`: true

## Gates

`forbidden_input_check`: passed
`forbidden_output_check`: passed
`no_future_label_check`: passed
`no_backtest_check`: passed
`no_trading_signal_check`: passed
`no_parameter_optimization_claim_check`: passed
`manifest_contains_row_payload`: false
`summary_contains_row_payload`: false
`R1-T02_allowed_to_start`: true
`R2_allowed_to_start`: false
