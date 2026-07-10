# R1-T06 Contemporaneous Retention Lift Nested Increment Evidence

`task_id`: R1-T06
`task_class`: formal_experiment
`status`: author_analysis_complete
`run_id`: R1-T06-20260710T1216Z
`code_commit`: be1ee9946855f0b4b3eb25de23bcc14a999041da

`engineering_validator_status`: passed
`result_artifact_status`: passed
`author_result_analysis_status`: passed
`scientific_review_status`: pending
`anomaly_resolution_status`: passed
`review_phase`: author_analysis_complete

`experiment_summary_path`: data/generated/r1/r1_t06/R1-T06-20260710T1216Z/r1_t06_experiment_summary.json
`experiment_summary_sha256`: 71f95c5bb9c414ab4deb0c50afc641f1d2a7dfa95681b508ffce15541a01f5f6
`primary_result_artifacts`: r1_t06_layer_step_profile.csv sha256=98c80443be455f31a279666c6d9074180a3050bbdb11665e45a36099d4d7f3e4 rows=27; r1_t06_denominator_sensitivity.csv sha256=3829c9e07ab1df05204c8d9306e82ec9fbcde38bb47265128bf7863a4f389655 rows=27; r1_t06_year_step_profile.csv sha256=f1f90060a56cb1f492a018e7e179388831e54c1fcbb9bde2e111947e507b8d03 rows=270; r1_t06_security_step_summary.csv sha256=f8a6aedb9267b37d214c7b70981812c8a2efd493071e0884fcaf6786e21c76f6 rows=27; r1_t06_r0_nested_reconciliation.csv sha256=b756a27caa3094c365d7e7c0b44a7d7f53699d30752c6ea634f35f5073fd323f rows=36; r1_t06_dimension_state_reconciliation.csv sha256=0b1e32e2146b45eb664326c24df8c426b2e917ff756bbe45434e8357cb496460 rows=36; r1_t06_q_nesting_reconciliation.csv sha256=039af0550ad9e20160231d731183cdaf07117f4ca4a047b3e1c42011e8b8d208 rows=78
`diagnostic_summary_path`: data/generated/r1/r1_t06/R1-T06-20260710T1216Z/r1_t06_diagnostic_summary.json
`diagnostic_summary_sha256`: d8f731ae76feb841c62d34c9a618e01f918e0c8e6b98f59695b7344f102f4887
`engineering_validation_result_path`: data/generated/r1/r1_t06/R1-T06-20260710T1216Z/r1_t06_engineering_validation_result.json
`engineering_validation_result_sha256`: ad49b1d3ec5147f9dd62014929b6b3758c8af6fc42b22a4120e6be737a95ca50
`result_analysis_path`: docs/experiments/r1/R1-T06_contemporaneous_retention_lift_nested_increment_result_analysis.md
`result_analysis_sha256`: 7ae2872ab5b36e962420caf3007d297ae3e7dda8509986277a3f5e2bc517bd98
`anomaly_scan_path`: data/generated/r1/r1_t06/R1-T06-20260710T1216Z/r1_t06_anomaly_scan.json
`anomaly_scan_sha256`: aa62818298ab578499901c418bf64ce5f82d25879b580b730faf165e1662de98
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
`supersedes`: R1-T06-20260710T1155Z
`downstream_gate_allowed`: false

## 说明

R1-T06 author-draft formal rerun 已完成，task-specific engineering validator passed。旧 run `R1-T06-20260710T1155Z` 的 primary metrics 未退化，但 q nesting artifact 的 symmetric-difference 字段语义由本 run 修复并 supersede。更早的 `R1-T06-20260710T1058Z` 已由 1155Z supersede。

`author_draft_package_validation_result_path`: data/generated/r1/r1_t06/R1-T06-20260710T1216Z/r1_t06_author_draft_package_validation_result.json

当前阶段不得生成 passed scientific review，不得推进 README 到 R1-T07。
