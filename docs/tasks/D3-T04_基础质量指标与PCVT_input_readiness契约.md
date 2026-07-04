# D3-T04 基础质量指标与 PCVT input readiness 契约

状态：contract-only；D3 real generation not authorized。

## 目标

定义 D3 基础质量指标、质量摘要字段、unknown policy、window validity policy、trading
constraint handling、mechanical gap handling、amount/volume unit readiness、DailyVWAP
readiness、continuous price readiness、PCVT input readiness 和 blocking reasons 的
contract。该 contract 只定义规则，不计算真实质量指标，不生成真实 readiness rows。

## 核心设计

D3-T04 不定义 PCVT 指标值，不定义状态，不定义 q，不定义阈值。它只定义 R0 未来读取
D3 value layer 时，哪些底层输入字段可以被视为 ready、partial、blocked、unknown 或
diagnostic_required。PCVT input readiness 是 D3 对 R0 的输入可用性声明，不是 PCVT
value、PCVT score 或 state machine result。

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
- `configs/d3/component_lineage_no_bypass_contract.v1.json`
- `configs/d2/market_quality_pcvt_dependency_contract.v1.json`
- `configs/d2/d2_acceptance_d3_handoff_contract.v1.json`
- `configs/d0/data_product_contracts.v1.json`

## 输出

- `configs/d3/quality_readiness_contract.v1.json`
- `schemas/d3_quality_readiness_contract.schema.json`
- `tests/test_d3_quality_readiness_contract.py`
- 本任务文档
- `docs/tasks/README.md` 阶段索引更新
- `scripts/validate_configs.py` 配置校验接入

## 阻塞条件 / 失败状态

- formal ingestion 未授权。
- D3-T04 不授权 DuckDB write、DDL、真实数据物化或 `data_version` release。
- D2 formal materialization 未完成前，D3-T07 仍 blocked。
- unknown trading status、price limit status、mechanical gap attribution 或 unit status 不得静默转正常值。
- 若 contract、schema、tests、README 或 config validation 未通过，本 PR 失败。
- 若 PR 引入真实数据读取、DuckDB 写入、DDL、manifest、`data_version`、PCVT values、future labels、backtest 或 formal source promotion，本 PR 失败并应回退。

## 验收标准

- contract JSON 通过 JSON Schema。
- quality domains、quality summary fields、status/severity vocabularies 完整。
- raw OHLCV、continuous price、raw-vs-continuous reconciliation、amount/volume/DailyVWAP、trading constraint、mechanical gap 和 window validity 规则均被声明。
- PCVT input readiness matrix 覆盖 8 个候选指标，且不包含 PCVT value / score / state。
- README 推进到 D3-T04 / D3-T05，且 D3-T07 和 R0 仍 blocked。

## 回退方式

回退本 PR 新增的 D3-T04 contract、schema、tests、任务文档和 README 阶段索引更新。
不得修改 D0/D1/D2 已 accepted 契约来绕过 D3 阻塞条件。
