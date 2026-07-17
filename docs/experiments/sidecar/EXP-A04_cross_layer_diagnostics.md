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

## Formal run result

The approved implementation SHA was `896444244d4f72069a654812e318fb312c01f018` and the exact-run Quality was `29602494775 / success`. The one formal run was `EXP-A04-20260717T183534377Z`. Its external canonical authorized manifest is `D:\Code\convergence-research-inputs\exp_a04\EXP-A04-INPUT-V1\exp_a04_authorized_input_manifest.json` with SHA256 `73347a2ff738dd32cb756e3aeaed229574f46da28bded501bfa407f6724b1ca0`. It bound the accepted A03 package, A01 raw metrics, the accepted PCVT handoff, and the corrected PCVT raw path in the separate `D:\Code\convergence-research` worktree; the raw DuckDB files and manifest remain local-only.

The compact package is committed at `data/generated/sidecar/exp_a04/EXP-A04-20260717T183534377Z`. It contains exactly 13 files: 11 indicator/pair/summary CSV or JSON-analysis inputs plus the manifest, validator, anomaly, disposition, and analysis artifacts specified by the config; no DuckDB or Parquet is present. The package has 11 indicator-registry rows, 24 coverage rows, 24 overall rows, 264 year rows, 19,200 security rows, 72 tail rows, 12 layer-summary rows, and 3 candidate-summary rows. The runner validator and the standalone independent validator both passed with zero errors and zero mismatches; the latter replayed lineage and aggregates from disk with one core-validator execution.

The anomaly scan is `passed`, with zero blocking anomalies and zero investigation items. All 24 hard-collision booleans are false, so the hard-collision pair list is empty. The candidate carry-forward set remains `["A1", "A2", "A2b"]`; each candidate has zero hard-collision pairs and provisional status `carry_to_A05`. The nearest overall-Spearman pair for A1 is C1 (`0.6090569`), for A2 is T1 (`0.3608307`), and for A2b is P2 (`0.7291708`). These are descriptive diagnostics only and do not select a winner.

Formal-result review is pending. `formal_run_allowed=true`, `formal_run_executed=true`, `formal_artifacts_generated=true`, `result_review_status=not_started`, `EXP_A05_started=false`, `A_layer_registered=false`, and `PCATV_created=false`. No candidate was accepted or deleted, no A-layer was registered, and no PCATV was created.
