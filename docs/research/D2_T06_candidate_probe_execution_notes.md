# D2-T06 Candidate Probe Execution Notes

## Status

The BAOSTOCK small-sample probe execution remains blocked in the current local environment. PR #32 records the attempted execution workflow without changing the committed execution report to an executed status.

## Commands

Dry-run command:

```text
python scripts/run_d2_candidate_market_snapshot_probe.py --plan configs/d2/candidate_market_snapshot_probe_execution_plan.v1.json --dry-run
```

BAOSTOCK dependency check:

```text
python -c "import importlib.util; print(importlib.util.find_spec('baostock') is not None)"
```

## Result

- Source: BAOSTOCK.
- Sample security count: 3.
- Sample date window: 2024-12-16 to 2024-12-31.
- Dry-run result: `not_executed_environment_blocked`.
- Real execution result: not executed because the current environment does not have the `baostock` Python package installed.
- Raw snapshot committed: false.
- Row-level prices committed: false.
- DuckDB written: false.
- Run, dataset, and source snapshot manifests created: false.
- Formal D1/D2/D3 materialization: false.

## Redacted Report Summary

- `execution_status`: `not_executed_environment_blocked`.
- `raw_ohlcv_coverage`: `not_executed`.
- `qfq_coverage`: `not_executed`.
- `hfq_coverage`: `not_executed`.
- `vendor_adjustment_factor_coverage`: `not_executed`.
- `factor_as_of_time_coverage`: `not_executed`.
- `revision_timestamp_coverage`: `not_executed`.
- `implied_qfq_factor_check`: `not_executed`, checked count 0.
- `implied_hfq_factor_check`: `not_executed`, checked count 0.
- `history_revision_class`: `unknown`.
- `research_use_tier`: `exploration_only`.

## Blocking Reasons

- `environment_not_authorized_for_external_api`.
- `source_terms_pending_for_formal_ingestion`.
- `factor_as_of_time_not_verified`.
- `revision_comparison_not_run`.
- `formal_d1_d2_materialization_not_authorized`.
- `d3_not_authorized`.

## Next Decision

Run the PR #31 execution framework in an explicitly authorized local environment with `baostock` installed, then update only the committed redacted execution report if the output passes the redaction and governance checks.
