# EXP-A01 formal result analysis

## 1. Actual run / reviewed SHA
run_id: EXP-A01-20260717T040145984Z
reviewed_implementation_sha: c9a52dc29f7d41c85ab416e99bb9ef8cc6411b9d
started_at: 2026-07-17T04:01:47.995Z
finished_at: 2026-07-17T04:35:13.062Z
parallel_mode: single_process_duckdb_parallel; worker_count: 1
duckdb_threads: 12
memory_limit: 12GB
execution_profile_owner_override: true; authorization_continuity: preserved

## 2. Input manifest and authorization
input_manifest_sha256: 44ef2e18ae6edff5dce18702f9290867382c12e114b392668358b28c10b29057
authorized_for_task: EXP-A01; authorized_research_candidate_input: true
formal_data_version: false

## 3. D3-T07 lineage
The D3-T07 candidate, handoff and quality evidence passed their declared source, role and quality gates.

## 4. Input governance override
D3-T08 is explicitly not required for EXP-A01 under the owner-approved four-artifact input contract; no D3-T08 evidence is used or synthesized.

## 5. Dense expected-index reconciliation
{"duplicate_index_security_date": 0, "duplicate_index_security_sequence": 0, "empty_index_source_contract": 0, "empty_index_source_ref": 0, "index_date_type_invalid": 0, "index_row_count": 1751066, "index_sequence_type_invalid": 0, "invalid_index_date": 0, "invalid_index_identity": 0, "invalid_index_sequence_value": 0, "invalid_index_status": 0, "invalid_main_date": 0, "main_duplicate_security_date": 0, "main_effective_factor_invalid": 0, "main_generated_by_task_invalid": 0, "main_invalid_identity": 0, "main_key_not_present_index": 0, "main_listing_pause_row_present": 0, "main_row_count": 1730769, "main_row_provenance_missing": 0, "main_source_task_invalid": 0, "non_monotonic_index_date": 0, "non_monotonic_index_sequence": 0, "non_present_index_key_in_main": 0, "present_index_key_missing_main": 0}

## 6. Fixed candidate definitions
A1, A2 and A2b use the frozen current-day-inclusive adjusted-price definitions, MA windows and dense slot counts.

## 7. Raw table cardinality
raw_table_rows: 5253198; expected_index_rows: 1751066; expected_raw_rows: 5253198
Each expected slot has exactly three persisted indicator rows.

## 8. Metric domains and distributions
A1_LogBodyCenterToMACloudCenter_5_60: valid_count=1632073, valid_rate=0.9320453940628166; A2_BodyCenterOutsideMACloudRate20_5_60: valid_count=1602937, valid_rate=0.9154063867381355; A2b_BodyToMACloudGapMean20_5_60: valid_count=1602937, valid_rate=0.9154063867381355

## 9. Validity status profile
The persisted validity profile is checked independently against the raw table.

## 10. Reason-code profile
Reason-code counts are derived from the canonical compact JSON arrays and are not interpreted as additional metrics.

## 11. Year coverage
The year coverage table reports every observed calendar year and candidate.

## 12. Security coverage
The security coverage table reports every observed security and candidate.

## 13. Full invariant validation and stratified independent oracle
The validator performed a full persisted DuckDB invariant and compact-profile scan. It did not perform a full Python raw-row recomputation. A deterministic stratified independent oracle compared the selected observation targets and all three indicators.
validation_strategy: r0_t10_full_invariants_plus_stratified_oracle_v1
full_persisted_invariant_scan_performed: True
full_independent_recompute_performed: False
oracle_mode: deterministic_stratified_sample
oracle_sample_version: EXP_A01_STRATIFIED_ORACLE_V1
oracle_target_observation_count: 4893
oracle_sample_target_fingerprint: 72981029607b6393e8cf2424ecd662438693cb9971166571d7e020547162d333
oracle_compared_raw_row_count: 14679
oracle_sample_security_count: 800
oracle_sample_validity_statuses: ["blocked", "unknown", "valid"]
oracle_sample_reason_codes: ["adjustment_failure", "invalid_trading_status", "listing_pause_in_required_window", "missing_adjusted_close", "missing_adjusted_open", "missing_required_history", "valid_no_blocker", "window_insufficient"]
oracle_sample_years: ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"]
oracle_numeric_tolerances: {"A1_LogBodyCenterToMACloudCenter_5_60": {"absolute": 1e-12, "relative": 1e-09}, "A2_BodyCenterOutsideMACloudRate20_5_60": {"absolute": 1e-12, "relative": 1e-09}, "A2b_BodyToMACloudGapMean20_5_60": {"absolute": 1e-12, "relative": 1e-09}}
oracle_mismatch_count: 0
oracle_max_absolute_difference_by_indicator: {"A1_LogBodyCenterToMACloudCenter_5_60": 1.7763568394002505e-15, "A2_BodyCenterOutsideMACloudRate20_5_60": 0.0, "A2b_BodyToMACloudGapMean20_5_60": 1.7694179454963432e-16}
oracle_max_relative_difference_by_indicator: {"A1_LogBodyCenterToMACloudCenter_5_60": 1.7763568394002505e-15, "A2_BodyCenterOutsideMACloudRate20_5_60": 0.0, "A2b_BodyToMACloudGapMean20_5_60": 1.7694179454963432e-16}
comparison_counts: {"raw_rows_expected": 5253198}

## 14. Validator result
status: passed; valid: True; errors: 0

## 15. Anomaly scan
status: passed; blocking_anomaly_count: 0; investigation_item_count: 0

## 16. Supported and unsupported conclusions
This package supports statements about raw-metric materialization, numeric domains, validity, coverage and persisted-result integrity only. It does not establish downstream selection or later-stage decisions.

## 17. Readiness for user Formal-result review
ready_for_user_formal_result_review
