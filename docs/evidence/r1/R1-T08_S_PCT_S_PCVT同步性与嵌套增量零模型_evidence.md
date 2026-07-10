# R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型 Evidence

`task_id`: R1-T08
`task_class`: formal_experiment
`status`: author_analysis_complete
`run_id`: R1-T08-20260710T1629Z
`code_commit`: 59218fa714f3275f7bdc4995265f381aa1140fa5

`engineering_validator_status`: passed
`result_artifact_status`: passed
`author_result_analysis_status`: passed
`scientific_review_status`: pending
`anomaly_resolution_status`: passed
`review_phase`: author_analysis_complete
`downstream_gate_allowed`: false

`experiment_summary_path`: data/generated/r1/r1_t08/R1-T08-20260710T1629Z/r1_t08_experiment_summary.json
`experiment_summary_sha256`: 0d10c21bd05778bd770384624b3297a0156375d6046014235c026361805f400f
`candidate_registry_path`: data/generated/r1/r1_t08/R1-T08-20260710T1629Z/r1_t08_candidate_registry.csv
`candidate_registry_sha256`: 371cbe9e1fd4a44a94c660f0894fdde0805ad4b23007c8452c813cc3b29bbd05
`test_registry_path`: data/generated/r1/r1_t08/R1-T08-20260710T1629Z/r1_t08_test_registry.csv
`test_registry_sha256`: c92327b82290cdebeb3d8b9c3553670dbf83b2b150d8f5ed46ce6e6cee8f5cd0
`observed_reconciliation_path`: data/generated/r1/r1_t08/R1-T08-20260710T1629Z/r1_t08_observed_reconciliation.csv
`observed_reconciliation_sha256`: aea7f8b276bf6d7c6b44d1fab6f5fc077fb09c848eef239e8397ecb19518616e
`block_diagnostics_path`: data/generated/r1/r1_t08/R1-T08-20260710T1629Z/r1_t08_block_diagnostics.csv
`block_diagnostics_sha256`: 8146c1dc8021eeebdf1a749fec9724dc5bcb0dd3975ae562c9311e1fb440f241
`offset_plan_diagnostics_path`: data/generated/r1/r1_t08/R1-T08-20260710T1629Z/r1_t08_offset_plan_diagnostics.csv
`offset_plan_diagnostics_sha256`: 9389b1931e63ddd5e6891ef0bffd6e667413e9cc6ba745b2566cdb98dec3417b
`null_replicate_metrics_path`: data/generated/r1/r1_t08/R1-T08-20260710T1629Z/r1_t08_null_replicate_metrics.csv
`null_replicate_metrics_sha256`: 771fd24bbf0fc7337e954d2c6a43c665fd6c25e1dd871febae69f9783390c403
`null_model_results_path`: data/generated/r1/r1_t08/R1-T08-20260710T1629Z/r1_t08_null_model_results.csv
`null_model_results_sha256`: 080a8a531e333ca68cf01b354a0f177489da949be81b55b5810d668502adb4db
`execution_diagnostics_path`: data/generated/r1/r1_t08/R1-T08-20260710T1629Z/r1_t08_execution_diagnostics.csv
`execution_diagnostics_sha256`: a4bd5cd5016b29d9a9dc7366aa868068705353bda87c8b85afea0a2cab28ec35
`diagnostic_summary_path`: data/generated/r1/r1_t08/R1-T08-20260710T1629Z/r1_t08_diagnostic_summary.json
`diagnostic_summary_sha256`: c035b90dd52bf8a4a896cfcb48e08d074d3c6d34390ef065fcf60bc6910b1be6
`engineering_validation_result_path`: data/generated/r1/r1_t08/R1-T08-20260710T1629Z/r1_t08_engineering_validation_result.json
`engineering_validation_result_sha256`: a62769e19b7b96445be67b51a1ed635998e5826951a0a0ad9e4bf7a047c5114c
`anomaly_scan_path`: data/generated/r1/r1_t08/R1-T08-20260710T1629Z/r1_t08_anomaly_scan.json
`anomaly_scan_sha256`: 4682848f713409dad61e321c82abf67068335e64eb1550f52de80028833263b5
`result_analysis_path`: docs/experiments/r1/R1-T08_S_PCT_S_PCVT同步性与嵌套增量零模型_result_analysis.md
`result_analysis_sha256`: 66a23faefb5ed98ea4ca3da063bc7a774ca75377e15d83aceaac2aafd2b3a0b8
`readme_path`: docs/tasks/README.md

## 结果与门禁说明

正式 run 完成十个 test groups、20,000 个 replicate、22 行 aggregate，failed simulation 为 0。Observed full-key reconciliation、R1-T04/R1-T06 对账、block/offset/payload preservation 均为零 mismatch；engineering validator 从 replicate artifact 重算统计量，并从 root seed 重建全部 offset-plan hash，结果为 passed。

四个 global confirmed coverage 和六个 nested retention 均位于相应 2,000-replicate upper tail 之外；duration 与 fragment 的 separation 不完全一致，已在 15 节 result analysis 中作为 material warning 分开陈述。当前仅为 author draft：scientific review pending，downstream false，README 不推进，R1-T09 与 R2 均不放行。
