# R1-T02 R0 产物接收、lineage 与无前视复检 evidence

`task_id`: R1-T02
`status`: completed
`validator_status`: passed
`run_id`: R1-T02-20260708T1820Z
`code_commit`: e97ce154b174d661f0628c19014485509c022547

`summary_path`: data/generated/r1/r1_t02/R1-T02-20260708T1820Z/r1_t02_lineage_pit_audit_summary.json
`summary_sha256`: e5e1b7fef464363e662397e10eee97c2b04b9eb0435406f8446e13718aeb9d6f
`validation_result_path`: data/generated/r1/r1_t02/R1-T02-20260708T1820Z/r1_t02_lineage_pit_audit_validation_result.json
`validation_result_sha256`: e2afc49cd237b233607cd0e5e436601add70ac2d15e720acac42ccda996709e0

`config_path`: configs/r1/r1_t02_r0_lineage_pit_audit.v1.json
`config_sha256`: bf52e25c5745fe60560a6d1b8e398e36787ee1458a3e8104a6d05a7313991193
`r1_t01_evidence_path`: docs/evidence/r1/R1-T01_validation_protocol_manifest_lock_evidence.md
`r1_t01_evidence_sha256`: 441a5a218ac182179aa5fb0386e5f0024078bc35228999a90608881008b3d40a
`r0_t10_05_evidence_path`: docs/evidence/r0/R0-T10-05_authorized_input_manifest_full_grid_evidence.md
`r0_t10_05_evidence_sha256`: 25b6176de27add5532bb0a3809b6b7e0fd8403ef350f82685faa9cb5a0a52dab
`r0_t11_evidence_path`: docs/evidence/r0/R0-T11_r0_audit_report_r1_handoff_evidence.md
`r0_t11_evidence_sha256`: f6e16acb25b929ff3f96dbadec10b0253a9031e47943de6646a4b564a0eac65c
`r0_strict_past_evidence_path`: docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence_repair_20260708T1730Z.md
`r0_strict_past_evidence_sha256`: 1ff5674690dad654d3f6f731e953748b90d5710ee65cb132e4b45177115d1a2f

`authorized_input_manifest_path`: data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t10_05_authorized_input_manifest.json
`authorized_input_manifest_sha256`: d18d4841476abb80da804635d15d9b9b853e5fb9e40545288c445be27af713f9
`full_grid_manifest_path`: data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t09_full_grid/r0_t10_05_full_grid_manifest.json
`full_grid_manifest_sha256`: b031ae22a3cf396961bcefcf6479c18870b8206a348372cf87d4b9f73c1fd96b

`selected_config_count`: 27
`completed_config_count`: 27
`failed_config_count`: 0
`daily_candidate_row_count_total`: 186923052
`confirmed_interval_row_count_total`: 1012396
`daily_confirmed_true_count_total`: 10206649
`confirmed_interval_zero_config_count`: 0
`zero_interval_reason`: null

`row_payload_embedded`: false
`forbidden_input_check`: passed
`forbidden_output_check`: passed
`no_future_label_check`: passed
`no_backtest_check`: passed
`no_trading_signal_check`: passed
`config_artifact_hash_check`: passed
`zero_interval_consistency_check`: passed
`strict_past_evidence_chain_check`: passed
`strict_past_artifact_field_check`: evidence_chain_only
`unknown_blocked_semantics_check`: passed
`confirmation_time_backfill_check`: passed
`forbidden_column_absence_check`: passed
`row_payload_absence_check`: passed

`R1-T03_allowed_to_start`: true
`R1-T07_allowed_to_start`: false
`R2_allowed_to_start`: false

## 说明

本 evidence 只记录 manifest、evidence、artifact path/hash、行数摘要和门禁状态。R1-T02 未扫描日频状态行，未计算结构统计、零模型、未来标签、回测、组合或交易信号；strict-past artifact field check 仅按 R0 strict-past evidence chain 复核，未声称重新读取行级 artifact 字段。修复后的 R0-T10-05 package 已包含非零 confirmed interval，R1-T03 可以基于该修复包重新执行轻量结构扫描；R1-T07 和 R2 仍保持阻塞。
