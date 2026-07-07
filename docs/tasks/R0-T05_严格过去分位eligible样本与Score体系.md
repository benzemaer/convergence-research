# R0-T05 严格过去分位、eligible 样本与 Score 体系

状态：completed via PR #63。

## 目标

本任务在 R0-T04 raw/base metric engine 之后建立 synthetic-only score layer。输入为 R0-T04 的 raw/base metric result objects 或等价 in-memory mappings；输出为每个 active indicator 的 eligible flag、strict-past percentile、indicator score、`V2_AmountLevel20Pct`、P/C/T/V dimension score、`score_*_min` 和 common eligible sample 语义。历史分位窗口固定为 `W = 120 / 250 / 500`，并使用同一证券、同一指标、当前日前的有效历史观测。

## 非目标

本任务不读取真实 DuckDB、MarketDB、`.day`、`data/raw/`、`data/external/` 或 D1/D2/D3 generated outputs，不写 CSV、JSON、DuckDB 或 generated artifact，不发布 formal `data_version`。本任务不重新计算 R0-T04 raw metrics，不改变 R0-T03 V 层 baseline，不恢复旧 `V1_VolShrink20_60`。本任务不应用 q 阈值、不实现 weak dimension rule、不生成 P/C/T/V binary state、`S_P`、`S_PC`、`S_PCT`、`S_PCVT`、confirmation、streak、interval、manifest、future labels、future returns、breakout direction、backtest 或 portfolio。

## 输入

输入字段至少包括 `security_id`、`trading_date`、`indicator_id`、`raw_metric_name`、`raw_value`、`validity_status`、`reason_codes`、`required_observation_count`、`actual_valid_observation_count`、`source_field_names` 和 `metric_engine_version`。允许的 logical lineage 仅为 `synthetic_in_memory_raw_metrics` 与 `r0_t04_raw_metric_engine`。输入可乱序，engine 必须按 security、date、indicator 和 W 稳定排序；分位参考集只使用同一 security 与同一映射后 active indicator。

## 输出

indicator score result 包含 `security_id`、`trading_date`、`percentile_window_W`、`indicator_id`、`raw_metric_name`、`raw_value`、`eligible`、`percentile`、`score`、`validity_status`、`reason_codes`、`reference_observation_count`、`reference_window_start`、`reference_window_end`、`current_value_in_reference_set`、`tie_method` 和 `score_engine_version`。dimension score result 包含 `dimension`、`score_dimension`、`score_dimension_min`、`eligible_dimension`、component ids 和 reason。common eligible sample result 只表达同一 security-date 是否在 `W=120/250/500` 下八个 active indicators 均 eligible。

## 严格过去分位与 eligible 规则

对普通 raw metric，参考集为当前日前最近 W 个 valid raw observations，当前值不得进入参考集，`current_value_in_reference_set` 固定为 `false`。tie method 固定为 midrank：`(# historical values < current value + 0.5 * # historical values == current value) / W`。W 是有效历史观测数，不是 calendar days；有效历史不足 W 时 `eligible=false`、`percentile=None`、`score=None`、`validity_status=unknown`，reason 包含 `insufficient_strict_past_history`。若上游 raw metric 非 valid，则传播 upstream status 与 reason，不得填 0、false、前值或均值。

## Score 与 V2 规则

普通指标 `score_i = 1 - percentile_i`，所有指标仍保持 lower raw value is more convergent、higher score is more convergent。`V2_LogAmount20_base` 在本任务映射为 `V2_AmountLevel20Pct`；`AmountLevel20Pct` 本身就是 `LogAmount20` 的 strict-past percentile，`score_V2 = 1 - AmountLevel20Pct`。若输入已经是 `V2_AmountLevel20Pct` 并再次请求 percentile，必须返回 blocked 和 `amount_level_repeated_percentile_forbidden`。

## Dimension Score 与 Common Eligible

P、C、T、V 各由两个 component scores 构成：P 为 `P1_NATR14` 与 `P2_LogRange20`，C 为 `C1_LogMASpread_5_60` 与 `C2_AdjVWAPSpread_5_60`，T 为 `T1_ER20` 与 `T2_AbsTrendT20`，V 为 `V1_TurnoverShrink20_60` 与 `V2_AmountLevel20Pct`。两个 component scores 均 valid 时，`score_D` 为均值，`score_D_min` 为最小值；任一 component unknown、diagnostic 或 blocked 时，dimension 不 eligible，两个 score 均为 `None`，并传播 component reason。common eligible sample 仅当同一 security-date 在 W=120、250、500 下八个 active indicators 均 eligible 时为 true。

## 验收标准

验收要求包括：R0-T05 contract/schema 通过 `validate_configs.py`；strict-past percentile 使用当前日前同证券同指标 valid observations；W=120/250/500 均有合成测试；midrank tie 可重复；`V2_LogAmount20_base` 只转换一次为 `V2_AmountLevel20Pct`；indicator score、dimension score 和 common eligible sample 可测试；forbidden guard 拒绝 state、interval、q、future、backtest 和 portfolio 字段；README 推进到 R0-T06 / R0-T07。

## 失败状态

若当前值进入 reference set、使用横截面分位、未使用 midrank、对 `AmountLevel20Pct` 重复 percentile、读取真实数据、写 generated artifact、生成 state/q/K/interval/future/backtest/portfolio，或将 unknown 填为 0、false、前值或均值，则本任务失败。

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

回退本任务新增的 R0-T05 contract、schema、percentile/score engine、tests、task 文档、README 和 R0 阶段文档更新。由于本任务不读取真实数据、不写 generated outputs、不发布 data_version，不需要数据回滚。回退后 R0 当前任务应回到 R0-T05，不得让 R0-T06 消费未固定的 score layer。
