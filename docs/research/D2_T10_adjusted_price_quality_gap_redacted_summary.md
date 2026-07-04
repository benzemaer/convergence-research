# D2-T10 Adjusted Price Quality Gap Redacted Summary

## Scope

This is a redacted local execution summary for PR D2-T10. It reports aggregate
candidate artifact quality, trading-constraint readiness, mechanical-gap counts,
and file hashes only. It does not include row-level prices, source symbols,
security mapping rows, vendor payloads, raw parquet bytes, generated candidate
artifacts, DuckDB files, accepted manifests, published data versions, D3 rows,
PCVT values, labels, returns, backtests, or portfolio outputs.

## Local Inputs

- raw candidate artifact: `data/generated/d2/d2_t09_candidate_raw_market_prices/candidate_raw_market_prices.parquet`
- raw candidate quality summary: `data/generated/d2/d2_t09_candidate_raw_market_prices/candidate_quality_summary.json`
- adjustment event input: `data/raw/a_share_adjustment_factors_event_none_all_20260704.parquet`
- probe report: `data/generated/d2/d2_t09_candidate_raw_market_prices/probe_report_20260704.json`
- output directory: `data/generated/d2/d2_t10_adjusted_price_quality_gap/`

All generated files above are local ignored artifacts and are not committed.

## Redacted Candidate Summary

```json
{
  "row_count_raw_candidate": 1673517,
  "row_count_adjusted_candidate": 1673517,
  "security_count": 800,
  "trading_date_min": "2016-07-03",
  "trading_date_max": "2026-07-02",
  "missing_adjustment_factor_count": 1673517,
  "factor_as_of_time_missing_count": 1673517,
  "adjustment_revision_missing_count": 1673517,
  "unknown_trading_status_count": 1673517,
  "unknown_price_limit_status_count": 1673517,
  "mechanical_gap_candidate_count": 0,
  "mechanical_gap_unknown_count": 44042,
  "quality_blocking_flag": true,
  "quality_blocking_reasons": [
    "adjustment_factor_direction_unverified",
    "adjustment_factor_missing_or_unresolved",
    "adjustment_revision_missing",
    "amount_volume_unit_unknown_blocks_d2_acceptance",
    "factor_as_of_time_missing",
    "price_limit_status_unknown_blocks_d2_acceptance",
    "st_status_unknown_blocks_d2_acceptance",
    "suspension_status_unknown_blocks_d2_acceptance",
    "trading_status_unknown_blocks_d2_acceptance"
  ]
}
```

## File Hash Summary

```json
{
  "artifact_sha256": "7f4b7067e596ac628bfe68fb0b407fa10fc4af3f61e7086b4567c71ee7889a95",
  "quality_flags_sha256": "a0c6be063701487f8829c3f6bb860bfdcde3ba775ee953df575394f3b9c8ad06",
  "mechanical_gap_sha256": "3343ada88c3606ec4f304bb08355cebab7c398fcefe70671de60f011a5722a49",
  "readiness_report_sha256": "8ea9d96e4559d146885db04104b91a88e69468a2a96eb2f6f31bdb701a0ad7f7",
  "raw_adjusted_reconciliation_sha256": "fb2b02ef6cee3bb4033af554972806c60ce989e87d9c8c2a6aa56f2f795de554",
  "materialization_report_sha256": "7b0d83a707e197238808accbbb4d0f0ae6f861b019b023ef83f26898b392f376"
}
```

## Boundary Notes

- Candidate artifact creation succeeded as a local candidate run only.
- `candidate_blocking_flag` remains `true`.
- The HiThink adjustment event dump used in this run did not provide directly
  joinable `security_id + trading_date` daily factors for the D2-T09 raw candidate
  artifact, so adjusted prices are raw-equivalent fallback candidates and are
  blocked by missing factor/as-of/revision evidence.
- Trading status, price limit status, suspension status, and ST status readiness
  remain blocked.
- This run does not accept HiThink as a formal source.
- This run does not publish a data version.
- This run does not write DuckDB or create accepted manifests.
- D3-T07 and R0 remain blocked.
