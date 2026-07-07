# R0-T03 V层 turnover 替代指标可行性、口径决策与输入门禁

状态：in_progress。

本任务在 R0 内完成 V 层 baseline 口径决策：`V1` 从原始成交量相对收缩切换为 `TurnoverShrink20_60`，使用 D3-T11 标准字段 `turnover_float` 和 `float_share_shares`；`V2` 继续为 `AmountLevel20Pct`，输入改为 D3-T11 标准字段 `amount_yuan`。该调整只改变 V 层候选指标规格和 readiness gate，不改变 R0-T01 的 weak baseline 状态规则，不进入 raw metric engine。

本任务的非目标是：不读取真实数据，不生成 PCVT raw values、percentiles、scores、states 或 intervals，不生成 readiness audit 真实输出文件，不生成 future labels、returns、breakout direction、backtest 或 portfolio，不修改 D2/D3 数据契约语义，不进入 R0-T04。`FreeTurnoverShrink20_60`、`TurnoverLevel20Pct` 和 `FreeTurnoverLevel20Pct` 只登记为 R1 sensitivity 或 optional alternative，不进入 R0 baseline。

输入边界来自 D3-T11 的 `turnover_float`、`amount_yuan`、`volume_shares`、`float_share_shares`、`share_field_status`、`turnover_field_status`、`provider_turnover_crosscheck_status` 以及公司行为可比性字段。D3-T12 的开放候选层不自动授予 R0 readiness；R0-T03 必须只通过自己的 pure gate 判断是否 ready、unknown、diagnostic_required 或 blocked。禁止直接读取 D1/D2 表、`data/raw/`、`data/external/`、MarketDB 或 `.day` 文件。

`TurnoverShrink20_60` 需要 recent 20 trading days 与 prior non-overlapping 60 trading days 的完整窗口。若 `turnover_float` 缺失、`float_share_shares` 非正、股本字段状态无效、turnover 字段状态无效、provider crosscheck fail、停牌或 listing pause、zero volume，均不得返回 ready。若 80 日窗口内存在送转、拆并股、配股等影响股份数量可比性的公司行为，必须存在 `common_share_basis_policy` 或 `volume_comparability_policy`；否则返回 `corporate_action_turnover_comparability_policy_missing`。

`AmountLevel20Pct` 需要 `amount_yuan`、`amount_unit`、`amount_volume_unit_status`、`zero_amount_flag`、`trading_status` 和 `suspension_flag`。该指标本身就是近期 20 日平均成交额的严格过去历史位置，不得再嵌套一层相同 percentile；若检测到重复 percentile，应返回 `amount_level_repeated_percentile_forbidden`。

验收标准是：R0-T01 candidate spec 与 schema 接受 `V1_TurnoverShrink20_60` 和 `V2_AmountLevel20Pct`；新增 R0-T03 contract 与 schema；`src/r0/input_readiness_gate.py` 提供纯函数级 V 层 readiness gate；合成测试覆盖窗口不足、字段缺失、股本非正、provider crosscheck fail、停牌/零量、公司行为可比性缺失、amount 单位失败和重复 percentile；README 将 D3-T12 标记为 completed via PR #60，并把下一任务推进到 R0-T04 raw metric engine。
