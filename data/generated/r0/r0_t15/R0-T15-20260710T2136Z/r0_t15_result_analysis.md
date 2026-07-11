# R0-T15 层级 q-vector 正式物化与 R1-T14-02 交接 result analysis

## 1. REV1 结论与门禁边界

原 formal materialization run `R0-T15-20260710T2136Z` 继续绑定 execution commit `b7cd0c2a3d4d3dbe3867246712c68107ea604c96`、v1 execution config、原 request binding、artifact manifest、candidate registry 与四张 DuckDB。外部审阅评论 `4941872279` 没有发现 vector、row count 或数值守恒错误，但判定 canonical handoff 仍携带 Windows CRLF runtime 哈希，未绑定仓库中的 LF manifest/registry 字节，因此结论为 NEEDS REVISION。

`R0-T15-REV1` 是 post-run lineage/handoff revision，不是新运行，不重算或覆盖 DuckDB，也不改写 execution summary、request binding、artifact manifest、candidate registry 或 v1 config。REV1 revision commit 为 `da902266d804944de086de5c9e4123a99f9ec318`；旧 handoff、package、analysis 与 evidence 按原字节归档，新的 canonical handoff/package 已由外部复审评论 `4943245857` 在 reviewed HEAD `3210c35a6a5a5679792bfd455969e78664fc5e13` 上判定 PASS。repository final gate 通过但 PR 尚未合并时仍必须保持 `independent_review_status=passed`、`repository_final_gate_status=passed`、`R1-T14-02_allowed_to_start=false`、`R1-T10_allowed_to_start=false`、`R2_allowed_to_start=false`、`formal_task_completed=false` 与 `selection_path_not_independently_confirmed=true`。

## 2. 执行时 lineage 与 post-run final authorization

原运行由 PR #87 author head `2e2cc2931a4c3ff1ab427966bc78f79a0f69c151` 的 goal-internal continuation 授权。其 request SHA-256 始终为 `7ee17192ae32c71d6ee839af93993b4b7f841738dbc0a17e9078ac1d1408fb33`，10-vector frozen registry、R0-T05/R0-T07 输入与科学计算实现均未变化。execution binding 中的 author package runtime hash `ceb869...` 是当时 Windows CRLF 表示；REV1 将它保留为历史事实，不拿它与现已 final 的 canonical package 路径逐字比较。

独立 scientific review 后，#87 finalization commit `be446a8fe73a8575c76bee3ee1975993010cad93` 通过 merge commit `13598861a620ab9e599957db3a34f8595630035b` 合入 main。REV1 另行绑定 #87 final result package `300bbc213a1b42b317f1a8ea7452b846ee5406882eae7aff79e9c4ce12138a35`、scientific review `bfdfb7060f01e47580edd31a96a13406bf28fec82dd14808df3973cedeacc19f` 和 final-gate validation `e7298a9acc1258143913890114c1055dbd7f0160dc81b896195af2cfe7c4558e`。这条 post-run binding 证明原 request 后来获准进入 R0-T15，但不追认运行时已经存在 repository final gate。

## 3. Handoff lineage finding 与修复

外部 finding 可逐字复现：旧 handoff 的 artifact manifest hash `4434adfa9fe0941d340ff0f16b194993894cd39c7151acb94e7565e4ea7999a9` 和 registry hash `f689b53a7603f32a54d17d71afcd36841da793746a4bdd226e97b592db54a9d3`，恰好分别等于当前 LF 文件转换为 CRLF 后的 SHA-256。仓库 canonical LF 字节实际为：

- artifact manifest：`664b6d4558978806db80912aa5e544e0c81824b188a5ea71fece8e20507a8c51`；
- candidate registry：`02fdaf1b94780ef42115a9109ae9f1fd6b90a6e019925a5067ad1bac96d4944f`。

REV1 不修改这两个 source artifacts，而是从实际 LF 字节重建 handoff，随后再生成 package。Validator 逐项检查 package↔handoff↔manifest↔registry、request 的 typed registry payload hash、旧 handoff/package archives、#87 final binding 和所有 committed artifact hashes；CRLF stale target、任一 cross-file mismatch 或任一误开的 downstream gate都会失败。

## 4. 正式输出与 local DuckDB attestation

四个 local-only DuckDB 共 `1,820,639,232` bytes，仍与原 artifact manifest 一致：

- dimension state：55,384,608 rows、8 vectors、800 securities，SHA-256 `f979cf5c13fab855842e834a2c5af67f4d488022c137140ee4098c4241c8e95a`；
- nested daily state：13,846,152 rows、8 vectors、800 securities，SHA-256 `39ec9c7c798280a67218cc32ce41b8ae854e68f4c1cf7826520c3eb91eab14d1`；
- daily confirmation：55,384,608 rows、8 vectors、800 securities，SHA-256 `310393bf78d58eaf76fa5a02aeb18cfa069c3e917ba1526c014167f9dca00d46`；
- confirmed interval：340,625 rows、8 vectors、794 securities，SHA-256 `40c3ec70e68999d0db413a57e79705d85aabd5d0f8c26c498769d4560992a171`。

REV1 validator-side attestation fresh-reread 了四库实际字节，复算 SHA、file size、row/vector/security count、schema 与主键；四表 duplicate count 均为 0，raw/confirmed parent-child violation 均为 0，confirmation/interval duration mismatch 为 0。该动作是 implementation-side fresh reread/recomputation，不是独立 reviewer 的直接字节复核：`external_direct_duckdb_byte_review_performed=false`，`independent_byte_validation_status=not_performed`。四库未提交 Git、未上传 Actions artifact，外部 reviewer 只能审查代码、manifest、reconciliation 与 committed attestation。

## 5. Frozen registry 与 baseline reconciliation

Candidate registry 仍恰好包含 request 的 10 个 vector ids：W120/W250 各一个 baseline reference、一个 T=.25 center、一个 T=.30 neighbor、一个 V=.30 center 和一个 V=.25 neighbor。8 个 nonbaseline vectors 全部物化，未新增、删除、重排或重新选择 family；两个 baseline 沿用既有正式 lineage。

W120/W250 shared baseline 的 S_PCT/S_PCVT 在 raw days、confirmed days、valid/unknown/blocked rows、interval count、confirmed duration 与 open interval 上形成 32 项 reconciliation，`mismatch_count=0`。所有 8 vectors 的 PCT/PCVT raw、confirmed、interval count 和 interval-duration 仍与 T14-01 diagnostic artifacts 对账一致。REV1 不重新评价候选优劣，也不把 same-sample selection 写成独立 confirmation。

## 6. 直接事实、有限推断与不可支持结论

直接事实是原 R0-T15 四库继续逐字匹配 manifest，registry/row/schema/PK/parent-child/duration conservation 均无退化，且 stale handoff 的 CRLF→LF 根因已定位并由新 cross-file validator 捕获。有限推断是这些结果可以作为等待重新审阅的 R0-T15 revision candidate。

仍不能声称外部 reviewer 已直接验证 1.8GB DuckDB 字节。外部 reviewer 已对 committed REV1 lineage 给出 PASS，repository final gate validator 也已通过；但 #88 merge 尚未发生，因此仍不能启动 R1-T14-02。更不能据此声称 T/V q-vector 优于 shared q、构成冻结状态、具有独立 confirmation、预测能力或交易价值。

## 7. REV1 gate 状态

```text
R0_q_vector_materialization_status=final_gate_passed_pending_merge
R0_q_vector_materialization_request_status=approved
independent_review_status=passed
repository_final_gate_status=passed
goal_internal_continuation_gate_status=closed_pending_repository_merge
goal_internal_continuation_allowed=false
goal_internal_t14_02_authorized=false
repository_t14_02_gate_passed=false
R1-T14-02_allowed_to_start=false
R1-T10_allowed_to_start=false
R2_allowed_to_start=false
selection_path_not_independently_confirmed=true
external_direct_duckdb_byte_review_performed=false
formal_task_completed=false
```

外部 reviewer 已对 REV1 给出 PASS，repository final gate validator 也已通过。本 final-gate commit 只将 README 标记为 `final_gate_passed_pending_merge`；在 #88 合并前不授权 R1-T14-02，不触碰 #89 的 authoritative dependency，也不把旧 #89 结果作为当前 evidence。

## 8. 外部复审记录与 merge 边界

外部复审评论 `4943245857` 绑定 reviewed HEAD `3210c35a6a5a5679792bfd455969e78664fc5e13`、REV1 package `078cb456...` 与 handoff `438d2f09...`，结论为 PASS，blocking findings 为空。复审没有直接读取四张 local-only DuckDB，因此 `external_direct_duckdb_byte_review_performed=false` 与 `independent_byte_validation_status=not_performed` 继续保留。被复审的 package、analysis 与 evidence 已按原字节归档；canonical handoff 不作修改。repository final gate 的作用域仅到 #88 merge candidate，不会提前打开 R1-T14-02、R1-T10 或 R2。
