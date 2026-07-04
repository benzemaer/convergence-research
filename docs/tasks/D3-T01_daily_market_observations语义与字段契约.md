# D3-T01 daily_market_observations 语义与字段契约

状态：contract-only；D3 real generation not authorized。

## 目标

定义 `d3.daily_market_observations` refs-only canonical entry table 的语义、
grain、primary key、required fields、component refs、source lineage、
`observed_at` / revision policy、`research_use_tier`、no-bypass policy 和
prohibited fields。

核心契约：`d3.daily_market_observations` 是 D3 层正式入口表，只保存每日观测的
component refs、source lineage、`observed_at`、revision policy、
`research_use_tier` 和 no-bypass 语义；它不直接承载 R0 计算所需的全部数值字段。
R0 将来只能读取 D3 层正式入口，不能绕过 D3 直接读取 D1/D2。后续 D3-T02 将单独
定义 `d3.daily_market_observation_values` 或等价 D3 value view/table，用于暴露
R0 可读取的标准化数值字段。

## 非目标

- 不生成真实 D3 rows。
- 不读取真实 raw/adjusted price。
- 不写 DuckDB。
- 不创建 manifest。
- 不发布 `data_version`。
- 不计算 PCVT。
- 不定义 R0 threshold、q、state machine、returns、labels 或 backtest。

## 输入

- D0 data product contracts：`configs/d0/data_product_contracts.v1.json`。
- D2-T07 market quality PCVT dependency contract：
  `configs/d2/market_quality_pcvt_dependency_contract.v1.json`。
- D2-T08 D2 acceptance D3 handoff contract：
  `configs/d2/d2_acceptance_d3_handoff_contract.v1.json`。
- DuckDB schema 中现有 D3 表定义：`sql/duckdb/schema.sql` 的
  `d3.daily_market_observations`。

## 输出

- `configs/d3/daily_market_observations_contract.v1.json`。
- `schemas/d3_daily_market_observations_contract.schema.json`。
- `tests/test_d3_daily_market_observations_contract.py`。
- 本任务文档。
- `docs/tasks/README.md` 阶段索引更新。

## 字段契约

grain：one row per `data_version, universe_id, security_id, trading_date,
observation_revision`。

primary key：`data_version, universe_id, security_id, trading_date,
observation_revision`。

required fields 至少包括 identity、component refs、source lineage、observed/revision
和 research-use 字段：

- `data_version`
- `universe_id`
- `time_segment_id`
- `security_id`
- `trading_date`
- `observation_revision`
- `observed_at`
- `raw_price_ref`
- `adjusted_price_ref`
- `trading_constraint_ref`
- `market_price_quality_ref`
- `mechanical_gap_ref`
- `pcvt_input_readiness_ref`
- `membership_ref`
- `calendar_ref`
- `source_snapshot_ref`
- `run_ref`
- `price_fact_source`
- `corporate_action_source`
- `membership_source`
- `calendar_source`
- `revision_policy`
- `observed_at_rule`
- `history_revision_class`
- `research_use_tier`
- `source_registry_id`
- `source_snapshot_id`
- `run_id`

当前 `sql/duckdb/schema.sql` 的 D3 table 尚未包含
`market_price_quality_ref`、`mechanical_gap_ref`、`pcvt_input_readiness_ref`、
`source_snapshot_ref`、`run_ref`、`history_revision_class` 和 `research_use_tier`。
本任务只声明未来 D3 canonical contract required fields，不修改 DDL；DDL alignment
留给后续实现或单独 task。

## 禁止字段

refs-only canonical table 禁止直接承载 raw/adjusted OHLCV、PCVT value/state、
future label、backtest、portfolio 或 vendor payload 字段。该限制不表示这些数值字段
永久禁止出现在 D3 层；D3-T02 可在 value view/table contract 中定义标准化数值字段。

## 阻塞条件

- formal ingestion 未授权。
- 真实 D2 raw price 未物化。
- 真实 D2 adjusted price 未物化。
- 真实 D2 quality flags 未物化。
- `factor_as_of_time` coverage 未验证。
- revision timestamp coverage 未验证。
- D3 generation 未授权。

## 验收标准

- contract JSON 通过 JSON Schema。
- contract 明确 `canonical_table_mode = refs_only`。
- formal ingestion、DuckDB write、real materialization、`data_version` release、
  PCVT calculation 和 R0 generation 均保持 false。
- required fields 覆盖 D0 / DuckDB 既有字段和 D2-T08 component refs。
- prohibited fields 覆盖 future return、label、breakout、backtest、portfolio、
  vendor payload 以及 refs-only canonical table 不应直接承载的 OHLCV 数值字段。
- README 当前阶段推进到 D3-T01，next task 为 D3-T02，且不暗示 D3 generation 或
  R0 已解锁。

## 回退方式

回退本 PR 新增的 D3-T01 contract、schema、tests、任务文档和 README 阶段索引更新。
不得修改 D0/D1/D2 已 accepted 契约来追认或绕过 D3 阻塞条件。
