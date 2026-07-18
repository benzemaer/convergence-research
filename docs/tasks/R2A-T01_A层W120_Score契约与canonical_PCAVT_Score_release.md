# R2A-T01 A 层 W120 Score 契约与 canonical PCAVT Score release

## 1. 目标

本任务实现 R2A 的第一层不可变基础设施：冻结 A1/A2 的 W120 strict-past
Score 契约，并建立统一的 canonical PCAVT Score release materializer、输入绑定、
独立 validator、后置 result analysis 与 synthetic/integration tests。

本任务停在 implementation review。它不授权真实输入读取、formal run、正式
authorized input manifest、正式 artifact、`DONE`、T01 acceptance 或 R2A-T02。

## 2. 非目标

R2A-T01 不定义或输出动态阈值、维度联合条件、连续确认、日度收敛状态、区间、
d/g、缓存、未来收益、回测、交易信号或 R3 handoff。任何此类字段进入 T01 config、
schema、DuckDB 表或 manifest 都是阻塞错误。

本任务不重构 R0 engine，不重新计算全部 P/C/V/T，也不读取 R0/R2 的状态、区间或
freeze result。

## 3. Score contract

唯一窗口为 `W=120`。对同一 `security_id + component_id`，参考集合只包含当前
`observation_sequence` 之前最近 120 个 `validity_status=valid` 且 `raw_value`
finite 的 observation；当前 observation 永不进入自身参考集合。

Authoritative sequence 采用 `0,1,2,...,N`，不得重映射为 1-based；重复或缺口均
fail closed。严格过去窗口只跳过 invalid/non-finite raw observation，不跳过
authoritative spine observation。

```text
percentile = (N_less + 0.5 * N_equal) / 120
score = 1 - percentile
tie_method = midrank
```

A 层只包含：

```text
A1_LogBodyCenterToMACloudCenter_5_60
A2_BodyCenterOutsideMACloudRate20_5_60
```

A2b 不得出现。只有 A1、A2 均 eligible、valid 且 score finite 时才计算：

```text
A_Score_W120 = 0.5 * A1_Score_W120 + 0.5 * A2_Score_W120
A_Min_W120   = min(A1_Score_W120, A2_Score_W120)
```

禁止单组件 fallback、填零、前向填充、缩短窗口、日历日 rolling、包含当前行的
percentile、横截面 percentile、W250/W500、NaN 或 Infinity。

## 4. 输入边界

P/C/V/T 只复用 accepted R0-T05 W120 component 和 dimension Score rows。正式输入
adapter 对 authorized manifest 显式绑定的 DuckDB 执行 `ATTACH ... READ_ONLY`，逐项
复验文件 SHA-256、字节数、精确 logical table、schema identity、行数、证券数、日期
范围、accepted source lineage 与 input role；不得推断或模糊匹配表名。实现只负责
读取、重映射、完整 spine 扩展和 source reconciliation，不从旧状态反推 Score。

A Score 必须从 accepted A1/A2 raw observations 在 R2A 中新计算。Synthetic unit tests
仍可绑定同一显式 temporary root 下的 JSON-array fixtures；formal path 不调用该 loader。
正式 A1/A2 按证券分片，`spawn` worker 只写 Parquet shard 并返回小型元数据，parent
通过 DuckDB native scan 汇总；禁止 worker 返回全量 rows 或用 Python `executemany`
写正式日表。

正式 authorized input manifest 是 local-only 授权文件，不进入 Git source binding。
正式 package 只记录该 manifest 的 SHA-256、formal authorization ID，以及去除本机路径
后的 artifact/table/hash/coverage/input-role 摘要。

## 5. Availability contract

逻辑 availability policy 固定为：

```text
policy_id: r2a_t01_eod_close_1500_asia_shanghai.v1
timezone: Asia/Shanghai
utc_offset: +08:00
market_information_cutoff: 15:00:00
policy_class: research_logical_availability_time
physical_ingestion_timestamp_required: false
same_timestamp_execution_assumed: false
row_available_time: trading_date + 15:00:00 Asia/Shanghai
```

该时间表示研究信息集在收盘形成，不表示物理入库时间，也不假设可在同一时间戳成交。
`trading_sessions.available_time`、spine observation availability、component availability
和 dimension availability 均为非空 `TIMESTAMPTZ`，并由独立 validator 精确复验。

## 6. Canonical release

Synthetic tests 仅在临时目录建立与未来 candidate package 同形的结构：

```text
score_data.duckdb
manifest.json
schema.json
validation_receipt.json   # validator 后生成
result_analysis.md        # validator passed 后由 analyzer 生成
```

Runner 不提前生成 validation receipt 或空 analysis；acceptance 前不创建 `DONE`。
DuckDB 恰有七张表：

```text
securities
trading_sessions
security_observation_spine
dimension_definitions
dimension_components
daily_component_scores
daily_dimension_scores
```

完整 `security_observation_spine` 是左表。每个 spine observation 必须显式扩展为十个
component rows 与五个 dimension rows；`missing` / `listing_pause` 必须保留 NULL score、
`validity_status=blocked` 和稳定 reason codes。Present observation 的 source row 缺失
必须 fail closed，禁止 inner join 丢行或自动降级为 placeholder。

`score_release_id` 不接受 CLI 覆盖，而由 release contract、dimension definition、W120、
availability policy hash 和 ordered materialization input hashes 的 canonical JSON
preimage 计算。所有七表主键均包含该 ID；`schema.json` 记录字段类型/nullability、复合
主外键、unique/check、enum domain 与 canonical order，并与 DuckDB introspection 对比。

## 7. Validator 与 result analysis

Validator 必须重新打开实际 DuckDB、manifest 和绑定输入，检查七表/schema introspection、
0-based 序列、P/C/V/T 双向 key/value reconciliation、五维十组件 cardinality、Score
domain、reference window、availability、expected-empty blocked rows、全零/全一/全 NULL
和 source-valid coverage。`pcvt_validation_raw` 作为 validation-only input 独立抽样复算
P/C/V/T strict-past Score；A component 也由 validator 内独立算法复算，全部五维 mean/min
从 output component rows 复算，不调用 production A Score 函数。

只要 DuckDB、manifest、schema 和 validation receipt 可读，Analyzer 就必须运行；failed
receipt 生成 `analysis_status=blocked`、`release_recommendation=do_not_publish`。报告独立
读取实际 DuckDB，覆盖七表行数、证券/日期/年度 coverage、component/dimension 分布、
mean/min 与 availability mismatch、expected-empty、source reconciliation、复算样本及
异常解释。异常未解释前不得发布或推进 gate。

## 8. Formal 边界

通用 engine 不硬编码 800。只有未来获得独立授权的 formal runner/validator 才强制：

```text
security_count = 800
calendar years = 2016..2026
```

当前 config 固定 `formal_run_allowed=false`、`real_input_read_allowed=false`。本 PR
不得执行正式 archive builder、正式 materialization 或 formal result analysis。
未来 formal 授权还必须提供精确 `execution_commit`，并从 Git blobs 绑定 config、
availability policy、六个 schema、R2A 执行源码/脚本与 environment lock；dirty、staged
或工作树内容不一致均 fail closed。Local-only authorized input manifest 不要求存在于
execution commit；正式数据 artifact 由 accepted source manifest、精确 logical table、
内容哈希和 coverage 绑定，不以文件 mtime 或本地运行时间替代 lineage。

## 9. 验收与停止点

Implementation review 前至少通过 config/schema 校验、canonical text、format/lint、
`pytest tests/r2a -q`、合订本检查和 PR Quality。README 只记录：

```text
R2A-T01_status: implementation_complete_pending_review
formal_run_allowed: false
formal_run_status: not_started
result_review_status: not_started
readme_advanced: false
R2A-T02_allowed_to_start: false
```

任务停止在 R2A-T01 implementation review，不接受 T01，不推进 R2A-T02。
