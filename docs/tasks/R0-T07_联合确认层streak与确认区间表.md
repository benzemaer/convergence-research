# R0-T07 联合确认层、streak 与确认区间表

状态：completed via PR #65。

## 目标

本任务在 R0-T06 synthetic raw daily state layer 之上实现 confirmation、streak 与 confirmed interval 基础层。输入为 `NestedDailyStateResult` 或等价 in-memory mappings；输出为 `S_P`、`S_PC`、`S_PCT`、`S_PCVT` 的 raw streak、confirmed flag、confirmation start/date，以及已经 confirmed 的 interval rows。确认窗口固定为 `K = 1 / 2 / 3`，baseline K 为 `2`。

## 非目标

本任务不读取真实 DuckDB、MarketDB、`.day`、`data/raw/`、`data/external/`、`data/generated/` 或 D1/D2/D3 generated outputs，不写 CSV、JSON、DuckDB 或 generated artifact，不发布 formal `data_version`，不生成 manifest。本任务不重新计算 raw metrics、strict-past percentile、indicator score、dimension score、indicator active、dimension weak state、raw nested state 或 exclusive layer。本任务不生成 future label、future return、breakout direction、backtest 或 portfolio，不做 gap merge，不进入 R0-T08 主网格落表。

## 输入

输入字段至少包括 `security_id`、`trading_date`、`percentile_window_W`、`q`、`weak_delta`、`S_P_raw`、`S_PC_raw`、`S_PCT_raw`、`S_PCVT_raw`、`exclusive_state_layer`、`eligible_state`、`validity_status`、`reason_codes` 和 `state_engine_version`。允许 logical lineage 仅为 `synthetic_in_memory_daily_states` 与 `r0_t06_weak_dimension_nested_state`。

## 输出

daily confirmation result 包含 `state_name`、`confirmation_k`、`raw_state`、`raw_streak`、`raw_streak_start_date`、`confirmed_state`、`confirmation_start_date`、`confirmation_date`、status、reason 和 engine version。confirmed interval result 包含 `interval_id`、`raw_start_date`、`confirmation_date`、`confirmed_start_date`、`interval_end_date`、`last_observed_date`、duration、open flag 和 termination reason。R0-T07 只输出已经 confirmed 的 intervals；raw true 但尚未达到 K 的片段只保留在 daily confirmation result 中。

## Streak 规则

对同一 `security_id / percentile_window_W / q / weak_delta / state_name` 按 `trading_date` 升序扫描。raw state 为 true 时 streak 增长并保留当前连续段起点；raw state 为 false 时 streak 归零；raw state 为 unknown、diagnostic_required、blocked 或 `None` 时 streak 为 `None` 并中断。unknown 不得当作 false，也不得延续 previous streak。

## Confirmation 规则

`confirmed_state = raw_streak >= K`，但只能在 raw state true、streak 非空且 status valid 时判断。确认日期是当前连续 true 段首次达到 K 的日期，`confirmation_start_date` 是该连续段 raw 起点。确认不得回填：例如 K=3 时，连续 true 的第 1、2 天仍为 confirmed false，第 3 天才为 confirmed true。

## Interval 表规则

confirmed interval 从某状态首次 confirmed 的日期开始输出。`raw_start_date` 是 raw true 连续段第一天，`confirmation_date` 与 `confirmed_start_date` 是首次 confirmed 日期，`interval_end_date` 是 raw true 连续段结束日期；若输入结束时仍未终止，则 `is_open_interval=true` 且 `termination_reason=end_of_input_open`。遇到 raw false、unknown、diagnostic_required 或 blocked 会终止已 confirmed interval，termination reason 分别为 `raw_state_false`、`raw_state_unknown`、`raw_state_diagnostic_required` 或 `raw_state_blocked`。

## Unknown 传播与嵌套关系

若 raw state 为 `None` 或上游 `validity_status` 非 valid，则 `confirmed_state=None`、`raw_streak=None`，并传播上游 reason。R0-T07 不修补 R0-T06 raw nested states；若输入破坏 `S_PCVT_raw => S_PCT_raw => S_PC_raw => S_P_raw`，则返回 blocked，并包含 `nested_raw_state_invariant_violation`。同一 K 下，合法输入的 confirmed states 应继承 raw nested invariant。

## 验收标准

验收要求包括：R0-T07 contract/schema 通过 `validate_configs.py`；K=1/2/3 均有合成测试；confirmed state 不回填；unknown、diagnostic 和 blocked 不转 false；confirmed interval 覆盖 closed、open、false 终止和 non-ready 终止；非法 K 被拒绝；forbidden guard 拒绝 future、backtest、portfolio 和 formal data version；lineage guard 阻断 `data/generated`、`data/raw`、MarketDB 和 `.day`；README 推进到 R0-T08 / R0-T09。

## 失败状态

若本任务读取真实数据、写 generated artifact、用未来收益或回测选择 K、将 confirmed state 回填到 raw 起点、把 unknown/diagnostic/blocked 转为 false、生成 future label/return/backtest/portfolio、做 gap merge、破坏 confirmed nested invariant，或未同步 contract/schema/README/tests，则本任务失败。

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

回退本任务新增的 R0-T07 contract、schema、confirmation interval engine、tests、task 文档、README 和 R0 阶段文档更新。由于本任务不读取真实数据、不写 generated outputs、不发布 data_version，不需要数据回滚。回退后 R0 当前任务应回到 `R0-T07 联合确认层、streak 与确认区间表`，不得让 R0-T08 消费未固定的 confirmation / interval layer。
