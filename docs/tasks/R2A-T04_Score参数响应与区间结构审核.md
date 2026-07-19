# R2A-T04 CA q15/q25 参数响应与区间结构审核

## 1. 当前阶段

```text
scope_id: r2a_t04_ca_q15_q25_k5_response_audit.v1
panel_id: r2a_t04_ca_q15_q25_k5_panel.v1
request_count: 2
status: authorized_not_started
authorization_revision: 5
formal_authorization_id: R2A-T04-CA-Q-AUDIT-AUTH-20260720-R5
reviewed_harness_head: fc685e451600adb9eca0e09da985d45b5352c729
reviewed_harness_Quality: 29698931225 / success
formal_run_authorized: true
formal_run_started: false
formal_run_consumed: false
R2A-T04_DONE: absent
R2A-T05_allowed_to_start: false
```

唯一输入是 accepted R2A-T01 Score release。唯一研究比较是 `CA_q15_k5` 与 `CA_q25_k5` 的 Score 参数响应和收敛区间结构。

## 2. Revision 4 失败事实

Revision 4 run `R2A-T04-20260719T090524491Z` 已开始并消费，但因性能被人工终止，只完成 `D01_P_q15_k3`，在 `D02_PA_q15_k3` 中断。其状态固定为 `terminated_incomplete_performance / rejected_incomplete`。该 revision 不可恢复、不可重跑，旧 RunRoot 不得删除或修改，结果不得接受。

## 3. 冻结请求

```text
CA_q15_k5
request_id: pcavt-dynreq-v1-cf420e9c025374d1
request_hash: cf420e9c025374d19bbc4e83bd75fee96d10d0c322605826ae5cffcf4029674f
selected_dimensions: [C, A]
q_by_dimension: {C: 1500, A: 1500}
confirmation_k: 5

CA_q25_k5
request_id: pcavt-dynreq-v1-b210f9e5211c46db
request_hash: b210f9e5211c46db6cbc41ca1da9ff340018b4ef69e56df07ae22cecafbad3e9
selected_dimensions: [C, A]
q_by_dimension: {C: 2500, A: 2500}
confirmation_k: 5
```

请求必须由 `build_canonical_request()` 构建，并继续执行 request ID/hash uniqueness 与 short-ID collision guard。

## 4. 科学检查

只允许以下四项 response checks：

1. `ca_q_joint_ready_equality`：两请求逐 security/date 的 `joint_ready` 完全相同；
2. `ca_q_raw_subset`：q=1500 raw-true keys 是 q=2500 的子集；
3. `ca_q_confirmed_subset`：q=1500 confirmed-true keys 是 q=2500 的子集；
4. `ca_q_response_non_degenerate`：raw 或 confirmed 至少一个集合严格变化。

任何 subset violation 或 readiness mismatch 阻塞；两层集合均相同则 `blocked_ca_q_response_degenerate`。旧 P→PA→PCA→PCAV→PCAVT ladder、K chain、PCAVT equal-q chain、五个 marginal request 及其 checks 不再执行或要求。

## 5. 保持不变的输出

复用 T03 canonical request validation、source validation、dimension/joint 状态公式、raw streak、K=5 confirmation、confirmed interval、termination/right-censoring、五张 output tables 与 accepted validator。继续生成 request/year/termination metrics、interval inventory、deterministic samples，以及四类 interval endpoint 上的五维和十组件 Score 结构。Endpoint 中的 P/V/T 只作上下文，不参与 CA 联合条件。

## 6. Set-based transfer repair

`src/r2a/r2a_t04_set_based_evaluator.py` 是 T04-local wrapper。它复用 T03 private helpers，唯一计算路径差异是通过 DuckDB `ATTACH '<score_data.duckdb>' AS score_source (READ_ONLY)` 和 `INSERT ... SELECT` 将 spine 与 C/A dimension rows 直接写入 staging。禁止 pandas、全量 Python rows、source `fetchall/fetchmany` 搬运、全量 `executemany` 写入和跨 request persistent cache。

T03 evaluator、T03 output contract 和 legacy `r2a_t04_real_data_audit.py` 不修改。

## 7. Benchmark 与授权顺序

Implementation HEAD 通过 Quality 后，使用固定证券 `603345.SH, 603233.SH, 688220.SH, 300316.SZ`、完整历史、threads=4，对两个 request 分别运行旧/新 evaluator，五表 schema、row count、PK、所有非键字段和 canonical profiles 必须完全一致。

随后只用新 evaluator 严格串行运行两个 full-800 benchmark。每个 request 必须 validator passed、800 securities、wall ≤600 秒、peak RSS ≤6442450944；合计 wall ≤1200 秒。Benchmark 不创建 formal authorization，不消费 attempt，不产生科学结论。

Passed receipt 提交并通过 Quality 后，才允许创建 metadata-only revision 5 authorization commit；该提交的 parent 必须是精确 evidence HEAD。授权提交 Quality 成功后仍不得在本轮运行 formal。

上述 benchmark 已通过。四证券的两 request 旧/新五表 schema、row count、PK、非键字段及 canonical profiles 全部一致，mismatch 为 0。Full-800 `CA_q15_k5` 为 203.9756 秒、peak RSS 5,042,262,016 bytes；`CA_q25_k5` 为 555.4190 秒、peak RSS 5,134,106,624 bytes；合计 759.3947 秒。两者 validator 均 passed、security count 均为 800，且所有性能 gate 通过。Receipt SHA-256 为 `59e87d0124e52411a47242d017facfd91f98659c205539364cd187a09005dd76`；evidence HEAD `fc685e451600adb9eca0e09da985d45b5352c729` 的 Quality `29698931225` 成功。

当前 metadata-only revision 5 authorization 候选只绑定上述 evidence HEAD。`formal_run_started=false`、`formal_run_consumed=false`，且授权只有在精确 authorization HEAD Quality 成功后才生效；不得在本轮运行 formal。

## 8. Compact review 与分析边界

Compact bundle 保持原 14 文件清单且总计 ≤60 MiB；request count 和 profiles count 均为 2。`result_analysis.md` 固定为 Score identity、两请求 panel、validator、joint evaluability、raw/confirmed response、interval duration、breadth、year、termination、Score endpoints、limitations、automated recommendation 十三节。

Recommendation 只能是 `continue_to_owner_result_review` 或 `blocked_evaluator_or_response_degeneracy`。不得写最佳 q、canonical q、交易信号、未来收益、回测或组合。

## 9. 停止点

最终停止在 `R2A-T04 CA two-request formal authorization review`。Revision 4 保持 consumed/unaccepted；revision 5 仅 authorized_not_started，`DONE` absent，R2A-T05 false。
