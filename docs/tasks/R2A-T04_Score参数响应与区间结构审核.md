# R2A-T04 Score 参数响应与区间结构审核

## 1. 定位与当前状态

R2A-T04 的唯一输入是 accepted R2A-T01 Score release；唯一正式范围是冻结 16-request panel 的 Score 参数响应、区间结构与 accepted Score 端点结构审核。它不依赖其他数据产品。

```text
task_id: R2A-T04
scope_id: r2a_t04_score_parameter_response_interval_structure.v1
status: score_scope_repair_pending_review
formal_authorization_id: R2A-T04-REAL-AUDIT-AUTH-20260719
authorization_revision: 2
formal_run_authorized: false
formal_run_started: false
formal_run_consumed: false
full_universe_request_count: 0
full_universe_request_concurrency: 1
duckdb_thread_count: 4
R2A-T04_DONE: absent
R2A-T05_allowed_to_start: false
```

Authorization revision 2 HEAD `9d3c2dab43a10b12931db921ef730db6e8552ff1` 已在 formal run 前被替代，未被使用、未开始正式运行、未消费 formal attempt：

```text
authorization_revision_2_status: superseded_before_formal_run
authorization_revision_2_used: false
authorization_revision_2_formal_run_started: false
authorization_revision_2_formal_attempt_consumed: false
superseded_reason: scope_corrected_to_score_parameter_response_and_interval_structure
```

## 2. 不可变输入绑定

```text
score_release_id: pcavt-score-w120-v1-c7e04f11a2cd09aa
score_database_sha256: d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3
score_database_byte_size: 4255395840
score_security_count: 800
score_date_min: 2016-01-04
score_date_max: 2026-06-30

evaluator_version: r2a_t03_dynamic_evaluator.v1
output_schema_version: r2a_t03_dynamic_evaluation_output.v1
dynamic_protocol_version: pcavt_dynamic_state_protocol.v1
panel_id: r2a_t04_representative_panel.v1
request_count: 16
```

Score database 只读打开。线程 benchmark evidence 直接复用，不得重跑：

```text
benchmark_execution_head: 01bf7e12f0cb19a31c71689ada32f7a78f8aec75
benchmark_receipt_sha256: c0fa81d08138cc0e2d5121be9affa52db11c3df36b0227fe420ca0c78ff6d369
benchmark_receipt_byte_size: 97485
benchmark_fingerprint: 049eeca525592e9a3d9659b3d0a3ce1eccc322f0289f283d0e9d8fe647e82231
selected_duckdb_threads: 4
thread_benchmark_evidence_reused: true
reuse_basis: evaluator_request_output_and_fingerprint_core_byte_identical
thread_benchmark_rerun_required: false
```

## 3. 冻结的 16-request panel

Panel 包含五级维度阶梯 `P`、`PA`、`PCA`、`PCAV`、`PCAVT`；PCAVT equal-q 1000/1500/2000/2500 bp；PCAVT confirmation K=2/3/5/7；以及 P/C/A/V/T 各自从 q=1500 bp 单独放宽至 2500 bp 的五个 marginal requests。D05 基线在比较组间复用，总 request 数恰为 16。

Panel 用于审核响应关系，不构成最佳参数候选集。T04 不选择或冻结唯一 q/K。

## 4. 参数响应硬校验

必须验证：

- equal-q 的 raw 与 confirmed 状态随 q 放宽形成 superset，joint-ready 精确相等；
- 不同 K 的 raw 状态精确相等，confirmed 状态随 K 增大收缩，高 K confirmation 不早于低 K；
- `P → PA → PCA → PCAV → PCAVT` 的 raw 与 confirmed 状态逐级收缩；
- 每个 marginal request 的目标维 active state 严格扩张，非目标维精确不变，joint raw state 为 D05 的 superset；
- 整个 panel 的 raw true 与 confirmed interval 总数均大于零，响应不得退化。

任一响应 mismatch 或退化都阻塞正式结果。

## 5. 区间结构审核

每个 request 报告 spine、present、joint-ready、raw true/false/null、raw rate、最大 streak 与证券级 streak 分位数、confirmed count/rate、confirmation event、interval count、security breadth、zero-interval securities、duration 分布、right-censored 分布与 termination distribution。年度表报告相同核心结构，并明确 2026 是截至 2026-06-30 的部分年度。

`interval_inventory` 的主键为：

```text
logical_request_name
request_id
security_id
interval_ordinal
```

每个 request 的 inventory row count 必须与 request metrics 的 confirmed interval count 完全一致，且主键不得重复。

## 6. Score 端点结构审核

对每个 confirmed interval 抽取四类非空日期：`raw_start`、`confirmation`、`last_confirmed_end` 和 `termination`。每个端点保留五个 dimension 的 mean/min、eligibility、validity、reason codes，以及十个 component 的 raw value、percentile、Score、eligibility、validity、reason codes。

若四类端点的非空日期总数为 `endpoint_count`，则每个 request 必须满足：

```text
score_dimension_structure rows = endpoint_count × 5
score_component_structure rows = endpoint_count × 10
```

端点 key 不得重复。聚合分位数必须由 DuckDB `quantile_cont` 计算，不能把全量 endpoint rows 载入 Python。

## 7. 确定性区间样本

每个 request 最多选择 20 个 interval，稳定排序键为：

```text
sha256(request_hash + ":" + security_id + ":" + confirmation_date + ":" + interval_ordinal)
```

按 hash 升序截取；不足 20 个时保留全部。不得人工选样或按结果好坏筛选。

## 8. 串行正式执行

Formal gate 通过后，16 个 requests 必须严格串行。每个 request 使用 800 只证券的完整 observation history，DuckDB threads 固定为 4。执行顺序固定为 evaluator、accepted output validator、五表 canonical profiles、metrics/response/interval/Score endpoint 抽取、formal log，然后删除临时 result DuckDB。禁止并行 requests、resume、自动重跑、跳过 request、按日期切片、证券抽样或动态调整 threads。

Gate 必须在创建 output root 前验证 authorization HEAD/parent/revision、Score identity、benchmark receipt identity/fingerprint/threads、panel identity/count 与 concurrency=1。

## 9. Formal 与 compact review 产物

Local formal root 保留 authorization、Score identity、panel、manifest、receipt、analysis、per-request request JSON、log、`audit_metrics.duckdb`、完整 interval parquet 与证券级 interval distribution。完整数据库与 interval 明细不得提交 Git。

Compact review bundle 恰含：

```text
request_metrics.csv
year_metrics.csv
termination_metrics.csv
response_checks.csv
interval_structure_summary.csv
interval_samples.csv
score_dimension_endpoint_summary.csv
score_component_endpoint_summary.csv
request_output_profiles.json
request_panel.json
score_source_identity.json
validation_receipt.json
result_analysis.md
run_summary.json
```

Bundle 总大小不超过 60 MiB，不含完整 request result 或 audit database。自动 recommendation 只能为 `continue_to_owner_result_review` 或 `blocked_evaluator_or_response_degeneracy`，owner result review 保持 pending。

## 10. 研究边界与停止点

T04 不选择最佳 q/K，不注册 canonical dynamic state，不生成预测标签或交易信号，不做回测或组合。正式结果接受前不得创建 `DONE`，不得允许 R2A-T05。

本轮先建立 Score-only scope repair commit；其精确 Quality 成功后，才创建 metadata-only authorization revision 3。Revision 3 只绑定 repair HEAD 并把状态改为 `authorized_not_started`，不得修改实现文件。其精确 Quality 成功后停止在：

```text
R2A-T04 Score-only formal authorization review
formal_run_authorized: true
formal_run_started: false
formal_run_consumed: false
full_universe_request_count: 0
R2A-T04_DONE: absent
R2A-T05_allowed_to_start: false
```
