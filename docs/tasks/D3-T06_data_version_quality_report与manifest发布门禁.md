# D3-T06 data_version、quality report 与 manifest 发布门禁

状态：gate / contract-only；D3 real generation not authorized。

## 目标

定义 D3 candidate `data_version`、quality report、dataset manifest、source snapshot refs、
run refs、row count/coverage/hash checks、release gate statuses 和 formal blocking reasons 的
契约，并实现 synthetic-only release gate validator。

## 核心设计

D3-T06 不生成正式 `data_version`，不创建真实 manifest，不写 DuckDB。它只定义未来
D3-T07 发布 candidate D3 data product 前必须满足的 gate。D3-T06 validator 只验证
synthetic release candidate payload 或内存对象，证明 gate 逻辑可以拒绝不完整、不合规
或越权的 release candidate。

当前 formal release decision 固定为 `formal_release_blocked`。D2 formal materialization、
source authorization、factor_as_of_time coverage、revision timestamp coverage、formal D3
generation 和 R0 release 仍为 blocking gates。

## 非目标

- 不生成真实 D3 rows。
- 不读取真实 D1/D2/D3 data。
- 不读取 MarketDB、`.day`、`data/raw/` 或 `data/external/`。
- 不调用外部 API。
- 不写 DuckDB。
- 不创建 DDL。
- 不创建真实 run manifest、dataset manifest、source snapshot manifest 或 `data_version`。
- 不计算 PCVT values。
- 不定义 q、threshold 或 state machine。
- 不生成 returns、labels、future outcome、backtest 或 portfolio。
- 不升级 BAOSTOCK/HITHINK formal source。
- 不解锁 R0。

## 输入

- `configs/d3/daily_market_observations_contract.v1.json`
- `configs/d3/daily_market_observation_values_contract.v1.json`
- `configs/d3/component_lineage_no_bypass_contract.v1.json`
- `configs/d3/quality_readiness_contract.v1.json`
- `configs/d3/synthetic_daily_observation_build_contract.v1.json`
- `configs/d2/d2_acceptance_d3_handoff_contract.v1.json`
- `configs/d2/market_quality_pcvt_dependency_contract.v1.json`
- `configs/d0/data_product_contracts.v1.json`
- `scripts/validate_d3_component_lineage_no_bypass.py`
- `scripts/build_d3_synthetic_daily_observation.py`

## 输出

- `configs/d3/data_version_quality_manifest_gate_contract.v1.json`
- `schemas/d3_data_version_quality_manifest_gate_contract.schema.json`
- `scripts/validate_d3_release_gate.py`
- `tests/test_d3_data_version_quality_manifest_gate_contract.py`
- `tests/test_validate_d3_release_gate.py`
- 本任务文档
- `docs/tasks/README.md` 阶段索引更新
- `scripts/validate_configs.py` 配置校验接入

## 阻塞条件 / 失败状态

- formal ingestion 未授权。
- D3-T06 不授权 DuckDB write、DDL、真实数据物化、manifest 创建或 `data_version` release。
- D2 formal materialization 未完成前，D3-T07 仍 blocked。
- release candidate 缺少 data_version、manifest、quality report 或 gate results 时失败。
- row count、security count 或 date range 在三类 candidate 之间不一致时失败。
- required formal gate 缺失、failed 或 blocked 时不得声明 `release_allowed`。
- 当前硬阻塞 gate 被标记为 `passed` 时失败。
- payload path 或 payload 内容包含 `data/raw`、`data/external`、MarketDB、`.duckdb` 或 `.day` 时失败。
- payload 任意层级包含 PCVT values、future labels、backtest、portfolio、vendor payload 或 raw/qfq/hfq rows 时失败。
- 若 contract、schema、validator、tests、README 或 config validation 未通过，本 PR 失败。
- 若 PR 引入真实数据读取、DuckDB 写入、DDL、manifest、`data_version`、PCVT values、future labels、backtest 或 formal source promotion，本 PR 失败并应回退。

## 验收标准

- contract JSON 通过 JSON Schema。
- release gate status vocabulary、release decision vocabulary 和当前 blocking gates 完整。
- data_version、manifest、quality report 字段契约完整。
- release gate checklist 覆盖 D2 formal materialization、source authorization、lineage/no-bypass、quality readiness、manifest、quality report、row count、hash、prohibited field、forbidden path 和 R0 lock。
- validator 能接受合法 synthetic blocked candidate，并拒绝结构缺失、计数不一致、越权 release、硬阻塞 gate passed、禁止字段和禁止路径。
- README 推进到 D3-T06 / D3-T07，且 D3-T07 和 R0 仍 blocked。

## 回退方式

回退本 PR 新增的 D3-T06 contract、schema、validator、tests、任务文档和 README 阶段索引更新。
不得修改 D0/D1/D2 已 accepted 契约来绕过 D3 阻塞条件。
