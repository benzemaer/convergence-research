# R0-T11 R0 Audit Report And R1 Handoff Evidence

This evidence records the R0-T11 audit and handoff closure. It records only paths, hashes, gate values, and validation status. It does not embed row-level payloads and does not copy generated DuckDB, Parquet, CSV, or JSONL contents.

## Run Record

`task_id`: R0-T11
`status`: completed
`run_id`: R0-T11-20260708T1810Z
`code_commit`: e97ce154b174d661f0628c19014485509c022547

## Source Evidence

`source_evidence_files`: R0-T10-01, R0-T10-02, R0-T10-03, R0-T10-04, R0-T10-05
`R0-T10-01_evidence_path`: `docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence_repair_20260708T1715Z.md`
`R0-T10-01_evidence_sha256`: `732a0fb622d1bc78d80383a35dd1a142a32626935e9b156216517f1291bc1df9`
`R0-T10-02_evidence_path`: `docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence_repair_20260708T1730Z.md`
`R0-T10-02_evidence_sha256`: `1ff5674690dad654d3f6f731e953748b90d5710ee65cb132e4b45177115d1a2f`
`R0-T10-03_evidence_path`: `docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence_repair_20260708T1740Z.md`
`R0-T10-03_evidence_sha256`: `255d3419be61bdb54a1c47696e416135ccbddaa7f6130da577f61cffc900e71a`
`R0-T10-04_evidence_path`: `docs/evidence/r0/R0-T10-04_r0_t07_confirmation_interval_materialization_evidence_repair_20260708T1746Z.md`
`R0-T10-04_evidence_sha256`: `1029c22daf3819db9cba12010c43f065e06a8deac8a880f67387d6175c0ee59e`
`R0-T10-05_evidence_path`: `docs/evidence/r0/R0-T10-05_authorized_input_manifest_full_grid_evidence.md`
`R0-T10-05_evidence_sha256`: `25b6176de27add5532bb0a3809b6b7e0fd8403ef350f82685faa9cb5a0a52dab`

## Audit Outputs

`task_doc_path`: `docs/tasks/R0-T11_R0审计报告与R1交接.md`
`task_doc_sha256`: `9e0e07988327856e602c6d8d4d0a19f1be88eb329714767168a40c542c392570`
`engineering_standard_path`: `docs/03_可复现研究工程标准.md`
`engineering_standard_sha256`: `27b7cd0da0a18eecc641746901fb98e245d54c8bd57237eef8e95ca3af6ae6d4`
`audit_report_path`: `docs/reports/r0/R0_audit_report.md`
`audit_report_sha256`: `6c0c470c36e42c4cdd92906b17ada97ab54bfb475dd75b29ad3a437537717add`
`r1_handoff_path`: `docs/reports/r0/R0_r1_handoff.md`
`r1_handoff_sha256`: `04023419357e30e7e566ec25896c6ac547087c250b786a4ba30fddeb94669b86`
`evidence_index_path`: `docs/reports/r0/R0_evidence_index.md`
`evidence_index_sha256`: `671174159c74bc79265e321fd5c3104bb13b49741e745d05c98a7ae533838800`
`known_limitations_path`: `docs/reports/r0/R0_known_limitations.md`
`known_limitations_sha256`: `8ef03a2010668532228dd5ce379908de5e6e5c991efb70c0bcf1cc01c1fde4df`

## Validation

`validator_command`: `python -m src.r0.r0_t11_audit_validator_cli`
`wrapper_validator_command`: `python scripts/r0/validate_r0_t11_audit.py`
`validator_status`: passed
`required_report_files_check`: passed
`required_formal_evidence_check`: passed
`formal_evidence_gate_check`: passed
`audit_report_content_check`: passed
`r_stage_formal_run_standard_check`: passed
`r1_formal_run_standard_gate`: passed
`forbidden_claim_check`: passed
`readme_gate_check`: passed

## Gates

`R0_status`: completed
`R1_allowed_to_start`: true
`R1_starting_task`: R1-T01
`r_stage_formal_run_standard_updated`: true
`confirmed_interval_package_acknowledged`: true
`no_future_label_check`: passed
`no_backtest_check`: passed
`no_trading_signal_check`: passed
`no_parameter_optimization_claim_check`: passed
`README_updated_to_R1`: true
`downstream_gate_allowed`: true
