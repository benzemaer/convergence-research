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

## Full Run Attempt Summary

The D2-T13 script supports full remote fetch, resume checkpoints, and scoped
sample runs. A full remote run was started locally with `--full`, using the
DR-001 full date boundary in CLI arguments. The run exceeded the local execution
window for this PR update and was stopped by the shell timeout before final
candidate artifacts and full-run reports were written. The checkpoint can be
used to resume without restarting completed trade-date fetches.

This PR update adds the endpoint-worker runner, shared adaptive rate governor,
partitioned local staging writer, fetch ledger, rate governor state, quality
progress summary, and partial hash manifest hooks. The staging store is local
and ignored; it is not a formal DuckDB publication.

The runner now migrates legacy `tnskhdata_fetch_checkpoint.json` records into
the new fetch ledger when `fetch_ledger.jsonl` is absent, so resume does not
restart from 2016. Legacy `completed_trade_dates` are only resume hints; they
are not D2 acceptance evidence. `--repair-failed-only` limits repair runs to
failed trade-date tasks and does not refetch completed dates.

Endpoint staging is no longer loaded into memory as whole endpoint lists during
the fetch stage. Final artifact assembly remains blocked until a streaming or
local-staging SQL assembly pass completes.

Because the full run is incomplete, the D2 acceptance decision remains blocked.
No sample run result is used as D2 acceptance evidence.

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
  "worker_mode": "endpoint",
  "max_workers": 7,
  "initial_requests_per_minute": 200,
  "max_requests_per_minute": 500,
  "final_requests_per_minute": null,
  "rate_increase_events": null,
  "rate_decrease_events": null,
  "candidate_artifact_output_dir": "data/generated/d2/d2_t13_tnskhdata_full_candidate/",
  "candidate_universe_row_count": 1671919,
  "mapped_row_count": null,
  "unmapped_row_count": null,
  "daily_raw_row_count": null,
  "source_status_row_count": null,
  "factor_evidence_row_count": null,
  "adjusted_price_row_count": null,
  "security_count": 800,
  "trading_date_min": "20160703",
  "trading_date_max": "20260630",
  "missing_daily_count": null,
  "missing_stk_limit_count": null,
  "missing_adj_factor_count": null,
  "missing_trade_cal_count": null,
  "missing_stock_basic_count": null,
  "missing_stock_st_count": null,
  "missing_suspend_count": null,
  "unresolved_trading_status_count": null,
  "unresolved_suspension_status_count": null,
  "unresolved_st_status_count": null,
  "unresolved_price_limit_status_count": null,
  "unresolved_adjustment_factor_count": null,
  "amount_unit_status": "not_evaluated_full_run_incomplete",
  "volume_unit_status": "not_evaluated_full_run_incomplete",
  "duplicate_key_count": null,
  "null_ohlc_count": null,
  "non_positive_price_count": null,
  "high_low_violation_count": null,
  "primary_provider_error_count": 0,
  "reconciliation_provider_error_count": 0,
  "pro_bar_reconciliation_status": "not_reached_full_run_incomplete",
  "pro_bar_reconciliation_warning_count": 0,
  "rate_limit_count": 0,
  "timeout_count": 0,
  "retry_count": null,
  "successful_request_count": null,
  "failed_request_count": null,
  "resume_checkpoint_count": 111,
  "last_successful_trade_date": "20161213",
  "failed_trade_dates": [],
  "request_count": 560,
  "request_count_source": "derived_from_completed_trade_dates_after_counting_fix",
  "endpoint_task_counts": {
    "stock_basic": 4,
    "trade_cal": 1,
    "daily": 2426,
    "stk_limit": 2426,
    "adj_factor": 2426,
    "stock_st": 2426,
    "suspend_d": 2426
  },
  "completed_task_counts": {
    "legacy_checkpoint_completed_trade_dates": 111
  },
  "failed_task_counts": {},
  "legacy_checkpoint_migration_supported": true,
  "legacy_completed_dates_are_resume_hints_only": true,
  "repair_failed_only_supported": true,
  "endpoint_partitions_loaded_into_memory": false,
  "keyboard_interrupt_cancel_futures": true,
  "sample_acceptance_decision": null,
  "d2_acceptance_decision": "blocked_pending_tnskhdata_full_materialization_run",
  "d3_handoff_decision": "d3_candidate_generation_blocked",
  "r0_handoff_decision": "r0_blocked",
  "duckdb_written": false,
  "data_version_published": false,
  "d3_rows_generated": false,
  "pcvt_values_generated": false,
  "r0_state_generated": false
}
```

## Artifact Hash Summary

The full run did not complete, so no full-run artifact hash summary is claimed
in this committed redacted summary. Previously generated sample artifacts under
the ignored output directory are superseded for D2 acceptance purposes and are
not used as full-run evidence.

```json
{
  "full_run_artifact_hashes_complete": false,
  "full_run_hash_summary_sha256": null
}
```

## Acceptance Boundary

D2 can only move to `accepted_for_d3_candidate_generation` when generated
artifact hashes are complete, source status covers the candidate universe,
factor evidence covers the candidate universe or is resolved as not applicable,
adjusted price covers normal-trading rows with daily and factor evidence,
price-limit status is resolved or not applicable, units are resolved, duplicate
keys are zero, and no fatal quality blockers remain.

Sample acceptance cannot promote D2. Until the full tnskhdata materialization run
finishes and the full-run artifact hash summary is complete, D2 remains blocked,
D3 candidate generation remains blocked, and D3 data version publication, PCVT,
R0, labels, returns, backtests, and portfolio outputs remain outside this PR.
