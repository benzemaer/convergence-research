# D3-T03 组件引用、source lineage 与 no-bypass 校验器

状态：contract-only；D3 real generation not authorized。

## 目标

定义并实现 D3 component refs、source lineage、`observed_at` / revision inheritance、
`research_use_tier` propagation 和 no-bypass policy 的 contract-only validator。该
validator 只验证 synthetic payload 或内存对象，不读取真实 D1/D2/D3 数据。

## 核心设计

D3-T03 不定义新的数据表，不创建 DDL，不生成真实数据。它只规定 D3 canonical refs
table 与 D3 value layer 的引用关系应如何被校验。

未来 `d3.daily_market_observations` 中的 component refs 必须可追溯到 D1/D2
component artifact refs、source snapshot refs 和 run refs；
`d3.daily_market_observation_values` 必须继承 canonical observation 的 lineage、
`observed_at`、`revision_policy`、`history_revision_class` 和 `research_use_tier`。
R0 只能读取 D3 formal entry layer，不能直接读取 D1/D2 raw component tables。

## 非目标

- 不生成真实 D3 rows。
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
- `configs/d3/daily_market_observation_values_contract.v1.json`
- `configs/d2/d2_acceptance_d3_handoff_contract.v1.json`
- `configs/d2/market_quality_pcvt_dependency_contract.v1.json`
- `configs/d0/data_product_contracts.v1.json`

## 输出

- `configs/d3/component_lineage_no_bypass_contract.v1.json`
- `schemas/d3_component_lineage_no_bypass_contract.schema.json`
- `scripts/validate_d3_component_lineage_no_bypass.py`
- `tests/test_d3_component_lineage_no_bypass_contract.py`
- `tests/test_validate_d3_component_lineage_no_bypass.py`
- 本任务文档
- `docs/tasks/README.md` 阶段索引更新
- `scripts/validate_configs.py` 配置校验接入

## 阻塞条件 / 失败状态

- formal ingestion 未授权。
- D3-T03 不授权 DuckDB write、DDL、真实数据物化或 `data_version` release。
- 缺少任一 required component ref 时 validator 必须失败。
- value layer row 缺少 `canonical_observation_ref`、primary key 不一致或 lineage
  inheritance 不一致时 validator 必须失败。
- `final_revised_history` 声称 point-in-time support 时 validator 必须失败。
- `observed_at`、`revision_policy`、`history_revision_class` 或 `research_use_tier`
  缺失时 validator 必须失败。
- R0 allowed sources 出现 D1/D2 direct table 时 validator 必须失败。
- payload 包含 prohibited fields、vendor payload 或 raw/qfq/hfq row payload 时 validator
  必须失败。
- 若 contract、schema、tests、README 或 config validation 未通过，本 PR 失败。

## 验收标准

- contract JSON 通过 JSON Schema。
- validator 仅接受 synthetic payload 或内存对象。
- validator 不读取 `data/raw/`、`data/external/`、MarketDB、`.day` 或 DuckDB。
- validator 覆盖 component refs、canonical/value primary key alignment、lineage
  inheritance、observed/revision policy、research use tier 和 no-bypass policy。
- README 推进到 D3-T03 / D3-T04，且 D3-T07 和 R0 仍 blocked。

## 回退方式

回退本 PR 新增的 D3-T03 contract、schema、validator、tests、任务文档和 README 阶段索引
更新。不得修改 D0/D1/D2 已 accepted 契约来绕过 D3 阻塞条件。
