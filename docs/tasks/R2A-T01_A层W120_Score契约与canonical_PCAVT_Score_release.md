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

唯一窗口为 `W=120`。对同一 `security_id + indicator_id`，参考集合只包含当前
`observation_sequence` 之前最近 120 个 `validity_status=valid` 且 `raw_value`
finite 的 observation；当前 observation 永不进入自身参考集合。

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

P/C/V/T 只复用 accepted R0-T05 W120 component 和 dimension Score rows。实现只负责
输入绑定、哈希验证、读取、重映射、完整 spine 扩展和 source reconciliation；不从
旧状态反推 Score，也不重新计算 P/C/V/T。

A Score 必须从 accepted A1/A2 raw observations 在 R2A 中新计算。本 implementation
仅允许 builder 绑定同一显式 temporary synthetic root 下的 JSON-array fixtures；任何
非 synthetic manifest 或哈希变化都 fail closed。

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
component rows 与五个 dimension rows；缺失 observation 保留 NULL score、validity 和
稳定 reason codes，禁止 inner join 丢行。

## 7. Validator 与 result analysis

Validator 必须重新打开实际 DuckDB、manifest 和绑定输入，检查七表/字段契约、主键与
序列、P/C/V/T source reconciliation、五维十组件 cardinality、score domain、reason
codes、availability、缺失行、异常全零/全一/全 NULL，以及 source-valid 到下游的异常
减少。A component 和 dimension mean/min 使用 validator 内独立算法复算，不调用
production A Score 函数。

Analyzer 只在 validation receipt passed 后运行，并重新打开实际 DuckDB、manifest 和
receipt 生成包含真实行数、分布、维度 coverage 与 observation-status 扫描的
`result_analysis.md`。

## 8. Formal 边界

通用 engine 不硬编码 800。只有未来获得独立授权的 formal runner/validator 才强制：

```text
security_count = 800
calendar years = 2016..2026
```

当前 config 固定 `formal_run_allowed=false`、`real_input_read_allowed=false`。本 PR
不得执行正式 archive builder、正式 materialization 或 formal result analysis。
未来 formal 授权还必须提供精确 `execution_commit` 和已提交的 authorized input
manifest；runner 从 Git blobs 绑定 config、availability policy、六个 schema、R2A
执行源码/脚本与 environment lock，并拒绝 dirty、staged 或工作树内容不一致的正式
输入。正式数据 artifact 由 accepted source manifest 和内容哈希绑定，不以文件 mtime
或本地运行时间替代 lineage。

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
