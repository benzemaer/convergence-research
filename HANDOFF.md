# R2A / PCAVT 研究交接

> 本文是无上下文新会话的当前入口。R2A-T04 revision 6 formal result 已接受并随 PR #113 合并，repository-local storage migration 已随 PR #114 合并；当前停在 R2A-T05 implementation review，未执行 formal run。

## 0. 当前状态

```text
repository: benzemaer/convergence-research
branch: codex/r2a-t05-ca-exit-decomposition
PR: Draft pending creation
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
R2A-T05_status: implementation_candidate_pending_owner_review
R2A-T05_scope_id: r2a_t05_ca_exit_mechanism_decomposition.v1
R2A-T05_implementation_version: r2a_t05_ca_exit_decomposition.v1
research_anchor_q: 2000
research_anchor_role: exit_mechanism_decomposition
q_selection_status: not_selected
canonical_dynamic_request_selected: false
formal_run_allowed: false
formal_run_started: false
real_score_data_read: false
formal_artifacts_generated: false
R2A-T05_DONE: absent
R2A-T06_started: false
R2A-T06_allowed_to_start: false
current_stop: R2A-T05 implementation review
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

唯一 `DONE` 已存在且保持 byte-identical。Repository-local copy、locator reconciliation 和 post-delete verification 均已通过，旧 external input root 已永久退役且 absent，未建立备份或兼容链接。R2A-T05 implementation candidate 已在 PR #114 合并后的 `origin/main` 上启动；本轮不读取真实 Score，不执行 formal run，不生成正式 artifacts 或 DONE，不选择 q、不注册动态状态、不生成交易信号，也不执行回测。

## 6. R2A-T05 路线与停止点

```text
R2A-T05: CA q20 退出原因、阈值距离、快速重入和跨 q 结构分解
R2A-T06: 读取 point-in-time 价格未来路径，冻结 release onset、release recognition、方向和强度标签
R2A-T07: 版本注册、消费者契约与冻结
R2A-T08: 阶段验收与 R3 handoff
```

q20 仅是 `exit_mechanism_decomposition` research anchor，`q_selection_status=not_selected`。T06 的 no-lookahead/PIT 要求保留为未来 release 标签协议的强制验收组成部分；当前 T05 不实现 T06，不创建 T06 config/schema/runner，不读取价格数据。Owner 必须先审阅并明确批准精确 implementation HEAD，之后才可另行授权 formal execution；当前 `R2A-T06_allowed_to_start=false`。
