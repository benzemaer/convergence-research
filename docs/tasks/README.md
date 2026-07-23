# 任务记录与阶段索引

本目录保存可审核任务契约，并维护当前阶段任务索引。任务记录不是决策记录、运行授权、
数据 manifest 或研究证据，不得替代 G0–G7 门禁。

每个任务必须明确目标、非目标、输入、输出、验收标准、失败状态和回退方式。任务关闭后
仍保留记录；实质变更创建新版本，不覆盖原记录。

## 使用规则

- 每进入一个新阶段，先明确阶段目标、输入、输出、非目标和完成标准。
- 每个 task 都必须挂在阶段索引下。
- 每个 PR 只实现一个 task。
- task 完成后更新本索引状态，不在 PR 内临时扩大范围。
- 当只剩标题级 task、或下一步将引入新的数据源/运行/研究范围时，先确认下一个 PR 边界，再继续实现。

## 当前阶段

```text
current_stage: R2
current_task: R2-T08 R2 阶段验收与 R3 交接
# Historical route marker retained for R1 contract replay; it is not the current task.
historical_current_task: R2-T04 Hard gate、Pareto 推荐、用户决策与 freeze plan
next_planned_task: R3-T01 释放定义（尚未授权）
historical_next_planned_task: R2-T05 canonical 日度状态与事件区间物化
R1-T04 completed via PR #80
R1-T05 completed via PR #81
R1-T06 completed via PR #82
R1-T07 completed via PR #83
R1-T08 completed via PR #84
R1-T09 completed via PR #85
R1-T14-01_decision_status: q_vector_materialization_request
R1-T14-02_status: completed
R1-T14-02_scientific_review_status: passed
R1-T14-02_independent_review_status: passed
R0_q_vector_materialization_request_status: fulfilled
R0_q_vector_materialization_task_id: R0-T15
R0_q_vector_materialization_allowed_to_start: false
R0_q_vector_materialization_status: completed
R1-T05_allowed_to_start: true
R1-T06_allowed_to_start: true
R1-T07_allowed_to_start: true
R1-T08_allowed_to_start: true
R1-T09_allowed_to_start: true
R1-T14-01_allowed_to_start: true
R1-T14-02_allowed_to_start: false
R1-T10_allowed_to_start: true
R1-T10_status: completed
R1-T10_scientific_review_status: passed
R1-T10_independent_review_status: passed
R1-T11_allowed_to_start: false
R1-T12_allowed_to_start: false
R1-T13_allowed_to_start: false
R2_allowed_to_start: true
R2-T01_allowed_to_start: true
R2-T01_status: completed
R2-T01_scientific_review_status: passed
R2-T01_independent_review_status: passed
R2-T02_status: completed
R2-T02_scientific_review_status: passed
R2-T02_independent_review_status: passed
R2-T02_repository_final_gate_status: passed
R2-T02_formal_task_completed: true
R2-T02_allowed_to_start: false
R2-T03_allowed_to_start: false
R2-T03_initial_startup_status: blocked_missing_authoritative_t02_final_gate_binding
R2-T03_resolution_status: resolved
R2-T03_startup_status: passed
R2-T03_resolved_by: r2_t02_repository_final_gate_handoff.json
R2-T03_status: completed
R2-T03_historical_run_id: R2-T03-20260712T1205Z
R2-T03_historical_run_status: author_draft_invalidated_pending_successor_run
R2-T03_formal_rerun_executed: false
R2-T03_final_execution_mode: promoted_preserved_fact_run_plus_current_postscan
R2-T03_availability_adapter_status: resolved_research_policy
R2-T03_expected_key_adapter_status: resolved_upstream_adapter
R2-T03_interval_reconciliation_adapter_status: resolved_upstream_adapter
R2-T03_scientific_review_scope: implementation_only
R2-T03_formal_task_completed: true
R2-T03_scientific_review_status: passed
R2-T03_repository_final_gate_status: passed
R2-T03_repository_final_gate_binding: r2_t03_repository_final_gate_handoff.json
R2-T04_allowed_to_start: true
R2-T04_status: completed
R2-T04_scientific_review_status: passed
R2-T04_repository_final_gate_status: passed
R2-T04_repository_final_gate_binding: r2_t04_repository_final_gate_handoff.json
R2-T04_formal_task_completed: true
R2-T05_allowed_to_start: true
R2-T05_status: completed_via_PR_97_merged_pr_direct_binding
R2-T05_scientific_review_status: passed
R2-T05_repository_final_gate_status: passed
R2-T05_startup_status: passed
R2-T05_formal_run_executed: true
R2-T05_formal_task_completed: true
R2-T05_authoritative_run: R2-T05-20260713T154957Z
R2-T05_merge_commit: db0a44e481b8d7389b3e72f4a2425ad89bf766ef
R2-T05_final_pr_head: 9ab4ddc77fce8c662e2159ad3f541fe354640b09
R2-T05_reviewed_head: d3a18236e2c60775c0248642b3fadec2007afd90
R2-T05_scientific_review_id: 4686515222
R2-T05_execution_commit: a35bea847f8f7b923c1196f1341be32494f394ef
R2-T05_artifact_commit: 1f9c0538138e829904976308e6c012f67aa249c4
R2-T06_allowed_to_start: true
R2-T06_status: completed_via_PR_98_merged_pr_direct_binding
R2-T06_scientific_review_status: passed
R2-T06_repository_final_gate_status: passed
R2-T06_startup_status: passed
R2-T06_formal_run_executed: true
R2-T06_formal_task_completed: true
R2-T07_allowed_to_start: true
R2-T07_status: completed_via_PR_99_merged_pr_direct_binding
R2-T07_scientific_review_status: passed
R2-T07_startup_status: passed_merged_pr_direct_binding
R2-T07_historical_run_id: R2-T07-20260714T015043Z
R2-T07_historical_run_status: superseded_author_draft
R2-T07_formal_run_successor_pending: false
R2-T07_formal_run_executed: true
R2-T07_formal_task_completed: true
R2-T07_authoritative_run: R2-T07-20260714T034053Z
R2-T07_reviewed_head: 6b78f79515475b80e133a1a0df251ce4ff5b4f88
R2-T07_scientific_review_id: 4690778899
R2-T07_merge_commit: 90aba54a54474185fa258afd605e24934bd9a864
R2-T08_allowed_to_start: true
R2-T08_status: author_package_complete_pending_independent_scientific_review
R2-T08_formal_run_executed: true
R2-T08_formal_task_completed: false
R2_evidence_chain_status: passed_pending_T08_scientific_review_and_merge
R3_handoff_eligible: true
R3_allowed_to_start: false
R2A-T01_status: completed_accepted
implementation_review_status: passed
reviewed_implementation_sha: 3f36357be9d469d7a9751eef79f368676d7ec97a
formal_execution_commit: 7c3fe76c575eb350a8e94d2f7534d123e865a64c
reviewed_execution_commit: 7c3fe76c575eb350a8e94d2f7534d123e865a64c
formal_execution_quality: 29640937790 / success
owner_execution_amendment_approved: true
successor_formal_run_required: false
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
A_layer_W120_score_contract_registered: true
canonical_PCAVT_score_release_registered: true
PCAVT_dynamic_state_created: false
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
R2A-T03_base_main_sha: 83750e7d09188a2f69456bb4f3d7c966adc0ab0a
implementation_review_status: accepted
reviewed_implementation_head: 73b9b54ef76191fdbb44ffd7e4ae335601016466
reviewed_implementation_Quality: 29653640376 / success
evaluator_version: r2a_t03_dynamic_evaluator.v1
output_schema_version: r2a_t03_dynamic_evaluation_output.v1
bound_dynamic_protocol_version: pcavt_dynamic_state_protocol.v1
dynamic_evaluator_accepted: true
evaluator_registered: false
output_schema_registered: false
real_score_data_read: false
real_dynamic_evaluation_executed: false
dynamic_state_artifact_committed: false
R2A-T03_DONE: present
R2A-T04_allowed_to_start: true
R2A-T04_started: true
R2A-T04_scope_id: r2a_t04_ca_q10_q15_q20_q25_k5_response_audit.v1
R2A-T04_panel_id: r2a_t04_ca_four_q_k5_panel.v1
R2A-T04_status: completed_accepted
R2A-T04_base_main_sha: a2c2ee0a7857fad86e4b8b14f6bf82f0d24a639a
benchmark_execution_head: 01bf7e12f0cb19a31c71689ada32f7a78f8aec75
benchmark_execution_Quality: 29658749232 / success
formal_authorization_id: R2A-T04-CA-FOUR-Q-AUDIT-AUTH-20260720-R6
authorization_revision: 6
reviewed_harness_head: 277b5c3d6433caee05d3d0156318f9b386eb316a
reviewed_harness_Quality: 29707568838 / success
formal_run_authorized: false
authorization_effective_only_after_exact_head_quality_success: true
formal_run_started: true
formal_run_consumed: true
formal_run_completed: true
formal_run_attempts: 1
additional_formal_run_allowed: false
accepted_run_id: R2A-T04-20260720T002158508Z
accepted_execution_head: 1d34cf49b9816aac92837213fa668356d5c7b45d
formal_result_candidate_status: passed
formal_result_review_status: accepted
owner_result_review: accepted
result_review_status: accepted
independent_review_attempt_count: 2
independent_review_result: passed_after_owner_authorized_successor_review
failed_independent_review_receipt_sha256: 81da003835f045c1938ebc36f9d7dfc9d22a1b020c44a41a55ca00051b2c98b1
accepted_independent_review_receipt_sha256: 8b698c68deb5053634cac9affcb1be7946c6f5b97dc66215a138105efe0eac16
revision_4_authorization_head: bd906df6b314352dccde75bc087709503d5e2262
revision_4_run_id: R2A-T04-20260719T090524491Z
revision_4_formal_run_started: true
revision_4_formal_run_consumed: true
revision_4_formal_run_completed: false
revision_4_result: terminated_incomplete_performance
revision_4_completed_request_count: 1
revision_4_completed_request: D01_P_q15_k3
revision_4_interrupted_request: D02_PA_q15_k3
revision_4_result_review_status: rejected_incomplete
revision_5_run_id: R2A-T04-20260719T212259066Z
revision_5_formal_run_started: true
revision_5_formal_run_consumed: true
revision_5_formal_run_completed: true
revision_5_automated_validation: passed
revision_5_independent_review: passed
revision_5_owner_result_review: not_accepted
revision_5_result_status: valid_scope_superseded_before_owner_acceptance
revision_5_superseded_reason: owner_requested_q10_q20_scope_extension
authorization_revision_2_head: 9d3c2dab43a10b12931db921ef730db6e8552ff1
authorization_revision_2_status: superseded_before_formal_run
authorization_revision_2_used: false
authorization_revision_2_formal_run_started: false
authorization_revision_2_formal_attempt_consumed: false
authorization_revision_2_superseded_reason: scope_corrected_to_score_parameter_response_and_interval_structure
authorization_revision_3_head: 21837edddfcc298b8539bcf9f71a1b7e016b6d47
authorization_revision_3_status: superseded_before_formal_run
authorization_revision_3_used: false
authorization_revision_3_formal_run_started: false
authorization_revision_3_formal_attempt_consumed: false
superseded_reason: independent_review_cli_not_aligned_with_score_only_scope
thread_benchmark_status: passed
thread_benchmark_receipt_sha256: c0fa81d08138cc0e2d5121be9affa52db11c3df36b0227fe420ca0c78ff6d369
thread_benchmark_receipt_byte_size: 97485
thread_benchmark_fingerprint: 049eeca525592e9a3d9659b3d0a3ce1eccc322f0289f283d0e9d8fe647e82231
thread_benchmark_evidence_reused: true
reuse_basis: evaluator_request_output_and_fingerprint_core_byte_identical
thread_benchmark_rerun_required: false
full_universe_request_concurrency: 1
full_universe_request_count: 4
duckdb_thread_count: 4
optimized_evaluator_head: cd41877a3423d7760eacc148049d6cbcbc8ed5c7
optimized_evaluator_Quality: 29697311968 / success
optimized_benchmark_status: passed
optimized_benchmark_receipt_sha256: 59e87d0124e52411a47242d017facfd91f98659c205539364cd187a09005dd76
optimized_benchmark_CA_q15_wall_seconds: 203.97563770017587
optimized_benchmark_CA_q25_wall_seconds: 555.4190305001102
optimized_benchmark_combined_wall_seconds: 759.3946682002861
q10_q20_benchmark_status: passed
q10_q20_benchmark_receipt_sha256: adf58b303e52f1f9e869e679532bf399a44d3ca8a19f740e14182f1a97b6bec6
scope_expansion_implementation_head: abd78af8c2fb10d3bd8257355a57df29c923632c
scope_expansion_implementation_Quality: 29706820683 / success
q10_q20_benchmark_evidence_head: 277b5c3d6433caee05d3d0156318f9b386eb316a
q10_q20_benchmark_evidence_Quality: 29707568838 / success
q10_full_800_wall_seconds: 115.87203370011412
q20_full_800_wall_seconds: 261.42730220011435
q10_q20_combined_wall_seconds: 377.29933590022847
four_q_combined_evaluator_seconds: 1136.6940041005146
R2A-T04_formal_full_universe_score_data_read: true
R2A-T04_formal_dynamic_evaluation_executed: true
R2A-T04_unique_input: accepted_R2A-T01_Score_release
R2A-T04_unique_formal_scope: CA_q10_q15_q20_q25_k5_response_curve
R2A-T04_request_count: 4
CA_q10_k5_request_id: pcavt-dynreq-v1-d07aae4bbbd98f88
CA_q10_k5_request_hash: d07aae4bbbd98f88989cf6b50c3b808935f237cd69f56271f6a210aa90f7ac8f
CA_q15_k5_request_id: pcavt-dynreq-v1-cf420e9c025374d1
CA_q15_k5_request_hash: cf420e9c025374d19bbc4e83bd75fee96d10d0c322605826ae5cffcf4029674f
CA_q20_k5_request_id: pcavt-dynreq-v1-21bd144aaed98d9e
CA_q20_k5_request_hash: 21bd144aaed98d9e7d404aaa8d2fa0685f7ec29a3deb714d0d1df99c05d5e971
CA_q25_k5_request_id: pcavt-dynreq-v1-b210f9e5211c46db
CA_q25_k5_request_hash: b210f9e5211c46db6cbc41ca1da9ff340018b4ef69e56df07ae22cecafbad3e9
CA_q10_k5_selection_status: evaluated_not_selected
CA_q15_k5_selection_status: evaluated_not_selected
CA_q20_k5_selection_status: evaluated_not_selected
CA_q25_k5_selection_status: evaluated_not_selected
q_selection_status: not_selected
canonical_dynamic_request_selected: false
selected_request_id: null
selected_request_hash: null
selected_q_by_dimension: null
R2A-T04_DONE: present
LOCAL-STORAGE-MIGRATION-01_status: completed_verified
local_storage_root: repository/data
external_input_root: retired_absent
R2A-T05_allowed_to_start: true_after_LOCAL-STORAGE-MIGRATION-01_merge
independent_output_validator: full_persisted_table_recomputation_accepted
implementation_review_blockers: 0
per_dimension_q_properties: P_and_A_independent_verified
```

R2A-T03 的任务契约见
[`R2A-T03_Dynamic_evaluator实现.md`](R2A-T03_Dynamic_evaluator实现.md)。Reviewed implementation
`73b9b54ef76191fdbb44ffd7e4ae335601016466` 已接受，accepted handoff 与唯一 `DONE` 已建立。
接受范围仅覆盖 evaluator、开发期输出契约与 synthetic/property evidence；尚未读取真实 Score release、
运行真实 dynamic evaluation、选择最佳 q/K 或产生真实状态产物。PR #112 合并后
R2A-T04 的唯一输入仍是 accepted R2A-T01 Score release。Revision 4 formal run
`R2A-T04-20260719T090524491Z` 已消费但因性能终止，只完成一个 request，结果不可接受且不可重跑。
Revision 5 的 q15/q25 结果有效但在 owner 接受前被四档 q scope 取代。Revision 6 run
`R2A-T04-20260720T002158508Z` 已严格串行完成 q10/q15/q20/q25；四个 validator、formal validation、
八项 response checks、benchmark profile reconciliation 和 owner-authorized successor independent review
全部通过，所有 blocking/mismatch count 为 0。Owner 已接受该 formal 参数响应证据，但未选择任何 q，
也未注册 canonical dynamic request 或 dynamic state。Accepted handoff 与唯一 `DONE` 已建立。
PR #113 与 PR #114 已合并，R2A-T04 为 `completed_accepted`。Repository-local copy 与
post-delete verification 已通过，旧 external input root 已永久退役。R2A-T05
formal result、post-run remediation、技术验收、科学审阅和 owner review 已接受，
accepted handoff 与 canonical `DONE` 已建立。PR #115 已合并；R2A-T06 implementation
SHA `2710d282fadcb998b80b9a482a5d55a4facc775a` 已通过 owner review，当前为 formal-execution
successor candidate pending owner review；前一 formal-execution candidate `4ebadc8aea216730cc6eb9c8b0b8c911574e488d`
未获批准，且当前状态不授权 formal run 或真实 Score 读取。
任务契约见
[`R2A-T04_Score参数响应与区间结构审核.md`](R2A-T04_Score参数响应与区间结构审核.md)。

## R2A 后续路线修订（R2A-T05 accepted closure）

R2A-T05 已完成接受关闭；本节不改变并行 R2 阶段的 `current_stage/current_task`。当前 R2A 状态如下：

```text
R2A-T05_status: completed_accepted
R2A-T05_accepted_run_id: R2A-T05-20260722T012719685Z
R2A-T05_formal_result_review_status: accepted
R2A-T05_scientific_review_status: passed
R2A-T05_owner_result_review: accepted
R2A-T05_post_run_artifact_remediation: owner_authorized_completed
R2A-T05_formal_run_attempts: 2/2
R2A-T05_additional_formal_run_allowed: false
R2A-T05_q_selection_status: not_selected
R2A-T05_canonical_dynamic_request_selected: false
R2A-T05_DONE: present
R2A-T06_allowed_to_start: true_after_PR_115_merge
R2A-T06_started: true
R2A-T06_status: formal_execution_candidate_pending_owner_review
R2A-T06_previous_unapproved_implementation_sha: 2bd24badf22ede38392ef7a4b3467602cc929106
R2A-T06_owner_implementation_review_status: passed
R2A-T06_approved_implementation_sha: 2710d282fadcb998b80b9a482a5d55a4facc775a
R2A-T06_formal_execution_candidate_status: pending_owner_review
R2A-T06_formal_execution_candidate_sha: exact PR head（Git/PR external binding）
R2A-T06_owner_formal_execution_review_status: pending_successor_review
R2A-T06_previous_unapproved_formal_execution_sha: 4ebadc8aea216730cc6eb9c8b0b8c911574e488d
R2A-T06_successor_formal_execution_candidate_sha: exact PR head（Git/PR external binding）
R2A-T06_approved_formal_execution_sha: absent
R2A-T06_selected_exit_confirmation_m: null
R2A-T06_authoritative_manifest_generated: false
R2A-T06_formal_authorization_created: false
R2A-T06_formal_run_allowed: false
R2A-T06_real_score_data_read: false
R2A-T06_formal_run_executed: false
R2A-T06_formal_artifacts_generated: false
R2A-T06_DONE: absent
R2A-T07_allowed_to_start: false
R3_allowed_to_start: false
R2A-T06_owner_formal_execution_review_required: true
```

Accepted handoff：[`../../data/generated/r2a/r2a_t05/R2A-T05-20260722T012719685Z/r2a_t05_accepted_result_handoff.json`](../../data/generated/r2a/r2a_t05/R2A-T05-20260722T012719685Z/r2a_t05_accepted_result_handoff.json)。Acceptance evidence：[`../evidence/r2a/R2A-T05_CA_exit_mechanism_formal_result_acceptance.md`](../evidence/r2a/R2A-T05_CA_exit_mechanism_formal_result_acceptance.md)。

后续路线已改为：

```text
R2A-T05: CA q20 退出原因、阈值距离、快速重入和跨 q 结构分解
R2A-T06: CA 连续失效退出确认与迟滞规则选择（M=1/2/3）
R2A-T07: 版本注册、消费者契约与冻结
R2A-T08: 阶段验收与 R3 handoff
```

T05 的 q20 是退出机制分解研究锚点，不是 best、optimal、selected canonical、winner 或正式参数选择。T06 只在 accepted daily facts 上新增连续失效生命周期，不读取未来价格、收益或路径标签，不生成交易信号或回测。Implementation successor 已获 owner 批准；当前 formal-execution successor 只修复五项 owner blocker：attempt 原子消费、Score/request coverage 对账、按 horizon 独立 reentry、persisted 核心表/detail 对账和最终 artifact-manifest 完整性。它仍等待 owner 审阅 exact candidate SHA，未生成权威 manifest、authorization 或 formal artifacts。详细契约见 [`R2A-T06_CA连续失效退出确认与迟滞规则选择.md`](R2A-T06_CA连续失效退出确认与迟滞规则选择.md)。

## 命名与路径规则

从 D3-T09 / R0 开始，task、branch、task 文档和 PR 标题采用以下规范：

```text
branch: codex/d3-t09-r-stage-engineering-layout-task-as-step-governance
task file path: docs/tasks/D3-T09_R阶段工程分层与Task-as-Step规范收敛.md
task H1: # D3-T09 R阶段工程分层与 Task-as-Step 规范收敛
PR title: [codex] D3-T09 R阶段工程分层与 Task-as-Step 规范收敛
```

branch 使用英文 slug。task 文件路径使用中文任务标题，可保留必要英文术语，例如 `Task-as-Step`、`PCVT`、`registry`。task H1 使用中文标题。PR 标题使用 `[codex] 阶段-任务号 中文标题`。

不批量重命名历史 task 文件。历史英文或中英混排 task 文件继续保留，除非未来单独开 rename-only PR。`docs/tasks/` 继续平铺管理，不拆成 `d0/`、`d1/`、`d2/`、`d3/`、`r0/` 等子目录。

跨阶段治理 task 使用 `GOV-Txx`。GOV task 不改变 current_stage/current_task，只有直接推进研究阶段的 task 才能修改 current_task。

`GOV-T02` completed via PR #102。该治理任务本身不需要 formal run 或 Formal-result 阶段，formal run executed: false。它只重置后续研究流程，不推进当前 `current_stage`、`current_task` 或下一 task。新任务采用两个逻辑审阅阶段：先由用户审阅并批准 implementation SHA，再执行 formal run 并由用户直接决定 Formal-result；两个阶段不等于必须两个 PR，同一 PR 分两次提交是默认模式，两个独立 PR 也是合法模式。

## 跨阶段研究治理

- `GOV-T01` R1-R6 formal 实验结果包、异常门禁与独立科学审阅治理：completed via this PR。该治理 task 不改变当前 R1 task 指针。draft PR #77 is superseded by PR #78 / merge commit `8694cba4ddbd5a18e43ab18454dfc19cfb9903cd`；PR #77 不合并、不 rebase、不 cherry-pick，其结果不得作为当前 evidence、参数选择依据或后续 formal input。
- `GOV-T02` 先审实现后运行的两阶段研究流程：completed via PR #102；formal run executed: false；不适用于已完成的 R1/R2 历史任务，不改变当前研究指针。

历史索引：D2-T01 完成后曾推进到 `current_task: D2-T02`、
`next_planned_task: D2-T03`；D2-T02 完成本 PR 后当前索引继续推进到 D2-T03 / D2-T04。
D2-T02 完成时的任务队列仍为：`D2-T03` 原始行情价格落账：planned。
D2-T03 进入阻塞门禁时的任务队列仍为：
`D2-T04` 复权因子与 `factor_as_of_time` 契约：planned。
D2-T04 进入阻塞门禁时的任务队列仍为：
`D2-T05` 连续研究价格构建与反推校验：planned。
D2-T05 进入阻塞门禁时的任务队列仍为：
`D2-T06` 跳空归因与价格质量标记：planned。
D2-T06 contract-only PR 合并时的任务队列仍为：
`D2-T06` 候选行情快照探针：contract-only pending separately authorized probe execution via PR #30。
D2-T06 候选探针执行前的任务队列仍为：
`D2-T07` 跳空归因与价格质量标记：planned。
D2-T07 进入契约门禁前的任务队列仍为：
`D2-T08` D2 阶段验收与 D3 交接：planned。
D2-T08 完成后曾进入 D3 contract queue；D2 formal materialization 未完成前，
`D3-T07` remained blocked pending D2 formal materialization，`R0` remained blocked。
D3-T07 was later unblocked for research candidate generation by D2-T20 evidence-verified candidate acceptance; formal data_version remains blocked.
D3-T06 发布门禁 PR 合并时的阶段索引仍为：
```text
current_stage: D3
current_task: D3-T06
next_planned_task: D3-T07
```
D3-T07 candidate observation PR 合并前的阶段索引仍为：
```text
current_stage: D3
current_task: D3-T07 candidate daily observation from D2-T20
next_planned_task: D3-T08 PCVT input readiness and feature-base quality checks
```
D3-T07 PR 合并前的任务队列曾包含：
`D3-T07` 从 D2-T20 evidence-verified candidate 生成标准日频观测表：in_progress；
`D3-T08` PCVT input readiness and feature-base quality checks：planned。
R0 remains blocked until D3 output is accepted by later gates.
R0 历史状态快照：状态：blocked until D3 output is accepted by later gates。
D3-T08 research dataset registry PR 合并前的阶段索引仍为：
```text
current_stage: D3
current_task: D3-T08 research dataset registry and route-agnostic base quality
next_planned_task: R0-T01 PCVT candidate indicator specification
```
D3-T08 research dataset registry PR 合并前的任务队列曾包含：
`D3-T08` 研究基础数据集 registry 与路线无关质量审计：in_progress。
formal data_version remains blocked until explicit release gate.
R0 state remains blocked until PCVT candidate indicators and later gates are accepted.
D3-T08 合并后进入 D3-T09 governance convergence；R0 仍未开始，R0-T01 将在 D3-T09 合并后单独开启。

## G0：样本宇宙与时间边界

状态：completed

- `G0-T01` 官方中证 800 成分证据获取与审核：completed
- `G0-T02` 原始快照受控交付与独立哈希复核：completed
- `G0-T03` 配置落账 verified / approved / eligible_for_d0：completed via PR #5

完成标准：

- 官方成分证据完成获取；
- 独立审核完成原始字节复算；
- G0 配置写回 `verified / approved / eligible_for_d0`；
- G0 后续不再新增流程 PR。

## D0：数据源资格审查、原始快照与基础审计

状态：completed

目标：

- 建立 DuckDB 架构边界；
- 明确数据源资格、原始快照和基础审计要求；
- 定义 D1/D2/D3 数据产品契约。

非目标：

- 不采集行情；
- 不运行 D0 装载；
- 不创建正式 DuckDB 文件；
- 不计算 PCVT、事件、标签或回测。

任务列表：

- `D0-T01` DuckDB 数据架构设计：completed via PR #6
- `D0-T02` 数据源资格审查与 source registry：completed via PR #7
- `D0-T03` D1 / D2 / D3 数据产品契约：completed via PR #8

完成标准：

- `D0-T01`、`D0-T02`、`D0-T03` 合并；
- D0 的设计、来源资格、原始快照审计要求和数据产品契约均固定；
- 仍未进入研究运行。

## D1：证券主数据、交易状态、公司行为与交易日历

状态：completed

- `D1-T00` DuckDB 依赖、空 schema 与契约测试：completed via PR #9
- `D1-T01` `security_master` 与代码映射：completed via PR #10
- `D1-T02` 交易日历与交易状态主表：completed via PR #11
- `D1-T03` 公司行为与复权因子主表：completed via PR #12
- `D1-T04` `CSI800_STATIC_2026_06` universe membership materialization：completed via completion PR

## D2：时点一致的原始价格、连续研究价格和跳空归因

状态：planned

目标：

- 建立原始交易事实、复权/因子、连续研究价格和跳空归因的分层边界；
- 保证 raw price facts 与 continuous research prices 并存、可追溯、不可覆盖或混用；
- 在 source/as-of/snapshot/manifest 阻塞条件关闭前，只做契约、探针和小样本验收设计，不启动全量正式行情拉取。

非目标：

- 不从 D2-T01 直接开始全市场数据采集；
- 不绕过 D0 source registry 和 D1/D2 数据产品契约；
- 不将候选来源返回的历史修订价格、复权价或供应商标签直接升级为正式研究证据。

任务列表：

- `D2-T01` 价格来源与 raw OHLCV 探针契约：completed via PR #25
- `D2-T02` 成员对齐层物化：completed via PR #26
- `D2-T03` 原始行情价格落账：blocked pending source authorization via PR #27
- `D2-T04` 复权因子与 `factor_as_of_time` 契约：blocked pending factor source authorization via PR #28
- `D2-T05` 连续研究价格构建与反推校验：blocked pending raw and factor authorization via PR #29
- `D2-T06` 候选行情快照探针：small-sample redacted execution report via PR #32; formal ingestion and D1/D2/D3 materialization remain blocked
- `D2-T07` 价格质量、交易约束、机械缺口与 PCVT 底层依赖契约：contract-only via PR #33
- `D2-T08` D2 阶段验收与 D3 交接契约：contract-only via PR #34; D3 contract work may proceed, but formal D3 generation remains blocked
- `D2-T09` HiThink 主行情源、补充源与 raw OHLCV 探针契约：completed via PR #41; candidate raw market prices remain superseded diagnostic output and do not define D2-T13 date domain
- `D2-T10` adjusted price、质量标记与机械缺口正式候选物化：completed via PR #42
- `D2-T11` 来源状态与复权证据补齐、D2验收与D3交接候选：completed via PR #43; D2/D3 remained blocked
- `D2-T12` tnskhdata/Tushare证据源探针、统一代码映射与HiThink REST适配修复：completed via PR #44
- `D2-T13` tnskhdata全量候选物化与D2验收交接：completed via PR #45; D2 acceptance remained blocked by listed-open provider coverage
- `D2-T14` listed-open 行级 provider 修复诊断：closed / superseded by D2-T15; not merged
- `D2-T15` 按证券主轴的 DuckDB 候选物化骨架与质量门禁：completed via PR #47
- `D2-T16` 按证券主轴的 tnskhdata 远程拉取 runner：completed via PR #48
- `D2-T17` 按 endpoint 配置 D2 runner chunk 策略：completed / runner available after PR #49
- `D2-T18` provider coverage blocker 诊断与最小修复策略：completed / diagnostics available after PR #50
- `D2-T19` targeted repair and coverage policy evidence：completed / stk_limit targeted repair succeeded; daily repair empty due to listing pause
- `D2-T20` fast coverage policy acceptance：completed via PR #52; evidence-verified research candidate accepted for D3 candidate generation
- `D3-T07` 标准日频观测表 candidate 生成：completed via PR #53; reads D2-T20 evidence-verified candidate only
- `D3-T08` 研究基础数据集 registry 与路线无关质量审计：completed via PR #54

D3-T07 candidate generation may read D2-T20 candidate output. Formal data_version remains blocked until explicit release gate. R0 state remains blocked until PCVT candidate indicators and later gates are accepted.

完成标准：

- D2-T01 至 D2-T08 均完成对应 PR 级验收；
- `d1.raw_market_prices`、`d2.adjusted_market_prices`、`d2.market_price_quality_flags` 和
  `d2.membership_alignment` 的来源、as-of、snapshot、manifest 和 revision 边界均通过审核；
- 原始交易事实层、连续研究价格层、交易约束引用和公司行为/机械缺口归因之间的使用边界可测试、可追溯；
- D3 可以仅通过引用已验收的 D1/D2 事实构建 `daily_market_observations`。

## D3：跨研究复用的标准日频观测表与基础质量指标

状态：in_progress

D2-T08 已完成 D2 acceptance 与 D3 handoff contract-only 验收。D2-T20 已完成
evidence-verified research candidate acceptance，并只授权 D3 candidate generation。
formal data_version、formal source promotion 与 R0 交接仍未授权。

- `D3-T01` `daily_market_observations` 语义与字段契约：completed via PR #35
- `D3-T02` D3 标准数值观测 view/table 契约：completed via PR #36
- `D3-T03` 组件引用、source lineage 与 no-bypass 校验器：completed via PR #37
- `D3-T04` 基础质量指标与 PCVT input readiness 契约：completed via PR #38
- `D3-T05` 标准日频观测合成构建与最小集成测试：completed via PR #39
- `D3-T06` `data_version`、quality report 与 manifest 发布门禁：completed via PR #40
- `D3-T07` 从 D2-T20 evidence-verified candidate 生成标准日频观测表：completed via PR #53
- `D3-T08` 研究基础数据集 registry 与路线无关质量审计：completed via PR #54
- `D3-T09` R阶段工程分层与 Task-as-Step 规范收敛：completed
- `D3-T10` D3 字段可用性探针与字段缺口补全：completed via PR #58
- `D3-T11` 量额股本换手字段全量候选物化与数据更新：completed via PR #59
- `D3-T12` 开放候选层门禁与下游消费审计解耦：completed via PR #60

D3 是跨研究开放 candidate observation layer。D3 candidate generation 不等于 formal release，也不等于任一 R-stage readiness。R0-R6 或未来研究路线由各自消费 task 定义 consumer readiness profile；D3 只记录通用质量、evidence 和 lineage 状态。`policy_evidence_pending_hash` 是 candidate warning，不是 D3 candidate hard blocker。formal release gate 和下游 research consumer gate 后续仍可严格阻塞消费。

PR #60 的 D3-T11 full-run 摘要以 canonical local output-dir `data/generated/d3/d3_t11_volume_amount_share_turnover_candidate/` 为准；该目录已由 clean rerun compact artifact 覆盖回默认路径。retry-patched artifact 仅作为本地备份/审计，不作为最终摘要来源，generated DuckDB/CSV/JSON 仍不得提交。

## R0：PCVT 候选观测量与候选状态定义

状态：in_progress

- `R0-T01` PCVT 候选指标规格、状态族与 candidate spec contract：completed via PR #56
- `R0-T02` 输入 readiness gate 与 C2/V1 公司行为口径审计：completed via PR #57
- `R0-T03` V层 turnover 替代指标可行性、口径决策与输入门禁：completed via PR #61
- `R0-T04` PCVT raw metric engine 与合成测试：completed via PR #62
- `R0-T05` 严格过去分位、eligible 样本与 Score 体系：completed via PR #63
- `R0-T06` weak 维度规则、嵌套状态与互斥分层：completed via PR #64
- `R0-T07` 联合确认层、streak 与确认区间表：completed via PR #65
- `R0-T08` 主网格 candidate 状态日表与 manifest：completed via PR #66
- `R0-T09` runner/contract/smoke：completed via PR #67
- `R0-T09` formal input manifest：blocked / superseded by R0-T10-05 pending real R0-T04 -> R0-T07 upstream artifacts
- `R0-T09` production full-grid materialization：blocked until R0-T10-05 authorized input manifest and streaming/artifact-manifest mode
- `R0-T10-01` 真实数据源与 R0-T04 raw metrics 物化：completed via PR #69
- `R0-T10-02` R0-T05 strict-past score 物化：completed via PR #70
- `R0-T10-03` R0-T06 nested state 物化：completed via PR #71
- `R0-T10-04` R0-T07 confirmation / interval 物化：completed via PR #72
- `R0-T10-05` authorized input manifest 与 27 组 full-grid 执行：completed via PR #73; repaired by R0 C2 readiness and state-specific validity rerun
- `R0-T11` R0 审计报告与 R1 交接：completed via PR #74
- `R0-T12` 替代指标口径敏感性骨架：optional
- `R0-T13` Post-Up-Release Short-PCT 研究接口占位：optional
- `R0-T14` R0 并行确定性与性能优化：optional
- `R0-T15` 层级 q-vector 正式物化与 R1-T14-02 交接：REV1 author revision pending external rereview in Draft PR #88

## R1：状态存在性、结构关系、稳定性与零模型检验

状态：in_progress / active

本 PR 修复 R0 C2 readiness alias 与 state-specific validity blocker，并将 R1-T01、R1-T02、R1-T03 重新锁定到修复后的 R0-T10-05 full-grid package。R1-T04 可以基于非零 `S_PC` / `S_PCT` / `S_PCVT` raw 与 confirmed 结构继续做分线画像；R1-T07 与 R2 仍保持 blocked。

- `R1-T01` 验证协议、状态线假设与 manifest 锁定：completed via PR #75; relocked to repaired R0 package via this PR
- `R1-T02` R0 产物接收、lineage 与无前视复检：completed via this PR
- `R1-T03` 27 组 W/q/K 全量轻量结构扫描：completed via this PR against the repaired R0-T10-05 package; draft PR #77 is superseded by the repaired nonzero package evidence
- `R1-T04` S_PCT 与 S_PCVT 分线状态画像：completed via PR #80
- `R1-T05` 单指标诊断与层内互补性分析：completed via PR #81
- `R1-T06` 层间同期留存、关联 Lift 与嵌套增量：completed via PR #82
- `R1-T07` P 首入锚定的固定滞后结构关系：completed via PR #83
- `R1-T08` S_PCT/S_PCVT 同步性与嵌套增量零模型：completed via PR #84
- `R1-T09` 年份稳定性与状态集中度检查：completed via PR #85
- `R1-T14-01` 层级 q 单变量响应诊断与候选提名：completed via PR #87
- `R1-T14-02` 层级 q-vector R0 物化接收与正式结构复验：completed via PR #89
- `R1-T10` R1 验收门禁与 R2 交接矩阵：completed via PR #90 final gate；R2-T01 启动资格打开
- `R1-T11` 27 组全量零模型 family-level sidecar：optional / triggered
- `R1-T12` CTV-bundle、无锚平移与块长 B 对照零模型：optional / triggered
- `R1-T13` 替代指标口径 sensitivity sidecar：optional / triggered

若 R1-T14-01 输出 `no_q_decoupling_candidate`，R1-T14-02 可正式记录为 `not_triggered`，经 T14-01 final gate 后直接推进 R1-T10。若输出 `q_vector_materialization_request`，必须先完成单独授权的 R0 formal materialization handoff，再允许启动 R1-T14-02。R1-T11/T12/T13 不因本路线自动触发，R2 在 R1-T10 完成前始终关闭。

### R1-T14 分支状态机

T14-01 当前初始状态为：

```text
R1-T14-01_decision_status: pending
R1-T14-02_status: blocked_pending_t14_01_decision
R0_q_vector_materialization_request_status: not_requested
R0_q_vector_materialization_task_id: unbound
R0_q_vector_materialization_allowed_to_start: false
R0_q_vector_materialization_status: not_started
R1-T14-02_allowed_to_start: false
R1-T10_allowed_to_start: false
R2_allowed_to_start: false
```

若 T14-01 final gate 选择 `no_q_decoupling_candidate`，README 只能推进到：

```text
current_stage: R1
current_task: R1-T10 R1 验收门禁与 R2 交接矩阵
next_planned_task: R2-T01 参数候选收敛
R1-T14-01_decision_status: no_q_decoupling_candidate
R1-T14-02_status: not_triggered
R0_q_vector_materialization_request_status: not_requested
R0_q_vector_materialization_task_id: unbound
R0_q_vector_materialization_allowed_to_start: false
R0_q_vector_materialization_status: not_started
R1-T14-02_allowed_to_start: false
R1-T10_allowed_to_start: true
R2_allowed_to_start: false
```

若 T14-01 final gate 选择 `q_vector_materialization_request`，必须先绑定具体 `R0_q_vector_materialization_task_id`，README 只能推进到：

```text
current_stage: R0
current_task: <bound R0 task_id and title>
next_planned_task: R1-T14-02 层级 q-vector R0 物化接收与正式结构复验
R1-T14-01_decision_status: q_vector_materialization_request
R0_q_vector_materialization_request_status: approved
R0_q_vector_materialization_task_id: <bound concrete R0 task_id before final gate>
R0_q_vector_materialization_allowed_to_start: true
R0_q_vector_materialization_status: authorized
R1-T14-02_status: blocked_pending_R0
R1-T14-02_allowed_to_start: false
R1-T10_allowed_to_start: false
R2_allowed_to_start: false
```

R0 q-vector materialization final gate 通过后，README 才能返回 R1：

```text
current_stage: R1
current_task: R1-T14-02 层级 q-vector R0 物化接收与正式结构复验
next_planned_task: R1-T10 R1 验收门禁与 R2 交接矩阵
R0_q_vector_materialization_request_status: fulfilled
R0_q_vector_materialization_allowed_to_start: false
R0_q_vector_materialization_status: completed
R1-T14-02_status: authorized
R1-T14-02_allowed_to_start: true
R1-T10_allowed_to_start: false
R2_allowed_to_start: false
```

## R2：参数、事件规则与状态版本冻结

状态：R2-T01 至 R2-T04 已完成独立科学审阅和 repository final gate；R2-T04 author package 保持不可变，并由 immutable post-merge handoff 持久绑定。该 handoff 记录复用 T02 consumer 的 `formal_surface_changed_after_artifact_commit` 对 R2-T04 不适用，且不豁免 T04 其余门禁。R2-T03 保留 promoted preserved-fact run；R2-T04 两个 W120 primary 及 strict-core pair 已冻结。T05 的 154500Z run 已由 successor formal run supersede，当前 successor author package 等待独立科学审阅；R3 继续关闭。

R2-T01 author-draft 历史门禁记录：`current_task: R2-T01 参数候选收敛与 shortlist registry`、`next_planned_task: R2-T02 K/d/g、事件指标、hard gate 与 R3 risk-set 契约`、`R2-T02_allowed_to_start: false`。这些 marker 仅用于复验 author-draft fail-closed 行为，现行状态以“当前阶段”块中的 R2-T02 author package 记录为准。

- `R2-T01` 参数候选收敛与 shortlist registry：completed via PR #91 final gate
- `R2-T02` confirmed-state 与 event-zone 双层状态机契约：completed via PR #94 and immutable post-merge handoff
- `R2-T03` 四路线 d×g event-zone 状态机扫描与区间几何审计：implementation-correction-only；v2 adapters implemented and aggregate-validated；历史 1205Z author-draft invalidated；formal rerun not executed；implementation review requested
- `R2-T04` Hard gate、Pareto 推荐、用户决策与 freeze plan：completed via PR #96 and post-merge final-gate handoff
- `R2-T05` canonical daily state、event zone 与 membership 物化：successor author package complete，pending independent scientific review
- `R2-T06` canonical 状态机无前视回放与一致性验收：blocked
- `R2-T07` 状态版本登记册与最终 freeze manifest：completed via PR #99 merged direct binding
- `R2-T08` R2 阶段验收与 R3 交接：author package complete pending independent scientific review

## R3：释放定义、风险集、对照组与未来标签

状态：blocked until R2

- `R3-T01` 释放定义
- `R3-T02` 风险集与对照组
- `R3-T03` 未来标签契约

## R4：释放后的方向、幅度、持续期与路径研究

状态：blocked until R3

- `R4-T01` 方向与幅度研究
- `R4-T02` 持续期与路径研究

## R5：样本外验证、回测、成本与稳健性检验

状态：blocked until R4

- `R5-T01` 样本外验证
- `R5-T02` 回测与成本检验
- `R5-T03` 稳健性检验

## R6：交易可行性、执行约束、运行监控与结论发布

状态：blocked until R5

- `R6-T01` 交易可行性与执行约束
- `R6-T02` 运行监控
- `R6-T03` 结论发布

## 说明

- 本索引只定义阶段和任务队列，不替代 task 正文契约。
- 若某阶段范围发生实质变化，应先更新本索引，再新增 task。
