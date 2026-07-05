# D2-T13 tnskhdata Full Materialization Acceptance Redacted Summary

## Scope

This summary records the D2-T13 tnskhdata full candidate materialization gate
without committing generated artifacts. It contains aggregate counts, date
range, coverage status, quality flags, acceptance decisions, source snapshot
identity, and hashes only.

It does not contain row-level prices, source-symbol lists, security mapping
rows, vendor payloads, raw provider responses, API tokens, generated artifact
contents, DuckDB files, D3 rows, PCVT values, R0 states, labels, returns,
backtests, or portfolio outputs.

## Date Boundary

The provider fetch window follows DR-001:

```json
{
  "date_boundary_source": "docs/decisions/DR-001_G0静态中证800样本与时间边界.md",
  "start_date": "20160101",
  "end_date": "20260630",
  "calendar_boundary": "closed_interval",
  "fetch_date_domain": "calendar",
  "date_domain_source": "DR-001"
}
```

D2-T09 `candidate_raw_market_prices.parquet` is superseded diagnostic input
only. It is a HiThink candidate diagnostic output with a blocking flag and must
not define the D2-T13 canonical fetch date domain. D2-T13 owns tnskhdata
calendar-domain materialization from DR-001 and the formal
`CSI800_STATIC_2026_06` membership/security mapping artifact.

## Source Decision

```json
{
  "primary_candidate_source": "tnskhdata",
  "diagnostic_fallback": ["Tushare", "BAOSTOCK"],
  "deprecated_probe_only": ["HiThink raw"],
  "d1_raw_source": "tnskhdata daily",
  "d2_factor_source": "tnskhdata adj_factor",
  "lifecycle_evidence_source": "stock_basic",
  "new_share_reconciliation_required": false,
  "new_share_reconciliation_status": "not_requested_optional",
  "status_sources": [
    "tnskhdata stock_basic",
    "tnskhdata trade_cal",
    "tnskhdata stk_limit",
    "tnskhdata stock_st",
    "tnskhdata suspend_d"
  ]
}
```

Optional future reconciliation: `new_share.issue_date` can be used later to
cross-check `stock_basic.list_date` for post-2016 IPOs. It is diagnostic only
and is not a D2-T13 blocker unless stock_basic lifecycle evidence is missing or
contradictory.

## Local Assembly Summary

D2-T13 calendar-domain assembly completed locally. The 3,067,200
source/factor rows are expected because the skeleton is 800 securities by 3,834
calendar dates. The 1,730,769 daily and adjusted rows are plausible because
daily rows only exist for listed, open, applicable dates. Pre-listing,
post-delist, suspended, and non-trading dates are expected `not_applicable`
gaps, not provider defects.

The previous pre-fix quality report blocked D2 acceptance because it compared
daily row counts against the full calendar skeleton and counted non-applicable
gaps as unresolved. This PR changes the gate so only
`listed_open_missing_daily` / `missing_daily_unexpected_count` can block daily
coverage.

```json
{
  "run_id": "tnskhdata_d2_t13_20160101_20260630_full",
  "source_snapshot_id": "tnskhdata_d2_t13_20160101_20260630_full",
  "run_mode": "full",
  "sample_mode": false,
  "staging_store_type": "partitioned-jsonl",
  "staging_store_path_redacted": "data/generated/d2/d2_t13_tnskhdata_full_candidate/**",
  "formal_duckdb_write_authorized": false,
  "local_staging_write_authorized": true,
  "fetch_date_domain": "calendar",
  "canonical_fetch_date_domain": "calendar",
  "date_domain_source": "DR-001",
  "dr001_start_date": "20160101",
  "dr001_end_date": "20260630",
  "closed_calendar_interval": true,
  "security_universe_source": "CSI800_STATIC_2026_06 membership / security mapping",
  "candidate_price_artifact_superseded": true,
  "candidate_price_artifact_date_domain_ignored": true,
  "d2_t09_candidate_raw_market_prices_is_superseded_diagnostic_input_only": true,
  "fetch_stage_only": false,
  "artifact_hashes_complete": true,
  "amount_unit_status": "resolved_thousand_yuan",
  "volume_unit_status": "resolved_lot",
  "calendar_date_count": 3834,
  "security_count": 800,
  "candidate_universe_row_count": 3067200,
  "daily_raw_row_count": 1730769,
  "source_status_row_count": 3067200,
  "factor_evidence_row_count": 3067200,
  "adjusted_price_row_count": 1730769,
  "daily_row_count_interpretation": "daily rows cover listed/open/applicable dates, not every security-calendar date",
  "missing_daily_unexpected_count_gate": "must_be_zero",
  "listed_open_missing_daily_count_gate": "must_be_zero",
  "pre_listing_and_non_trading_dates": "not_applicable_not_provider_defects",
  "d2_acceptance_decision": "pending_local_finalize_rerun_after_lifecycle_gate_fix",
  "d3_handoff_decision": "d3_candidate_generation_blocked_pending_review"
}
```

## Lifecycle Applicability Gate

For each `security_id` by calendar date, D2-T13 classifies applicability before
counting unresolved fields. Dates not in `trade_cal`, closed dates, pre-listing
dates, and post-delist dates are `not_applicable` for daily, price-limit, and
adjustment-factor evidence. Suspended listed open dates are treated as expected
empty or carry-forward-policy-required according to provider evidence.

Only listed, open, not-suspended security dates with missing daily rows become
`listed_open_missing_daily` and contribute to
`missing_daily_unexpected_count`. Missing `stk_limit` or `adj_factor` rows only
count as unresolved when the security date is listed, open, and not suspended.

## Acceptance Boundary

D2 can only move to `accepted_for_d3_candidate_generation` when source status
and factor evidence cover the full calendar skeleton, adjusted price row count
equals daily raw row count, `missing_daily_unexpected_count` and
`listed_open_missing_daily_count` are zero, unresolved status/factor counts are
zero, artifact hashes are complete, units are resolved, duplicate keys are
zero, and no fatal quality blockers remain.

Sample acceptance cannot promote D2. D3 candidate generation remains blocked
until a full local finalize with the revised lifecycle applicability gate passes
and its aggregate redacted summary is reviewed. D3 data version publication,
PCVT, R0, labels, returns, backtests, and portfolio outputs remain outside this
PR.
