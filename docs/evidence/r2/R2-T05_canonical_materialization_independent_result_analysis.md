# HISTORICAL / SUPERSEDED / DO NOT USE

# R2-T05 canonical materialization independent result analysis

本报告基于已失效的 formal run `R2-T05-20260713T154500Z` 的 compact artifacts 和本地 DuckDB 读取结果编写，execution commit 为 `ef75bfbdd0be95f7a0d889a2f34cef1ce858c627`。该 run 已被后续 successor run supersede，不得作为当前 evidence、formal input、参数选择或 README gate 依据。报告不修改、不重新发布任何 R2-T04 artifact，也不替代 independent scientific review、repository final gate 或 R2-T06 replay。

## 输入与启动授权

T05 startup contract 状态为 `passed`。handoff 和 validation sidecar 的门禁字段均通过；T04 的 `freeze_decision`、`freeze_plan_manifest` 和 `phase_b_independent_validation` 均按 handoff 的 `committed_inputs` 从 source commit `981be003101668200e3c3c97ea491f7b2ab1c5fa` 的 Git blobs 读取，并通过 Git blob SHA 与 committed byte SHA-256 复核。T04 artifact 未被修改或重新发布。

冻结输入独立复核结果为：`selected_version_count=2`、`strict_core_only_count=2`、`rejected_decision_unit_count=2`、`planned_state_version_count=2`，两个 planned version 的 version ID、candidate cell、strict-core pair、W/K/q/d/g 与冻结决策一致。W250、shared-q 独立版本、PCT parent 和额外 selected candidate 的物化数量均为 0。

## 实际物化事实

| state version | daily rows | eligible | raw true | confirmed | state risk | strict-core | events | membership rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8` | 1,751,066 | 1,602,732 | 52,420 | 20,474 | 20,474 | 12,476 | 4,561 | 22,719 |
| `r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8` | 1,751,066 | 1,601,692 | 16,073 | 4,564 | 4,564 | 2,939 | 1,086 | 4,669 |

事件表共 5,647 条，event ID lineage 与 canonical event 一一对应。S_PCT 事件覆盖 771 个证券、4,733 个组件区间、172 个 bridge day；S_PCVT 事件覆盖 579 个证券、1,108 个组件区间、22 个 bridge day。membership 中的 prequalification、bridge 和 unqualified reentry 行均未扩张 qualified event risk set。

## 质量与异常结果

independent validator 状态为 `passed`，`failure_count=0`。实际复核包括 source DuckDB SHA-256、daily key surface、source fact reconciliation、strict-core exact-key subset、event count、membership source join、event ID 独立重算、membership row-level reconciliation、availability as-of、risk formula、bridge/prequalification exclusion、event revision、forbidden field 和 output manifest hash。

anomaly scan 状态为 `passed`，`blocking_failure_count=0`，未发现 strict-core subset violation、risk-set expansion、quality-break natural exit conflict 或 event-zone revision regression。committed artifact validation 状态为 `passed`，`failure_count=0`。大型 T05 DuckDB 保持 local-only，不提交到 Git。

## 结论边界

直接统计事实表明，两个 T04 selected W120 primary 已完成 selected-only canonical daily state、event zone 和 membership 的 author-stage 物化，并通过独立结构与 lineage 复核。上述结果不说明状态释放方向、未来收益、因果机制或交易优势；T05 result package 仍保持 `formal_task_completed=false`、`scientific_review_status=pending_independent_scientific_review`、`R2-T06_allowed_to_start=false` 和 `R3_allowed_to_start=false`。
