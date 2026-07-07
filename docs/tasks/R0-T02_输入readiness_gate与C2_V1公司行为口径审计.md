# R0-T02 输入 readiness gate 与 C2/V1 公司行为口径审计

> 状态：in_progress  
> 所属阶段：R0  
> PR 标题：`[codex] R0-T02 输入 readiness gate 与 C2/V1 公司行为口径审计`  
> 分支：`codex/r0-t02-input-readiness-c2-v1-corporate-action-gate`

## 目标

本 task 建立 R0-T02 输入 readiness gate，用于判断后续 R0 是否可以合法计算 `C2_AdjVWAPSpread_5_60` 与 `V1_VolShrink20_60`。核心目标是把 C2/V1 的高风险输入条件、公司行为口径、D3-only 读取边界和固定 reason code 固化为 contract、schema、纯 gate 逻辑与合成测试。若输入条件不足，后续 R0-T03 必须传播 `unknown / diagnostic_required / blocked` reason，不得硬算。

## 非目标

本 task 不计算 PCVT raw metrics，不生成 percentiles、scores、states 或 intervals，不生成 future labels、returns、breakout direction、backtest 或 portfolio，不发布 formal `data_version`。本 task 不读取真实 DuckDB、MarketDB、`.day`、`data/raw/` 或 `data/external/`，不修改 R0-T01 baseline weak 规则，不修改 R0-T01 八项指标定义，不修改 D2/D3 数据契约语义，也不推进到 R0-T03。

## 输入

输入为 R0-T01 candidate spec、R0 阶段纲领、D3-T07 candidate daily observation contract、D3-T08 research dataset registry contract、D3-T02 value layer contract、D3-T04 quality readiness contract、D2-T07 PCVT dependency contract 和 `docs/tasks/README.md`。本 PR 的 gate 函数只接收合成 `Mapping` 或 lineage 序列，不读取任何真实数据文件。

## 输出

输出包括 `configs/r0/r0_t02_input_readiness_gate_contract.v1.json`、`schemas/r0/r0_t02_input_readiness_gate_contract.schema.json`、`src/r0/input_readiness_gate.py`、R0-T02 合成测试、更新后的 `scripts/validate_configs.py`、本 task 文档、更新后的 `docs/tasks/README.md` 和重新检查的根目录合订本。本 PR 只允许 synthetic fixture outputs，不生成真实 readiness audit 文件。

## C2 Gate 规则

`C2_AdjVWAPSpread_5_60` 必须具备 `amount`、`volume`、`amount_unit`、`volume_unit`、`amount_volume_unit_status`、`raw_low`、`raw_high`、`daily_vwap_range_status`、`corporate_action_flag`、`adjusted_vwap_policy` 和 `trading_status`。若 amount 或 volume 单位未知，或 `amount_volume_unit_status` / `daily_vwap_range_status` 为 fail / unknown，C2 不得 ready。若窗口跨分红、送转、配股、拆并股等公司行为，必须存在 `adjusted_vwap_policy` 或等价共同公司行为基准；否则输出 `adjusted_vwap_policy_missing` / `corporate_action_window_without_common_basis`。不得将 raw VWAP 跨公司行为窗口直接累计后作为 adjusted VWAP。

## V1 Gate 规则

`V1_VolShrink20_60` 必须具备 `volume`、`volume_unit`、`trading_status`、`corporate_action_flag` 和 `suspension_flag`。80 日窗口必须完整，即 recent 20 trading days 加 prior non-overlapping 60 trading days。停牌与 zero volume 不得作为普通低参与观测。若 80 日窗口内存在送转、拆并股、配股等影响股份数量可比性的公司行为，只有存在 `adjusted_volume`、`common_share_basis_policy` 或 `volume_comparability_policy` 时才可 ready；否则输出 `corporate_action_volume_comparability_policy_missing`。

Superseded note：R0-T02 当时只固化 C2 与旧 V1 volume shrink 输入门禁，未直接替换 R0 baseline。R0-T03 已将 active V1 baseline 改为 `V1_TurnoverShrink20_60`，并以 `turnover_float`、`float_share_shares`、字段状态、provider crosscheck 和公司行为可比性元字段作为 active V1 required inputs。R0-T04 以后应以 R0-T03 contract 和 R0-T01 v0.4 candidate spec 为准，不再以旧 `V1_VolShrink20_60` 作为 active baseline。

## D3-only 读取边界

R0-T02 只允许逻辑来源 `d3_candidate_daily_observation`、`d3_t08_research_dataset_registry`、`d3_quality_readiness_contract` 和 `r0_t01_pcvt_candidate_spec`。若 source lineage 出现 `d1.raw_market_prices`、`d2.adjusted_market_prices`、`d2.market_price_quality_flags`、`d2.membership_alignment`、`data/raw`、`data/external`、`MarketDB` 或 `.day`，gate 必须返回 blocked，并包含 `direct_d1_d2_bypass_detected`。

## 验收标准

R0-T02 contract config 必须通过 schema 校验，并接入 `scripts/validate_configs.py`。`src/r0/input_readiness_gate.py` 必须只包含纯 gate 逻辑，不读取真实数据。C2 合成测试必须覆盖 ready、unit failure、DailyVWAP range failure、公司行为窗口缺少 adjusted VWAP policy、raw VWAP 跨公司行为窗口和停牌 / zero volume。V1 合成测试必须覆盖 ready、80 日窗口不足、停牌、zero volume、股份变化公司行为缺少政策、存在 comparability policy 和 volume unit unknown。Lineage guard 必须覆盖 allowed 与 prohibited sources。Unknown guard 必须证明 unknown 不会被写成 false、0、前值或均值。

## 失败状态

若 PR 引入真实数据读取、DuckDB 写入、PCVT raw values、percentiles、scores、states、state intervals、future labels、future returns、breakout direction、backtest、portfolio 或 formal `data_version`，则本 PR 失败并回退。若 unknown 被静默转换为 false、0、前值或均值，或 gate 允许绕过 D3 读取 D1/D2/raw/MarketDB/.day，则本 PR 失败。

## 回退方式

回退本 PR 新增的 R0-T02 contract、schema、gate 逻辑、测试、task 文档、配置校验入口和 task 索引更新。由于本 task 不读取真实数据、不写 DuckDB、不生成真实输出，因此无需数据回滚。

## Validation 命令

```bash
python scripts/build_compendium.py --check
python scripts/validate_configs.py
python scripts/validate_manifests.py
ruff format --check scripts tests src
ruff check scripts tests src
python -m unittest discover -s tests -v
git diff --check
```
