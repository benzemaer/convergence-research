# R1-T02 R0 产物接收、lineage 与无前视复检 evidence

`task_id`: R1-T02
`status`: completed
`validator_status`: passed
`run_id`: R1-T02-20260708T1420Z
`code_commit`: 10504538d36a58c17a10ba28580bb95b26d2cf7b

`summary_path`: data/generated/r1/r1_t02/R1-T02-20260708T1420Z/r1_t02_lineage_pit_audit_summary.json
`summary_sha256`: 96c5b566c03953d90d2944413b0a11955c36ebf54f4a3328fad4aaa6b29d4ab9
`validation_result_path`: data/generated/r1/r1_t02/R1-T02-20260708T1420Z/r1_t02_lineage_pit_audit_validation_result.json
`validation_result_sha256`: 95bebb39a37261a7e2d09ffc595788ed58938f62a1bbf98668282eff5f522a0d

`config_path`: configs/r1/r1_t02_r0_lineage_pit_audit.v1.json
`config_sha256`: 772a26936da330b138995f192336ec1f967325ccf987a3d2a34639ca90a9c833
`r1_t01_evidence_path`: docs/evidence/r1/R1-T01_validation_protocol_manifest_lock_evidence.md
`r1_t01_evidence_sha256`: d79f6573e9982a265e6f032673b32e17bdbf56cafd54df3025ee234af6d550ae
`r0_t10_05_evidence_path`: docs/evidence/r0/R0-T10-05_authorized_input_manifest_full_grid_evidence.md
`r0_t10_05_evidence_sha256`: 507b75bcbfc39afd72955e6b1b585c73a3c855cdbf080c1718c7e745b26e40ac
`r0_t11_evidence_path`: docs/evidence/r0/R0-T11_r0_audit_report_r1_handoff_evidence.md
`r0_t11_evidence_sha256`: 46e0e8c7f27d305238698043e2f5ea31f4666dc21ad4cc547dabbc16c053a24e
`r0_strict_past_evidence_path`: docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md
`r0_strict_past_evidence_sha256`: 6c4f14fa819b82f43e2a751a894f7f659d330edced57f26914cca8627d95a526

`authorized_input_manifest_path`: data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t10_05_authorized_input_manifest.json
`authorized_input_manifest_sha256`: 77d92279e55ea8bb012390c033d4f4f1ada9cee2f284532cd4be733689d4a40e
`full_grid_manifest_path`: data/generated/r0/r0_t10/R0-T10-05-20260707T1845Z/r0_t09_full_grid/r0_t10_05_full_grid_manifest.json
`full_grid_manifest_sha256`: a30d5bc7d1613637dbdfaa0f889f1f58719335bbf9831d95c079c6ba33ac1a96

`selected_config_count`: 27
`completed_config_count`: 27
`failed_config_count`: 0
`daily_candidate_row_count_total`: 186923052
`confirmed_interval_row_count_total`: 0
`daily_confirmed_true_count_total`: 0
`confirmed_interval_zero_config_count`: 27
`zero_interval_reason`: no_confirmed_segments_in_r0_t07_input

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
`confirmation_time_backfill_check`: skipped_zero_interval_input_fact
`forbidden_column_absence_check`: passed
`row_payload_absence_check`: passed

`R1-T03_allowed_to_start`: true
`R1-T07_allowed_to_start`: false
`R2_allowed_to_start`: false

## 说明

本 evidence 只记录 manifest、evidence、artifact path/hash、行数摘要和门禁状态。R1-T02 未扫描日频状态行，未计算结构统计、零模型、未来标签、回测、组合或交易信号；strict-past artifact field check 仅按 R0 strict-past evidence chain 复核，未声称重新读取行级 artifact 字段。R1-T03 可以开始轻量结构扫描，但 R1-T07 和 R2 仍保持阻塞。
