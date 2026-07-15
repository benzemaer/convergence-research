# Sidecar experiments

本目录只记录独立支线探索，不替代 `docs/tasks/README.md`，也不改变 R0–R6 的任何 gate、状态定义、freeze manifest 或主线任务指针。

当前 sidecar 状态：

```text
current_sidecar_task: EXP-C01 C层 C1/C2 单指标消融（W120）
workflow_mode: same_pr
phase: implementation_review
implementation_review_status: pending
reviewed_implementation_sha:
formal_run_allowed: false
formal_run_status: not_started
result_review_status: not_started
readme_advanced: false
mainline_task_unchanged: true
mainline_current_task: R3-T02
```

EXP-C01 采用同一个 Draft PR 的两阶段流程：先审 implementation commit；只有用户明确批准 `reviewed_implementation_sha` 后，才允许在后续阶段执行 formal run 并提交 results / manifest / analysis。当前没有正式结果，也没有创建正式 `<RUN_ID>` 结果目录。

EXP-C01 的 formal runner 还要求显式 `--input-manifest <exact-authorized-manifest-path>`。输入 artifact 必须由该 manifest 声明，runner 会校验 source-manifest SHA、artifact SHA、完整表行数、table identity 和 required columns，并记录完整表行数与过滤查询行数；不会通过目录递归搜索或同名文件猜测输入。正式结果的 analysis 只有在六个 CSV readback、独立统计复算、reconciliation、anomaly scan 和最终 governance-file validation 全部完成后，才会给出 `ready_for_user_formal_result_review` 或 `needs_investigation_before_user_review`。

除非用户在 Formal-result 审阅后同时指定下一项 sidecar 任务，否则不得自行推进 `current_sidecar_task`。
