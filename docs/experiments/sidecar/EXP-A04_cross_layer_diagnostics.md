# EXP-A04 Cross-layer Diagnostics

EXP-A04 is an implementation-stage sidecar experiment in the long-lived EXP-A pull request. It diagnoses contemporaneous relationships between the three accepted A candidates and the eight accepted R0-T04 P/C/T/V raw indicators. It is not a candidate selector, A-layer registration, PCATV construction, or EXP-A05 execution.

## Frozen inputs and registry

The A-side registry is the accepted EXP-A03 set: `A1_LogBodyCenterToMACloudCenter_5_60`, `A2_BodyCenterOutsideMACloudRate20_5_60`, and `A2b_BodyToMACloudGapMean20_5_60`. The PCVT registry is parsed from the committed R0-T01 candidate specification and R0-T04 raw contract. It contains exactly two indicators in each of P, C, T, and V, all with `lower_is_more_convergent`; V2 remains the raw base object `V2_LogAmount20_base`, not the downstream `V2_AmountLevel20Pct`.

The accepted PCVT raw handoff binds the repaired `R0-T10-01-20260708T1715Z` materialization, table `r0_t04_raw_metric_results`, 13,846,152 rows, 1,730,769 security-date keys, 800 securities, and 2016-01-04 through 2026-06-30. Because the R0 raw table has no observation sequence, EXP-A04 uses an explicit security/date adapter only after proving both sides are unique on that key. Duplicate or invalid canonical dates fail closed.

## Diagnostics

The 24 fixed pairs use their own valid finite intersection. Pearson is auxiliary; the primary relationship is tie-aware midrank Spearman computed overall, by year, and by security. Securities with fewer than 100 common observations are ineligible; constant or undefined eligible-sized groups are reported as undefined rather than coerced. Lower tails use `QUANTILE_DISC` at 0.01, 0.05, and 0.10 and include every threshold tie.

The hard cross-layer collision rule is all-of: overall Spearman at least 0.95, minimum yearly Spearman at least 0.90, eligible-security Spearman q10 at least 0.80, and both 5% and 10% tail Jaccards at least 0.80. Collision is an investigation result only. All three A candidates are carried to A05, with a collision-review status when applicable; no A candidate is deleted or selected.

## Outputs and governance

Only the 13 compact artifacts specified by the versioned config may be published. No joined row-level file, persistent DuckDB, Parquet, score, state, future outcome, return, signal, or backtest is produced. The runner has mutually exclusive synthetic and formal modes, performs lineage and exact-head gates before opening raw inputs, runs one independent validator and one anomaly scan, preserves a compact failure package without copying raw databases, and atomically publishes only after cheap final validation.

Implementation status at this commit is `pending`; `formal_run_allowed=false`, `formal_run_executed=false`, `formal_artifacts_generated=false`, `EXP_A05_started=false`, `A_layer_registered=false`, and `PCATV_created=false`.
