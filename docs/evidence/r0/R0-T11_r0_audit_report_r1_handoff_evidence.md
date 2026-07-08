# R0-T11 R0 Audit Report And R1 Handoff Evidence

This evidence records the R0-T11 audit and handoff closure. It records only paths, hashes, gate values, and validation status. It does not embed row-level payloads and does not copy generated DuckDB, Parquet, CSV, or JSONL contents.

## Run Record

`task_id`: R0-T11
`status`: completed
`run_id`: R0-T11-20260708T0900Z
`code_commit`: 2dc086b9eba2d470db9cce7152d5631b7654dc1b

## Source Evidence

`source_evidence_files`: R0-T10-01, R0-T10-02, R0-T10-03, R0-T10-04, R0-T10-05
`R0-T10-01_evidence_path`: `docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md`
`R0-T10-01_evidence_sha256`: `4a145e4363be47220e0cca55cdd92142bd422b2ee8f341a6c5ed7a114af59c31`
`R0-T10-02_evidence_path`: `docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md`
`R0-T10-02_evidence_sha256`: `6c4f14fa819b82f43e2a751a894f7f659d330edced57f26914cca8627d95a526`
`R0-T10-03_evidence_path`: `docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md`
`R0-T10-03_evidence_sha256`: `3996ede8d0f5df5f3084792e961e5e77c43e457ad2bfefc7d9b2192ac132c6f9`
`R0-T10-04_evidence_path`: `docs/evidence/r0/R0-T10-04_r0_t07_confirmation_interval_materialization_evidence.md`
`R0-T10-04_evidence_sha256`: `da5ab8cab732dd4fac7bd873b9569fa60dcd7fd6f0ad0be36518a9dccf0a5fd5`
`R0-T10-05_evidence_path`: `docs/evidence/r0/R0-T10-05_authorized_input_manifest_full_grid_evidence.md`
`R0-T10-05_evidence_sha256`: `507b75bcbfc39afd72955e6b1b585c73a3c855cdbf080c1718c7e745b26e40ac`

## Audit Outputs

`task_doc_path`: `docs/tasks/R0-T11_R0审计报告与R1交接.md`
`task_doc_sha256`: `5e18a7eae0bd571521668fab88f5dadb52cb6aa7cb5f9f9640801184dc373483`
`audit_report_path`: `docs/reports/r0/R0_audit_report.md`
`audit_report_sha256`: `548475b25b3dbe485b1ef9a91a20d450b32fdee3bac17b702f30c95f9745b314`
`r1_handoff_path`: `docs/reports/r0/R0_r1_handoff.md`
`r1_handoff_sha256`: `3fbe21ca1c1d5d2e77c4ff7a81f3ef3ece3e3a52c6a8ef2ce6d007dffddf4ae9`
`evidence_index_path`: `docs/reports/r0/R0_evidence_index.md`
`evidence_index_sha256`: `7957c71e6055cf6e15ad1e31c83d86e9b76fb485d9f326e2963a569ec64ed86c`
`known_limitations_path`: `docs/reports/r0/R0_known_limitations.md`
`known_limitations_sha256`: `ceabd546f7563f9024610090fcd908d87c3bded8c0a85fb7ff9a0ac2f719b12c`

## Validation

`validator_command`: `python -m src.r0.r0_t11_audit_validator_cli`
`wrapper_validator_command`: `python scripts/r0/validate_r0_t11_audit.py`
`validator_status`: passed
`required_report_files_check`: passed
`required_formal_evidence_check`: passed
`formal_evidence_gate_check`: passed
`audit_report_content_check`: passed
`forbidden_claim_check`: passed
`readme_gate_check`: passed

## Gates

`R0_status`: completed
`R1_allowed_to_start`: true
`R1_starting_task`: R1-T01
`zero_interval_acknowledged`: true
`no_future_label_check`: passed
`no_backtest_check`: passed
`no_trading_signal_check`: passed
`no_parameter_optimization_claim_check`: passed
`README_updated_to_R1`: true
`downstream_gate_allowed`: true
