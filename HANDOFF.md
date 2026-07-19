# R2A / PCAVT 研究交接

> 本文是无上下文新会话的当前入口。Revision 5 正式结果有效且通过独立复核，但在 owner 接受前由四档 q scope 取代，不能作为 T04 最终关闭证据。

## 0. 当前状态

```text
repository: benzemaer/convergence-research
branch: codex/r2a-t04-real-data-response-audit
PR: #113 / Open / Draft

R2A-T04 scope_id: r2a_t04_ca_q10_q15_q20_q25_k5_response_audit.v1
panel_id: r2a_t04_ca_four_q_k5_panel.v1
request_count: 4
status: ca_four_q_scope_expansion_pending_benchmark
authorization_revision: 6
formal_authorization_id: R2A-T04-CA-FOUR-Q-AUDIT-AUTH-20260720-R6
reviewed_harness_head: null
formal_run_authorized: false
formal_run_started: false
formal_run_consumed: false
R2A-T04_DONE: absent
R2A-T05_allowed_to_start: false
current_stop: R2A-T04 CA four-q scope-expansion implementation
```

## 1. 已接受基线

```text
R2A-T01: completed_accepted
score_release_id: pcavt-score-w120-v1-c7e04f11a2cd09aa
score_database_sha256: d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3
score_database_byte_size: 4255395840

R2A-T02: completed_accepted
dynamic_protocol_version: pcavt_dynamic_state_protocol.v1

R2A-T03: completed_accepted
evaluator_version: r2a_t03_dynamic_evaluator.v1
output_schema_version: r2a_t03_dynamic_evaluation_output.v1
```

长期架构仍是 immutable Score release → parameterized evaluator → request-scoped states/intervals。R2A-T04 不注册 canonical dynamic state。

## 2. Revision 4 不可变失败历史

```text
revision_4_authorization_head: bd906df6b314352dccde75bc087709503d5e2262
revision_4_run_id: R2A-T04-20260719T090524491Z
revision_4_formal_authorization_id: R2A-T04-REAL-AUDIT-AUTH-20260719
revision_4_formal_run_started: true
revision_4_formal_run_consumed: true
revision_4_formal_run_completed: false
revision_4_result: terminated_incomplete_performance
revision_4_completed_request_count: 1
revision_4_completed_request: D01_P_q15_k3
revision_4_interrupted_request: D02_PA_q15_k3
revision_4_result_review_status: rejected_incomplete
```

Revision 4 不可恢复、不可重跑，结果不得接受；旧 RunRoot 不得删除或修改。

## 3. Revision 5 有效但未接受的历史

```text
revision_5_run_id: R2A-T04-20260719T212259066Z
revision_5_formal_run_started: true
revision_5_formal_run_consumed: true
revision_5_formal_run_completed: true
revision_5_automated_validation: passed
revision_5_independent_review: passed
revision_5_owner_result_review: not_accepted
revision_5_result_status: valid_scope_superseded_before_owner_acceptance
revision_5_superseded_reason: owner_requested_q10_q20_scope_extension
```

Revision 5 没有失败、不可重跑，本地 formal artifacts 不得修改或删除；它未被 owner 接受，不能作为 T04 最终 accepted closure。其 q15/q25 panel 与 benchmark evidence 继续作为不可变历史。

## 4. Revision 6 四档 q active scope

Panel 顺序固定为 q10、q15、q20、q25；新增 canonical identity 为：

```text
CA_q10_k5: pcavt-dynreq-v1-d07aae4bbbd98f88
request_hash: d07aae4bbbd98f88989cf6b50c3b808935f237cd69f56271f6a210aa90f7ac8f
CA_q20_k5: pcavt-dynreq-v1-21bd144aaed98d9e
request_hash: 21bd144aaed98d9e7d404aaa8d2fa0685f7ec29a3deb714d0d1df99c05d5e971
```

四档只描述固定 C+A、K=5 下 q=1000/1500/2000/2500 的响应曲线，不选择 q。门禁恰有八项：四请求 joint-ready equality、三个相邻 raw subset、三个相邻 confirmed subset、整个 ladder 至少一次严格变化。相邻集合允许相同；区间数与持续期等只报告，不设单调硬门禁。

## 5. Revision 5 冻结范围（历史）

Panel 顺序与 canonical identity：

```text
CA_q15_k5
selected_dimensions: [C, A]
q_by_dimension: {C: 1500, A: 1500}
confirmation_k: 5
request_id: pcavt-dynreq-v1-cf420e9c025374d1
request_hash: cf420e9c025374d19bbc4e83bd75fee96d10d0c322605826ae5cffcf4029674f

CA_q25_k5
selected_dimensions: [C, A]
q_by_dimension: {C: 2500, A: 2500}
confirmation_k: 5
request_id: pcavt-dynreq-v1-b210f9e5211c46db
request_hash: b210f9e5211c46db6cbc41ca1da9ff340018b4ef69e56df07ae22cecafbad3e9
```

科学门禁只有四项：joint-ready equality、raw subset、confirmed subset，以及 raw/confirmed 至少一项 strict non-degeneracy。旧维度 ladder、K chain、PCAVT equal-q chain 和单维 marginal checks 已退出 active scope。

每个 request 仍复用 accepted T03 的 dimension/joint/streak/confirmation/interval 公式、五表输出和 validator。五维/十组件 Score endpoint 只作为四类 interval anchor 的诊断上下文，不表示 P/V/T 参与 CA request。

## 6. 性能修复与 benchmark 门禁

T03 evaluator 和 output contract 不修改。T04-local evaluator 只将 Score 搬运从 Python `fetchmany/executemany` 替换为 DuckDB `ATTACH ... READ_ONLY` 与 `INSERT ... SELECT`；每个 request 仍使用独立临时 result DB，严格串行，threads=4。

Revision 6 获得授权前必须依次完成 implementation Quality、q10/q20 supplemental equivalence/performance benchmark、evidence Quality 和 metadata-only authorization Quality。既有 q15/q25 receipt SHA-256 `59e87d0124e52411a47242d017facfd91f98659c205539364cd187a09005dd76` 不得改写或重跑。Supplemental benchmark 必须满足 q10/q20 各 ≤600 秒、合计 ≤1200 秒、各 peak RSS ≤6442450944，且结合既有 q15/q25 结果的四档总时长 ≤2400 秒。

历史 revision 5 获得授权前曾依次完成：

1. implementation HEAD Quality success；
2. 固定四证券、两个 request 的旧/新 evaluator 五表完全等价；
3. 两个 full-800 request 各自 validator passed、各 ≤600 秒、合计 ≤1200 秒、各 peak RSS ≤6442450944；
4. benchmark receipt 提交后的 evidence HEAD Quality success；
5. metadata-only authorization commit 的精确 HEAD Quality success。

旧 4/8/16 thread benchmark 不重跑，继续冻结 threads=4 与 T03 determinism evidence。Benchmark 不是 formal run，不消费 revision 5 attempt，不产生科学结论。

前四项已经完成：set-based implementation HEAD `cd41877a3423d7760eacc148049d6cbcbc8ed5c7` 的 Quality `29697311968` 成功；固定四证券的两请求旧/新五表完全等价；full-800 `CA_q15_k5` 与 `CA_q25_k5` 分别为 203.98 秒和 555.42 秒，合计 759.39 秒，validator 与性能 gate 均通过；benchmark receipt SHA-256 为 `59e87d0124e52411a47242d017facfd91f98659c205539364cd187a09005dd76`；evidence HEAD `fc685e451600adb9eca0e09da985d45b5352c729` 的 Quality `29698931225` 成功。当前只等待 metadata-only authorization HEAD 的精确 Quality，不得由此自动启动 formal。

## 7. 禁止事项与最终停止点

当前不得执行 revision 6 formal run，不得创建 `DONE`，不得允许 R2A-T05，不得选择最佳 q、产生交易信号、使用未来收益、回测或组合。

本轮最终停止点：

```text
R2A-T04 CA four-q formal authorization review
revision_4_consumed: true
revision_4_result_accepted: false
revision_5_formal_run_completed: true
revision_5_owner_result_review: not_accepted
revision_5_result_status: valid_scope_superseded_before_owner_acceptance
revision_6_formal_run_authorized: false
revision_6_formal_run_started: false
revision_6_formal_run_consumed: false
request_count: 4
R2A-T04_DONE: absent
R2A-T05_allowed_to_start: false
```
