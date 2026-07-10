# R0 To R1 Handoff

This handoff is the operational input guide for R1-T01. It describes the formal R0 package that R1 may consume after R0-T11 validator passes. It does not start R1 analysis and does not add new R0 state semantics.

## R1 Input Package

R1 may read the R0-T10-05 authorized input manifest at `data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t10_05_authorized_input_manifest.json`, the R0-T10-05 full-grid global manifest at `data/generated/r0/r0_t10/R0-T10-05-20260708T1754Z/r0_t09_full_grid/r0_t10_05_full_grid_manifest.json`, each per-config candidate daily state artifact, each per-config candidate confirmed interval artifact, the repaired R0-T07 daily confirmation and confirmed interval artifacts, the repaired R0-T06 nested daily state artifact, the repaired R0-T05 score artifacts, the repaired R0-T04 raw metric artifact, and all corresponding evidence records under `docs/evidence/r0/`.

R1 must keep the evidence chain intact. R1-T01 may use R0-T10-05 candidate daily state rows, R0-T07 daily confirmation rows, R0-T06 nested daily state rows, R0-T05 score artifacts, and R0-T04 raw metric artifacts only through the paths, hashes, and gates recorded in R0-T10-01 through R0-T10-05 evidence and indexed by R0-T11.

## R1 Prohibited Inputs

R1 must not read synthetic fixtures, contract-grid smoke payloads, raw/external/MarketDB/.day sources, D3 candidate outputs without the R0 evidence chain, unverified local generated outputs, row payload JSON, future labels, or backtest outputs. R1 must not bypass R0-T10 evidence by going directly to D3 candidate files or any lower-level raw source.

## Recommended R1-T01 Start

R1-T01 should begin with 状态存在性与频率轮廓. The minimum question set is daily candidate row count by W/q/K/config, raw_state and confirmed_state distribution, S_P / S_PC / S_PCT / S_PCVT frequency, validity_status distribution, unknown / blocked distribution, exclusive layer distribution, state sparsity, confirmed interval availability, and whether confirmed_state is sufficiently populated for later R1 structure and null-model work.

The repaired formal package has nonzero confirmed intervals across all 27 W/q/K configs. R1-T01 should treat that as an input fact while still avoiding release outcome, future-label, backtest, or parameter-selection interpretation.

## R1工程执行约束

R1-T01 必须引用并遵守 `docs/03 §12`。如果 R1-T01 只是 contract/synthetic work，则不能推进 formal evidence gate；如果 R1-T01 产生正式统计结果，则必须采用 two-stage / 两阶段推进、formal evidence、validator 和 README gate。R1-T01 不得生成 monolithic row payload input，不得绕过 evidence-bound R0 handoff package，也不得使用 future labels、future returns、backtest、portfolio 或 trade signal。

R1-T01 的输出如果进入 R1-T02，必须有 validator passed 的 evidence。R1-T02 只能消费 evidence-bound artifacts，不能直接读取 loose local artifacts 或未验证的 generated outputs。

## R1-T01 Forbidden Scope

R1-T01 must not introduce future收益, release direction, release magnitude, trading signal, backtest, parameter selection, portfolio construction, or out-of-sample validation. Those topics belong to later stages after R1 has completed existence, frequency, structure, stability, and null-model review.

## Deferred R1 Items

R1-T02 should handle structure relationship and coordination constraints after R1-T01 establishes frequency and state existence. R1-T03 should handle stability and null-model checks after R1-T01 and R1-T02 define the observed state distributions and structural relationships. Release outcome, future label, direction, path, and trading feasibility remain outside R1-T01 and outside R0-T11.
