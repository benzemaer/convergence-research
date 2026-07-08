# R0 blocker C2 readiness / state validity / full-grid repair evidence

`task_id`: R0-BLOCKER-C2-readiness-state-validity-fullgrid-repair
`status`: completed
`code_commit`: 234fea0f04486dacf684515db62ddb5670259d96

`C2_alias_fix`: passed
`state_specific_validity_fix`: passed
`formal_r0_rerun_performed`: true

`R0_T10_01_run_id`: R0-T10-01-20260708T1715Z
`R0_T10_02_run_id`: R0-T10-02-20260708T1730Z
`R0_T10_03_run_id`: R0-T10-03-20260708T1740Z
`R0_T10_04_run_id`: R0-T10-04-20260708T1746Z
`R0_T10_05_run_id`: R0-T10-05-20260708T1754Z

`authorized_manifest_path`: data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t10_05_authorized_input_manifest.json
`authorized_manifest_sha256`: d18d4841476abb80da804635d15d9b9b853e5fb9e40545288c445be27af713f9
`full_grid_manifest_path`: data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t09_full_grid/r0_t10_05_full_grid_manifest.json
`full_grid_manifest_sha256`: b031ae22a3cf396961bcefcf6479c18870b8206a348372cf87d4b9f73c1fd96b

`C2_valid_rate_before`: 0.000000
`C2_valid_rate_before_basis`: superseded old R0 package observed C2 blocked by missing required adjusted VWAP aliases
`C2_row_count_after`: 1730769
`C2_valid_count_after`: 1659385
`C2_valid_rate_after`: 0.958756
`C2_raw_value_null_count_after`: 71384
`C2_raw_value_null_rate_after`: 0.041244
`C_dimension_active_true_count_after`: 2795737

`S_P_raw_true_count_after`: 2690161
`S_PC_raw_true_count_after`: 1253587
`S_PCT_raw_true_count_after`: 399013
`S_PCVT_raw_true_count_after`: 123129
`S_P_confirmed_true_count_after`: 6667026
`S_PC_confirmed_true_count_after`: 2887479
`S_PCT_confirmed_true_count_after`: 504939
`S_PCVT_confirmed_true_count_after`: 147205
`S_P_confirmed_interval_count_after`: 489251
`S_PC_confirmed_interval_count_after`: 301501
`S_PCT_confirmed_interval_count_after`: 168810
`S_PCVT_confirmed_interval_count_after`: 52834

`daily_candidate_row_count_total`: 186923052
`daily_confirmed_true_count_total`: 10206649
`confirmed_interval_row_count_total`: 1012396
`selected_config_count`: 27
`completed_config_count`: 27
`failed_config_count`: 0
`zero_interval_config_count`: 0

`R1_relock_performed`: true
`R1_T01_relocked_to_repaired_R0`: true
`R1_T02_relocked_to_repaired_R0`: true
`R1_T03_relocked_to_repaired_R0`: true
`R1_T04_allowed_to_start`: true
`R1_T07_allowed_to_start`: false
`R2_allowed_to_start`: false
`do_not_use_old_R1_artifacts`: true
`blocked_reason`: none

## 说明

本 evidence 记录 R0 blocker 的修复结果：C2 readiness alias 恢复、nested state 输出 state-specific validity、confirmation interval 使用状态线自身 validity，并完成 R0-T10-01 至 R0-T10-05 的正式重跑。旧 R1-T03 draft PR #77 中基于 superseded zero-package 得出的 S_PC / S_PCT / S_PCVT 退化结论不得作为后续研究依据。
