# R2A / PCAVT 研究交接

> 本文写给一个完全没有此前会话上下文的新会话。
>
> 阅读完本文后，应能准确知道：当前研究在做什么、EXP-A 已完成什么、R2A 为什么存在、现在停在哪里、下一步应做什么，以及哪些错误绝对不能重犯。

## 0. 当前状态快照

```text
repository: benzemaer/convergence-research
local_repository: D:\Code\convergence-research
current_branch: codex/r2a-t04-real-data-response-audit
remote_branch: origin/codex/r2a-t04-real-data-response-audit
R2A-T04 PR: #113 / Open / Draft
R2A-T04 implementation HEAD: 486bc9ca94ef4b93c8fff6c4e0a31775a17c8bc4
R2A-T04 implementation Quality: 29657511712 / success
R2A-T04 reviewed harness / repair / benchmark execution HEAD: 01bf7e12f0cb19a31c71689ada32f7a78f8aec75
R2A-T04 reviewed harness Quality: 29658749232 / success
R2A-T04 base_main_sha: a2c2ee0a7857fad86e4b8b14f6bf82f0d24a639a
R2A-T03 PR: #112 / merged
R2A-T03 merge commit: a2c2ee0a7857fad86e4b8b14f6bf82f0d24a639a
R2A-T03 PR head at creation: 3927b6e3b7791d01dc6f94f537cf572f3624b45b
R2A-T03 reviewed implementation head: 73b9b54ef76191fdbb44ffd7e4ae335601016466
R2A-T03 reviewed implementation Quality: 29653640376 / success
R2A-T03 base_main_sha: 83750e7d09188a2f69456bb4f3d7c966adc0ab0a
R2A-T02 PR: #110 / merged
base_main_sha: 83750e7d09188a2f69456bb4f3d7c966adc0ab0a
R2A-T01 PR: #109 / merged
reviewed_implementation_sha: 3f36357be9d469d7a9751eef79f368676d7ec97a
formal_execution_commit: 7c3fe76c575eb350a8e94d2f7534d123e865a64c
reviewed_execution_commit: 7c3fe76c575eb350a8e94d2f7534d123e865a64c
formal_execution_quality: 29640937790 / success
owner_execution_amendment_approved: true
successor_formal_run_required: false
implementation_review_status: passed
R2A stage doctrine: merged via PR #108
R2A-T01 protocol / implementation planning: completed
R2A-T01 implementation: completed and reviewed
R2A-T01_status: completed_accepted
formal_run_allowed: true
real_input_read_allowed: true
formal_run_status: completed_accepted
formal_run_attempts: 1 / 1
formal_authorization_consumed: true
additional_formal_run_allowed: false
formal_result_review_status: accepted
result_review_status: accepted
accepted_run_id: R2A-T01-20260718T103110891Z
accepted_score_release_id: pcavt-score-w120-v1-c7e04f11a2cd09aa
review_evidence_bundle_status: accepted
independent_review_execution_status: completed
independent_review_result: passed
independent_review_mismatch_count: 0
readme_advanced: true
R2A-T01_DONE: present
R2A-T02_status: completed_accepted
R2A-T02_started: true
protocol_review_status: accepted
reviewed_protocol_head: 6c3198a6fd270b81fbeb13649eda51f4222f89d6
dynamic_protocol_version: pcavt_dynamic_state_protocol.v1
bound_score_release_id: pcavt-score-w120-v1-c7e04f11a2cd09aa
protocol_package_status: accepted
real_score_data_read: false
dynamic_evaluator_implemented: accepted
dynamic_state_materialized: false
dynamic_protocol_accepted: true
dynamic_protocol_registered: false
R2A-T02_DONE: present
post_merge_test_contract_issue: stale_candidate_only_DONE_assertion
post_merge_test_contract_status: corrected_merged_via_PR_111
accepted_protocol_artifacts_modified: false
next_task: R2A-T04
R2A-T03_allowed_to_start: true
R2A-T03_started: true
R2A-T03_status: completed_accepted
implementation_review_status: accepted
reviewed_implementation_head: 73b9b54ef76191fdbb44ffd7e4ae335601016466
evaluator_version: r2a_t03_dynamic_evaluator.v1
output_schema_version: r2a_t03_dynamic_evaluation_output.v1
bound_dynamic_protocol_version: pcavt_dynamic_state_protocol.v1
dynamic_evaluator_accepted: true
evaluator_registered: false
output_schema_registered: false
R2A-T03_real_score_data_read: false
real_dynamic_evaluation_executed: false
dynamic_state_artifact_committed: false
R2A-T03_DONE: present
R2A-T04_allowed_to_start: true
R2A-T04_started: true
R2A-T04_status: execution_gate_repair_pending_review
reviewed_harness_head: 01bf7e12f0cb19a31c71689ada32f7a78f8aec75
formal_authorization_id: R2A-T04-REAL-AUDIT-AUTH-20260719
formal_run_authorized: false
authorization_effective_only_after_exact_head_quality_success: false
formal_run_started: false
formal_run_attempt_consumed: false
superseded_authorization_head: 17f6ec68d24f50e49c389afb439a413d7a7edb85
authorization_head_17f6ec68_status: superseded_before_real_input_smoke
superseded_reason: real_input_smoke_and_formal_execution_binding_incomplete
formal_run_started_under_superseded_authorization: false
formal_run_attempt_consumed_under_superseded_authorization: false
market_context_read_under_superseded_authorization: false
synthetic_end_to_end_smoke: passed_in_tests
previous_thread_benchmark_status: blocked
previous_thread_benchmark_error: thread_fingerprint_mismatch
previous_thread_benchmark_evidence_status: incomplete_no_receipt
previous_thread_benchmark_logical_output_difference_confirmed: false
previous_thread_benchmark_fingerprint_algorithm_suspect: arrow_record_batch_boundary_sensitive
thread_benchmark_status: passed
thread_benchmark_receipt_sha256: c0fa81d08138cc0e2d5121be9affa52db11c3df36b0227fe420ca0c78ff6d369
thread_benchmark_receipt_byte_size: 97485
thread_benchmark_fingerprint: 049eeca525592e9a3d9659b3d0a3ce1eccc322f0289f283d0e9d8fe647e82231
thread_benchmark_evidence_reused: true
reuse_basis: benchmark_core_evaluator_request_and_fingerprint_code_byte_identical
thread_benchmark_rerun_required: false
real_input_smoke_status: not_started
full_universe_request_concurrency: 1
full_universe_request_count: 0
duckdb_thread_count: 4
R2A-T04_preflight_score_data_read: true
R2A-T04_preflight_score_scope: four_security_full_history_thread_benchmark
R2A-T04_preflight_dynamic_evaluation_executed: true
R2A-T04_preflight_market_context_data_read: false
R2A-T04_formal_full_universe_score_data_read: false
R2A-T04_formal_dynamic_evaluation_executed: false
real_score_data_read: true
real_score_data_read_scope: four_security_full_history_thread_benchmark
market_context_data_read: false
owner_visual_review: not_started
R2A-T04_DONE: absent
R2A-T05_allowed_to_start: false
independent_output_validator: full_persisted_table_recomputation_accepted
implementation_review_blockers: 0
per_dimension_q_properties: P_and_A_independent_verified
A_layer_W120_score_contract_registered: true
canonical_PCAVT_score_release_registered: true
PCAVT_dynamic_state_created: false
```

阶段纲领已通过 PR #108 合并。R2A-T01 implementation 已在 Draft PR #109 完成审阅，
批准的 implementation SHA 为 `3f36357be9d469d7a9751eef79f368676d7ec97a`。唯一一次
formal run 已由 execution commit `7c3fe76c575eb350a8e94d2f7534d123e865a64c`
完成，validator、result analysis 与独立 review 均通过，正式和独立 mismatch 均为 0。
Owner 已接受 run `R2A-T01-20260718T103110891Z` 及 Score release
`pcavt-score-w120-v1-c7e04f11a2cd09aa`；accepted handoff 与 canonical `DONE` 已建立。
该验收只注册 canonical PCAVT W120 Score release 与 A-layer W120 Score contract，未创建
动态 PCAVT 状态。PR #109 已合并；R2A-T02 的 reviewed protocol head
`6c3198a6fd270b81fbeb13649eda51f4222f89d6` 已通过 Quality `29649468929` 和正式审阅，协议
closure 已建立 accepted handoff 与 canonical `DONE`。T02 未读取真实 Score data、未物化动态
状态；统一 protocol registration 仍留给 R2A-T07。PR #110 合并后发现的 stale candidate-only
DONE assertion 已由 PR #111 修正并合并，协议 acceptance 与 handoff/DONE 哈希链未失效。
R2A-T03 已从 PR #111 merge commit `83750e7d09188a2f69456bb4f3d7c966adc0ab0a`
启动；reviewed implementation `73b9b54ef76191fdbb44ffd7e4ae335601016466` 已通过 Quality
`29653640376` 与 implementation review，accepted handoff 和唯一 canonical `DONE` 已建立。
该接受不注册 evaluator/output schema version，也未读取真实 Score release、执行真实 dynamic
evaluation、选择最佳 q/K、完成价格图审核或创建动态状态产物。PR #112 已合并；R2A-T04 已在该
merge commit 上启动，implementation candidate 与 synthetic end-to-end smoke 已完成。此前 threads
preflight 已读取 accepted Score 的固定四证券完整历史并运行 evaluator；首次证据因旧 fingerprint 与缺失
receipt 只能记为 blocked、evidence incomplete。Reviewed repair head `01bf7e12...` 通过 Quality 后执行的
唯一 repaired benchmark 已通过，4/8/16 输出逻辑完全一致，并冻结 DuckDB threads=4。Authorization
HEAD `17f6ec68...` 因 real-input smoke 与 formal execution 绑定不完整，已在读取 market context 或消费
formal attempt 前废弃；当前只修复 execution gate，formal authorization 为 false。Market context 尚未读取，
real-input smoke 和唯一 full-universe formal run 均未开始。

主分支在建立 R2A 分支时的 HEAD 为：

```text
a2c2ee0a7857fad86e4b8b14f6bf82f0d24a639a
```

该提交是 R2A-T03 PR #112 的 merge commit，也是 R2A-T04 的唯一允许基线。

---

## 1. 我们正在做什么

项目原有研究已经完成到 `R2-T08`，并冻结过一套旧的收敛状态版本与 R3 handoff。

之后完成了独立的 `EXP-A` sidecar 研究，目标是寻找一个新的“价格—均线附件/贴合”维度 A。研究最终接受：

```text
A1: A1_LogBodyCenterToMACloudCenter_5_60
A2: A2_BodyCenterOutsideMACloudRate20_5_60
```

并按用户研究范围决策排除：

```text
A2b: A2b_BodyToMACloudGapMean20_5_60
```

现在正在执行新阶段 R2A 的首个 formal task：

```text
stage: R2A
research_object: PCAVT
first_task: R2A-T01
```

R2A 的总目标是建立以下分层体系，并最终形成支持动态请求的新 R3 handoff：

```text
immutable canonical PCAVT Score release
→ parameterized dynamic state evaluator
→ request-scoped daily states and intervals
```

但 R2A 的研究对象是加入 A 层后的新架构 PCAVT，而不是对旧 R2-T08 结果做小修补。

### 1.1 R2A 的核心边界

R2A 是一次独立的 full PCAVT restudy：

```text
R2A_inherits_R2_T08_frozen_results: false
R2A_inherits_R2_T08_state_versions: false
R2A_inherits_R2_T08_parameter_decisions: false
R2A_inherits_R2_T08_R3_handoff: false
```

允许参考或复用旧 R2/R0 已验证的代码模式、原始数据接口和成熟的严格过去分位算法。

不允许把旧 R2-T08 的以下内容直接当成 R2A 结论：

- frozen state versions；
- K/d/g 参数；
- q 向量；
- 固定逐日状态表；
- 固定事件区间；
- 唯一状态版本；
- R3 handoff。

“可以复用工程资产”与“继承旧研究结论”是两件不同的事，不能混淆。

PCAVT 是可选维度全集，不是固定嵌套顺序。`selected_dimensions` 是用户请求参数；未选择维度不参与联合条件，也不使用默认 q。R2A 长期物化的是 Score release，动态结果按请求生成，不选择唯一 q/K 组合，也不注册唯一 canonical state version。

---

## 2. 已经完成了什么

## 2.1 EXP-A 已正式关闭

EXP-A 研究已完成到已接受的 `EXP-A04`。

关键提交：

```text
EXP-A04 formal result commit:
11a99cb8a34814a0f3412d8012fdc0130074e436

EXP-A closure commit:
96d7da4c45d87089063521fd690f66a8a53c9a4b

EXP-A closure Quality:
29612587939 / success
```

PR #106 已 merge：

```text
PR: #106
merge commit: baf37f64eb59cf0a6fb96e2a42e23b25f0e8662a
```

随后 PR #107 只修复了一个既有 JSON 文件末尾多余换行：

```text
PR: #107
merge commit: 7e6da62235d823b4258d45f583d2918820f92496
```

PR #107 没有改变任何研究语义、配置字段、artifact 或运行行为。

## 2.2 EXP-A 最终 handoff 已提交

路径：

```text
data/generated/sidecar/exp_a/exp_a_final_research_handoff.json
```

该 handoff 冻结了：

```text
EXP-A status: completed_accepted
completed through: EXP-A04
accepted A raw components: [A1, A2]
excluded A raw components: [A2b]
A-layer Score contract defined: false
A-layer Score contract owner: R2A-T01
next stage: R2A
next task: R2A-T01
```

A2b 的排除语义必须保持为：

```text
user_research_scope_decision_after_A04
```

不得改写为：

```text
statistically redundant
invalid indicator
proven no increment
hard collision
```

EXP-A04 证明的是 24 个 A-vs-PCVT raw pair 中没有达到预注册 hard-collision gate；它没有证明 A2b 完全无效。A2b 是因为预期增量较低、与 P/C 关系最强且研究资源需要收缩，被用户直接排除。

## 2.3 EXP-A 的关键科学结论

### A2

A2 是三个候选中对 P/C/T/V 最低相关的候选，跨层增量信号最强。

它测量的是过去 20 日价格实体位于均线云外的频率，属于 persistence topology，而不是简单的高波动或低参与度代理。

### A1

A1 是瞬时 attachment anchor，测量当前实体中心与均线云中心的距离。

A1 与 P/C/T 有中等且较均衡的关系，但低尾身份仍明显不同，因此保留为独立的瞬时机制视角。

### A2b

A2b 与 P2、C1、C2、P1 的相关性最高，较多继承 P/C 尺度信息。它未被证明统计冗余，但用户决定不再投入后续研究资源。

最终组合为：

```text
A-layer raw components: A1 + A2
```

机制解释：

```text
A1 = instantaneous attachment
A2 = persistence topology
```

---

## 3. 本地 artifact 迁移已完成

原有三个待删除实体目录中的本地文件已迁入主仓库的 ignored archive。

归档根目录：

```text
D:\Code\convergence-research\data\external\local_research_archive\exp_a_to_r2a
```

迁移 manifest：

```text
D:\Code\convergence-research\data\external\local_research_archive\exp_a_to_r2a\migration-control\migration_manifest.json
```

manifest SHA256：

```text
7d0dbea61387d3bfdf02a9a3ce80429038418b22caa27c1a074b84599805d407
```

迁移 inventory：

```text
shared inputs: 164 files / 635,418,087 bytes
EXP-C01 inputs: 8 files / 4,488 bytes
EXP-C01 local-only: 10 files / 4,929 bytes
inventory comparison: passed
```

当前策略：

```text
archive inputs: retained
main worktree: retained
historical A01/A04 old-path replay: closed
```

### 3.1 重要后果

不要再依赖以下旧绝对路径或兼容 junction：

```text
D:\Code\convergence-research-inputs
D:\Code\convergence-research-exp-c01-inputs
D:\Code\convergence-research-exp-c01
```

旧历史 manifest 保持不可变，即使其中记录的绝对路径已经不再用于直接重放，也不得编辑旧 manifest 来适配新位置。

R2A 必须创建新的 authorized input manifest，并记录当前 archive 中实际使用文件的路径、SHA256、表名、row count、security count 和日期范围。

migration manifest、inventory CSV、大型 DuckDB、外部 authorized manifest 和 failure package 都是 local-only，不得提交 Git。

---

## 4. 当前停在哪里

R2A-T01 已正式接受并通过 PR #109 合并。R2A-T02 已从该 merge commit 启动，协议、配置、
请求 schema、canonicalization、identity 与 synthetic truth tables 已形成候选包，当前停在
protocol review。没有读取真实 Score DuckDB，也没有生产 evaluator 或动态结果。

准确状态：

```text
branch: codex/r2a-t02-dynamic-state-protocol
remote branch: origin/codex/r2a-t02-dynamic-state-protocol
R2A-T02 PR: #110 / merged
branch base: 34eee561218141d64a2e347e532d88c0fb09c33c
R2A-T01 PR: #109 / merged
reviewed implementation SHA: 3f36357be9d469d7a9751eef79f368676d7ec97a
formal execution commit: 7c3fe76c575eb350a8e94d2f7534d123e865a64c
reviewed execution commit: 7c3fe76c575eb350a8e94d2f7534d123e865a64c
formal execution Quality: 29640937790 / success
owner execution amendment approved: true
successor formal run required: false
implementation review status: passed
R2A stage doctrine: merged via PR #108
R2A-T01 protocol / implementation planning: completed
R2A-T01 implementation: completed and reviewed
R2A-T01 status: completed_accepted
formal_run_allowed: true
real_input_read_allowed: true
formal_run_status: completed_accepted
formal_run_attempts: 1 / 1
formal_authorization_consumed: true
additional_formal_run_allowed: false
formal_result_review_status: accepted
result_review_status: accepted
accepted_run_id: R2A-T01-20260718T103110891Z
accepted_score_release_id: pcavt-score-w120-v1-c7e04f11a2cd09aa
review_evidence_bundle_status: accepted
independent_review_execution_status: completed
independent_review_result: passed
independent_review_mismatch_count: 0
readme_advanced: true
R2A-T01_DONE: present
R2A-T02_status: completed_accepted
R2A-T02_started: true
protocol_review_status: accepted
reviewed_protocol_head: 6c3198a6fd270b81fbeb13649eda51f4222f89d6
dynamic_protocol_version: pcavt_dynamic_state_protocol.v1
bound_score_release_id: pcavt-score-w120-v1-c7e04f11a2cd09aa
protocol_package_status: accepted
real_score_data_read: false
dynamic_evaluator_implemented: accepted
dynamic_state_materialized: false
dynamic_protocol_accepted: true
dynamic_protocol_registered: false
R2A-T02_DONE: present
post_merge_test_contract_issue: stale_candidate_only_DONE_assertion
post_merge_test_contract_status: corrected_merged_via_PR_111
accepted_protocol_artifacts_modified: false
next_task: R2A-T04
R2A-T03_allowed_to_start: true
R2A-T03_started: true
R2A-T03_status: completed_accepted
implementation_review_status: accepted
reviewed_implementation_head: 73b9b54ef76191fdbb44ffd7e4ae335601016466
evaluator_version: r2a_t03_dynamic_evaluator.v1
output_schema_version: r2a_t03_dynamic_evaluation_output.v1
bound_dynamic_protocol_version: pcavt_dynamic_state_protocol.v1
dynamic_evaluator_accepted: true
evaluator_registered: false
output_schema_registered: false
R2A-T03_real_score_data_read: false
real_dynamic_evaluation_executed: false
dynamic_state_artifact_committed: false
R2A-T03_DONE: present
R2A-T04_allowed_to_start: true
R2A-T04_started: true
R2A-T04_status: execution_gate_repair_pending_review
R2A-T04_base_main_sha: a2c2ee0a7857fad86e4b8b14f6bf82f0d24a639a
reviewed_harness_head: 01bf7e12f0cb19a31c71689ada32f7a78f8aec75
formal_authorization_id: R2A-T04-REAL-AUDIT-AUTH-20260719
formal_run_authorized: false
authorization_effective_only_after_exact_head_quality_success: false
formal_run_started: false
formal_run_attempt_consumed: false
superseded_authorization_head: 17f6ec68d24f50e49c389afb439a413d7a7edb85
authorization_head_17f6ec68_status: superseded_before_real_input_smoke
superseded_reason: real_input_smoke_and_formal_execution_binding_incomplete
formal_run_started_under_superseded_authorization: false
formal_run_attempt_consumed_under_superseded_authorization: false
market_context_read_under_superseded_authorization: false
synthetic_end_to_end_smoke: passed_in_tests
previous_thread_benchmark_status: blocked
previous_thread_benchmark_error: thread_fingerprint_mismatch
previous_thread_benchmark_evidence_status: incomplete_no_receipt
previous_thread_benchmark_logical_output_difference_confirmed: false
previous_thread_benchmark_fingerprint_algorithm_suspect: arrow_record_batch_boundary_sensitive
thread_benchmark_status: passed
thread_benchmark_receipt_sha256: c0fa81d08138cc0e2d5121be9affa52db11c3df36b0227fe420ca0c78ff6d369
thread_benchmark_receipt_byte_size: 97485
thread_benchmark_fingerprint: 049eeca525592e9a3d9659b3d0a3ce1eccc322f0289f283d0e9d8fe647e82231
thread_benchmark_evidence_reused: true
reuse_basis: benchmark_core_evaluator_request_and_fingerprint_code_byte_identical
thread_benchmark_rerun_required: false
real_input_smoke_status: not_started
full_universe_request_concurrency: 1
full_universe_request_count: 0
duckdb_thread_count: 4
R2A-T04_preflight_score_data_read: true
R2A-T04_preflight_score_scope: four_security_full_history_thread_benchmark
R2A-T04_preflight_dynamic_evaluation_executed: true
R2A-T04_preflight_market_context_data_read: false
R2A-T04_formal_full_universe_score_data_read: false
R2A-T04_formal_dynamic_evaluation_executed: false
real_score_data_read: true
real_score_data_read_scope: four_security_full_history_thread_benchmark
market_context_data_read: false
owner_visual_review: not_started
R2A-T04_DONE: absent
R2A-T05_allowed_to_start: false
independent_output_validator: full_persisted_table_recomputation_accepted
implementation_review_blockers: 0
per_dimension_q_properties: P_and_A_independent_verified
A_layer_W120_score_contract_registered: true
canonical_PCAVT_score_release_registered: true
PCAVT_dynamic_state_created: false
```

Formal run ID 为 `R2A-T01-20260718T103110891Z`，Score release ID 为
`pcavt-score-w120-v1-c7e04f11a2cd09aa`。唯一一次运行已消费，不得重跑。正式 package
的 validator status 与 analysis status 均为 `passed`，release recommendation 为
`publish_candidate`；独立审阅也已通过，Owner 随后正式接受该唯一 run 与 release。
审阅证据位于
`data/generated/r2a/r2a_t01/R2A-T01-20260718T103110891Z/formal-review/`：四个紧凑
formal 文件保持原始字节，另含 summary、30-table review extract 及两份 review manifest。
该目录是派生审阅证据，不是新的 formal release，也不改变原 package、run attempt 或 gate。

---

## 5. R2A-T01 的唯一目标

R2A-T01 应当完成两件紧密相关、但必须按顺序执行的工作：

1. 冻结 A-layer W120 Score contract；
2. 在该 contract 通过 implementation review 后，物化新的 canonical PCAVT Score artifact。

R2A-T01 不研究 q、确认天数或区间。

### 5.1 已达成一致的 A-layer Score contract 方向

Active components：

```text
A1_LogBodyCenterToMACloudCenter_5_60
A2_BodyCenterOutsideMACloudRate20_5_60
```

唯一窗口：

```text
W = 120
```

禁止计算：

```text
W = 250
W = 500
```

对同一 `security_id`、同一 `indicator_id`，当前 observation 的参考集合是：

```text
当前 observation_sequence 之前
最近 120 个 validity_status=valid
且 raw_value finite 的 observation
```

当前值不进入参考集合。

Tie method：

```text
midrank
```

设过去 120 个 eligible values 中：

```text
N_less  = raw_value < current raw_value 的数量
N_equal = raw_value = current raw_value 的数量
```

则：

```text
percentile = (N_less + 0.5 * N_equal) / 120
score      = 1 - percentile
```

两个 raw indicator 都是越低越贴合，因此 Score 越高表示 attachment 越强。

组件分数：

```text
A1_Score_W120
A2_Score_W120
```

Layer 分数：

```text
A_Score_W120 = mean(A1_Score_W120, A2_Score_W120)
A_Min_W120   = min(A1_Score_W120, A2_Score_W120)
```

权重固定：

```text
A1 = 0.5
A2 = 0.5
```

只有 A1、A2 均 eligible 时，A-layer Score 和 A-Min 才能生成。禁止单组件 fallback、填零、前向填充、缩短窗口或忽略缺失组件。

### 5.2 Score 与 State 必须分离

R2A-T01 只定义连续 Score，不定义：

```text
q threshold
raw state
confirmation streak
confirmed state
interval
exit rule
PCAVT state version
```

W=120 决定分数如何计算。

q、连续天数和区间规则决定如何从分数生成状态。

这两层绝对不能在同一个 contract 中混为一谈。

### 5.3 R2A-T01 的最终数据目标

目标是得到 800 只股票、W=120 条件下新的 canonical PCAVT 各维度连续分数：

```text
P Score
C Score
A Score
V Score
T Score
```

新 artifact 必须拥有 R2A 自己的：

```text
run_id
input manifest
input hashes
schema
logical table names
primary keys
row counts
security count
date range
validator result
artifact manifest
```

不能把旧 R2-T08 state outputs 改名后当成新 PCAVT Score artifact。

---

## 6. R2A-T01 已冻结的工程决策边界

R2A-T01 protocol、implementation 与 implementation review 已完成。以下工程边界已由
reviewed implementation 冻结；formal authorization 不得改写其科学或工程逻辑。

## 6.1 P/C/V/T Score 的来源

Reviewed implementation 已冻结采用方案 A。方案 B 仅保留为历史设计对照，不是当前
formal execution 路线：

### 方案 A：复用已接受的 R0-T05 W120 Score rows

前提：

- independently validate bytes、schema、semantic hashes、row counts；
- 只取 W120；
- 不消费旧 R2 状态或 interval；
- 在 R2A 中创建新的统一 PCAVT binding 和 artifact identity。

优点：避免重复计算成熟的 P/C/V/T Score。

### 方案 B：从 authoritative raw metrics 重新计算 P/C/V/T W120 Score

优点：所有五层在同一次 R2A materialization 中生成，lineage 更统一。

缺点：计算成本和实现范围更大，也可能无意义地重做已验证逻辑。

当前冻结结论：

> 可以复用已接受的 P/C/V/T W120 Score artifact，但必须在 R2A-T01 中独立验证并重新建立 canonical PCAVT Score interface；A Score 必须由 accepted A1/A2 raw 新计算。不要继承任何 R2-T08 state result。

Formal execution 必须复用并独立验证 accepted P/C/V/T W120 Score rows；不得在授权提交
中切换为方案 B，也不得继承 R2-T08 state result。

## 6.2 PCAVT 维度顺序和命名

用户当前目标名称为：

```text
PCAVT
```

不要随意写成：

```text
PCATV
PCTAV
PCVT+A
```

旧代码和旧 artifact 中 dimension order、变量命名与缩写并不总是直观一致。R2A-T01/T02 必须在 registry 或 protocol 中显式声明：

```text
dimension IDs
dimension order
component registry
output field names
selected_dimensions 的请求表示与 canonical normalization（后续 T02）
```

绝对不能只根据旧变量名推断顺序。

## 6.3 Formal 800-security gate 与 synthetic tests

正式物化必须要求：

```text
security_count = 800
calendar years = 2016..2026
```

但不要把“必须恰好 800”硬编码到通用单序列 Score 函数，导致小型 synthetic unit tests 无法运行。

正确分层：

```text
generic score engine:
可处理任意 synthetic security count

formal runner / formal validator:
强制 security_count = 800
```

---

## 7. R2A 动态状态任务路线

所有 task 使用独立的 `R2A-*` identity，路线与动态阶段纲领一致：

### R2A-T01：canonical PCAVT Score release

冻结 A-layer W120 Score contract，并物化不可变 canonical PCAVT Score release。T01 严格不包含 q、K、raw/confirmed state 或 interval。

### R2A-T02：dynamic state protocol freeze

冻结 `selected_dimensions`、`q_by_dimension`、`confirmation_k`、complete-case validity、raw state、连续确认、区间、zero-event 与请求 ID/hash 协议。T02 不选择唯一 q/K 组合。

### R2A-T03：parameterized evaluator implementation

实现从 Score release 到 request-scoped daily states 和 intervals 的参数化 evaluator，并覆盖 q/K 响应、未选维度隔离、无回填、invalid interruption 与 zero-event 等测试边界。

### R2A-T04：real-data parameter-response and scientific audit

在有独立授权后，对代表性动态请求执行真实数据参数响应与科学合理性审核。目标是确认允许参数域内响应合理，而不是挑选或冻结唯一参数。

### R2A-T05：formal dynamic evaluation package

为明确的动态请求建立可复现、不可变的 formal evaluation package；长期 canonical lineage 仍是 Score release，动态结果保持 request-scoped。

### R2A-T06：no-lookahead replay

验证 strict-past、available-time、逐日 replay、缺失 observation interruption 与并行一致性。

### R2A-T07：protocol/release version registration

注册 Score release、dimension definition、dynamic protocol、engine、schema 与 artifact hashes；不注册唯一 canonical state version。

### R2A-T08：stage acceptance and dynamic R3 handoff

完成阶段验收并形成提供动态状态查询接口的新 R3 handoff，而不是交付单一固定事件表。

只有 R2A-T08 被正式接受后，新的 PCAVT handoff 才能取代旧 R2-T08 handoff，成为新的 R3 入口。

旧 R2-T08 artifacts 不删除、不改写，只在新 handoff 中明确 superseded relationship。

---

## 8. 动态请求参数边界

PCAVT 是可选维度全集，不是固定嵌套顺序。用户通过 `selected_dimensions` 指定本次请求包含哪些维度；未选择维度不参与联合条件，也不使用默认 q。

每个已选择维度独立使用：

```text
qD ∈ {0.10, 0.15, 0.20, 0.25}
```

当前 Score 定义为 `1 - percentile`，因此维度主阈值为 `Score >= 1 - qD`。弱组件门固定为：

```text
weak_delta = 0.10
dimension_min >= 1 - qD - weak_delta
```

连续确认参数为：

```text
confirmation_k ∈ {2,3,4,5,6,7}
```

首版不使用 d/g、gap tolerance、退出延迟或区间自动合并。R2A 不选择唯一 q/K 组合，不注册唯一 canonical state version；长期物化的是 Score release，动态 daily states 和 intervals 按请求生成。

---

## 9. 新会话的第一步

新会话开始后，先做只读核对，不要直接写代码。

建议核对：

```powershell
cd D:\Code\convergence-research

git status --short
git branch --show-current
git rev-parse HEAD
git fetch origin --prune
git rev-parse origin/codex/r2a-pcavt-research
git log --oneline --decorate -5
```

确认：

```text
branch = codex/r2a-pcavt-research
local branch = remote branch
worktree clean
base main ancestor includes 7e6da62235d823b4258d45f583d2918820f92496
PR #108 is Draft
PR head matches the current review snapshot or an explicitly reviewed successor commit
```

然后读取：

```text
HANDOFF.md
data/generated/sidecar/exp_a/exp_a_final_research_handoff.json
docs/experiments/sidecar/README.md
R0-T05 strict-past Score contract/materializer
R2-T01..R2-T08 task route and accepted artifacts
```

下一步只允许做：

```text
R2A-T01 formal authorization commit
精确 execution commit Quality
一次已授权 formal run、validator 与实际 result analysis
```

Implementation review 与独立 formal 授权均已完成；仍必须先通过 execution commit Quality，
并只读取 manifest 精确绑定的 accepted inputs。不得扩大到第二次运行或修改 contract 后继续。

---

## 10. 绝对不要再踩的坑

## 10.1 不要过度治理

此前出现过为很小风险提出大规模 manifest lineage 扩展、十项运行时 hash 等方案，用户明确认为这是矫枉过正。

原则：

```text
只为真实风险增加门禁
不为形式完整性堆叠机制
不重复已有独立验证
不扩大用户明确限定的 scope
```

新会话不要重新提出已经撤回的：

```text
manifest lineage expansion
ten-input runtime hashing
preliminary manifest architecture
无必要的多层 validator
```

## 10.2 不要把 Score 与 State 混在一起

错误做法：

```text
在 R2A-T01 同时定义 W、任意 q、confirmation_k 和区间结束
```

正确做法：

```text
R2A-T01: Score
R2A-T02+: State / confirmation / interval
```

## 10.3 不要继承 R2-T08 研究结论

可以参考旧代码，但不能默认复用旧：

```text
旧固定确认天数
旧 d/g 组合
旧固定维度阈值
旧固定状态版本
R3 handoff
```

R2A 是 full restudy，不是旧版本加一列 A。

## 10.4 不要重新研究 A2b

A2b 已由用户直接排除。

禁止：

```text
A2b challenger test
A2-vs-A2b dominance gate
A2b score materialization
A1+A2b / A2+A2b combination search
```

同时禁止虚构结论“已证明 A2b 统计冗余”。

## 10.5 不要在 EXP-A sidecar 中补做 Score contract

EXP-A 已关闭。

A-layer Score contract 的 owner 是：

```text
R2A-T01
```

不要再创建 EXP-A05 或在 `src/sidecar/exp_a*` 下继续扩展正式 Score 研究。

## 10.6 不要计算 W250/W500

A-layer 已定调：

```text
W = 120 only
```

不要因为旧 R0-T05 支持 120/250/500，就自动继承三个窗口。

## 10.7 不要使用横截面分位替代 strict-past percentile

A-layer Score 口径是：

```text
same security
same indicator
last 120 valid finite historical observations
current excluded
midrank
score = 1 - percentile
```

禁止：

```text
cross-sectional rank
current included
calendar-day window
last 120 physical rows
future rows
dense rank
random tie breaking
```

## 10.8 不要把 invalid row 放入历史窗口

当前 row invalid 时：

- 当前不生成 score；
- 该 row 也不得进入后续 valid history。

不能把 unknown/diagnostic/blocked 当成低分、零分或有效历史。

## 10.9 不要复用旧 absolute path

历史 A01/A04 旧路径回放已关闭。

不要假设旧目录或 junction 仍可用。

R2A 必须用 archive 的实际路径创建新 manifest。不要编辑旧历史 manifest。

## 10.10 不要提交大型本地 artifacts

禁止提交：

```text
*.duckdb
*.parquet
data/external/**
migration manifest
inventory CSV
external authorized manifest
failure package
logs
```

Git 只提交 compact contract、schema、code、tests、evidence summary 和小型 result package。

## 10.11 不要混用阶段/门禁标识符

R2-T08 历史结果中已经存在类似 `R2A01...R2A08` 的 gate ID。

新阶段 task ID 必须使用：

```text
R2A-T01
R2A-T02
...
```

新 gate 建议使用：

```text
R2A-T01-G01
R2A-T01-G02
...
```

不要创建裸 `R2A01` task，避免与历史 gate 冲突。

## 10.12 不要自动推进到 PR、formal 或下一阶段

当前 R2A-T01 Draft PR 是 #109；保持 Draft，不得自行标记 Ready for review 或合并。

任何 implementation 完成后都应停在 implementation review；formal 必须经过独立授权。

任何 formal result 完成后都应停在 formal-result review；不得自动接受、自动注册 A-layer 或自动创建 PCAVT。

---

## 11. 重要引用

### Git / PR

```text
EXP-A04 result commit:
11a99cb8a34814a0f3412d8012fdc0130074e436

EXP-A closure commit:
96d7da4c45d87089063521fd690f66a8a53c9a4b

PR #106 merge:
baf37f64eb59cf0a6fb96e2a42e23b25f0e8662a

PR #108 document gate merge / R2A-T01 base main:
2e623d0e207be2568f235f659c83a794f3b56ffb
```

### EXP-A handoff

```text
data/generated/sidecar/exp_a/exp_a_final_research_handoff.json
```

### Local archive

```text
D:\Code\convergence-research\data\external\local_research_archive\exp_a_to_r2a
```

### Migration manifest

```text
D:\Code\convergence-research\data\external\local_research_archive\exp_a_to_r2a\migration-control\migration_manifest.json
SHA256: 7d0dbea61387d3bfdf02a9a3ce80429038418b22caa27c1a074b84599805d407
```

---

## 12. 最简接手结论

```text
EXP-A 已结束。
A1+A2 已选定。
A2b 已按研究范围排除。
A-layer W120 Score contract 已在 reviewed implementation 中定义。
R2A 是 PCAVT 的独立完整重研，不继承 R2-T08 结果。
R2A-T01 Draft PR #109 的 implementation review 已通过；reviewed implementation SHA 为 3f36357be9d469d7a9751eef79f368676d7ec97a。
R2A-T01 当前为 completed_accepted；formal_run_status=completed_accepted，formal_result_review_status=accepted，result_review_status=accepted。
唯一 formal execution commit 为 7c3fe76c575eb350a8e94d2f7534d123e865a64c；Quality 29640937790 success；不得再次运行。
Owner 已接受 run R2A-T01-20260718T103110891Z 与 release pcavt-score-w120-v1-c7e04f11a2cd09aa；review_evidence_bundle_status=accepted；DONE=present。
independent_review_execution_status=completed；independent_review_result=passed；independent_review_mismatch_count=0。
A_layer_W120_score_contract_registered=true；canonical_PCAVT_score_release_registered=true；PCAVT_dynamic_state_created=false。
长期目标是 immutable canonical PCAVT Score release → parameterized dynamic state evaluator → request-scoped daily states and intervals。
R2A-T02_status=completed_accepted；protocol_review_status=accepted；dynamic_protocol_version=pcavt_dynamic_state_protocol.v1。
reviewed_protocol_head=6c3198a6fd270b81fbeb13649eda51f4222f89d6；protocol_package_status=accepted；real_score_data_read=false。
dynamic_protocol_accepted=true；dynamic_protocol_registered=false；PCAVT_dynamic_state_created=false。
dynamic_evaluator_implemented=accepted；dynamic_state_materialized=false；R2A-T02_DONE=present。
post_merge_test_contract_issue=stale_candidate_only_DONE_assertion；post_merge_test_contract_status=corrected_merged_via_PR_111。
accepted_protocol_artifacts_modified=false；R2A-T03_allowed_to_start=true；R2A-T03_started=true。
R2A-T03_status=completed_accepted；implementation_review_status=accepted；
reviewed_implementation_head=73b9b54ef76191fdbb44ffd7e4ae335601016466；evaluator_version=r2a_t03_dynamic_evaluator.v1；
output_schema_version=r2a_t03_dynamic_evaluation_output.v1；dynamic_evaluator_accepted=true；
evaluator_registered=false；output_schema_registered=false；real_score_data_read=false；
real_dynamic_evaluation_executed=false；dynamic_state_artifact_committed=false；PCAVT_dynamic_state_created=false；
R2A-T03_DONE=present；next_task=R2A-T04；R2A-T04_allowed_to_start=true；R2A-T04_started=true。
R2A-T04_status=execution_gate_repair_pending_review；
reviewed_harness_head=01bf7e12f0cb19a31c71689ada32f7a78f8aec75；
formal_authorization_id=R2A-T04-REAL-AUDIT-AUTH-20260719；
formal_run_authorized=false；
authorization_effective_only_after_exact_head_quality_success=false；formal_run_started=false；
formal_run_attempt_consumed=false；synthetic_end_to_end_smoke=passed_in_tests；
superseded_authorization_head=17f6ec68d24f50e49c389afb439a413d7a7edb85；
authorization_head_17f6ec68_status=superseded_before_real_input_smoke；
superseded_reason=real_input_smoke_and_formal_execution_binding_incomplete；
formal_run_started_under_superseded_authorization=false；
formal_run_attempt_consumed_under_superseded_authorization=false；
market_context_read_under_superseded_authorization=false；
previous_thread_benchmark_status=blocked；previous_thread_benchmark_error=thread_fingerprint_mismatch；
previous_thread_benchmark_evidence_status=incomplete_no_receipt；
previous_thread_benchmark_logical_output_difference_confirmed=false；
previous_thread_benchmark_fingerprint_algorithm_suspect=arrow_record_batch_boundary_sensitive；
thread_benchmark_status=passed；
thread_benchmark_receipt_sha256=c0fa81d08138cc0e2d5121be9affa52db11c3df36b0227fe420ca0c78ff6d369；
thread_benchmark_receipt_byte_size=97485；
thread_benchmark_fingerprint=049eeca525592e9a3d9659b3d0a3ce1eccc322f0289f283d0e9d8fe647e82231；
thread_benchmark_evidence_reused=true；
reuse_basis=benchmark_core_evaluator_request_and_fingerprint_code_byte_identical；
thread_benchmark_rerun_required=false；
real_input_smoke_status=not_started；full_universe_request_concurrency=1；full_universe_request_count=0；
duckdb_thread_count=4；
R2A-T04_preflight_score_data_read=true；
R2A-T04_preflight_score_scope=four_security_full_history_thread_benchmark；
R2A-T04_preflight_dynamic_evaluation_executed=true；R2A-T04_preflight_market_context_data_read=false；
R2A-T04_formal_full_universe_score_data_read=false；R2A-T04_formal_dynamic_evaluation_executed=false；
real_score_data_read=true；real_score_data_read_scope=four_security_full_history_thread_benchmark；
market_context_data_read=false；
owner_visual_review=not_started；R2A-T04_DONE=absent；R2A-T05_allowed_to_start=false。
当前停止点是 R2A-T04 execution-gate repair review。首次 benchmark 的 blocked evidence 不足以确认逻辑
差异；唯一 repaired benchmark 已证明 4/8/16 输出逻辑一致并选择 threads=4。Authorization HEAD
17f6ec68... 因执行绑定不完整已在 real-input smoke 前废弃；尚未读取 market context、执行 real-input smoke、
消费 formal attempt 或执行任何 full-universe request。
```
