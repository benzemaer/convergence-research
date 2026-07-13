# R2-T05 successor formal run 实际结果分析

本报告基于权威 successor formal run `R2-T05-20260713T154957Z` 的实际 DuckDB、compact artifacts、独立 validator 和 anomaly scan。execution commit 为 `a35bea8`，artifact commit 为 `1f9c053`。154500Z 及更早 run 已被 committed supersession records 标记为 superseded；本报告不修改或重新发布任何 R2-T04 artifact。

## 输入绑定与启动

startup gate 从 handoff 指定的 committed Git blobs 读取 T04 freeze decision、freeze plan 和 Phase B validation，并复核了三项 Git blob SHA 与 committed byte SHA-256。selected、strict-core、rejected decision-unit 数量分别为 2、2、2；planned state version 数量为 2；W250、shared-q 独立版本、PCT parent 和其他未选版本数量均为 0。

## 实际 canonical 物化

| state version | daily rows | state risk | qualified event risk | strict-core | events | membership rows |
|---|---:|---:|---:|---:|---:|---:|
| `r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8` | 1,751,066 | 20,474 | 12,803 | 12,476 | 4,561 | 22,719 |
| `r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8` | 1,751,066 | 4,564 | 2,387 | 2,939 | 1,086 | 4,669 |

event reconciliation 的 source/canonical event rows 分别为 4,561/4,561 和 1,086/1,086；membership 中 qualified event risk 分别为 12,803 和 2,387。`qualified_event_risk_set_eligible` 已进入 daily schema，并由 daily as-of membership、当前 daily state-risk 和独立重建共同验证；跨 `state_version_id × security_id` 的 active event FK violation 为 0，daily as-of 三字段独立重建 mismatch 为 0。

当前-component qualification 与 qualified-event risk 的六项语义 mismatch 均为 0：`daily_qualified_key_mismatch`、`daily_component_qualified_key_mismatch`、`qualified_component_transition_mismatch`、`unqualified_reentry_daily_qualified_rows`、`accepted_reentry_first_day_qualified_rows` 和 `accepted_reentry_qualification_day_unqualified_rows`。因此 accepted reentry 首日、qualification day 和 unqualified reentry 的逐日语义均与冻结契约一致。

## Audit 与异常

risk-set audit 的 `event_member_not_state_risk` 为 516 和 66，但这两个值是允许的 bridge/preconfirmation member diagnostic，不再被错误地判为失败；bridge、prequalification、unqualified reentry 和 qualified-not-state-risk violation 均为 0。per-version terminal rows 分别为 4,561 和 1,086。所有 compact audit status 均为 `passed`，anomaly scan 为 `passed`、`blocking_failure_count=0`。

工程 materialization validator、独立 validator 和 committed-artifact validator 均为 `passed`，failure count 均为 0。大 DuckDB 保持 local-only，不提交到 Git。

## 结论边界

这些是 successor author-stage 的结构、lineage 和数量事实；独立科学审阅已对该权威 run 给出 PASS，但不代表 final freeze、T06 replay 或交易优势。当前仍保持 `scientific_review_status=needs_revision`、`formal_task_completed=false`、`R2-T06_allowed_to_start=false`、`R2-T07_allowed_to_start=false`、`R2-T08_allowed_to_start=false` 和 `R3_allowed_to_start=false`，下游 gate 暂不启动。
