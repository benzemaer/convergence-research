# Sidecar experiments

本目录只记录独立支线探索，不替代 `docs/tasks/README.md`，也不改变 R0–R6 的任何 gate、状态定义、freeze manifest 或主线任务指针。

当前 sidecar 状态：

```text
current_sidecar_task: EXP-C01 C层 C1/C2 单指标消融（W120）
workflow_mode: same_pr
phase: completed
implementation_review_status: approved
reviewed_implementation_sha: 58020f299b2c1def96c10eb49778afd6d1eb09d5
formal_run_allowed: true
formal_run_status: completed
result_review_status: accepted
formal_run_executed: true
formal_run_id: EXP-C01-20260715T181429267Z
formal_result_readback_status: passed
result_analysis_readiness: ready_for_user_formal_result_review
EXP-C01_status: completed_accepted
accepted_run_id: EXP-C01-20260715T181429267Z
accepted_result_commit: 54ed238609d116c784b121a5b6df72e4c0179fc8
execution_sha: 58020f299b2c1def96c10eb49778afd6d1eb09d5
authorized_input_manifest_sha256: 2d10de31897955595a33d642cfdfe57773b3304a8bd0b763aea56253a5e9e0fa
replacement_decision: not_approved
selected_indicator: none
retain_current_C1_C2_pair: true
readme_advanced: true
mainline_task_unchanged: true
mainline_current_task: R3-T02
```

EXP-C01 采用同一个 Draft PR 的两阶段流程：先审 implementation commit，再审 formal result。`EXP-C01-20260715T181429267Z` 已在批准的 implementation SHA 上完成；工程 validator、anomaly scan、baseline reconciliation、磁盘 readback 和独立统计复算均通过，并已由用户接受。接受结论为保留当前 C1+C2 pair，不批准单指标替代、删除指标或 C v2；本任务标记为 `completed_accepted`。`current_sidecar_task` 保持 EXP-C01，不创建或推进下一项 sidecar task。

EXP-C01 的 formal runner 还要求显式 `--input-manifest <exact-authorized-manifest-path>`。输入 artifact 必须由该 manifest 声明，runner 会校验 source-manifest SHA、artifact SHA、完整表行数、table identity 和 required columns，并记录完整表行数与过滤查询行数；不会通过目录递归搜索或同名文件猜测输入。正式结果的 analysis 只有在六个 CSV readback、独立统计复算、reconciliation、anomaly scan 和最终 governance-file validation 全部完成后，才会给出 `ready_for_user_formal_result_review` 或 `needs_investigation_before_user_review`。

除非用户在 Formal-result 审阅后同时指定下一项 sidecar 任务，否则不得自行推进 `current_sidecar_task`。
