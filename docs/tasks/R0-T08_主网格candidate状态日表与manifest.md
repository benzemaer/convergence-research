# R0-T08 主网格 candidate 状态日表与 manifest

状态：completed via PR #66。

## 目标

本任务在 R0-T04 至 R0-T07 synthetic result objects 或等价 mappings 之上实现主网格 candidate artifact assembly layer。R0-T08 只生成 27 个 deterministic candidate configurations、candidate daily state rows、confirmed interval rows 与 manifest metadata，不反向修改 raw metric、strict-past percentile、score、weak state 或 confirmation 语义。

## 非目标

本任务不读取真实 DuckDB、MarketDB、`.day`、`data/raw/`、`data/external/` 或未授权 `data/generated/` 产物，不调用 provider，不运行全量真实股票池，不提交 generated artifact。本任务不重新计算 raw metrics、percentiles、scores、dimension states、nested raw states、confirmation、streak 或 intervals。本任务不生成 future label、future return、future volatility、breakout/release direction、risk set、backtest、portfolio 或 trading signal，不做 gap merge、cooldown、释放事件或参数选择。

## 输入

输入集合为 `raw_metric_results`、`indicator_score_results`、`dimension_score_results`、`nested_daily_state_results`、`daily_confirmation_results` 和 `confirmed_interval_results`。输入可为 dataclass result objects 或 mappings，按 `security_id`、`trading_date`、`percentile_window_W`、`q`、`weak_delta`、`confirmation_k`、`state_name`、`indicator_id` 和 `dimension` 对齐。允许 logical lineage 仅为 `synthetic_in_memory_r0_grid_inputs`、`r0_t04_raw_metric_engine`、`r0_t05_strict_past_percentile_score`、`r0_t06_weak_dimension_nested_state` 与 `r0_t07_confirmation_streak_interval`。

## 主网格配置

主网格固定为 `W in {120,250,500}`、`q in {0.10,0.20,0.30}`、`K in {2,3,5}`、`dimension_rule=weak`、`weak_delta=0.10`，共 27 个配置。baseline 为 `W=250, q=0.20, K=3`。`K=1` 由 R0-T06 raw daily state reference 提供，不进入 R0-T08 confirmation grid。

`candidate_config_id` 使用稳定可读格式，例如 `R0_W250_Q20_K3_WEAK_D010`。`config_hash` 使用 canonical JSON 的 SHA-256，输入只包含 W、q、K、dimension rule、weak delta、metric variant 和 state definition draft version，不包含 `run_id`、时间戳或本机路径。

## 输出

candidate daily state rows 包含 config metadata、raw/base metric fields、strict-past percentile/score fields、dimension score fields、eligibility、nested raw states、exclusive layer、streak、confirmed states、confirmation dates、validity、unknown reasons、lineage 和 artifact engine version。`AmountLevel20Pct` 是 R0-T05 输出的最终历史位置字段，不命名为 `AmountLevel20Pct_raw`。缺失 raw diagnostic fields 保留为 `None` 并进入 manifest `field_availability`，不得填 0、false、前值或均值。

confirmed interval rows 映射 R0-T07 confirmed intervals：`state_name` 到 `state_level`，`confirmation_date` 到 `confirmation_time`，`duration_raw_days` 到 `raw_length`，`duration_confirmed_days` 到 `confirmed_length`，open interval 的 termination time 为 `None`。R0-T08 不生成未确认 interval。

manifest 包含 27 个 configs、baseline config id、输入 sources/hash/count、daily/interval row count、content hash、schema/contract ids、quality summary、field availability、forbidden output guard 与 lineage guard。quality summary 只统计结构质量，例如 row count、unknown/blocked count、state frequency 和 open interval count，不包含收益、胜率、方向或交易表现。

## Unknown 与 missing 规则

上游 unknown、diagnostic_required 或 blocked 必须保留 status 和 reason，不得转成 false。若某个必要上游对象缺失，candidate daily row 保留该行并标记 `validity_state=unknown`，`unknown_reason_codes` 包含 `missing_upstream_result`。R0-T08 不跨 W/q/K join，也不静默丢弃缺失上游造成的 candidate row。

## Forbidden outputs 与 lineage

输出、manifest 和 schema 中不得包含 future label、future return、future volatility、breakout/release direction、win rate、pnl、return、backtest、portfolio、trade signal、buy signal 或 sell signal。lineage guard 必须阻断 `data/raw`、`data/external`、未授权 `data/generated`、MarketDB 和 `.day`。

## 验收标准

验收要求包括：R0-T08 contract/schema 通过 `validate_configs.py`；27 个主网格配置稳定生成；baseline 为 `R0_W250_Q20_K3_WEAK_D010`；`K=1` 不出现；candidate daily rows 和 confirmed interval rows 可由 synthetic upstream mappings 组装；manifest 包含 configs、hash、row counts、schema、contract、lineage、field availability 和 quality summary；unknown/blocked 不转 false；writer 只在测试 tmpdir 写出且 hash 可复算；README 推进到 R0-T09 / R0-T10。

## 失败状态

若本任务读取真实数据、调用 provider、提交 generated artifact、让 `K=1` 进入 grid、主网格不是 27 个 configs、baseline 不是 W250/Q20/K3、跨 W/q/K join、把 unknown/blocked 转 false、静默丢弃缺失上游、让 manifest/config hash 不稳定、生成 future/return/backtest/portfolio/signal 字段，或修改 R0-T04/T05/T06/T07 语义，则本任务失败。

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

回退本任务新增的 R0-T08 contract、schema、candidate artifact engine、tests、task 文档、README 和 R0 stage 文档更新。由于本任务不读取真实数据、不提交 generated artifacts、不发布 formal data version，不需要数据回滚。回退后 R0 当前任务应回到 `R0-T08 主网格 candidate 状态日表与 manifest`，不得让 R0-T09 消费未固定的 candidate artifact / manifest layer。
