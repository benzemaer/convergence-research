# R1-T14-01 层级 q 单变量响应诊断与候选提名 evidence

```text
task_id=R1-T14-01
run_id=R1-T14-01-20260710T2113Z
code_commit=9b7ff557e7bf5f01f0984b7d89f9e51b3ba8778b
task_class=exploratory_structural_diagnostic
diagnostic_namespace=r1_t14_01_diagnostic_only
authoritative=false
formal_candidate_state=false
```

## 输入与运行

正式运行逐字消费版本化 config `configs/r1/r1_t14_01_layer_q_response_diagnostic.v1.json`。输入 dimension score、baseline daily confirmation 和 baseline interval 的 SHA-256 分别为 `4a04fbada9ecac15936e3ab5d968cba8f1205db5dbe66a0491c7141e6fc5b8a5`、`e9bcaafbd60229b6d9e01967cedb2739efb3407159a66d1ef47b3d779689b4e3`、`583187e213edc7b9796d5db5ef0b5484ad4b3fb17624212796ea1b9a721208ad`。34/34 vectors 完成，未读取未来结果或交易结果。

## 工程与结果验收

engineering validator status 为 passed；32 项 baseline reconciliation 的 mismatch_count 合计为 0；anomaly scan status 为 passed，`blocking_findings=[]`、`unresolved_questions=[]`。四个 center 的 raw counts 已从 score DuckDB 独立复算，四组 pooled Delta/Lift 已由 2×2 counts 独立复算，均与提交 artifact 相等。当前 run 与前一完整 run 的核心 artifacts 逐 hash 一致。

## Author-side decision

decision 为 `q_vector_materialization_request`。冻结 centers 是 W120/W250 的 T=.25 PCT vectors 与 V=.30 PCVT vectors；mandatory nonbaseline neighbors 是对应的 T=.30 与 V=.25，另绑定两个 shared-baseline references。nonbaseline formal vector count 为 8，未超过 10。request 的最终 SHA-256 由 author result package 在写入内部 continuation 状态后按最终字节绑定。

## 门禁边界

```text
engineering_validator_status=passed
author_result_analysis_status=passed
anomaly_resolution_status=passed
goal_internal_continuation_gate_status=passed
goal_internal_continuation_allowed=true
scientific_review_status=passed
reviewer_identity=benzemaer
independence_attestation=true
repository_final_gate_status=passed
downstream_gate_allowed=true
downstream_gate_scope=R0-T15_only
R0_q_vector_materialization_task_id=R0-T15
R0_q_vector_materialization_request_status=approved
R0_q_vector_materialization_allowed_to_start=true
R1-T14-02_allowed_to_start=false
R1-T10_allowed_to_start=false
R2_allowed_to_start=false
formal_task_completed=true
selection_path_not_independently_confirmed=true
```

外部 scientific review 已在 GitHub comment `4941866339` 记录为 PASS，并由本 evidence 绑定到独立 review record。final gate 只授权 R0-T15 消费冻结 request；R1-T14-02、R1-T10 与 R2 继续关闭，且同一样本选择路径仍不得表述为独立确认。
