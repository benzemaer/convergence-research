# D2-T04 复权因子与 factor_as_of_time 门禁及合成验收框架

状态：

blocked pending factor source authorization via PR #28

## 目标

建立 D2-T04 复权因子、`factor_as_of_time`、`adjustment_revision`、公司行为关联和
合成验收的可执行门禁。本任务固定未来 `d2.adjusted_market_prices` 进入正式流程前
必须满足的字段、主键、source boundary、as-of、revision、质量检查和阻塞条件。

本 PR 不完成真实 adjustment factor materialization，不生成真实
`d2.adjusted_market_prices`，不构造连续研究价格。

## 非目标

- 不采集行情；
- 不导入真实公司行为；
- 不计算真实复权因子；
- 不生成 adjusted prices 或 `d2.adjusted_market_prices` 实体数据；
- 不写 DuckDB；
- 不创建 run manifest、dataset manifest 或 source snapshot manifest；
- 不读取 G0 raw evidence、`data/external`、MarketDB 或 `.day` 文件；
- 不调用外部 API；
- 不计算 raw gap、adjusted gap、gap attribution、PCVT、状态、事件、标签、收益或回测；
- 不解锁 D2-T05。

## 输入

- `configs/d1/corporate_actions_adjustment_contract.v1.json`
- `configs/d2/raw_ohlcv_source_contract.v1.json`
- `configs/d2/raw_market_prices_materialization_contract.v1.json`
- `configs/d2/raw_market_prices_materialization_blocking_report.v1.json`
- `configs/d2/csi800_static_2026_06_membership_alignment.v1.json`
- `configs/d0/data_product_contracts.v1.json`
- `configs/d0/source_registry.v1.json`
- `configs/g0/universe_time_boundaries.v1.json`
- `sql/duckdb/schema.sql`

## 输出

- `configs/d2/adjustment_factor_asof_contract.v1.json`
- `schemas/d2_adjustment_factor_asof_contract.schema.json`
- `configs/d2/adjustment_factor_asof_blocking_report.v1.json`
- `schemas/d2_adjustment_factor_asof_blocking_report.schema.json`
- `scripts/validate_d2_adjustment_factor_asof.py`
- `tests/test_d2_adjustment_factor_asof_contract.py`
- `tests/test_d2_adjustment_factor_asof_validator.py`

## 契约边界

- `target_table` 固定为 `d2.adjusted_market_prices`；
- required fields 与 primary key 必须匹配 D1-T03 中已定义的 adjusted price 契约；
- candidate source 仅限 `HITHINK_FINANCIAL_API` 与 `BAOSTOCK`，且二者不得在本 PR
  升级为正式 ingestion source；
- `CSINDEX_OFFICIAL` 只能作为 membership source，不得作为 corporate action、factor
  或 adjusted price source；
- `factor_as_of_time` 必须存在，且不得晚于对应 `trading_date` 的 observation cutoff；
- `adjustment_method` 与 `adjustment_revision` 的 `unknown` 只能作为阻塞状态，不得进入
  validated、frozen 或 released 产物；
- 公司行为机械缺口不得被解释为普通市场跳空、趋势变化或释放；
- adjustment factor、method、as-of、source 或 attribution 修订必须新建
  `adjustment_revision`、`source_snapshot_id` 或 `data_version`，不得覆盖旧证据。

## 阻塞条件

当前 D2-T04 仍被以下条件阻塞：

- source terms 与正式 ingestion 授权未关闭；
- factor as-of policy 未完成审核；
- corporate action as-of policy 未完成审核；
- revision policy 未完成验证；
- raw snapshot、SHA-256、source snapshot manifest、run manifest、dataset manifest 缺失；
- D2-T03 raw price materialization 仍为 `blocked_pending_source_authorization`；
- `factor_as_of_time` 与未来公司行为知识污染规则尚未通过正式源验证；
- `BAOSTOCK` 不能作为正式 adjusted price source；
- DuckDB 写入、真实 factor artifact 和真实 adjusted price artifact 均未授权。

## 验收标准

- contract 与 blocking report 通过 JSON Schema；
- contract 明确所有真实 factor、adjusted price、DuckDB 写入和 artifact 授权均为 false；
- blocking report 明确所有真实数据读取、生成、写入和 manifest flags 均为 false；
- validator 只验证内存对象或合成 fixture；
- 合成测试覆盖 required fields、禁止字段、OHLC、factor 正数、词表 unknown、
  `factor_as_of_time`、source boundary、membership alignment、重复 primary key 和静默 false；
- README 不推进到 D2-T05；
- D2-T05 不因本 PR 自动解锁。

## 回退方式

若 contract、blocking report、validator、schema、测试或任务索引失败，完整回退本 PR
新增的 D2-T04 文档、contract、blocking report、schema、validator、tests 和 README
索引更新。不得通过读取真实公司行为、读取真实行情、写 DuckDB、创建 manifest、
手工编辑数据或修改上游 D1/D2 产物来追认失败结果。
