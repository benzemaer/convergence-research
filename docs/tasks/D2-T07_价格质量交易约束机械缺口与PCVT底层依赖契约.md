# D2-T07 价格质量、交易约束、机械缺口与 PCVT 底层依赖契约

## 状态

contract-only; no real data materialization via PR #33。

D2-T06 已完成 BAOSTOCK 候选源小样本探针并提交脱敏报告，但 formal ingestion still blocked。D2-T07 不做 D2-T06R，不新增 repeated snapshot / revision stability task，不调用外部 API，不读取真实 raw data，不写 DuckDB，不生成 D1/D2/D3 正式数据。

## 目标

- 为 D2-T08、D3 和 R0 定义价格质量、交易约束、机械缺口和 PCVT 底层依赖契约。
- 明确 raw trading fact、continuous research price、membership、corporate action / mechanical gap evidence 的未来输入层。
- 定义 unknown policy、trading constraint policy、mechanical gap policy、amount/volume unit policy、DailyVWAP policy 和 adjusted volume/VWAP 风险。
- 定义 PCVT proposed candidate dependency set，但不计算 PCVT，不冻结 R0 阈值，不定义状态机。

## 非目标

- 不调用 BAOSTOCK、HITHINK 或任何外部 API。
- 不读取 `data/raw/` 或 `data/external/` 中的真实 vendor raw data。
- 不提交 row-level raw/qfq/hfq price、CSV、Parquet、DuckDB、pickle、xlsx、vendor export 或 manifest。
- 不生成正式 `d1.raw_market_prices`、`d2.adjusted_market_prices` 或 D3 `daily_market_observations`。
- 不定义 R0 状态阈值，不计算 PCVT 因子真实值，不生成 returns、labels、breakout、future outcome 或 backtest。
- 不推进 D2-T08，不推进 D3。

## 输入

- `configs/d2/candidate_market_snapshot_probe_execution_report.v1.json`
- `configs/d2/csi800_static_2026_06_membership_alignment.v1.json`
- D2-T03 / D2-T04 / D2-T05 blocked contracts
- D2-T06 candidate probe contract and redacted execution report

## 输出

- `configs/d2/market_quality_pcvt_dependency_contract.v1.json`
- `configs/d2/market_quality_pcvt_dependency_blocking_report.v1.json`
- `schemas/d2_market_quality_pcvt_dependency_contract.schema.json`
- `schemas/d2_market_quality_pcvt_dependency_blocking_report.schema.json`
- `scripts/validate_d2_market_quality_pcvt_dependency.py`
- synthetic validator tests and schema tests

## PCVT Dependency Matrix

All eight indicators are `pcvt_candidate_not_r0_finalized`; they are proposed D3/R0 dependency declarations only.

- `P1_NATR14`: P layer, continuous high/low/close plus previous continuous close, 15 valid trading days, exploration-ready after full-window pull, formal-ready blocked pending formal continuous prices and quality flags.
- `P2_LogRange20`: P layer, continuous high/low, 20 valid trading days, exploration-ready after full-window pull.
- `C1_LogMASpread_5_60`: C layer, continuous close, 60 valid trading days, exploration-ready after full-window pull.
- `C2_AdjVWAPSpread_5_60`: C layer, raw amount/volume, raw low/high, continuous price basis and adjusted VWAP policy, 60 valid trading days; partial until amount/volume units and adjusted VWAP policy are validated.
- `T1_ER20`: T layer, continuous close, 21 valid trading days, exploration-ready after full-window pull.
- `T2_AbsTrendT20`: T layer, continuous close, 20 valid trading days and SE=0 rule, exploration-ready after full-window pull.
- `V1_VolShrink20_60`: V layer, volume, 80 valid trading days, non-overlapping windows and corporate-action volume comparability; partial until volume unit and adjusted volume policy are validated.
- `V2_AmountLevel20Pct`: V layer, amount, 20 valid trading days and strict past percentile history; ready only after amount unit validation and history window pull.

Price-based indicators can become exploration-ready after full-window pull and continuous quality gates. Amount/volume indicators have additional unit, adjusted VWAP, adjusted volume and corporate-action comparability risks.

## Unknown Policy

- Missing must not become false.
- Unknown must not become normal.
- Suspended days must not use repeated close fills.
- Missing previous close must not use same-day open or zero gap.
- Nonpositive prices make log indicators unknown.
- Missing factor/as-of/revision blocks formal readiness.
- Missing corporate action evidence makes mechanical-gap windows `diagnostic_required` or `unknown`.
- Unknown amount/volume units prevent C2/V1/V2 from becoming `full_ready`.
- Missing `price_limit_status` makes R1 diagnostics incomplete.

## Trading Constraint Policy

Controlled vocabulary: `normal_trading`, `suspended`, `zero_volume`, `limit_up`, `limit_down`, `one_price_limit_up`, `one_price_limit_down`, `reopen_after_suspension`, `unknown`.

- `unknown` must not become `normal_trading`.
- `suspended` is invalid for indicator windows.
- `zero_volume` is not an ordinary low-participation day.
- Limit rows are retained for later diagnosis, not silently dropped in R0.

## Mechanical Gap Policy

Controlled vocabulary: `none`, `market_gap`, `corporate_action_mechanical_gap`, `suspension_reopen_gap`, `limit_constraint_gap`, `code_mapping_gap`, `unknown`.

- Corporate-action mechanical gaps must not be interpreted as ordinary market gaps.
- Missing corporate action evidence makes gap attribution `unknown`.
- Unknown gap attribution must not become `none`.
- R0 must not use future returns or future direction to explain gaps.

## D3 Handoff Requirements

D3 handoff requires quality flags, trading constraint flags, mechanical gap attribution and PCVT input readiness. D3 generation remains unauthorized by this PR, and formal use remains blocked until D2-T08 acceptance and later D3 contracts close the remaining gates.

## 回退方式

完整回退 D2-T07 contract、blocking report、schema、validator、tests、task document and README update. Do not repair a failed contract by importing raw data, writing DuckDB, creating manifests, or advancing D3/R0.
