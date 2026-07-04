# D2-T01 价格来源与 raw OHLCV 探针契约

## 状态

completed via PR #25

## 目标

本任务建立 D2 价格数据进入正式流程前的 source/as-of/snapshot/manifest 边界。
目标是基于 `configs/d0/source_registry.v1.json`、`configs/d0/data_product_contracts.v1.json`
和既有 D1 契约，定义 raw OHLCV 探针应验证的来源资格、字段语义、原始快照保留、
observed_at 规则、历史修订识别、manifest 链路和失败状态。

D2-T01 只回答“候选行情来源是否具备进入后续小样本落账设计的条件”，不回答
“全量行情能否直接拉取并作为正式研究数据”。

## 非目标

- 不调用任何外部 API。
- 不新增 loader、API client、ETL worker 或批量行情采集代码。
- 不拉取全市场行情、复权因子、公司行为或交易约束数据。
- 不导入真实 OHLCV、成交额、复权价格、复权因子或供应商调整价。
- 不生成 D1/D2 DuckDB 实体数据，不创建 committed DuckDB 文件。
- 不生成 raw snapshot、dataset manifest、run manifest 或 artifact manifest。
- 不改变 D0 source registry 的来源资格结论。
- 不授权 `HITHINK_FINANCIAL_API`、`BAOSTOCK` 或任何公共端点进入正式 ingestion。

## 输入

- `configs/d0/source_registry.v1.json`
- `configs/d0/data_product_contracts.v1.json`
- `configs/d1/trading_calendar_status_contract.v1.json`
- `configs/d1/corporate_actions_adjustment_contract.v1.json`
- `sql/duckdb/schema.sql`
- D1-T04 universe membership materialization 结果

## 输出

- `configs/d2/raw_ohlcv_source_contract.v1.json`
- `schemas/d2_raw_ohlcv_source_contract.schema.json`
- `tests/test_d2_raw_ohlcv_source_contract.py`
- D2 raw OHLCV 探针契约配置或设计文档
- 探针字段、快照、manifest、observed_at、as-of、revision 和失败状态的测试
- 本任务文档与 `docs/tasks/README.md` 索引更新

## 契约边界

- raw OHLCV 探针只验证候选来源能否提供 `raw_open`、`raw_high`、`raw_low`、
  `raw_close`、`volume`、`amount`、`trading_status`、`price_limit_status`、
  `observed_at`、`source_registry_id` 和 `source_snapshot_id` 所需证据。
- 原始交易价格必须保持原始交易事实语义，不得被复权价、供应商调整价或连续研究价格覆盖。
- 探针必须声明原始响应或导出文件的保存规则、SHA-256 计算规则、snapshot id 生成规则、
  source snapshot manifest、dataset manifest 和 run manifest 的最小字段。
- 探针必须区分 endpoint retrieval time、vendor timestamp、trading_date 和 observed_at。
- 若候选来源返回最终修订历史，必须显式标记为 final-revised candidate history，不得冒充
  point-in-time history。
- `BAOSTOCK` 可作为备选或交叉验证候选，但 adjusted price 或复权标记不得在 D2-T01 中
  被接受为正式连续研究价格来源。
- `CSINDEX_OFFICIAL` 只能用于 membership evidence / alignment，不得作为行情、交易状态、
  公司行为或复权因子来源。
- `A_STOCK_DATA_RECON` 只能作为 endpoint reconnaissance，不得作为 raw snapshot publisher。

## 阻塞条件

- source terms、license 或 redistribution 审查未允许对应价格用途。
- as-of、observed_at、revision 或 repeated snapshot comparison 规则未知。
- 原始响应、导出文件、SHA-256、source snapshot manifest、dataset manifest 或 run manifest
  的任一链路不可追溯。
- wrapper/SDK 返回数据无法追溯到原始 publisher、endpoint、参数和版本。
- trading_status、price_limit_status 或停牌/涨跌停语义未知且无法保留为 `unknown`。
- 探针设计试图以供应商复权价替代 raw trading fact。

## 验收标准

- D2 队列从 4 个标题级 task 拆分为 7 个 PR 级 task。
- D2-T01 明确不做 API 调用、全量拉取、loader、DuckDB 实体数据或 manifest 产物生成。
- `raw_ohlcv_source_contract.v1.json` 能通过 `d2_raw_ohlcv_source_contract.schema.json`。
- 探针契约覆盖 source identity、license/terms、endpoint 参数、raw snapshot、SHA-256、
  observed_at、revision policy、manifest references、failure states 和 no-substitution 规则。
- 测试验证 D2-T01 不授权正式 ingestion，且 D2 不能从全量行情拉取开始。
- 后续 D2-T02 只能在本任务边界通过后进入成员对齐层物化，不得临时扩大到价格落账或复权构建。

## 回退方式

若契约或测试未通过，回退本任务新增的 D2-T01 文档、索引更新和测试。
不得用补写说明、手工下载、临时 CSV、DuckDB 文件或供应商标签追认失败结果。
