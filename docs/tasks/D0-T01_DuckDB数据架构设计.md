# D0-T01：DuckDB 数据架构设计

> Task ID：D0-T01
> 状态：draft
> 关联阶段：D0
> 目标门禁：G1
> 当前运行资格：eligible_for_d0

## 1. 目标

在不运行正式数据处理的前提下，定义本项目 DuckDB 数据产品的逻辑边界、文件布局、
schema 分层、表级职责、键约束、时间语义与并发写入约束，为后续 D0→D3 的实现提供
可审核的架构基线。

## 2. 非目标

- 不创建 DuckDB 文件；
- 不执行 D0 数据抓取、解析或装载；
- 不采集行情、公司行为、停牌、涨跌停或指数成分以外的数据；
- 不写研究特征、事件、标签、收益或回测结果；
- 不生成 `d3.daily_market_observations` 实体数据；
- 不把运行 manifest、数据 manifest 或 artifact manifest 伪造成架构设计产物。

## 3. 设计边界

DuckDB 在本项目中的职责是“结构化仓库与派生层”，不是原始快照存储层。

原始事实必须继续保存在只读文件层：

```text
data/raw/
data/external/
```

DuckDB 只保存：

```text
- 对原始快照的结构化登记与审计索引；
- 可重建的标准化明细表；
- 经过门禁批准的派生宽表或观测表；
- 面向 R0 的正式日频入口表定义。
```

## 4. 架构原则

1. 原始字节不进入 DuckDB，DuckDB 只引用原始文件路径、哈希和快照版本。
2. 一个正式运行周期内，只允许一个 writer 向同一 DuckDB 文件提交写入。
3. 任何并发 worker 不得同时写同一 `.duckdb` 文件；并发只能写分片中间产物，再由单 writer 合并。
4. 表分层必须区分 source registry、snapshot audit、normalized facts、research-ready observations。
5. 所有正式表都必须可追溯到 `run_id`、`data_version`、`code_commit`、`config_hash`、`environment_lock_hash` 和输入哈希。
6. `d3.daily_market_observations` 是 R0 唯一正式日频入口；不得绕过它直接从 D1/D2 表进入研究。
7. D1–D3 正式表必须显式继承 `universe_id`、`data_version` 和时间分段字段；不得只依赖总原则或外部说明补足研究入口约束。

## 5. 目标文件布局

建议的物理布局如下：

```text
data/interim/duckdb/
  convergence.duckdb
  exports/
  checkpoints/
```

约束：

- `convergence.duckdb` 作为主结构化仓库；
- `exports/` 用于只读导出物，不作为正式写回入口；
- `checkpoints/` 仅保存可重建的中间交换物；
- 正式运行不得在多个路径下维护多个真源 DuckDB 主库。

## 6. 逻辑 schema 分层

建议的 schema 分层如下：

```text
meta/      来源注册、快照、运行、字段字典、质量审计
d0/        原始快照登记与结构化审计索引
d1/        标准化基础事实层
d2/        经门禁批准的对齐与补充层
d3/        研究正式入口层
```

### meta

- `meta.source_registry`
- `meta.snapshot_registry`
- `meta.run_registry`
- `meta.field_dictionary`
- `meta.quality_audit`

### d0

- `d0.external_snapshot_files`
- `d0.index_membership_evidence`
- `d0.raw_dataset_inventory`

### d1

- `d1.security_master`
- `d1.trading_calendar`
- `d1.raw_market_prices`
- `d1.corporate_actions`
- `d1.trading_constraints`

### d2

- `d2.adjusted_market_prices`
- `d2.market_price_quality_flags`
- `d2.membership_alignment`

### d3

- `d3.daily_market_observations`

## 7. 核心表级约束

### `d0.index_membership_evidence`

用途：登记官方指数成分证据与审核结论，不存原始字节。

粒度与键约束：

```text
grain: 一个 snapshot_id 下的一份指数成分证据文件或文档的一次审核版本
primary key: (snapshot_id, index_code, document_id, review_revision)
uniqueness rule: 同一 snapshot_id、index_code、document_id、review_revision 只能登记一条审核证据；若同一来源重新抓取或重新审核，必须生成新的 snapshot_id 或 review_revision。
```

至少包含：

```text
snapshot_id
index_code
document_id
document_title
effective_date
source_url
retrieved_at
file_path
file_sha256
review_status
review_commit
reviewed_by
reviewed_at
independence_attested
review_revision
```

### `d1.raw_market_prices`

用途：保存原始交易事实层，不混入复权结果。

粒度与键约束：

```text
grain: 一个 data_version / universe_id / security_id / trading_date / source_snapshot_id 下的一条原始行情观测
primary key: (data_version, universe_id, security_id, trading_date, source_snapshot_id)
uniqueness rule: 同一 data_version 内，同一 universe_id、security_id、trading_date、source_snapshot_id 不得重复；供应商修订不得覆盖旧记录，必须形成新的 data_version 或 source_snapshot_id。
```

至少包含：

```text
data_version
universe_id
time_segment_id
security_id
trading_date
raw_open
raw_high
raw_low
raw_close
volume
amount
trading_status
price_limit_status
source_snapshot_id
```

### `d2.adjusted_market_prices`

用途：保存连续研究价格层及其来源，不覆盖原始事实层。

粒度与键约束：

```text
grain: 一个 data_version / universe_id / security_id / trading_date / adjustment_revision 下的一条连续研究价格观测
primary key: (data_version, universe_id, security_id, trading_date, adjustment_revision)
uniqueness rule: 同一 data_version 内，同一 universe_id、security_id、trading_date、adjustment_revision 不得重复；复权因子、公司行为归因或 as-of 规则变化必须生成新的 adjustment_revision 或 data_version。
```

至少包含：

```text
data_version
universe_id
time_segment_id
security_id
trading_date
adj_open
adj_high
adj_low
adj_close
adjustment_factor
factor_as_of_time
corporate_action_flag
source_snapshot_id
adjustment_revision
```

### `d3.daily_market_observations`

用途：作为 R0 唯一正式日频入口，统一承接研究所需的基础日频观测。

粒度与键约束：

```text
grain: 一个 data_version / universe_id / security_id / trading_date / observation_revision 下的一条研究入口日频观测
primary key: (data_version, universe_id, security_id, trading_date, observation_revision)
uniqueness rule: 同一 data_version 内，同一 universe_id、security_id、trading_date、observation_revision 只能有一条正式入口观测；任何字段定义、来源拼接、质量规则或 observed_at 规则变化必须生成新的 observation_revision 或 data_version。
```

至少包含：

```text
data_version
universe_id
time_segment_id
security_id
trading_date
observation_revision
observed_at
```

必须显式区分：

```text
price_fact_source
corporate_action_source
membership_source
calendar_source
revision_policy
observed_at_rule
```

## 8. 并发与写入策略

正式实现必须采用：

1. 单 writer 写主库；
2. worker 只写文件分片或只读查询结果；
3. 合并步骤由单独、可审计的 writer 进程完成；
4. 合并前后要做主键、行数、排序边界和关键统计量一致性校验。

禁止：

- 多个 worker 直接 append 同一主库；
- 在主库上做不带审计的就地覆盖；
- 使用 DuckDB 作为原始 API 响应的唯一保存位置。

## 9. 验收标准

- DuckDB 角色边界与原始文件层边界明确；
- schema 分层、表职责和主键策略明确；
- 单 writer 约束明确；
- `d3.daily_market_observations` 被定义为 R0 唯一正式日频入口；
- D0/D1/D2/D3 核心表的 grain、primary key 和唯一性规则明确；
- D1–D3 表级契约显式包含 `universe_id`、`data_version` 和时间分段继承要求；
- 所有正式表的追溯字段要求明确；
- PR 不包含 DuckDB 文件、采集代码、装载代码或正式运行结果。

## 10. 后续任务

本任务通过后，后续实现应拆分为至少两个独立任务：

1. `D0-T02`：数据源资格审查与 source registry
2. `D0-T03`：D1 / D2 / D3 数据产品契约
