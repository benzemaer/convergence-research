# D2-T12 tnskhdata/Tushare HiThink Provider Remediation Redacted Summary

## Scope

This is a redacted local provider-remediation probe summary for D2-T12. It reports
aggregate mapping, provider capability, field coverage, blocking decisions, and
report hashes only. It does not include row-level prices, source symbols,
security mapping rows, vendor payloads, API tokens, raw parquet bytes, generated
evidence artifacts, DuckDB files, manifests, data versions, D3 rows, PCVT values,
labels, returns, backtests, or portfolio outputs.

## Redacted Decision Summary

```json
{
  "candidate_universe_total_count": 1673517,
  "sample_mode": "latest_and_eventful",
  "sample_row_count": 100,
  "sample_security_count": 20,
  "sample_exchange_coverage": ["SSE", "SZSE"],
  "sample_coverage_limitation": [],
  "mapping_success_count": 100,
  "mapping_failure_count": 0,
  "query_skipped_for_unmapped_count": 0,
  "provider_count": 4,
  "provider_failure_categories": {
    "Exception": 7,
    "URLError": 6,
    "empty": 6,
    "field_missing": 1,
    "ok": 3
  },
  "source_status_resolved_counts_by_field": {
    "trading_status": 80,
    "price_limit_status": 0,
    "suspension_status": 100,
    "st_status": 100,
    "limit_up_price": 80,
    "limit_down_price": 80,
    "is_trading_day": 100,
    "trading_calendar_status": 100
  },
  "source_status_unresolved_counts_by_field": {
    "trading_status": 20,
    "price_limit_status": 100,
    "suspension_status": 0,
    "st_status": 0,
    "limit_up_price": 20,
    "limit_down_price": 20,
    "is_trading_day": 0,
    "trading_calendar_status": 0
  },
  "factor_evidence_resolved_counts_by_field": {
    "adjustment_factor": 0,
    "factor_as_of_time": 0,
    "adjustment_revision": 0,
    "adjustment_factor_direction": 0,
    "point_in_time_eligible": 0
  },
  "factor_evidence_unresolved_counts_by_field": {
    "adjustment_factor": 100,
    "factor_as_of_time": 100,
    "adjustment_revision": 100,
    "adjustment_factor_direction": 100,
    "point_in_time_eligible": 100
  },
  "fallback_used_counts_by_source": {
    "source_status": {
      "tnskhdata": 240,
      "baostock": 400,
      "tushare": 0
    },
    "factor_evidence": {
      "tnskhdata": 0,
      "baostock": 0,
      "tushare": 0
    }
  },
  "conflict_count": 160,
  "conflict_fields": ["st_status", "suspension_status"],
  "silent_override_count": 0,
  "remaining_blockers": [
    "adjustment_revision_unresolved",
    "factor_as_of_time_unresolved",
    "factor_evidence_unresolved",
    "point_in_time_evidence_unresolved",
    "provider_discrepancy_unresolved",
    "source_status_unresolved"
  ],
  "d2_acceptance_decision": "blocked_pending_source_status_resolution",
  "d3_handoff_decision": "d3_candidate_generation_blocked",
  "r0_handoff_decision": "r0_blocked"
}
```

## Report Hashes

```json
{
  "provider_capability_matrix": "d43d562b86f226ea098bbe4a7a30f397523b6bc5e2c7e92f5af59631b04f1a3f",
  "security_code_mapping_probe_report": "f7ccb29f7ff35c061533d7de0d21b3a54213510abe9a419ebdf0440a49c729d0",
  "source_status_field_coverage_report": "94aff433c0c70999210d64d482b6cdec2b1f065200827f726bf19f6ef5e6fb19",
  "factor_evidence_field_coverage_report": "eeef1363f30d3ee69a51fbf4f867ebca9db88a70bb35a410a2acd9d7aaabbe61",
  "provider_discrepancy_report": "97ab1ffee98c8803868f67c60b99a788ce1a5e7e58234bd6f411ce8d80f14d07",
  "d2_t12_gate_decision_summary": "77020790c7db3663ea70144a08f7425ce1ca629324248e2dbac0ac1ad64853f2",
  "candidate_file_hash_summary": "efa095fd0bdde19e50ad59ac5eb24fac624c7a962b85a59faf9763e478bc9cfb"
}
```

## Boundary Notes

- The probe read only the required candidate-universe columns from the ignored
  local D2-T09 raw candidate parquet.
- Unified code mapping resolved all sampled rows across both SSE and SZSE.
- BAOSTOCK and tnskhdata provided partial candidate source-status evidence, but
  `price_limit_status` remains unresolved for every sampled row.
- ST and suspension evidence has cross-provider conflicts that require remediation;
  no silent override was performed.
- Tushare-compatible factor evidence still lacks `factor_as_of_time` and
  `adjustment_revision`; `point_in_time_eligible` remains false for every sampled
  row.
- HiThink REST was probed with `X-api-key`; endpoint failures are recorded in the
  capability matrix without exposing the key.
- D2 acceptance and D3 handoff remain blocked. R0 remains blocked.
