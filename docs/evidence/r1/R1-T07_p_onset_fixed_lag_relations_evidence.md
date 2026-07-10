# R1-T07 P 首入锚定的固定滞后结构关系 Evidence

`task_id`: R1-T07

`run_id`: R1-T07-20260710T1800Z

`code_commit`: eb800a828eda028d07913c143eb995169ab626a7

`config_sha256`: 04e77933c94bee8356d6e3a02aed4a2b88094cc77aa764952f7db5af8357bbff

`engineering_validator_status`: passed

`result_artifact_status`: passed

`author_result_analysis_status`: passed

`scientific_review_status`: pending

`anomaly_resolution_status`: passed

`downstream_gate_allowed`: false

`supersedes_run_id`: R1-T07-20260710T1510Z

`supersession_reason`: prior author-draft run used non-executed point bootstrap intervals, overlapping anchor funnel counts, constructed state reconciliation, and target-valid denominator mismatch in standardized baselines.

`result_analysis_path`: docs/experiments/r1/R1-T07_p_onset_fixed_lag_relations_result_analysis.md

`experiment_summary_path`: data/generated/r1/r1_t07/R1-T07-20260710T1800Z/r1_t07_experiment_summary.json

`experiment_summary_sha256`: 47bd9f168bb3ae9c64712f10bf8bc89de74c0a634631d3505593ce0350599eda

`anomaly_scan_path`: data/generated/r1/r1_t07/R1-T07-20260710T1800Z/r1_t07_anomaly_scan.json

`anomaly_scan_sha256`: eca378753cb204e58af7d884d636aacc3f53766e77a2b01e5f715f215275d36e

`engineering_validation_result_path`: data/generated/r1/r1_t07/R1-T07-20260710T1800Z/r1_t07_engineering_validation_result.json

`engineering_validation_result_sha256`: 7645771a94a23670b5b849e430607037db39259a9ece101609c4cf59842a7534

`primary_result_path`: data/generated/r1/r1_t07/R1-T07-20260710T1800Z/r1_t07_fixed_lag_profile.csv

`primary_result_sha256`: 0081d3146904a11c025072ac4832770f6c9153df451835e0c052bb888903d8bf

`primary_result_rows`: 225

`baseline_sensitivity_rows`: 225

`p_survival_rows`: 45

`anchor_target_status_rows`: 45

`anchor_funnel_rows`: 9

`year_lag_rows`: 2250

`security_lag_summary_rows`: 225

`state_reconciliation_rows`: 54

`q_onset_transition_rows`: 66

`lag_alignment_rows`: 45

`bootstrap_cluster_key`: security_id

`bootstrap_B_boot`: 2000

`bootstrap_seed`: 20260710

`bootstrap_interval_rows_written`: 225

`bootstrap_failed_replicates`: 0

`bootstrap_replicate_detail_written`: false

`anchor_funnel_accounting`: exact mutually exclusive partition passed

`state_reconciliation`: full outer key reconciliation and row-level ordered chain-AND reconstruction passed

`baseline_standardization_denominator`: aligned to per-lag target-valid event risk set

`expected_current_task`: R1-T07 P 首入锚定的固定滞后结构关系

`expected_next_planned_task`: R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型

`expected_downstream_gate_marker`: R1-T08_allowed_to_start: false

本 evidence 仅记录路径、hash、counts、gate 和 validator result，不嵌入逐行 payload。当前阶段为 author-draft，implementation actor 不得把 scientific review 标记为 passed，也不得推进 README gate。
