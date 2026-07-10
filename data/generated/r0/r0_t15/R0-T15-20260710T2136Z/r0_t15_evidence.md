# R0-T15 层级 q-vector 正式物化与 R1-T14-02 交接 evidence

```text
task_id=R0-T15
run_id=R0-T15-20260710T2136Z
code_commit=b7cd0c2a3d4d3dbe3867246712c68107ea604c96
task_class=formal_materialization_bridge
upstream_pr_number=87
upstream_head_commit=2e2cc2931a4c3ff1ab427966bc78f79a0f69c151
```

## 运行事实

request registry 为 10 个 entries：2 个 baseline lineage references 与 8 个 nonbaseline materialized vectors。四个正式 DuckDB 共包含 55,384,608 dimension rows、13,846,152 nested rows、55,384,608 confirmation rows 与 340,625 intervals。四库最终 SHA-256 已写入 artifact manifest；大文件不提交到 Git，但在本地保持可读取、可复算。

## 验收事实

baseline reconciliation 共 32 项，mismatch_count=0。四表 schema 与 PK passed，duplicate count=0；parent-child violation=0；每个 vector/state 的 confirmed count 与 interval duration 守恒；unknown/blocked 未静默转换；8 个 vectors 的 PCT/PCVT 数值与 T14-01 diagnostic artifact 完全一致。engineering validator 与 anomaly scan passed，`blocking_findings=[]`、`unresolved_questions=[]`。

## 门禁边界

```text
R0_q_vector_materialization_status=author_draft_complete
engineering_validator_status=passed
author_result_analysis_status=passed
anomaly_resolution_status=passed
goal_internal_continuation_gate_status=passed
goal_internal_continuation_allowed=true
goal_internal_t14_02_authorized=true
independent_review_status=not_started
repository_final_gate_status=pending
repository_t14_02_gate_passed=false
R0_q_vector_materialization_request_status=pending_external_review
R1-T14-02_allowed_to_start=false
R1-T10_allowed_to_start=false
R2_allowed_to_start=false
formal_task_completed=false
```

内部 continuation 只授权基于精确 PR-B head、artifact manifest hash、result package hash 和 analysis hash 构建 stacked Draft PR-C，不替代外部审阅、README gate 或正式 request fulfillment。
