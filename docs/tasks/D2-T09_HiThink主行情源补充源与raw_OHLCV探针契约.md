# D2-T09 HiThink 主行情源、补充源与 raw OHLCV 探针契约

## 状态

in_progress via PR TBD；stage 1 contract-only / local-schema-probe only。

本 PR 第一阶段定义 HiThink Financial-API 本地 dump 作为 primary formal candidate source，BAOSTOCK 和 Tushare 作为 fallback / repair source，并废弃 `a-stock-data` formal source 路径。第一阶段只建立 source registry、schema/coverage probe contract 和 synthetic/local-only probe，不生成正式 raw price artifact。

## 目标

- 定义 HiThink Financial-API 为 primary formal candidate source。
- 定义 BAOSTOCK 为 fallback priority 1，Tushare 为 fallback priority 2。
- 声明 fallback 只能 missing-only / repair-only，不能静默覆盖 HiThink 价格冲突。
- 将 `a-stock-data` 从 formal/fallback active source 路径删除或标记为 rejected / deprecated。
- 实现 local-only schema 与 coverage probe contract，用于检查字段、覆盖率、单位、时间语义和 fallback 边界是否可进入 formal candidate review。

## 核心设计

HiThink 是 primary formal candidate source。BAOSTOCK 是 fallback priority 1。Tushare 是 fallback priority 2。Fallback 只能用于 missing-only / repair-only，必须记录 `fallback_reason`、`fallback_source`、`fallback_field`、`fallback_security_id`、`fallback_trading_date`、`repair_method` 和 `repair_confidence`。跨源价格冲突必须生成 discrepancy report，不得静默覆盖主源。

`a-stock-data` 不得出现在 primary source 或 fallback sources，只能出现在 rejected / deprecated source 清单。

## 非目标

- 不生成正式 raw price table。
- 不生成正式 D2 adjusted price。
- 不计算连续研究价格。
- 不写 DuckDB。
- 不创建 manifest。
- 不发布 `data_version`。
- 不创建 D3 artifact。
- 不计算 PCVT values。
- 不定义 q、threshold 或 state machine。
- 不生成 returns、labels、future outcome、backtest 或 portfolio。
- 不升级任何源为 accepted formal source。
- 不解锁 D3-T07 或 R0。

## 输入

- `configs/d2/d2_acceptance_d3_handoff_contract.v1.json`
- `configs/d2/market_quality_pcvt_dependency_contract.v1.json`
- `configs/d0/data_product_contracts.v1.json`
- `configs/d3/data_version_quality_manifest_gate_contract.v1.json`

本地可选输入路径，仅由用户显式传入 probe，不提交到 Git：

- `data/raw/a_share_daily_k_1d_none_10y_20260704.parquet`
- `data/raw/a_share_adjustment_factors_event_none_all_20260704.parquet`

## 输出

- `configs/d2/formal_source_registry_contract.v1.json`
- `configs/d2/hithink_raw_ohlcv_probe_contract.v1.json`
- `schemas/d2_formal_source_registry_contract.schema.json`
- `schemas/d2_hithink_raw_ohlcv_probe_contract.schema.json`
- `scripts/probe_hithink_raw_ohlcv_schema.py`
- `tests/test_d2_formal_source_registry_contract.py`
- `tests/test_d2_hithink_raw_ohlcv_probe_contract.py`
- `tests/test_probe_hithink_raw_ohlcv_schema.py`
- `docs/tasks/D2-T09_HiThink主行情源补充源与raw_OHLCV探针契约.md`

## Secret Handling

HiThink API key 只能从 `HITHINK_API_KEY` 环境变量读取。Tushare token 只能从 `TUSHARE_TOKEN` 环境变量读取。BAOSTOCK 不需要提交 token。任何真实 token、API key 或 secret 均不得写入代码、配置、测试、文档、日志、报告或 PR 描述。

第一阶段默认不调用远程 API。若未来增加 connectivity probe，必须默认关闭，并且只能在显式参数启用时读取环境变量。

## Probe Boundary

Probe 只读取用户显式传入的本地 parquet 路径或测试中的 synthetic parquet 路径；不得默认扫描 `data/raw/`。Probe 只输出 schema、counts、date range、security count、missing fields、unit inference、time semantics、fallback readiness 和 diagnostics，不输出 row-level raw price payload。

Probe 不写 DuckDB，不创建 manifest，不发布 `data_version`，不写 `data/raw` 或 `data/generated`。

## Stage Plan

- Stage 1：HiThink source registry + schema/coverage probe + `a-stock-data` removal。
- Stage 2：人工审阅通过后追加到同一 PR 分支，处理 HiThink raw market prices formal candidate materialization 与 BAOSTOCK/Tushare fallback repair probe。

## D2-T10 Relationship

D2-T10 仍为 planned，用于 adjusted price、quality flags 与 mechanical gap formal materialization。D2-T09 第一阶段不启动 D2-T10。

## D3 / R0 Boundary

D3-T07 remains blocked pending D2 formal materialization。R0 remains blocked。D2-T09 第一阶段不生成 D3 rows，不创建 D3 artifact，不计算 PCVT，不定义 R0 状态。

## 验收标准

- Formal source registry contract 和 HiThink raw OHLCV probe contract 均通过 JSON Schema。
- HiThink 是唯一 primary formal candidate source。
- BAOSTOCK / Tushare fallback priority 分别为 1 / 2。
- `a-stock-data` 不出现在 active source 中。
- Probe 接受 synthetic explicit parquet path，报告 schema、coverage、missing fields 和 fallback readiness。
- Probe 缺字段时只报告 missing / warning，不伪造默认值。
- README 回到 D2-T09 / D2-T10，且 D3-T07 和 R0 仍 blocked。

## 回退方式

若 contract、schema、probe、tests 或 README 未通过验证，完整回退本 PR 新增的 D2-T09 文件、`.gitignore` 更新和 `validate_configs.py` 接入。不得通过提交真实 parquet、补写 manifest、生成 DuckDB 或修改上游 D2/D3 结果来追认失败。
