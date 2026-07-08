# R0 Audit Report

## Executive Summary

R0 has completed the PCVT candidate state definition chain through an evidence-backed authorized input manifest and a 27-config candidate full-grid materialization. The completed scope covers candidate indicators, raw metrics, strict-past percentile scores, weak dimension nested states, confirmation / interval artifacts, and artifact-backed full-grid candidate outputs. The formal R0 run can be handed to R1 only as a state existence, frequency, structure, stability, and null-model research input.

R0 does not complete release definitions, future labels, direction or magnitude outcomes, path outcomes, backtest, portfolio construction, trading signal generation, or R1 statistical inference. R1 may consume the R0 handoff package, but R1 must not treat R0 candidate states as selected parameters, validated strategy rules, or tradeable signals.

## Scope

R0 completed PCVT candidate indicators, R0-T04 raw metrics, R0-T05 strict-past percentile scores, R0-T06 weak dimension nested states, R0-T07 confirmation / interval layer, R0-T10-05 27-config candidate artifact full-grid, and an evidence-backed authorized input chain.

R0 does not complete release definition, future labels, direction / magnitude / path outcome, backtest, portfolio, trading signal, or R1 statistical inference. R0-T11 is an audit and handoff task only; it does not recalculate upstream artifacts and does not start R1 analysis.

## Source Lineage

| Layer | Task | PR | Evidence | Run ID | Code Commit | Key Input Hash | Key Output Hash | Row Count | Security Count | Date Range | Downstream Gate |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |
| Raw metrics | R0-T10-01 / R0-T04 | #69 | `docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md` | R0-T10-01-20260707T1345Z | `7ea2e649f0c9f0d04614cbbe7240747b98adec39` | `57707f6ed5e821bd837029e3f0a8f42c1e1a0ecc432002df959a71064177f103` | `100f515de8e337c82e86e3f3760648df4229860dd83c16ac767065c4f2e16fc7` | 13,846,152 | 800 | 20160104-20260630 | R0-T05_allowed_to_start=true |
| Strict-past scores | R0-T10-02 / R0-T05 | #70 | `docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md` | R0-T10-02-20260707T1500Z | `bc0920f811bf683ecffbb81a5ce9119cb4858256` | `100f515de8e337c82e86e3f3760648df4229860dd83c16ac767065c4f2e16fc7` | `3061c07c0ab5074e54e1bbf83780c4fd3b2b065700314f1c1ca2f3524e83f944` | 41,538,456 indicator score rows | 800 | 20160104-20260630 | R0-T06_allowed_to_start=true |
| Nested states | R0-T10-03 / R0-T06 | #71 | `docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md` | R0-T10-03-20260707T1630Z | run argument `92dccee`; PR head `92dcceefd710de40a65daa7d0e414bd7708f5353` | `3061c07c0ab5074e54e1bbf83780c4fd3b2b065700314f1c1ca2f3524e83f944` | `1a5aa1375a46e5909f16d64353908dd7ad1d0754078079136b0aae06263be9d4` | 15,576,921 nested daily rows | 800 | 20160104-20260630 | R0-T07_allowed_to_start=true |
| Confirmation / interval | R0-T10-04 / R0-T07 | #72 | `docs/evidence/r0/R0-T10-04_r0_t07_confirmation_interval_materialization_evidence.md` | R0-T10-04-20260707T1711Z | `99a914d59b6563b5bd685d09ee5e7804a325c397` | `1a5aa1375a46e5909f16d64353908dd7ad1d0754078079136b0aae06263be9d4` | `643b988359823d89ca5d38b58716f6c5880aa0b45e0c81fe21bfe9faa991ae29` | 186,923,052 daily confirmation rows; 0 interval rows | 800 | 20160104-20260630 | R0-T10-05_allowed_to_start=true |
| Authorized manifest and full-grid | R0-T10-05 | #73 | `docs/evidence/r0/R0-T10-05_authorized_input_manifest_full_grid_evidence.md` | R0-T10-05-20260707T1845Z | `3bef6cab84f15771e24b3db903e8fa1c2726ad81` | `77d92279e55ea8bb012390c033d4f4f1ada9cee2f284532cd4be733689d4a40e` | `a30d5bc7d1613637dbdfaa0f889f1f58719335bbf9831d95c079c6ba33ac1a96` | 186,923,052 daily candidate rows; 0 interval rows | 800 | 20160104-20260630 | R0-T11_allowed_to_start=true |

## State Definition Audit

R0 freezes the PCVT candidate state vocabulary for R1 input review: P/C/T/V four dimensions, active indicators, dimension weak state, nested raw state, exclusive state layer, confirmation K=2/3/5, W=120/250/500, q=0.10/0.20/0.30, weak_delta=0.10, baseline config `R0_W250_Q20_K3_WEAK_D010`, and the 27 config grid. The R0 audit introduces no new parameter, no secondary tuning, and no recommended production parameter.

## Coverage Audit

The formal R0 chain covers security_count = 800 and date range = 20160104 to 20260630. R0-T04 row count is 13,846,152. R0-T05 indicator score row count is 41,538,456, dimension score row count is 20,769,228, and common eligible row count is 1,730,769. R0-T06 nested daily state row count is 15,576,921. R0-T07 daily confirmation row count is 186,923,052 and R0-T07 confirmed interval row count is 0. R0-T10-05 daily candidate row count is 186,923,052 and R0-T10-05 confirmed interval row count is 0. The full-grid selected_config_count: 27, completed_config_count: 27, failed_config_count: 0.

## Zero Interval Audit

R0-T07 confirmed interval row count = 0 and R0-T10-05 confirmed interval row count = 0. R0-T10-05 records confirmed_interval_row_count_total: 0, daily_confirmed_true_count_total: 0, confirmed_interval_zero_config_count: 27, and zero interval reason `no_confirmed_segments_in_r0_t07_input`. This is a legitimate fact from the formal input distribution, not a materializer failure.

R1-T01 cannot use confirmed interval as the primary analysis object because the current formal run has no confirmed intervals. R1-T01 should start from raw nested states, daily confirmation rows, and candidate daily state frequency profiles, including raw_state and confirmed_state distributions, state sparsity, unknown / blocked distributions, and the effect of absent confirmed intervals.

## Engineering Audit

R0-T10-05 uses no monolithic JSON payload production path. It uses artifact-backed input, a spawn process pool, parent-process summary aggregation without row payloads, and per-worker artifact reads. Generated DuckDB and Parquet outputs are not committed. Formal code_commit values use the full SHA policy, with short SHA forbidden since PR #72; R0-T10-03 remains documented as a historical short-SHA run argument rather than being rewritten. `scripts/r0` contains thin wrappers, and core logic resides under `src/r0`.

## Forbidden Field Audit

The R0 formal path records no future label, no future return, no release direction, no breakout direction, no backtest output, no portfolio output, no trade signal output, no direct raw/external/MarketDB/.day source lineage in R0-T10 formal input, no synthetic contract-grid production input, and no legacy V1 field. R0-T10-05 validator_status is passed, with source_evidence_check, input_artifact_hash_check, synthetic_input_check, raw_external_source_check, full_code_commit_check, forbidden_field_check, and legacy_v1_check all passed.

## R0 Completion Decision

R0_status: completed

R1_allowed_to_start: true

R1_starting_task: R1-T01 状态存在性与频率轮廓
