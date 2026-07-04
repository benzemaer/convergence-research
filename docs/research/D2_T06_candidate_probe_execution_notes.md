# D2-T06 Candidate Probe Execution Notes

## Status

The BAOSTOCK small-sample probe execution completed in a local authorized environment. PR #32 updates only the committed redacted execution report and documentation; formal ingestion and D1/D2/D3 materialization remain blocked.

## Commands

Dry-run command:

```text
python scripts/run_d2_candidate_market_snapshot_probe.py --plan configs/d2/candidate_market_snapshot_probe_execution_plan.v1.json --dry-run
```

BAOSTOCK dependency check:

```text
python -c "import importlib.util; print(importlib.util.find_spec('baostock') is not None)"
```

Execute command:

```text
$env:D2_PROBE_ALLOW_EXTERNAL_API="1"
python scripts/run_d2_candidate_market_snapshot_probe.py --plan configs/d2/candidate_market_snapshot_probe_execution_plan.v1.json --execute --source BAOSTOCK > $env:TEMP\d2_t06_baostock_redacted_report.json
```

## Result

- Source: BAOSTOCK.
- Sample security count: 3.
- Sample date window: 2024-12-16 to 2024-12-31.
- BAOSTOCK package import check: true.
- Dry-run result: `not_executed_environment_blocked`.
- Real execution result: `executed_small_sample`.
- Raw snapshot committed: false.
- Raw snapshot written local: true.
- Row-level prices committed: false.
- DuckDB written: false.
- Run, dataset, and source snapshot manifests created: false.
- Formal D1/D2/D3 materialization: false.

## Redacted Report Summary

- `execution_status`: `executed_small_sample`.
- `raw_ohlcv_coverage`: `pass`.
- `qfq_coverage`: `pass`.
- `hfq_coverage`: `pass`.
- `vendor_adjustment_factor_coverage`: `fail`.
- `factor_as_of_time_coverage`: `fail`.
- `revision_timestamp_coverage`: `fail`.
- `implied_qfq_factor_check`: `pass`, checked count 36, mismatch count 0.
- `implied_hfq_factor_check`: `pass`, checked count 36, mismatch count 0.
- `raw_response_sha256_count`: 3.
- `source_snapshot_id_count`: 3.
- `history_revision_class`: `final_revised_history`.
- `research_use_tier`: `exploration_only`.

## Blocking Reasons

- `environment_not_authorized_for_external_api`.
- `source_terms_pending_for_formal_ingestion`.
- `factor_as_of_time_not_verified`.
- `revision_comparison_not_run`.
- `formal_d1_d2_materialization_not_authorized`.
- `d3_not_authorized`.

## Next Decision

Review the redacted execution report and decide whether additional source terms, as-of, revision, factor_as_of_time, and repeated snapshot comparison evidence is sufficient for a later D2 decision. This note does not authorize formal ingestion.
