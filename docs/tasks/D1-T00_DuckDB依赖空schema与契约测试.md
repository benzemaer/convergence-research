# D1-T00 DuckDB 依赖、空 schema 与契约测试

## 状态

completed via PR #9

## 目标

本任务是 D1 阶段的准备任务，不采集正式数据。目标仅限于引入 DuckDB Python
依赖、建立空 DuckDB schema DDL、提供空库构建脚本，并用 schema contract tests
证明 DDL 与 `configs/d0/data_product_contracts.v1.json` 保持一致。

## 非目标

- 不授权任何外部 API 调用。
- 不授权任何真实数据导入。
- 不实现 source-specific loader、ETL worker 或正式装载流程。
- 不生成 manifest、source snapshot、D1/D2/D3 实体数据或正式数据产物。
- 不生成 `d3.daily_market_observations` 实体数据。
- 不计算 PCVT、状态、事件、标签、收益或回测。

## 输入

- `configs/d0/data_product_contracts.v1.json`
- D0-T01 DuckDB 架构边界
- D0-T02 source registry
- D0-T03 D1/D2/D3 数据产品契约

## 输出

- 精确 pin 的 `duckdb` Python 依赖。
- `sql/duckdb/schema.sql` 空 schema 与 9 张核心表 DDL。
- `scripts/create_duckdb_schema.py` 空库构建与 check 入口。
- `tests/test_duckdb_schema_contract.py` 临时 DuckDB 契约测试。

## 验收标准

- `.duckdb` 与 `.duckdb.wal` 文件已被 `.gitignore` 排除。
- DDL 能创建 `meta`、`d0`、`d1`、`d2`、`d3` schema。
- DDL 创建 9 张 D1/D2/D3 核心表，表集合等于 D0-T03 contract 表集合。
- 每张表字段覆盖 contract `required_fields`，并显式包含全局追溯字段。
- 每张表声明 `PRIMARY KEY`；后续实现仍必须通过 contract tests 与唯一性检查双重保证。
- `d3.daily_market_observations` 保留 R0 唯一正式日频入口所需来源与时点字段。
- 空库构建后所有核心表行数为 0。
- DuckDB 中不存在原始字节表、原始响应字段或 vendor payload 字段。

## 后续任务

本任务完成后，下一步才是 D1-T01 `security_master` 与代码映射设计 / 实现。
首次真实数据采集仍需单独 PR，并且只能在 source terms、raw snapshot、manifest、
as-of 与 revision 规则就位后进行。

## 回退方式

若 DDL 或契约测试失败，回退本任务新增的 DuckDB 依赖、DDL、脚本、测试和索引更新；
不得用补写说明或手工生成数据库追认失败结果。
