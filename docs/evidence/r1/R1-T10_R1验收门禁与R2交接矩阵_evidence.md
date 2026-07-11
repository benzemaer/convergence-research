# R1-T10 R1 验收门禁与 R2 交接矩阵：author evidence

Run：`R1-T10-20260711T2000Z`。REV3 为只读重建，不重跑 R1-T04 至 R1-T14-02。上游 task 数 12，schema-aware reconciliation 12/12 passed；矩阵 12 行；shared/center/neighbor 为 4/4/4；四类状态为 4/6/2/0。source hash mismatch、superseded source、upstream reconciliation failure、parent-child violation、decision mismatch 和 unresolved optional trigger 均为 0。

REV3 保留 q-vector `target_marginal` 字段映射、PCT/PCVT nested null family 确定性映射、逐行 source lineage 和 decision recomputation。所有矩阵行均通过 `retention = Lift x target_marginal` 与 `Delta = retention - target_marginal`；PCT q-vector 绑定 `F4_T_GIVEN_PC`，PCVT q-vector 绑定 `F5_V_GIVEN_PCT`。validator 现在使用独立只读 precedence engine，不再导入 builder decision function，并按 R1 状态定义区分 input/lineage failure 的 `blocked_return_to_R0` 与 scientific hard-gate failure 的 `do_not_freeze`。`r1_t10_readme_transition_artifact.json` 显式绑定 T14-02 final README hash、PR #89 merge commit、当前 README hash、允许字段和实际字段级变化。

REV3 failure-path tests 使用完整合法 fixture，mutation 前先断言 validator passed，mutation 后检查特定 error code。覆盖 upstream fail、superseded/duplicate source、review/final-gate fail、source hash mismatch、缺失 marginal、错误 F4/F5 nested family、warning loss、scientific hard-gate precedence mismatch、optional-trigger conflict 和非法 README transition。上游 evidence registry 也已补齐具体 lineage：正式任务绑定真实 merge commit，T02/T03 通过 legacy adapter 绑定历史 commit，不再携带 `repository_main_history` 占位。

工程 validator 通过不等于科学审阅通过。本证据保持 `scientific_review_status=pending`、`independent_review_status=pending_external_rereview`、`repository_final_gate_status=pending`、`formal_task_completed=false`、`R2_allowed_to_start=false`。
