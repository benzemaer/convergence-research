# R1-T06 Contemporaneous Retention Lift Nested Increment Evidence

`task_id`: R1-T06
`task_class`: formal_experiment
`status`: author_analysis_complete
`run_id`: R1-T06-20260710T1155Z
`code_commit`: e98a529e1c828ed4b7ce9fdad24f4120717ef533

`engineering_validator_status`: passed
`result_artifact_status`: passed
`author_result_analysis_status`: passed
`scientific_review_status`: pending
`anomaly_resolution_status`: passed
`review_phase`: author_analysis_complete

`experiment_summary_path`: data/generated/r1/r1_t06/R1-T06-20260710T1155Z/r1_t06_experiment_summary.json
`experiment_summary_sha256`: de94d6d59086875c1236c61ec0d47c24c817abc773bed6bf9387697da5e85bf7
`primary_result_artifacts`: r1_t06_layer_step_profile.csv sha256=0c9f42ef9a0e872b57ae6351d1a2d42b2c1e793f5cd284bb5a333b862d71cd24 rows=27; r1_t06_denominator_sensitivity.csv sha256=3829c9e07ab1df05204c8d9306e82ec9fbcde38bb47265128bf7863a4f389655 rows=27; r1_t06_year_step_profile.csv sha256=f1f90060a56cb1f492a018e7e179388831e54c1fcbb9bde2e111947e507b8d03 rows=270; r1_t06_security_step_summary.csv sha256=f8a6aedb9267b37d214c7b70981812c8a2efd493071e0884fcaf6786e21c76f6 rows=27; r1_t06_r0_nested_reconciliation.csv sha256=b756a27caa3094c365d7e7c0b44a7d7f53699d30752c6ea634f35f5073fd323f rows=36; r1_t06_dimension_state_reconciliation.csv sha256=0b1e32e2146b45eb664326c24df8c426b2e917ff756bbe45434e8357cb496460 rows=36; r1_t06_q_nesting_reconciliation.csv sha256=18c89a3776c91a9b747b4ca566d83fdfe0caa897b9a793dce52d003afaf74240 rows=78
`diagnostic_summary_path`: data/generated/r1/r1_t06/R1-T06-20260710T1155Z/r1_t06_diagnostic_summary.json
`diagnostic_summary_sha256`: 8737987d94182b31968de172a5eb987a50c67f91652336d805dff7e18ddb4e63
`engineering_validation_result_path`: data/generated/r1/r1_t06/R1-T06-20260710T1155Z/r1_t06_engineering_validation_result.json
`engineering_validation_result_sha256`: 1f63676c00efd166481141c6b615eb46a95fca4c2a1d7bdc90fd3e429cd7babf
`result_analysis_path`: docs/experiments/r1/R1-T06_contemporaneous_retention_lift_nested_increment_result_analysis.md
`result_analysis_sha256`: d75199f44bb2e07adb2eabfd023b4d60c4b23903d210a9a55ea5fb061d442c3e
`anomaly_scan_path`: data/generated/r1/r1_t06/R1-T06-20260710T1155Z/r1_t06_anomaly_scan.json
`anomaly_scan_sha256`: 00a5062f6de8adab7bc50fc10bb7a7665f77f0143ac8f597cf93c368c2e082c2
`formal_evidence_path`: docs/evidence/r1/R1-T06_contemporaneous_retention_lift_nested_increment_evidence.md
`formal_evidence_sha256`: computed_by_result_package
`scientific_review_path`: null
`scientific_review_sha256`: null
`scientific_review_md_path`: null
`scientific_review_md_sha256`: null
`readme_path`: docs/tasks/README.md
`readme_sha256`: f5635353b5ecc54da8cc02668c97f1a297d0ba700d9940b10e820ad645797bd6
`expected_current_stage`: R1
`expected_current_task`: R1-T06 层间同期留存、关联 Lift 与嵌套增量
`expected_next_planned_task`: R1-T07 P 首入锚定的固定滞后结构关系
`expected_downstream_gate_marker`: R1-T07_allowed_to_start: false

`superseded`: false
`superseded_by`: null
`supersedes`: R1-T06-20260710T1058Z
`downstream_gate_allowed`: false

## 说明

R1-T06 author-draft formal rerun 已完成，task-specific engineering validator passed。旧 run `R1-T06-20260710T1058Z` 的 primary metrics 未退化，但 nested reconciliation 与 q nesting contract gap 由本 run 修复并 supersede。

`author_draft_package_validation_result_path`: data/generated/r1/r1_t06/R1-T06-20260710T1155Z/r1_t06_author_draft_package_validation_result.json

当前阶段不得生成 passed scientific review，不得推进 README 到 R1-T07。
