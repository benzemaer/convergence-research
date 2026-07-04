# D2-T09 HiThink Candidate Raw Market Prices Redacted Summary

## Scope

This is a redacted local execution summary for PR #41 D2-T09 stage 3. It reports
aggregate candidate artifact quality and file hashes only. It does not include
row-level prices, source symbols, vendor payloads, raw parquet bytes, generated
candidate artifacts, security mapping rows, DuckDB files, accepted manifests,
published data versions, D3 rows, PCVT values, labels, returns, backtests, or
portfolio outputs.

## Local Inputs

- raw K input: `data/raw/a_share_daily_k_1d_none_10y_20260704.parquet`
- adjustment event input for probe: `data/raw/a_share_adjustment_factors_event_none_all_20260704.parquet`
- probe report: `data/generated/d2/d2_t09_candidate_raw_market_prices/probe_report_20260704.json`
- local security mapping: `data/generated/d2/d2_t09_candidate_raw_market_prices/security_mapping_local.json`
- output directory: `data/generated/d2/d2_t09_candidate_raw_market_prices/`

All generated files above are local ignored artifacts and are not committed.

## Candidate Quality Summary

```json
{
  "row_count_input": 10130182,
  "row_count_output": 1673517,
  "dropped_unmapped_security_count": 8456665,
  "security_count_output": 800,
  "trading_date_min": "2016-07-03",
  "trading_date_max": "2026-07-02",
  "null_ohlc_count": 0,
  "nonpositive_ohlc_count": 0,
  "ohlc_order_violation_count": 0,
  "null_volume_count": 0,
  "null_amount_count": 0,
  "negative_volume_count": 0,
  "negative_amount_count": 0,
  "unknown_trading_status_count": 1673517,
  "unknown_price_limit_status_count": 1673517,
  "duplicate_key_count": 0,
  "candidate_blocking_flag": true,
  "candidate_blocking_reasons": [
    "unknown_status_blocks_future_d2_acceptance"
  ]
}
```

## File Hash Summary

```json
{
  "candidate_artifact_sha256": "728d9a7c26e08a6660adfdcc19c5cfb762c77ffc6b60c4819b721a11788e72e1",
  "quality_summary_sha256": "78351668f2922f77964d7a53729c030e4f8d6851247a59fbf1137b7833d0e42d",
  "materialization_report_sha256": "6ef3553f1f10291dba96b5f2f01f52e321b4cc67d8e5d66909f014337e5b2027"
}
```

## Boundary Notes

- Candidate artifact creation succeeded as a local candidate run only.
- `candidate_blocking_flag` remains `true` because both `trading_status` and
  `price_limit_status` are `unknown` for all candidate rows.
- This run does not accept HiThink as a formal source.
- This run does not publish a data version.
- This run does not write DuckDB or create accepted manifests.
- D3-T07 and R0 remain blocked.
