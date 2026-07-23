# R2A / PCAVT 研究交接

> 本文是无上下文新会话的当前入口。R2A-T05 已接受关闭且 PR #115 已合并。R2A-T06 implementation 与 formal-execution SHA `462dc56271fe09e5b116dacc2422a342556ef1a0` 已获 owner 批准；当前仅提交 authorization-contract transition，尚未创建 authorization、消费 attempt 或读取真实 Score。

## 0. 当前状态

```text
repository: benzemaer/convergence-research
branch: codex/r2a-t06-ca-consecutive-failure-exit-confirmation
PR: #116
PR state: Draft
R2A-T04_merge_commit: a4b6696f3c9cd32cb9bc0c29606e3121958bc26e

R2A-T04_status: completed_accepted
scope_id: r2a_t04_ca_q10_q15_q20_q25_k5_response_audit.v1
panel_id: r2a_t04_ca_four_q_k5_panel.v1
accepted_run_id: R2A-T04-20260720T002158508Z
accepted_execution_head: 1d34cf49b9816aac92837213fa668356d5c7b45d
formal_authorization_id: R2A-T04-CA-FOUR-Q-AUDIT-AUTH-20260720-R6
authorization_revision: 6
formal_run_started: true
formal_run_consumed: true
formal_run_completed: true
additional_formal_run_allowed: false
formal_result_review_status: accepted
owner_result_review: accepted
independent_review_result: passed_after_owner_authorized_successor_review
q_selection_status: not_selected
canonical_dynamic_request_selected: false
selected_request_id: null
selected_request_hash: null
selected_q_by_dimension: null
R2A-T04_DONE: present
LOCAL-STORAGE-MIGRATION-01_status: completed_verified
copy_verification_status: passed
locator_reconciliation_status: passed
post_delete_verification_status: passed
source_deleted: true
local_storage_root: repository/data
external_input_root: retired_absent
old_root_runtime_reference_present: false
R2A-T05_allowed_to_start: true_after_LOCAL-STORAGE-MIGRATION-01_merge
R2A-T05_status: completed_accepted
R2A-T05_accepted_run_id: R2A-T05-20260722T012719685Z
R2A-T05_accepted_execution_head: 260c3e1fe040eb9a44ee64f54a01142e6c3d8efa
R2A-T05_formal_result_review_status: accepted
R2A-T05_scientific_review_status: passed
R2A-T05_owner_result_review: accepted
R2A-T05_post_run_artifact_remediation: owner_authorized_completed
R2A-T05_formal_attempts_consumed: 2
R2A-T05_additional_formal_run_allowed: false
R2A-T05_scope_id: r2a_t05_ca_exit_mechanism_decomposition.v1
R2A-T05_implementation_version: r2a_t05_ca_exit_decomposition.v1
research_anchor_q: 2000
research_anchor_role: exit_mechanism_decomposition
R2A-T05_q_selection_status: not_selected
R2A-T05_canonical_dynamic_request_selected: false
R2A-T05_DONE: present
R2A-T06_started: true
pre_merge_R2A-T06_allowed_to_start: false
R2A-T06_allowed_to_start: true_after_PR_115_merge
R2A-T06_status: formal_run_authorized_pending_execution
R2A-T06_previous_unapproved_implementation_sha: 2bd24badf22ede38392ef7a4b3467602cc929106
R2A-T06_owner_implementation_review_status: passed
R2A-T06_approved_implementation_sha: 2710d282fadcb998b80b9a482a5d55a4facc775a
R2A-T06_formal_execution_candidate_status: pending_owner_review
R2A-T06_formal_execution_candidate_sha: exact PR head（Git/PR external binding）
R2A-T06_owner_formal_execution_review_status: passed
R2A-T06_previous_unapproved_formal_execution_sha: 4ebadc8aea216730cc6eb9c8b0b8c911574e488d
R2A-T06_successor_formal_execution_candidate_sha: exact PR head（Git/PR external binding）
R2A-T06_approved_formal_execution_sha: 462dc56271fe09e5b116dacc2422a342556ef1a0
R2A-T06_reviewed_formal_execution_sha: 462dc56271fe09e5b116dacc2422a342556ef1a0
R2A-T06_proposed_formal_run_id: R2A-T06-20260723T081207955Z
R2A-T06_authorization_preview_manifest_sha256: 053fc7ead3a4304096127028313593607121ce99952e1c48b09b74fdc3faa0c7
R2A-T06_authorization_preview_manifest_byte_size: 6245
R2A-T06_authorization_contract_parent_sha: 462dc56271fe09e5b116dacc2422a342556ef1a0
R2A-T06_authorization_contract_review_status: pending_owner_review
R2A-T06_formal_run_allowed_now: false
R2A-T06_selected_exit_confirmation_m: null
R2A-T06_q_selection_status: not_selected
R2A-T06_canonical_dynamic_request_selected: false
R2A-T06_winner_selected: false
R2A-T06_authoritative_manifest_generated: false
R2A-T06_formal_authorization_created: false
R2A-T06_formal_attempt_consumed: false
R2A-T06_formal_run_allowed: true
R2A-T06_formal_run_executed: false
R2A-T06_real_score_data_read: false
R2A-T06_formal_artifacts_generated: false
R2A-T06_DONE: absent
R2A-T07_allowed_to_start: false
R3_allowed_to_start: false
owner_implementation_review_required: false
owner_formal_execution_review_required: false
current_stop: R2A-T06 authorization-contract successor pending owner review; no authorization or execution
```

## 1. 已接受基线与边界

R2A-T01、T02 和 T03 均已 `completed_accepted`。T04 唯一输入仍是 accepted Score release `pcavt-score-w120-v1-c7e04f11a2cd09aa`，SHA-256 为 `d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3`，byte size 为 4,255,395,840。

长期架构仍是 immutable Score release → parameterized evaluator → request-scoped states/intervals。T04 接受的是 formal 参数响应证据，不是参数选择：没有选择最佳 q，没有注册 canonical dynamic request 或 dynamic state，没有生成交易信号，也没有执行回测。

## 2. Revision 历史

Revision 4 run `R2A-T04-20260719T090524491Z` 已消费但因性能终止，只完成 `D01_P_q15_k3`，状态固定为 `terminated_incomplete_performance / rejected_incomplete`。它不可恢复或重跑，产物不得修改。

Revision 5 run `R2A-T04-20260719T212259066Z` 的自动验证和独立复核均 passed，但在 owner 接受前因扩展 q10/q20 scope 而成为 `valid_scope_superseded_before_owner_acceptance`。它没有失败，也不能作为 T04 accepted closure。

Revision 6 run `R2A-T04-20260720T002158508Z` 按 q10、q15、q20、q25 严格串行完成，threads=4。四个 validator、formal validation、八项 response checks 和 benchmark profile reconciliation 均通过，所有 blocking/mismatch count 为 0。

## 3. 四请求与接受事实

四个请求均为 `selected_dimensions=[C,A]`、`confirmation_k=5`，且全部为 `evaluated_not_selected`。

| Request | Request ID | q | Raw true | Confirmed true | Intervals | Securities with interval |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| CA_q10_k5 | `pcavt-dynreq-v1-d07aae4bbbd98f88` | 1000 | 20,559 | 1,916 | 751 | 473 |
| CA_q15_k5 | `pcavt-dynreq-v1-cf420e9c025374d1` | 1500 | 46,651 | 7,125 | 2,426 | 734 |
| CA_q20_k5 | `pcavt-dynreq-v1-21bd144aaed98d9e` | 2000 | 81,535 | 17,642 | 5,372 | 775 |
| CA_q25_k5 | `pcavt-dynreq-v1-b210f9e5211c46db` | 2500 | 124,893 | 35,098 | 9,107 | 788 |

允许结论仅为：在固定 C+A、K=5 和相同全市场 observation spine 下，q=1000→1500→2000→2500 形成严格、无违例的 raw-state 与 confirmed-state 嵌套扩张梯度；随 q 放宽，raw-state、confirmed-state、confirmed interval 和证券覆盖增加。不得将任何一档描述为最好或 canonical。

## 4. Independent review

首次 independent review 因 operator 提供不存在的 Score 路径而失败；failed receipt 保存在 `operator-logs/R2A-T04-20260720T002158508Z.independent.attempt1.failed.receipt.json`，SHA-256 为 `81da003835f045c1938ebc36f9d7dfc9d22a1b020c44a41a55ca00051b2c98b1`。它属于 operator invocation evidence，没有进入 immutable RunRoot，也没有使 formal result 失效。

Owner 授权的 successor review 使用同一 formal package，未重跑 request，最终 receipt 位于 `formal-runs/R2A-T04-20260720T002158508Z/independent_review_receipt.json`，SHA-256 为 `8b698c68deb5053634cac9affcb1be7946c6f5b97dc66215a138105efe0eac16`，status passed、mismatch count 0。

## 5. Accepted closure

Accepted handoff：

```text
data/generated/r2a/r2a_t04/R2A-T04-20260720T002158508Z/r2a_t04_accepted_result_handoff.json
```

Evidence：

```text
docs/evidence/r2a/R2A-T04_CA_four_q_formal_result_acceptance.md
```

R2A-T04 的唯一 `DONE` 已存在且保持 byte-identical。Repository-local copy、locator reconciliation 和 post-delete verification 均已通过，旧 external input root 已永久退役且 absent，未建立备份或兼容链接。R2A-T05 的 accepted handoff 与 canonical `DONE` 现已建立；其 formal result、post-run remediation、技术验收、科学审阅和 owner review 均已接受。

## 6. R2A-T06 路线与停止点

```text
R2A-T05: CA q20 退出原因、阈值距离、快速重入和跨 q 结构分解
R2A-T06: CA 连续失效退出确认与迟滞规则选择（M=1/2/3）
R2A-T07: 版本注册、消费者契约与冻结
R2A-T08: 阶段验收与 R3 handoff
```

q20 仅是 `exit_mechanism_decomposition` research anchor，`q_selection_status=not_selected`。T06 固定比较 M=1/2/3，但正式运行与独立结果审阅前不选择 winner。实现只读取 synthetic accepted-daily-state-shaped fixtures；未读取真实 Score、未来价格、收益或路径标签，未生成 formal artifact、DONE、交易信号或回测，也未允许 T07/R3 启动。

R2A-T05 accepted handoff 位于 `data/generated/r2a/r2a_t05/R2A-T05-20260722T012719685Z/r2a_t05_accepted_result_handoff.json`，acceptance evidence 位于 `docs/evidence/r2a/R2A-T05_CA_exit_mechanism_formal_result_acceptance.md`。

R2A-T06 task contract 位于 `docs/tasks/R2A-T06_CA连续失效退出确认与迟滞规则选择.md`。前一 implementation SHA `2bd24badf22ede38392ef7a4b3467602cc929106` 未获批准；successor implementation SHA `2710d282fadcb998b80b9a482a5d55a4facc775a` 已通过 owner review。前一 formal-execution candidate `4ebadc8aea216730cc6eb9c8b0b8c911574e488d` 的 review 为 changes required；当前 successor 修复 attempt 原子消费、Score/request coverage 对账、horizon-specific reentry、persisted 核心表/detail 对账和最终 artifact-manifest sealing，停止于 exact PR head 经 Quality 后等待 owner formal-execution review。不得创建权威 manifest、formal authorization、读取真实 Score、选择 M 或创建 DONE。
