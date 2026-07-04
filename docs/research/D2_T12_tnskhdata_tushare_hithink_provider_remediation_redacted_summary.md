# D2-T12 tnskhdata/Tushare HiThink Provider Remediation Redacted Summary

## Scope

This is a redacted D2-T12 provider-remediation summary. It records aggregate
coverage, source decisions, policy acceptance, gate decisions, and report hashes
only. It does not include row-level prices, source-symbol lists, security mapping
rows, vendor payloads, API tokens, raw parquet bytes, generated evidence
artifacts, DuckDB files, accepted manifests, data versions, D3 rows, PCVT values,
labels, returns, backtests, signals, or portfolio outputs.

## Source Decision

```json
{
  "ci_test_failure_fixed": true,
  "tnskhdata_raw_factor_status_path": "primary_candidate_source",
  "hithink_raw_source_path": "deprecated_for_d1_d2_candidate_materialization_after_D2-T12",
  "hithink_rest_path": "diagnostic_probe_only",
  "baostock_path": "fallback_diagnostic_only",
  "tushare_path": "fallback_diagnostic_only",
  "d1_raw_candidate_source": "tnskhdata daily",
  "d2_adjustment_factor_candidate_source": "tnskhdata adj_factor",
  "d2_status_constraint_candidate_sources": [
    "tnskhdata stk_limit",
    "tnskhdata trade_cal",
    "tnskhdata stock_basic",
    "tnskhdata stock_st",
    "tnskhdata suspend_d"
  ]
}
```

HiThink historical contracts, PR records, and probe artifacts are not deleted or
rewritten. D2-T12 only changes the candidate path decision after the failed
HiThink-mixed evidence route: future D1/D2 candidate remediation should rebuild
raw, factors, status, and continuous adjusted price candidates from tnskhdata.

## Accepted As-Of And Revision Policy

```json
{
  "policy_id": "D2_TNSKHDATA_SOURCE_LEVEL_ASOF_SNAPSHOT_REVISION_POLICY_V1",
  "source_id": "tnskhdata",
  "factor_as_of_time_policy": "tnskhdata_adj_factor_source_level_daily_ingestion_window",
  "factor_as_of_time": "trade_date 09:20:00 Asia/Shanghai",
  "row_level_factor_as_of_time_available": false,
  "adjustment_revision_class": "snapshot_level_revision",
  "adjustment_revision_source": "source_snapshot_id + artifact_sha256 + run_id",
  "provider_row_level_revision_available": false,
  "point_in_time_eligibility_class": "source_level_asof_snapshot_revision",
  "point_in_time_eligible_for_eod_research": true,
  "strict_provider_row_level_revision_eligible": false
}
```

This policy means tnskhdata `adj_factor` rows no longer fail solely because the
provider does not expose row-level adjustment revision timestamps. A candidate
factor can resolve when `adj_factor`, source snapshot identity, artifact hash,
and run identity are present.

## Coverage Summary

```json
{
  "mapping_success_count": 100,
  "mapping_failure_count": 0,
  "daily_raw_coverage_decision": "tnskhdata_daily_primary_candidate",
  "trade_cal_coverage_decision": "tnskhdata_trade_cal_primary_candidate",
  "stock_basic_coverage_decision": "tnskhdata_stock_basic_primary_candidate",
  "stock_st_coverage_decision": "tnskhdata_stock_st_primary_candidate",
  "suspend_d_coverage_decision": "tnskhdata_suspend_d_primary_candidate",
  "stk_limit_coverage_decision": "tnskhdata_stk_limit_primary_candidate",
  "adj_factor_coverage_decision": "tnskhdata_adj_factor_primary_candidate",
  "price_limit_status_derivation": "provider_stk_limit_plus_daily_ohlc",
  "trading_status_classification": "stock_basic + trade_cal + daily + suspend_d",
  "continuous_adjusted_price_candidate": "raw_price * adj_factor with explicit qfq end_date anchor"
}
```

The PR adds deterministic rules for:

- `not_listed_yet`, `after_delist`, `market_closed`, and `suspended` as resolved
  trading-status classes rather than unknowns.
- `suspended`, `resumed`, `not_suspended`, and `not_applicable` suspension
  classes.
- `stock_st` as the primary ST evidence source, with `namechange` retained only
  as a candidate fallback marked `namechange_derived_candidate`.
- `limit_up_price`, `limit_down_price`, and `price_limit_status` from
  `stk_limit + daily` with `price_compare_epsilon = 0.001`.
- `hfq` candidate reconstruction as `raw_price * adj_factor`.
- `qfq` candidate reconstruction as `raw_price * adj_factor / anchor_adj_factor`
  with an explicit end-date anchor requirement.

## Remaining Blockers

```json
{
  "d2_acceptance_decision": "blocked_pending_tnskhdata_full_materialization_run",
  "d3_handoff_decision": "d3_candidate_generation_blocked",
  "r0_handoff_decision": "r0_blocked",
  "remaining_blockers": [
    "full_tnskhdata_candidate_evidence_not_committed",
    "accepted_manifest_not_created",
    "data_version_not_published",
    "d3_generation_not_executed"
  ]
}
```

The source-level as-of and snapshot-level revision policy is accepted for
candidate evidence. D2 acceptance is still not marked as completed in this PR
because the generated candidate evidence files remain ignored local artifacts and
no accepted manifest or data version is created.

## Local Smoke Run

The new builder was executed locally against the ignored D2-T09 candidate
universe to verify output boundaries and hashing. This smoke run did not promote
the outputs and did not create an accepted manifest or data version.

```json
{
  "candidate_universe_input": "data/generated/d2/d2_t09_candidate_raw_market_prices/candidate_raw_market_prices.parquet",
  "output_dir": "data/generated/d2/d2_t12_tnskhdata_candidate_evidence/",
  "row_count_input": 1673517,
  "source_status_row_count": 1673517,
  "factor_evidence_row_count": 1673517,
  "adjusted_price_row_count": 0,
  "duckdb_written": false,
  "data_version_published": false,
  "d3_rows_generated": false,
  "r0_state_generated": false
}
```

Because this smoke run did not pull and commit full tnskhdata provider evidence,
it remains a boundary check, not D2 acceptance evidence.

## Report Hashes

The committed policy and contract files are validated by JSON Schema. Local
generated evidence artifacts remain ignored and are not committed.

```json
{
  "tnskhdata_source_level_asof_snapshot_revision_policy": "validated_by_schema",
  "tnskhdata_tushare_hithink_provider_remediation_contract": "validated_by_schema",
  "candidate_evidence_output_dir": "data/generated/d2/d2_t12_tnskhdata_candidate_evidence/",
  "tnskhdata_source_status_candidate": "55e110e509c01d9e1dcc938db972629cad4ba8883a35d1deee9dcc62ca6a3b56",
  "tnskhdata_factor_evidence_candidate": "8aaea0140fe6e87b1c4640aa8b5a6d1934289de0eedcf1d4a29daa2282c6846e",
  "tnskhdata_reconciliation_report": "03537c84522870e98728669bef880c6f1d53ab74cf0b533f75ac7f2740f7e4aa"
}
```

## Boundary Notes

- No D3 generation is performed by this PR.
- No R0 generation, labels, future returns, backtest, or portfolio output is
  produced.
- No DuckDB write, accepted manifest, formal data version, raw parquet, or
  row-level vendor payload is committed.
- Tests use fake provider clients and fake environment values only. Real provider
  credentials are loaded only from local environment or `.env.local` at runtime
  and are never printed or written to committed files.
