# D2-T13 tnskhdata Full Materialization Acceptance Redacted Summary

## Scope

This summary records the D2-T13 tnskhdata full candidate materialization gate
without committing generated artifacts. It contains aggregate counts, date range,
coverage status, quality flags, acceptance decisions, source snapshot identity,
and hashes only.

It does not contain row-level prices, source-symbol lists, security mapping rows,
vendor payloads, raw provider responses, API tokens, generated artifact contents,
DuckDB files, D3 rows, PCVT values, R0 states, labels, returns, backtests, or
portfolio outputs.

## Date Boundary

The provider fetch window follows DR-001:

```json
{
  "date_boundary_source": "docs/decisions/DR-001_G0静态中证800样本与时间边界.md",
  "start_date": "20160101",
  "end_date": "20260630",
  "calendar_boundary": "closed_interval",
  "trading_day_filter": "tnskhdata trade_cal"
}
```

## Source Decision

```json
{
  "primary_candidate_source": "tnskhdata",
  "diagnostic_fallback": ["Tushare", "BAOSTOCK"],
  "deprecated_probe_only": ["HiThink raw"],
  "d1_raw_source": "tnskhdata daily",
  "d2_factor_source": "tnskhdata adj_factor",
  "status_sources": [
    "tnskhdata stock_basic",
    "tnskhdata trade_cal",
    "tnskhdata stk_limit",
    "tnskhdata stock_st",
    "tnskhdata suspend_d"
  ]
}
```

## Local Scoped Run Summary

The D2-T13 script supports full remote fetch, resume checkpoints, and scoped
sample runs. A scoped remote sample run was executed locally with
`--sample-securities 1 --sample-dates-per-security 1`, using the DR-001 full
date boundary in CLI arguments. Generated outputs were written only under
ignored `data/generated/d2/d2_t13_tnskhdata_full_candidate/`.

The run resolved the main D1/D2 candidate evidence fields for the sampled row.
`pro_bar` is reconciliation-only and was unavailable through the active client,
so `pro_bar_reconciliation_status = failed_non_blocking`. The D2 acceptance
candidate is not blocked by this reconciliation-only warning.

```json
{
  "run_id": "tnskhdata_d2_t13_20160101_20260630_sample",
  "source_snapshot_id": "tnskhdata_d2_t13_20160101_20260630_sample",
  "candidate_artifact_output_dir": "data/generated/d2/d2_t13_tnskhdata_full_candidate/",
  "candidate_universe_row_count": 1,
  "mapped_row_count": 1,
  "unmapped_row_count": 0,
  "daily_raw_row_count": 1,
  "source_status_row_count": 1,
  "factor_evidence_row_count": 1,
  "adjusted_price_row_count": 1,
  "security_count": 1,
  "trading_date_min": "20260630",
  "trading_date_max": "20260630",
  "missing_daily_count": 0,
  "missing_stk_limit_count": 0,
  "missing_adj_factor_count": 0,
  "missing_trade_cal_count": 0,
  "missing_stock_basic_count": 0,
  "missing_stock_st_count": 0,
  "missing_suspend_count": 0,
  "unresolved_trading_status_count": 0,
  "unresolved_suspension_status_count": 0,
  "unresolved_st_status_count": 0,
  "unresolved_price_limit_status_count": 0,
  "unresolved_adjustment_factor_count": 0,
  "amount_unit_status": "resolved_thousand_yuan",
  "volume_unit_status": "resolved_lot",
  "duplicate_key_count": 0,
  "null_ohlc_count": 0,
  "non_positive_price_count": 0,
  "high_low_violation_count": 0,
  "primary_provider_error_count": 0,
  "reconciliation_provider_error_count": 1,
  "pro_bar_reconciliation_status": "failed_non_blocking",
  "pro_bar_reconciliation_warning_count": 1,
  "rate_limit_count": 0,
  "resume_checkpoint_count": 0,
  "request_count": 10,
  "d2_acceptance_decision": "accepted_for_d3_candidate_generation",
  "d3_handoff_decision": "d3_candidate_generation_allowed",
  "r0_handoff_decision": "r0_blocked",
  "duckdb_written": false,
  "data_version_published": false,
  "d3_rows_generated": false,
  "pcvt_values_generated": false,
  "r0_state_generated": false
}
```

## Artifact Hash Summary

The following hashes are from ignored local generated artifacts. They are
recorded here as aggregate evidence only; the artifacts themselves are not
committed.

```json
{
  "tnskhdata_daily_raw_candidate": "3fae6a56006bc9d93f88a444f3ccdbdff170c60fc8c867f22c4f2c0a5dbc41b5",
  "tnskhdata_source_status_candidate": "44a95fb619ec3b3bd7c8f22d7bd4dfddf849c407ee7a75c6c6a15df6d9df3193",
  "tnskhdata_factor_evidence_candidate": "129797b7e1a4dca69a2be28dea1989909c2ce056b8cee1f6aad234ed0210cc4d",
  "tnskhdata_adjusted_price_candidate": "30ca6fdf4f7755dfb5fbc0cae5ba6726b64bdcb62bc124bfb1ee36d1c1d51b15",
  "tnskhdata_quality_report": "f30e953bf408c8b7c7e62751c679ccd2d53ed10f1fdf9c9dab5c9011e6ce468e",
  "tnskhdata_reconciliation_report": "397584b111c80caf271de3d3a1b1c357181e23834bb9cd59154f24f2058f9bdc",
  "tnskhdata_d2_acceptance_candidate_report": "208d0bd0fc4f18cc15b0939f095039da9a0e95c718db5145212f505fb79b86a3",
  "tnskhdata_d3_handoff_candidate_report": "1c0c5e94425dddc8f8ea6f25bb91d24544ae5bd2c7bba74ae5628eed1f8b2379"
}
```

## Acceptance Boundary

D2 can only move to `accepted_for_d3_candidate_generation` when generated
artifact hashes are complete, source status covers the candidate universe,
factor evidence covers the candidate universe or is resolved as not applicable,
adjusted price covers normal-trading rows with daily and factor evidence,
price-limit status is resolved or not applicable, units are resolved, duplicate
keys are zero, and no fatal quality blockers remain.

D3 handoff may be allowed by the D2-T13 candidate decision, but D3 generation,
D3 data version publication, PCVT, R0, labels, returns, backtests, and portfolio
outputs remain outside this PR.
