# D1-T01 security_master 与代码映射契约

## 状态

completed via PR #10

## 目标

本任务实现 `d1.security_master` 与代码映射的设计契约。目标是基于
`configs/d0/data_product_contracts.v1.json` 中 `d1.security_master`
的数据产品契约，明确项目内部 `security_id`、交易所代码、ticker 标准化、
source symbol 映射边界、上市/退市日期语义，以及未来 loader 必须满足的质量检查。

## 非目标

- 不调用任何外部 API。
- 不导入真实证券主数据、行情、日历、公司行为或指数数据。
- 不新增 loader、API client、ETL worker 或 source-specific ingestion 代码。
- 不生成 DuckDB 实体数据，不创建 committed DuckDB 文件。
- 不生成 raw snapshot、dataset manifest、run manifest 或 artifact manifest。
- 不改变 D0 source registry 的来源资格结论。

## 输入

- `configs/d0/data_product_contracts.v1.json`
- `configs/d0/source_registry.v1.json`
- `sql/duckdb/schema.sql`
- D1-T00 空 schema 与契约测试结果

## 输出

- `configs/d1/security_master_contract.v1.json`
- `schemas/d1_security_master_contract.schema.json`
- `tests/test_d1_security_master_contract.py`
- 本任务文档与 `docs/tasks/README.md` 索引更新

## 契约边界

- `security_id` 是项目内部稳定键，格式为 `CN.{exchange}.{ticker}`。
- `security_id` 不直接等同供应商代码或 wrapper 返回代码。
- `ticker` 是六位文本代码，必须保留前导零。
- `exchange` 仅使用项目规范代码 `SSE` 与 `SZSE`。
- source symbol 只在未来 raw snapshot / manifest / mapping 证据链中保留和追溯；
  本任务不把 vendor payload 或 raw bytes 写入 DuckDB。
- `listing_date` 与 `delisting_date` 使用 Asia/Shanghai 交易所日期语义；
  `delisting_date = null` 只表示未观测到明确退市事实，不表示仍可交易。

## 阻塞条件

- HiThink source terms 未完成正式数据使用审查。
- as-of 与 revision 规则未闭环。
- raw snapshot、SHA-256、source snapshot manifest 或 run manifest 缺失。
- source symbol 映射规则未经审核。
- 证券身份质量为 unknown 或缺失且无法追溯。

## 验收标准

- D1-T00 状态更新为 `completed via PR #9`，当前任务推进到 D1-T01。
- D1-T01 契约覆盖 `d1.security_master` 全部 required fields。
- 明确 `security_id` 是项目内部稳定键，不等同供应商代码。
- 明确 ticker / exchange / source symbol 必须可追溯。
- 明确不授权正式 ingestion；`HITHINK_FINANCIAL_API` 仍仅为候选来源。
- tests 验证 contract JSON schema、字段全集、来源边界、质量检查和 no-loader/no-API/no-data-artifact 约束。

## 回退方式

若契约或测试未通过，回退本任务新增的 D1 contract、schema、测试和任务索引更新。
不得用补写文档、手工导入数据或临时 DuckDB 文件追认失败结果。
