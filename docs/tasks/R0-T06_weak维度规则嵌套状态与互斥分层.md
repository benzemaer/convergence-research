# R0-T06 weak 维度规则、嵌套状态与互斥分层

状态：completed via PR #64。

## 目标

本任务在 R0-T05 synthetic score layer 之上实现 raw daily state layer。输入为 R0-T05 的 indicator score、dimension score 和等价 in-memory mappings；输出为 per-indicator active flag、per-dimension weak active flag、P/C/T/V raw dimension state、`S_P`、`S_PC`、`S_PCT`、`S_PCVT` raw nested states 和 mutually exclusive layer label。R0-T06 首次引入候选 q 配置，固定 `q = 0.10 / 0.20 / 0.30`、baseline q 为 `0.20`、`weak_delta = 0.10`。

## 非目标

本任务不读取真实 DuckDB、MarketDB、`.day`、`data/raw/`、`data/external/`、`data/generated/` 或 D1/D2/D3 generated outputs，不写 CSV、JSON、DuckDB 或 generated artifact，不发布 formal `data_version`，不生成 manifest。本任务不重新计算 R0-T04 raw metrics，不重新计算 R0-T05 strict-past percentile，不修改 V1 baseline，不恢复旧 `V1_VolShrink20_60`。本任务不生成 confirmation、confirmed state、streak、state interval、future label、future return、breakout direction、backtest 或 portfolio。

## 输入

输入为 R0-T05 score layer result objects 或等价 mappings。indicator score 最低字段包括 `security_id`、`trading_date`、`percentile_window_W`、`indicator_id`、`score`、`eligible`、`validity_status` 和 `reason_codes`。dimension score 最低字段包括 `dimension`、`score_dimension`、`score_dimension_min`、`eligible_dimension`、`validity_status`、`reason_codes` 和 `component_indicator_ids`。允许 logical lineage 仅为 `synthetic_in_memory_scores` 与 `r0_t05_strict_past_percentile_score`。

## 输出

indicator state result 包含 q、score、eligible 和 `indicator_active`。dimension state result 包含 q、`weak_delta`、`score_dimension`、`score_dimension_min`、`eligible_dimension` 和 `dimension_active_weak`。nested daily state result 包含 P/C/T/V raw、`S_P_raw`、`S_PC_raw`、`S_PCT_raw`、`S_PCVT_raw`、`exclusive_state_layer`、`eligible_state`、status、reason 和 state engine version。输出只表达 raw daily states，不表达确认、streak 或区间。

## Indicator Active 规则

对每个 active indicator，若 `eligible=true`、`validity_status=valid` 且 `score` 非空，则 `indicator_active = score >= 1 - q`。如果 score 缺失、eligible 为 false 或上游 status 非 valid，则 `indicator_active=None`，并传播上游 status 与 reason。unknown、diagnostic 或 blocked 不得静默转为 false。

## Weak Dimension 规则

R0 baseline 使用 weak rule：`score_D >= 1 - q AND score_D_min >= 1 - q - weak_delta`。该规则要求维度均值达到阈值，同时两个 component 中不能有一项明显拖后腿。若 `score_dimension`、`score_dimension_min` 缺失，或 `eligible_dimension=false`，则 `dimension_active_weak=None` 并传播 reason；不得用单一 component score 补齐维度状态。

## Nested States 与互斥层

P/C/T/V raw state 使用 weak dimension active。嵌套状态定义为 `S_P_raw=P_raw`、`S_PC_raw=P_raw AND C_raw`、`S_PCT_raw=P_raw AND C_raw AND T_raw`、`S_PCVT_raw=P_raw AND C_raw AND T_raw AND V_raw`，必须满足 `S_PCVT_raw => S_PCT_raw => S_PC_raw => S_P_raw`。互斥层为 `NONE`、`P_ONLY`、`PC_ONLY`、`PCT_ONLY`、`PCVT`、`UNKNOWN`、`BLOCKED` 或 `DIAGNOSTIC_REQUIRED`；每个 security-date-W-q 只能有一个互斥层。

## Unknown 传播

如果 P unknown，则所有依赖 P 的 nested states 均为 unknown；如果 P 为 false，则所有 nested states 为 false。若 P true 且 C unknown，`S_P_raw=true`，但 `S_PC_raw`、`S_PCT_raw` 和 `S_PCVT_raw` 为 unknown。若 P/C/T true 且 V unknown，`S_PCT_raw=true`，`S_PCVT_raw=unknown`。blocked 和 diagnostic_required 按必要维度传播到 `exclusive_state_layer`。

## 验收标准

验收要求包括：R0-T06 contract/schema 通过 `validate_configs.py`；q=0.10/0.20/0.30 均生成；weak dimension rule 同时测试 mean 与 min 约束；indicator active 阈值等号可通过；unknown、diagnostic 和 blocked 不转 false；嵌套不变量和互斥层可测试；forbidden guard 拒绝 confirmation、streak、interval、future、backtest 和 portfolio；lineage guard 阻断 `data/generated`、`data/raw`、MarketDB 和 `.day`；README 推进到 R0-T07 / R0-T08。

## 失败状态

若本任务读取真实数据、写 generated artifact、用未来收益或回测选择 q/weak_delta、把 unknown/diagnostic/blocked 转为 false、生成 confirmation/streak/interval/confirmed state、生成 future label/return/backtest/portfolio，或破坏 nested state invariant 与互斥层唯一性，则本任务失败。

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

回退本任务新增的 R0-T06 contract、schema、daily state engine、tests、task 文档、README 和 R0 阶段文档更新。由于本任务不读取真实数据、不写 generated outputs、不发布 data_version，不需要数据回滚。回退后 R0 当前任务应回到 `R0-T06 weak 维度规则、嵌套状态与互斥分层`，不得让 R0-T07 消费未固定的 raw daily state layer。
