# D2-T11 Source Status Factor Evidence Acceptance Handoff Redacted Summary

## Scope

This is a redacted synthetic/local execution summary for PR D2-T11. It reports
aggregate gate decisions and report hashes only. It does not include row-level
prices, source symbols, security mapping rows, vendor payloads, raw parquet bytes,
generated candidate artifacts, API tokens, DuckDB files, accepted manifests,
published data versions, D3 rows, PCVT values, labels, returns, backtests, or
portfolio outputs.

## Redacted Decision Summary

```json
{
  "source_status_decision": "resolved",
  "factor_status_decision": "resolved",
  "d2_acceptance_decision": "accepted_for_d3_candidate_generation",
  "d3_handoff_decision": "d3_candidate_generation_allowed",
  "r0_handoff_decision": "r0_blocked",
  "raw_candidate_row_count": 1,
  "adjusted_candidate_row_count": 1,
  "security_count": 1,
  "trading_date_min": "2026-07-01",
  "trading_date_max": "2026-07-01",
  "resolved_counts_by_field": {
    "trading_status": 1,
    "price_limit_status": 1,
    "suspension_status": 1,
    "st_status": 1,
    "limit_price": 1,
    "adjustment_factor": 1,
    "factor_as_of_time": 1,
    "adjustment_revision": 1,
    "point_in_time_eligible": 1
  },
  "unresolved_counts_by_field": {
    "trading_status": 0,
    "price_limit_status": 0,
    "suspension_status": 0,
    "st_status": 0,
    "limit_price": 0,
    "adjustment_factor": 0,
    "factor_as_of_time": 0,
    "adjustment_revision": 0,
    "point_in_time_ineligible": 0
  },
  "fallback_used_counts_by_source": {
    "baostock": 0,
    "tushare": 0
  },
  "conflict_count": 0,
  "blocking_reasons": [],
  "allowed_next_actions": [
    "D3-T07 formal candidate generation gate execution"
  ],
  "forbidden_next_actions": [
    "R0 generation",
    "backtest",
    "portfolio generation"
  ]
}
```

## Report Hashes

```json
{
  "source_status_evidence_candidate": "6dc97e4db98a54de0fd1cd23d867f69ff9e27e2d0f857ad4edc3b7f67b3b8a08",
  "factor_evidence_candidate": "18c77f6ca4b9e37daa9b1b2cbc6cd1a631c827cf2c275e771c737eedaea9a591",
  "source_discrepancy_report": "30bf6fd1be155507dd46523ca50a32c2ae85fd7e512fee6e69cc78bb0bf1cb0d",
  "d2_acceptance_candidate_report": "26e15294404b5dd7832a72a8b41620fb3defa7cd8efc298a3e8dfa947b0caab4",
  "d3_handoff_candidate_report": "a18a57b6d827cd7871c0e5abb9b50b9ba23903abba6c66c2841c4e146832ce56",
  "d2_t11_gate_decision_summary": "b69ecdfc8284a6fe1308faeb7e70051e9bf70007961a671dcc1371a11529645b",
  "source_status_resolution_candidate_report": "c6f82330cee1579e0a851712de52a2fa892aad6f2a96b3d32b30a8c882cc0e94",
  "factor_status_resolution_candidate_report": "27450960ca55e2ae2ecc2cd835f9c134fe1baf80fa0296047854e99a59788cde"
}
```

## Boundary Notes

- This run used synthetic/local evidence and did not call remote APIs.
- No API token or key was printed, logged, written, or committed.
- `d3_candidate_generation_allowed` is a D2-T11 handoff candidate decision only.
- This PR still does not generate D3 rows, publish a data version, write DuckDB,
  create accepted manifests, generate PCVT values, or unlock R0.
- D3-T07 must independently re-check the D2-T11 handoff candidate before any
  D3 candidate generation.
