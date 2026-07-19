# R2A / PCAVT 研究交接

> 本文是面向完全无上下文新会话的当前交接入口。它只描述当前有效路线；被替代的执行方案不得作为后续指令。

## 0. 当前状态快照

```text
repository: benzemaer/convergence-research
local_repository: D:\Code\convergence-research
current_branch: codex/r2a-t04-real-data-response-audit
remote_branch: origin/codex/r2a-t04-real-data-response-audit
R2A-T04 PR: #113 / Open / Draft
R2A-T04 scope_id: r2a_t04_score_parameter_response_interval_structure.v1
R2A-T04 status: score_independent_review_repair_pending_review
R2A-T04 unique input: accepted R2A-T01 Score release
R2A-T04 unique formal scope: 16-request Score parameter response and interval structure audit
formal_authorization_id: R2A-T04-REAL-AUDIT-AUTH-20260719
authorization_revision: 3
reviewed_harness_head: ceb460d0e8dd7c459e45ae19da1bbe5582417a1f
reviewed_harness_Quality: 29669497735 / success
formal_run_authorized: false
authorization_effective_only_after_exact_head_quality_success: true
formal_run_started: false
formal_run_consumed: false
full_universe_request_count: 0
full_universe_request_concurrency: 1
duckdb_thread_count: 4
thread_benchmark_evidence_reused: true
thread_benchmark_rerun_required: false
R2A-T04_DONE: absent
R2A-T05_allowed_to_start: false
current_stop: R2A-T04 Score-only independent-review repair review
```

Authorization revision 3 HEAD `21837edddfcc298b8539bcf9f71a1b7e016b6d47` 已在 formal run 前被替代，未使用、未开始运行、未消费 attempt；原因是 `independent_review_cli_not_aligned_with_score_only_scope`。当前先修复独立审阅 CLI，并保持 formal authorization 关闭。本轮不读取 accepted Score 数据，不创建 formal output root，也不消费 formal attempt。

## 1. 已接受的 R2A 基线

R2A 的长期架构是：

```text
immutable canonical PCAVT Score release
→ parameterized dynamic state evaluator
→ request-scoped daily states and intervals
```

R2A-T01、T02、T03 已完成并接受：

```text
R2A-T01_status: completed_accepted
accepted_run_id: R2A-T01-20260718T103110891Z
accepted_score_release_id: pcavt-score-w120-v1-c7e04f11a2cd09aa
accepted_score_database_sha256: d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3
accepted_score_database_byte_size: 4255395840
R2A-T01_DONE: present

R2A-T02_status: completed_accepted
dynamic_protocol_version: pcavt_dynamic_state_protocol.v1
reviewed_protocol_head: 6c3198a6fd270b81fbeb13649eda51f4222f89d6
R2A-T02_DONE: present

R2A-T03_status: completed_accepted
evaluator_version: r2a_t03_dynamic_evaluator.v1
output_schema_version: r2a_t03_dynamic_evaluation_output.v1
reviewed_implementation_head: 73b9b54ef76191fdbb44ffd7e4ae335601016466
R2A-T03_merge_commit: a2c2ee0a7857fad86e4b8b14f6bf82f0d24a639a
R2A-T03_DONE: present
```

这些接受项不注册唯一 canonical dynamic state。长期不可变产品仍是 Score release；动态状态由请求参数生成。

## 2. R2A-T04 唯一正式范围

R2A-T04 只读取 accepted R2A-T01 `score_data.duckdb`，使用 accepted T03 evaluator 审核冻结的 16-request panel。它不依赖其他数据产品。

Panel 包含：五级维度阶梯 `P → PA → PCA → PCAV → PCAVT`；PCAVT equal-q 的 1000/1500/2000/2500 bp；PCAVT confirmation K 的 2/3/5/7；以及分别只把 P/C/A/V/T 从 1500 bp 放宽到 2500 bp 的五个边际请求。D05 基线跨组复用，因此总数恰为 16。

正式审核只回答三类问题：

1. q、K、维度阶梯与单维边际放宽是否满足冻结的集合响应关系，并且整体响应非退化；
2. 每个 request 的 joint-ready、raw/confirmed、streak、confirmation、interval、duration、breadth、censoring、termination 与年度结构是否合理；
3. confirmed interval 的 `raw_start`、`confirmation`、`last_confirmed_end`、非空 `termination` 四类端点上的五维与十组件 accepted Score 分布是否完成精确对账。

本任务不选择最佳 q/K，不注册 canonical dynamic state，不生成预测标签或交易信号，不做回测或组合。

## 3. 冻结输入与 benchmark evidence

```text
score_release_id: pcavt-score-w120-v1-c7e04f11a2cd09aa
score_database_sha256: d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3
score_database_byte_size: 4255395840
panel_id: r2a_t04_representative_panel.v1
request_count: 16

benchmark_execution_head: 01bf7e12f0cb19a31c71689ada32f7a78f8aec75
benchmark_execution_Quality: 29658749232 / success
benchmark_receipt_sha256: c0fa81d08138cc0e2d5121be9affa52db11c3df36b0227fe420ca0c78ff6d369
benchmark_receipt_byte_size: 97485
benchmark_fingerprint: 049eeca525592e9a3d9659b3d0a3ce1eccc322f0289f283d0e9d8fe647e82231
selected_duckdb_threads: 4
benchmark_security_ids: 603345.SH, 603233.SH, 688220.SH, 300316.SZ
thread_benchmark_evidence_reused: true
reuse_basis: evaluator_request_output_and_fingerprint_core_byte_identical
thread_benchmark_rerun_required: false
```

以下核心文件必须继续与 benchmark execution HEAD 字节一致：

```text
src/r2a/r2a_t04_real_data_audit.py
src/r2a/r2a_t04_request_panel.py
src/r2a/r2a_t03_dynamic_evaluator.py
src/r2a/r2a_t03_output_contract.py
```

Revision 2 的 HEAD `9d3c2dab43a10b12931db921ef730db6e8552ff1` 与 revision 3 HEAD `21837edddfcc298b8539bcf9f71a1b7e016b6d47` 均在正式运行开始前被替代，未被使用，也未消费 formal attempt。Revision 3 的替代理由仅为独立 review CLI 未与 Score-only scope 对齐，不表示 Score release、evaluator、panel、benchmark 或 formal harness 失败。

## 4. 执行与审阅边界

正式运行获准后，16 个 full-universe request 必须严格串行，每次固定 800 只证券、完整 observation history、DuckDB threads=4。每个 request 必须先通过 accepted output validator，再抽取 metrics、response、interval inventory 和 Score endpoint structure，随后删除临时 request result DuckDB。禁止 resume、自动重跑、跳过 request、按日期切片、证券抽样或动态改变 threads。

正式结果只提交不超过 60 MiB 的 compact review bundle；完整 `audit_metrics.duckdb`、interval inventory 和 request result 只留在 local formal root。自动 recommendation 只能是 `continue_to_owner_result_review` 或 `blocked_evaluator_or_response_degeneracy`。Owner result review 必须保持 pending，直到用户独立审阅；不得创建 `DONE` 或允许 R2A-T05。

## 5. 当前两提交门禁

当前工作必须严格分两步：

1. `fix: align R2A-T04 independent review with Score scope`：修复独立 review CLI，并将 revision 3 标记为未使用即被替代；formal authorization 保持关闭，等待精确 repair HEAD Quality success。
2. `chore: reauthorize R2A-T04 after review repair`：仅在第一步 Quality 成功后创建 metadata-only revision 4，并把 `reviewed_harness_head` 绑定到精确 repair HEAD。

最终停止点必须是：

```text
R2A-T04 Score-only independent-review repair review
formal_run_authorized: false
formal_run_started: false
formal_run_consumed: false
full_universe_request_count: 0
R2A-T04_DONE: absent
R2A-T05_allowed_to_start: false
```

不得在同一步执行正式 16-request run、创建 formal output root、标记 PR Ready、合并 PR 或启动 R2A-T05。

## 6. R2A 后续路线

```text
T04 Score parameter response and interval-structure audit
T05 formal dynamic evaluation package
T06 no-lookahead replay
T07 protocol/release version registration
T08 stage acceptance and dynamic R3 handoff
```

只有 R2A-T08 被正式接受后，新的 PCAVT handoff 才能取代旧 R2-T08 handoff。旧 artifacts 不删除、不改写，只在新 handoff 中记录 superseded relationship。
