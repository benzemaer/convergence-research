# R1-T01 Validation Protocol Manifest Lock Evidence

This evidence records only paths, hashes, validator results, and gate values for R1-T01. It does not embed row-level payloads and does not copy generated DuckDB, Parquet, CSV, or JSONL contents.

## Run Record

`task_id`: R1-T01
`status`: completed
`run_id`: R1-T01-20260708T1300Z
`code_commit`: 2982ec0d3f674908f9527e938efbd7badf6de81a

## Locked Inputs

`config_path`: configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json
`config_sha256`: b7d6d132d7e70b7df3a52558108f50d6c82880eb294ac7832aa353be5740872f
`schema_path`: schemas/r1/r1_t01_validation_protocol_manifest_lock.schema.json
`schema_sha256`: 9fefd6a078cdf8163f1ba1244e36b7433d76b94b8e50624305cddeaea4f9f689
`task_doc_path`: docs/tasks/R1-T01_验证协议状态线假设与manifest锁定.md
`task_doc_sha256`: 0aa0f06b643925f5f16f006e1258aedaa9c44dbcd1f3e72c0f4aa51d0d60a764
`stage_doc_path`: docs/stages/R1_状态存在性、结构关系、稳定性与零模型检验.md
`stage_doc_sha256`: 47d056c119558e5f63cf89a61503613c79d78ddbcd3a11374f85583f95f150ce

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
