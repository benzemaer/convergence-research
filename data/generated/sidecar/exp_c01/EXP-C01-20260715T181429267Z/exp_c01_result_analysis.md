# EXP-C01 结果分析

本文件只允许描述当前 C1/C2 指标状态身份、可用性、持续性和稳定性；不作未来结果、交易表现或指标替换结论。

## 1. Actual run / reviewed SHA / input lineage

run_id=`EXP-C01-20260715T181429267Z`；reviewed implementation SHA=`58020f299b2c1def96c10eb49778afd6d1eb09d5`；工程 validator 状态=`passed`。
source manifest path=`D:\Code\convergence-research-exp-c01-inputs\exp_c01_authorized_input_manifest_v2.json`；SHA=`2d10de31897955595a33d642cfdfe57773b3304a8bd0b763aea56253a5e9e0fa`；schema/version=`exp_c01_authorized_input_manifest.v1`。
- `dimension_score`：path=`D:\Code\convergence-research\data\generated\r0\r0_t10\R0-T10-02-20260708T1730Z\r0_t05\r0_t05_dimension_score_results.duckdb`，SHA=`4a04fbada9ecac15936e3ab5d968cba8f1205db5dbe66a0491c7141e6fc5b8a5`，table=`r0_t05_dimension_score_results`，required columns=['security_id', 'trading_date', 'percentile_window_W', 'dimension', 'score_dimension', 'score_dimension_min', 'eligible_dimension', 'validity_status']，source full rows=20769228，filtered query rows=1730769，security count=800，date range=2016-01-04 to 2026-06-30。
- `dimension_state`：path=`D:\Code\convergence-research\data\generated\r0\r0_t10\R0-T10-03-20260708T1740Z\r0_t06\r0_t06_dimension_state_results.duckdb`，SHA=`bbbb49ea2056bf6f257c1821236eb2b657eb1490153dfc9e56acee8f33264e08`，table=`r0_t06_dimension_state_results`，required columns=['security_id', 'trading_date', 'percentile_window_W', 'q', 'weak_delta', 'dimension', 'dimension_active_weak', 'validity_status']，source full rows=62307684，filtered query rows=1730769，security count=800，date range=2016-01-04 to 2026-06-30。
- `indicator_score`：path=`D:\Code\convergence-research\data\generated\r0\r0_t10\R0-T10-02-20260708T1730Z\r0_t05\r0_t05_indicator_score_results.duckdb`，SHA=`6da065875c8270e321910083409f4dba5c1ee63bc6328e56aff3a1d489924447`，table=`r0_t05_indicator_score_results`，required columns=['security_id', 'trading_date', 'percentile_window_W', 'indicator_id', 'score', 'eligible', 'validity_status']，source full rows=41538456，filtered query rows=3461538，security count=800，date range=2016-01-04 to 2026-06-30。

## 2. Fixed parameters and variants

W=120、q=0.20、weak_delta=0.10；denominator=`pair_common_valid`。
- `baseline_pair`: pair_valid AND score_C_mean >= 0.80 AND score_C_min >= 0.70。
- `c1_only`: C1 valid AND score_C1 >= 0.80；`c2_only`: C2 valid AND score_C2 >= 0.80。

## 3. Cardinality and date range

year profile calendar range=`2016` to `2026`；year rows=22；security rows=1590。
persisted CSV row counts：variant=3，overlap=3，score=3，year=22，security=1590，availability=3。

## 4. Core counts

- `baseline_pair`：valid rows=1563558，active true=361374，active false=1202184，active rate=0.23112286208762323，valid blocks=1113，valid steps=1562445。
- `c1_only`：valid rows=1563558，active true=387892，active false=1175666，active rate=0.24808289810803308，valid blocks=1113，valid steps=1562445。
- `c2_only`：valid rows=1563558，active true=377593，active false=1185965，active rate=0.2414959982296787，valid blocks=1113，valid steps=1562445。

## 5. Overlap

- `baseline_pair` vs `c1_only`：Jaccard=0.8193751730099605，baseline retention=0.9337694466120972，candidate precision=0.8699328679116868，symmetric difference rate=0.04757482613372833。
- `baseline_pair` vs `c2_only`：Jaccard=0.8256466635373175，baseline retention=0.9247953643593617，candidate precision=0.8850720219919331，symmetric difference rate=0.04513615740509786。
- `c1_only` vs `c2_only`：Jaccard=0.6815641599043983，baseline retention=，candidate precision=，symmetric difference rate=0.09271098353882619。

## 6. Score correlations and score differences

- `c1_vs_c2`：pooled Spearman=0.9048447469786155，median absolute difference=0.05833333333333335。
- `c1_vs_baseline_mean`：pooled Spearman=0.9757513057316767，median absolute difference=0.029166666666666674。
- `c2_vs_baseline_mean`：pooled Spearman=0.9759645511618367，median absolute difference=0.029166666666666674。

## 7. Duration, fragments, and transitions

- `baseline_pair`：segments=36285，duration sum=361374，singleton ratio=0.09053327821413808，transitions=72190，transition rate per 100 valid steps=4.620322635356764。
- `c1_only`：segments=36969，duration sum=387892，singleton ratio=0.08745164867862262，transitions=73501，transition rate per 100 valid steps=4.704229588881528。
- `c2_only`：segments=38495，duration sum=377593，singleton ratio=0.09775295492921159，transitions=76598，transition rate per 100 valid steps=4.902444566048725。

## 8. Availability

- `C1_LogMASpread_5_60`：native valid=1587742，pair common-valid=1563558，gain vs pair=24184。
- `C2_AdjVWAPSpread_5_60`：native valid=1563558，pair common-valid=1563558，gain vs pair=0。
- `pair_common_valid`：native valid=1563558，pair common-valid=1563558，gain vs pair=0。

## 9. Year profiles

- `c1_only`：annual Jaccard range=[0.793335, 0.846269]；annual retention min/median/max=0.918663 / 0.933742 / 0.942025；annual precision min/median/max=0.844614 / 0.879488 / 0.9021。
- `c2_only`：annual Jaccard range=[0.796987, 0.850601]；annual retention min/median/max=0.914776 / 0.924089 / 0.938205；annual precision min/median/max=0.853537 / 0.887099 / 0.909434。
- `baseline_pair`：max-year active share=0.133886，max-year active rate=0.327991，dominant year=2025。
- `c1_only`：max-year active share=0.137206，max-year active rate=0.338808，dominant year=2025。
- `c2_only`：max-year active share=0.13129，max-year active rate=0.341503，dominant year=2023。

## 10. Security profiles

- `c1_only`：security Jaccard q25/median/q75=0.788237 / 0.825101 / 0.854987；retention median=0.934629；precision median=0.876924；max baseline-security active share=0.00177932，max candidate-security active share=0.00172986；pooled-vs-security-median direction=pooled_at_or_below_security_median (pooled=0.819375; security median=0.825101)。
- `c2_only`：security Jaccard q25/median/q75=0.796875 / 0.829971 / 0.858757；retention median=0.926966；precision median=0.888689；max baseline-security active share=0.00177932，max candidate-security active share=0.00183266；pooled-vs-security-median direction=pooled_at_or_below_security_median (pooled=0.825647; security median=0.829971)。

## 11. Baseline reconciliation

reconciliation status=`passed`；mismatch_total=0；key/score/eligible/active/validity mismatches=[('key_count_mismatch', 0), ('score_mean_mismatch', 0), ('score_min_mismatch', 0), ('eligible_mismatch', 0), ('active_mismatch', 0), ('validity_mismatch', 0)]。

## 12. Anomaly scan

- no anomaly was emitted by the registered scan.

## 13. Independent recomputation

status=`passed`；mismatches=[]。
The readback formulas independently check n2x2 conservation, Jaccard, retention, precision, symmetric-difference rate, active rate, valid-step transition rate, segment-duration conservation, singleton ratio, max-year share/rate, and availability gain.

## 14. Alternative explanations

Observed identity or concentration can arise from the fixed threshold geometry, shared pair-valid availability, calendar/security composition, missing or blocked rows, or duplicated upstream materialization. These descriptive artifacts do not identify a causal mechanism.

## 15. Supported conclusions

Only the persisted counts, overlap statistics, score differences, duration summaries, availability differences, and year/security profile statistics are supported. A nonzero reconciliation mismatch, anomaly, or readback mismatch blocks a formal-result interpretation.
User review may separately assess whether the descriptive strong-substitutability reference is reached, whether an availability advantage is evident, whether duration or fragmentation changes, whether year/security concentration exists, and whether any order-of-magnitude item needs investigation; this file does not make those decisions automatically.

## 16. Unsupported conclusions

This result does not support a statement about future outcomes, release direction, trading value, stable advantage, causal substitution, deletion of an indicator, or promotion of a replacement state definition.

## 17. Readiness for user formal-result review

`ready_for_user_formal_result_review`
