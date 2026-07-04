# D2-T11 Source Status Factor Evidence Acceptance Handoff Redacted Summary

## Scope

This is a redacted local provider-probe execution summary for PR D2-T11. It reports
aggregate gate decisions and report hashes only. It does not include row-level
prices, source symbols, security mapping rows, vendor payloads, raw parquet bytes,
generated candidate artifacts, API tokens, DuckDB files, accepted manifests,
published data versions, D3 rows, PCVT values, labels, returns, backtests, or
portfolio outputs.

## Redacted Decision Summary

```json
{
  "source_status_decision": "unresolved",
  "factor_status_decision": "unresolved",
  "d2_acceptance_decision": "blocked_pending_source_status_resolution",
  "d3_handoff_decision": "d3_candidate_generation_blocked",
  "r0_handoff_decision": "r0_blocked",
  "candidate_universe_total_count": 1673517,
  "remote_probe_row_count": 8,
  "raw_candidate_row_count": 8,
  "adjusted_candidate_row_count": 8,
  "security_count": 1,
  "trading_date_min": "2026-06-23",
  "trading_date_max": "2026-07-02",
  "resolved_counts_by_field": {
    "trading_status": 0,
    "price_limit_status": 0,
    "suspension_status": 0,
    "st_status": 0,
    "limit_up_price": 0,
    "limit_down_price": 0,
    "is_trading_day": 0,
    "trading_calendar_status": 0,
    "adjustment_factor": 0,
    "factor_as_of_time": 0,
    "adjustment_revision": 0,
    "adjustment_factor_direction": 8,
    "point_in_time_eligible": 0
  },
  "unresolved_counts_by_field": {
    "trading_status": 8,
    "price_limit_status": 8,
    "suspension_status": 8,
    "st_status": 8,
    "limit_up_price": 8,
    "limit_down_price": 8,
    "is_trading_day": 8,
    "trading_calendar_status": 8,
    "adjustment_factor": 8,
    "factor_as_of_time": 8,
    "adjustment_revision": 8,
    "adjustment_factor_direction": 0,
    "point_in_time_eligible": 8
  },
  "fallback_used_counts_by_source": {
    "baostock": 0,
    "tushare": 0
  },
  "conflict_count": 0,
  "provider_probe_failed_count": 1,
  "provider_probe_diagnostics": [
    {
      "provider_id": "hithink_financial_api",
      "probe_status": "provider_probe_failed",
      "probe_failure_reason": "hithink_python_adapter_unavailable",
      "rows_requested": 0,
      "status_rows_returned": 0,
      "factor_rows_returned": 0
    },
    {
      "provider_id": "baostock",
      "probe_status": "provider_probe_completed",
      "rows_requested": 8,
      "status_rows_returned": 0,
      "factor_rows_returned": 0
    },
    {
      "provider_id": "tushare",
      "probe_status": "provider_probe_completed",
      "rows_requested": 8,
      "status_rows_returned": 0,
      "factor_rows_returned": 0
    }
  ],
  "blocking_reasons": [
    "source_status_unresolved",
    "factor_evidence_unresolved",
    "point_in_time_evidence_unresolved"
  ],
  "allowed_next_actions": [
    "D2-T12 source status / factor evidence remediation"
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
  "source_status_evidence_candidate": "a2ffb2ffff89a3aac503d07699f13477a2a1c6fd568885a65e0f80b7f28cdd15",
  "factor_evidence_candidate": "cd2768fac513c9f285ba38220e66821cba4fb207a04a46d6e60e7c34e3ae9db1",
  "source_discrepancy_report": "a30b920095684cdf429340f48403936b31fead3980a7dfc6bdc7d2255a8da10d",
  "d2_acceptance_candidate_report": "174ae7b93375621fa1ffa17c8f1e0cede5f400cfe07ad24c775f04928271e975",
  "d3_handoff_candidate_report": "ebe0bfdbc1706c17992b7af62dcc3da6e58bda30235d7c212f9a1fc427f23a2f",
  "d2_t11_gate_decision_summary": "ed3992e0bc6d3b3d445f6b86602dc33626cffd66a29fde2d17032b27a1355412",
  "source_status_resolution_candidate_report": "10198f1d12dcd39884198c5595de4fe02167906f5035bfd52f767fe95186f604",
  "factor_status_resolution_candidate_report": "fad960c8f9111a9a36874288d5e09d6447abc791e5d23ac097862c0ba48a4efa"
}
```

## Boundary Notes

- This run used local `.env.local` credentials and provider-specific remote probes,
  but no API token or key was printed, logged, written, or committed.
- The probe input universe came from the ignored local D2-T09 raw candidate parquet
  and read only `security_id`, `trading_date`, `universe_id`, and
  `time_segment_id`.
- HiThink did not have an available Python adapter in this environment, so it is
  recorded as `provider_probe_failed`, not silently treated as resolved.
- BAOSTOCK and Tushare probes completed for the sampled universe but returned no
  usable source-status or factor evidence for this D2-T11 gate.
- Because source status, factor evidence, and point-in-time evidence remain
  unresolved, D2 acceptance remains blocked and D3 candidate generation remains
  blocked.
- This PR still does not generate D3 rows, publish a data version, write DuckDB,
  create accepted manifests, generate PCVT values, or unlock R0.
