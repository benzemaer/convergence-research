# EXP-A02 raw domain, availability and validity analysis

## 1. Actual run / reviewed SHA
run_id: EXP-A02-20260717T100527443Z
reviewed_implementation_sha: bfd7ad71de8638d0a9d0adde824078d7ddc595b5
execution_mode: formal_not_authorized

## 2. Accepted EXP-A01 handoff
accepted_run_id: EXP-A01-20260717T040145984Z
accepted_status: completed_accepted
formal_result_review_status: accepted

## 3. Input artifact and hash bindings
input_artifact_count: 5
upstream_consumption: accepted_EXP_A01_artifact_only

## 4. Raw-table cardinality
raw_row_count: 5253198
indicator_count: 3

## 5. Raw domains
The three registered raw domains are checked from finite valid values; the rate-valued candidate is checked on the fixed twenty-point grid.

## 6. Indicator availability
A1_LogBodyCenterToMACloudCenter_5_60: native_valid_count=1632073; native_valid_rate_expected=0.9320453940628166
A2_BodyCenterOutsideMACloudRate20_5_60: native_valid_count=1602937; native_valid_rate_expected=0.9154063867381355
A2b_BodyToMACloudGapMean20_5_60: native_valid_count=1602937; native_valid_rate_expected=0.9154063867381355

## 7. Common-valid availability
A1_A2: common_valid_count=1602937; union_valid_count=1632073
A1_A2b: common_valid_count=1602937; union_valid_count=1632073
A2_A2b: common_valid_count=1602937; union_valid_count=1602937
A1_A2_A2b: common_valid_count=1602937; union_valid_count=1632073

## 8. Validity-status distribution
The compact status profile uses the complete expected-row denominator for each indicator.

## 9. Reason-code distribution
Reason-code counts are overlapping evidence counts and are not a mutually exclusive partition.

## 10. Reason-combination distribution
Canonical reason-code arrays are retained as complete combinations.

## 11. Year availability
Year-level availability is reported without using future outcomes or selection criteria.

## 12. Security availability
Security-level availability is reported for every security present in the input artifact.

## 13. Deterministic extreme-value sample
Each indicator uses deterministic lower and upper tails ordered by value, security, and observation sequence.

## 14. Full invariant validation
status: passed; mismatch_count: 0

## 15. Independent aggregate recomputation
The validator defines independent set-based aggregate SQL and compares every persisted compact field.

## 16. Validator result
status: passed; valid: True

## 17. Anomaly scan
status: passed; blocking_anomaly_count: 0; investigation_item_count: 0

## 18. Supported conclusions
This implementation package supports only raw-domain, availability, validity, reason-code, and compact aggregate integrity checks.

## 19. Unsupported conclusions
Candidate identity comparisons, downstream selection, predictive outcomes, and state-machine decisions are outside EXP-A02.

## 20. Readiness for user Formal-result review
ready_for_user_formal_result_review
