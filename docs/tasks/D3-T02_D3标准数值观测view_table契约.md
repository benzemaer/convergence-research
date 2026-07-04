# D3-T02 D3 标准数值观测 view/table 契约

状态：contract-only；D3 real generation not authorized。

## 目标

定义 `d3.daily_market_observation_values` 或等价 D3 value view/table 的语义、
grain、primary key、输入依赖、字段分组、数值字段、质量字段、readiness 字段、
source lineage 继承规则、`observed_at` / revision 继承规则、R0 允许读取边界和
禁止字段。

## 核心设计

`d3.daily_market_observation_values` 是从 D3 canonical refs table 解析出的
R0-readable value layer。它必须通过 `d3.daily_market_observations` 的 component refs
追溯 D1/D2，R0 不得绕过 D3 直接读取 D1/D2。

该 value layer 可以承载 raw trading values、continuous research prices、participation
values、trading constraints、quality summary 和 PCVT input readiness 等标准化数值字段。
它不得承载 PCVT 最终指标值、PCVT score、状态、未来收益、标签、回测或组合结果。

D3-T01 仍保持 refs-only canonical table。本任务不削弱 D3-T01 的血缘、as-of、
revision 和 no-bypass 约束。D3-T07 才是未来正式生成完整 D3 data product /
candidate `data_version` 的任务，且当前仍 blocked pending D2 formal materialization。

## 非目标

- 不生成真实 rows。
- 不读取真实 D1/D2 data。
- 不写 DuckDB。
- 不创建 view/table DDL。
- 不创建 manifest。
- 不发布 `data_version`。
- 不计算 PCVT。
- 不定义 q、threshold 或 state machine。
- 不生成 returns、labels、future outcome、backtest 或 portfolio。
- 不升级 BAOSTOCK/HITHINK formal source。

## 输入

- `configs/d3/daily_market_observations_contract.v1.json`
- `configs/d2/market_quality_pcvt_dependency_contract.v1.json`
- `configs/d2/d2_acceptance_d3_handoff_contract.v1.json`
- `configs/d0/data_product_contracts.v1.json`
- `sql/duckdb/schema.sql`

## 输出

- `configs/d3/daily_market_observation_values_contract.v1.json`
- `schemas/d3_daily_market_observation_values_contract.schema.json`
- `tests/test_d3_daily_market_observation_values_contract.py`
- 本任务文档
- `docs/tasks/README.md` 阶段索引更新

## 字段分组

目标对象：`d3.daily_market_observation_values`。

object kind：`view_or_materialized_table_contract`。本 PR 不决定真实实现采用 view 还是
materialized table。

grain：one row per `data_version, universe_id, security_id, trading_date,
observation_revision`。

primary key：`data_version, universe_id, security_id, trading_date,
observation_revision`。

required identity / lineage fields 至少包括 `canonical_observation_ref`、
`observed_at`、`observed_at_rule`、`revision_policy`、`history_revision_class`、
`research_use_tier`、`source_registry_id`、`source_snapshot_id` 和 `run_id`。

R0-readable value field groups：

- `raw_trading_value_fields`
- `continuous_research_price_fields`
- `participation_value_fields`
- `trading_constraint_value_fields`
- `quality_summary_fields`
- `pcvt_input_readiness_fields`
- `lineage_ref_fields`

`daily_vwap` 是 derived candidate field，公式为 `amount_yuan / volume_shares`。
formal readiness 取决于 amount/volume unit validation 和 DailyVWAP range check。
本 PR 不计算真实值。

`turnover` 和 `float_shares` 不作为 current formal required fields；它们保留在
`future_or_blocked_fields`，状态为 `blocked_pending_source_contract`。

## R0 读取边界

Future formal policy 下，R0 may read：

- `d3.daily_market_observations`
- `d3.daily_market_observation_values`

R0 must not read：

- `d1.raw_market_prices`
- `d2.adjusted_market_prices`
- `d2.market_price_quality_flags`
- `d2.membership_alignment`
- D1/D2 raw component tables directly

当前 R0 仍 blocked，直到 D3 contract 和后续 D3 `data_version` gates accepted。

## 验收标准

- contract JSON 通过 JSON Schema。
- contract 绑定 `d3.daily_market_observations` canonical refs table。
- formal ingestion、DuckDB write、DDL、real materialization、`data_version` release、
  PCVT calculation 和 R0 state generation 均保持 false。
- value field groups 覆盖 R0 未来 PCVT 候选指标所需底层字段。
- PCVT input readiness fields 明确不是 PCVT values / score / state。
- prohibited fields 覆盖 future、label、backtest、portfolio、vendor payload 和 PCVT state。
- README 推进到 D3-T02 / D3-T03，且 D3-T07 和 R0 仍 blocked。

## 回退方式

回退本 PR 新增的 D3-T02 contract、schema、tests、任务文档和 README 阶段索引更新。
不得修改 D0/D1/D2 已 accepted 契约来绕过 D3 阻塞条件。
