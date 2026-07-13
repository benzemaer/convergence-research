# R2-T06 canonical 状态机无前视回放与一致性验收

## 目标

从 T03 committed `route_dense_input` 独立重建冻结的确认状态、atomic interval、component qualification、event zone、membership 与 canonical daily as-of，验证 T05 权威产物的一致性，并证明 membership availability time 不产生前视。

## 启动授权

T06 使用 `merged_pr_direct_binding`。启动授权绑定已合并的 PR #97、merge commit `db0a44e481b8d7389b3e72f4a2425ad89bf766ef`、最终 head `9ab4ddc77fce8c662e2159ad3f541fe354640b09`、科学审阅 head `d3a18236e2c60775c0248642b3fadec2007afd90`、review `4686515222`、权威 T05 run `R2-T05-20260713T154957Z`、execution commit `a35bea847f8f7b923c1196f1341be32494f394ef` 和 artifact commit `1f9c0538138e829904976308e6c012f67aa249c4`。启动时仅使用本地 Git objects 与 committed artifacts；不创建或要求 T05 post-merge handoff。

## 范围与非目标

本 task 不修改 T04/T05 artifacts，不重开 T05，不生成新的 T05 formal run，不使用 T03 event-zone 输出作为 T06 replay input，也不推进科学审阅或 R2-T07/R3 gate。T05 canonical database 只作为只读的 authoritative reconciliation target。

## 验收

必须通过 merged-PR binding、T03/T05 database hash、source committed text binding、双版本 daily exact reconciliation、event/membership exact reconciliation、current-component qualification、accepted reentry 与 unqualified reentry、strict-core subset、event FK、availability-time 和 transition lineage 检查。formal runner、independent validator 与 committed-artifact validator 任一失败均 fail closed。

当前 successor formal evidence 记录于 `docs/evidence/r2/R2-T06_canonical_replay_successor_result_analysis.md`，权威 run 为 `R2-T06-20260713T183455Z`。旧 `R2-T06-20260713T174639Z` 已标记为 incomplete/superseded，不得作为当前 evidence。

author-stage 结果保持：

```text
scientific_review_status=pending_independent_scientific_review
formal_task_completed=false
R2-T07_allowed_to_start=false
R3_allowed_to_start=false
```

正式 run、artifact commit、PR 和 exact-head CI 记录在对应 evidence 中补充；未通过科学审阅前不得将结果写成正式研究结论。
