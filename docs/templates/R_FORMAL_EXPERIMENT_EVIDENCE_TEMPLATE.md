# R Formal Experiment Evidence Template

`task_id`:
`task_class`: formal_experiment
`status`:
`run_id`:
`code_commit`:

`engineering_validator_status`:
`result_artifact_status`:
`author_result_analysis_status`:
`scientific_review_status`:
`anomaly_resolution_status`:
`review_phase`:

`experiment_summary_path`:
`experiment_summary_sha256`:
`primary_result_artifacts`:
`diagnostic_summary_path`:
`diagnostic_summary_sha256`:
`engineering_validation_result_path`:
`engineering_validation_result_sha256`:
`result_analysis_path`:
`result_analysis_sha256`:
`anomaly_scan_path`:
`anomaly_scan_sha256`:
`formal_evidence_path`:
`formal_evidence_sha256`:
`scientific_review_path`:
`scientific_review_sha256`:
`scientific_review_md_path`:
`scientific_review_md_sha256`:
`readme_path`:
`readme_sha256`:
`expected_current_stage`:
`expected_current_task`:
`expected_next_planned_task`:
`expected_downstream_gate_marker`:

`superseded`:
`superseded_by`:
`downstream_gate_allowed`:

## 说明

Evidence 只记录路径、hash、counts、gate 和 validator result，不嵌入 row payload。author-draft 阶段 `scientific_review_status` 必须为 pending 且 `downstream_gate_allowed=false`；final-gate 阶段必须有独立 scientific review record。
