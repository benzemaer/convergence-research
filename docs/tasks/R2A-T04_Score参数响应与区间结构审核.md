# R2A-T04 CA q10/q15/q20/q25 参数响应与区间结构审核

## 1. 接受状态

```text
status: completed_accepted
scope_id: r2a_t04_ca_q10_q15_q20_q25_k5_response_audit.v1
panel_id: r2a_t04_ca_four_q_k5_panel.v1
accepted_run_id: R2A-T04-20260720T002158508Z
accepted_execution_head: 1d34cf49b9816aac92837213fa668356d5c7b45d
formal_authorization_id: R2A-T04-CA-FOUR-Q-AUDIT-AUTH-20260720-R6
authorization_revision: 6
formal_run_consumed: true
formal_run_completed: true
additional_formal_run_allowed: false
formal_result_review_status: accepted
owner_result_review: accepted
R2A-T04_DONE: present
R2A-T05_allowed_to_start: true_after_PR_113_merge
```

唯一输入是 accepted R2A-T01 Score release。T04 接受的是固定 C+A、K=5 下 q=1000/1500/2000/2500 的 formal 参数响应证据，不选择最佳 q。

## 2. 不可变历史

Revision 4 run `R2A-T04-20260719T090524491Z` 已消费并因性能中止，状态为 `terminated_incomplete_performance / rejected_incomplete`。Revision 5 run `R2A-T04-20260719T212259066Z` 自动验证和独立复核均 passed，但在 owner 接受前因 q10/q20 scope extension 而成为 `valid_scope_superseded_before_owner_acceptance`。两者均不可重跑或改写。

Revision 6 run `R2A-T04-20260720T002158508Z` 是本 task 唯一 accepted run。它严格串行执行四个 request，DuckDB threads=4，四个 validator 与 formal validation 均 passed，benchmark profile mismatch、response violation、scope mismatch、interval/Score reconciliation failure 和 blocking anomaly 均为 0。

## 3. 请求与正式事实

| Request | Request ID | Request hash | q(C/A) | Raw true | Confirmed true | Intervals | Securities with interval |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| CA_q10_k5 | `pcavt-dynreq-v1-d07aae4bbbd98f88` | `d07aae4bbbd98f88989cf6b50c3b808935f237cd69f56271f6a210aa90f7ac8f` | 1000 | 20,559 | 1,916 | 751 | 473 |
| CA_q15_k5 | `pcavt-dynreq-v1-cf420e9c025374d1` | `cf420e9c025374d19bbc4e83bd75fee96d10d0c322605826ae5cffcf4029674f` | 1500 | 46,651 | 7,125 | 2,426 | 734 |
| CA_q20_k5 | `pcavt-dynreq-v1-21bd144aaed98d9e` | `21bd144aaed98d9e7d404aaa8d2fa0685f7ec29a3deb714d0d1df99c05d5e971` | 2000 | 81,535 | 17,642 | 5,372 | 775 |
| CA_q25_k5 | `pcavt-dynreq-v1-b210f9e5211c46db` | `b210f9e5211c46db6cbc41ca1da9ff340018b4ef69e56df07ae22cecafbad3e9` | 2500 | 124,893 | 35,098 | 9,107 | 788 |

所有请求的 `selected_dimensions=[C,A]`、`confirmation_k=5`，且 selection status 均为 `evaluated_not_selected`。

## 4. 接受的响应结论

八项 response checks 全部 passed：joint-ready equality、三个相邻 raw subset、三个相邻 confirmed subset 和 ladder non-degeneracy。所有 violation count 为 0，raw 与 confirmed 的三个相邻台阶均为 strict change。

允许冻结的结论是：在固定 C+A、K=5、相同全市场 observation spine 条件下，q=1000→1500→2000→2500 形成严格、无违例的 raw-state 和 confirmed-state 嵌套扩张梯度；随 q 放宽，raw-state、confirmed-state、confirmed interval 和出现过区间的证券覆盖增加。

```text
q_selection_status: not_selected
canonical_dynamic_request_selected: false
selected_request_id: null
selected_request_hash: null
selected_q_by_dimension: null
```

不得宣称 q10、q15、q20 或 q25 最好或已成为 canonical。

## 5. Independent review 与证据链

首次 independent review 因 operator 输入路径错误而失败，failed receipt 位于 `operator-logs/R2A-T04-20260720T002158508Z.independent.attempt1.failed.receipt.json`，SHA-256 为 `81da003835f045c1938ebc36f9d7dfc9d22a1b020c44a41a55ca00051b2c98b1`。该记录属于 operator invocation evidence，没有复制进 RunRoot，也不是 formal computation 或 result mismatch。

Owner 授权 successor independent review 后，在不重跑 formal request、不修改 formal package 的条件下，对同一 run 完成复核。最终 receipt 位于 `formal-runs/R2A-T04-20260720T002158508Z/independent_review_receipt.json`，SHA-256 为 `8b698c68deb5053634cac9affcb1be7946c6f5b97dc66215a138105efe0eac16`，status passed、Score identity passed、mismatch count 0。

## 6. Closure 边界

Accepted handoff 与唯一 `DONE` 位于 `data/generated/r2a/r2a_t04/R2A-T04-20260720T002158508Z/`。T04 acceptance 表示 formal parameter-response evidence accepted，不表示 parameter selected、dynamic state registered 或 trading signal authorized。

R2A-T05 仅可在 PR #113 merge 后启动。本 closure 不定义或启动 T05 implementation，最终停止点为 `R2A-T04 accepted closure review`。
