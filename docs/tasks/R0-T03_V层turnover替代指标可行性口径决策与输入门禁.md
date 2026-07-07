# R0-T03 V层 turnover 替代指标可行性、口径决策与输入门禁

状态：completed via PR #61。

## 目标

本任务在 R0 内完成 V 层 baseline 口径决策：`V1` 从原始成交量相对收缩切换为 `TurnoverShrink20_60`，使用 D3-T11 标准字段 `turnover_float` 和 `float_share_shares`；`V2` 继续为 `AmountLevel20Pct`，输入改为 D3-T11 标准字段 `amount_yuan`。本任务同时固化 V 层输入 readiness gate，使 R0-T04 raw metric engine 只能消费明确 ready 的合成语义，或传播固定的 `unknown / diagnostic_required / blocked` reason。

## 非目标

本任务不读取真实数据，不生成 PCVT raw values、percentiles、scores、states 或 intervals，不生成 readiness audit 真实输出文件，不生成 future labels、returns、breakout direction、backtest 或 portfolio，不修改 D2/D3 数据契约语义，不进入 R0-T04 raw metric engine。本任务不改变 R0-T01 weak baseline 状态规则；`FreeTurnoverShrink20_60`、`TurnoverLevel20Pct` 和 `FreeTurnoverLevel20Pct` 只登记为 R1 sensitivity 或 optional alternative，不进入 R0 baseline。

## 输入

输入边界来自 D3-T11 的 `turnover_float`、`amount_yuan`、`volume_shares`、`float_share_shares`、`share_field_status`、`turnover_field_status`、`provider_turnover_crosscheck_status` 以及公司行为可比性字段。D3-T12 的开放候选层不自动授予 R0 readiness；R0-T03 只允许通过自己的 pure gate 判断 `ready`、`unknown`、`diagnostic_required` 或 `blocked`。禁止直接读取 D1/D2 表、`data/raw/`、`data/external/`、MarketDB 或 `.day` 文件。

## 输出

输出包括更新后的 `configs/r0/r0_t01_pcvt_candidate_spec.v1.json` 与 schema、新增 `configs/r0/r0_t03_v_layer_turnover_readiness_contract.v1.json` 与 schema、`src/r0/input_readiness_gate.py` 中的 V 层 pure readiness functions、合成测试、R0 阶段文档和 task 索引。本任务只提交契约、schema、代码、测试和文档，不提交任何真实数据、generated artifact 或 formal manifest。

## 契约与门禁语义

`TurnoverShrink20_60` 需要 recent 20 trading days 与 prior non-overlapping 60 trading days 的完整窗口。`turnover_float`、`turnover_field_status`、`share_field_status`、`provider_turnover_crosscheck_status`、`volume_shares`、`float_share_shares`、`trading_status`、`corporate_action_flag`、`suspension_flag`、`corporate_action_types_in_window`、`share_comparability_corporate_action_in_window`、`common_share_basis_policy` 和 `volume_comparability_policy` 都是 required fields；字段必须存在，值可为 `not_required`。若字段缺失、`turnover_float` 缺失、`float_share_shares` 非正、股本字段状态无效、turnover 字段状态无效、provider crosscheck fail、停牌、listing pause 或 zero volume，均不得返回 ready。

若 80 日窗口内存在送转、拆并股、配股等影响股份数量可比性的公司行为，必须存在 `common_share_basis_policy` 或 `volume_comparability_policy`；否则返回 `corporate_action_turnover_comparability_policy_missing`。若窗口内不存在此类事件，相关元字段仍必须存在，但可以填 `not_required`，以避免缺失元数据被误读为“无公司行为风险”。

`AmountLevel20Pct` 需要 `amount_yuan`、`amount_unit`、`amount_volume_unit_status`、`zero_amount_flag`、`trading_status` 和 `suspension_flag`。该指标本身就是近期 20 日平均成交额的严格过去历史位置，不得再嵌套一层相同 percentile；若检测到重复 percentile，应返回 `amount_level_repeated_percentile_forbidden`。`zero_amount_flag` 缺失不得 ready；零成交额或停牌状态进入 diagnostic-required 语义，不得被解释为普通低参与。

## 验收标准

验收标准包括：R0-T01 candidate spec 与 schema 接受 `V1_TurnoverShrink20_60` 和 `V2_AmountLevel20Pct`；R0-T03 contract 与 schema 通过 `validate_configs.py`；pure gate 覆盖 turnover 和 amount required fields、窗口不足、股本非正、provider crosscheck fail、停牌/零量、公司行为可比性缺失、amount 单位失败、重复 percentile、D3-only lineage 和 unknown-not-false guard；README 将 R0-T03 标记为 completed via PR #61，并推进到 R0-T04 / R0-T05。

## 失败状态

若 contract 与实现 required fields 不一致、缺失公司行为可比性元字段仍返回 ready、缺失 `zero_amount_flag` 仍返回 ready、optional alternatives 被加入 R0 baseline、任何真实数据被读取或 generated artifact 被提交，或 R0-T04 raw metric engine 在本任务中被实现，则本任务失败。

## 验证命令

```bash
python scripts/build_compendium.py --check
python scripts/validate_configs.py
python scripts/validate_manifests.py
ruff format --check scripts tests src
ruff check scripts tests src
python -m unittest discover -s tests -v
git diff --check
```

## 回退方式

若本任务需要回退，应恢复 R0-T01 candidate spec 中的 V 层 baseline、移除 R0-T03 contract/schema 和对应 pure gate 测试，并将 README 中 R0-T03 状态退回 in progress 或 planned。若回退影响后续 R0-T04，应停止 raw metric engine 消费该 V 层 readiness gate，直到新 PR 重新固定 baseline 口径和 required field 语义。
