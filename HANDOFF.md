# R2A / PCAVT 研究交接

> 本文是无上下文新会话的当前入口。Revision 4 的失败事实不可改写；revision 5 尚未获得正式运行授权。

## 0. 当前状态

```text
repository: benzemaer/convergence-research
branch: codex/r2a-t04-real-data-response-audit
PR: #113 / Open / Draft

R2A-T04 scope_id: r2a_t04_ca_q15_q25_k5_response_audit.v1
panel_id: r2a_t04_ca_q15_q25_k5_panel.v1
request_count: 2
status: ca_scope_performance_repair_pending_benchmark
authorization_revision: 5
formal_authorization_id: R2A-T04-CA-Q-AUDIT-AUTH-20260720-R5
formal_run_authorized: false
formal_run_started: false
formal_run_consumed: false
R2A-T04_DONE: absent
R2A-T05_allowed_to_start: false
current_stop: R2A-T04 CA scope and set-based transfer implementation
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

## 3. Revision 5 唯一范围

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

## 4. 性能修复与 benchmark 门禁

T03 evaluator 和 output contract 不修改。T04-local evaluator 只将 Score 搬运从 Python `fetchmany/executemany` 替换为 DuckDB `ATTACH ... READ_ONLY` 与 `INSERT ... SELECT`；每个 request 仍使用独立临时 result DB，严格串行，threads=4。

Revision 5 获得授权前必须依次完成：

1. implementation HEAD Quality success；
2. 固定四证券、两个 request 的旧/新 evaluator 五表完全等价；
3. 两个 full-800 request 各自 validator passed、各 ≤600 秒、合计 ≤1200 秒、各 peak RSS ≤6442450944；
4. benchmark receipt 提交后的 evidence HEAD Quality success；
5. metadata-only authorization commit 的精确 HEAD Quality success。

旧 4/8/16 thread benchmark 不重跑，继续冻结 threads=4 与 T03 determinism evidence。Benchmark 不是 formal run，不消费 revision 5 attempt，不产生科学结论。

## 5. 禁止事项与最终停止点

当前不得执行 revision 5 formal run，不得创建 `DONE`，不得允许 R2A-T05，不得选择最佳 q、产生交易信号、使用未来收益、回测或组合。

本轮最终停止点：

```text
R2A-T04 CA two-request formal authorization review
revision_4_consumed: true
revision_4_result_accepted: false
revision_5_formal_run_authorized: true
revision_5_formal_run_started: false
revision_5_formal_run_consumed: false
request_count: 2
R2A-T04_DONE: absent
R2A-T05_allowed_to_start: false
```
