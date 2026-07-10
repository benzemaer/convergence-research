# R1-T06 层间同期留存、关联 Lift 与嵌套增量

`task_id`: R1-T06
`task_class`: formal_experiment
`protocol_version`: R1.v0.3.R1-T06.v1
`status`: author_draft_pending

本 task 在 R1-T05 final-gate 已完成并合并后启动，只研究三个预注册同期层间步骤：`C_GIVEN_P`、`T_GIVEN_PC`、`V_GIVEN_PCT`。目标是描述前序构念成立时下一层构念同期成立的 retention、同一合法样本中的 target marginal rate、Lift、正式 Delta、non-anchor contrast 与 joint excess，并检查 denominator、availability、年份和证券层面的描述性稳定性。

本 task 不研究形成顺序、滞后、因果、预测能力、交易价值、经验 p-value、z-score、permutation/null model、未来收益、释放路径、回测、参数选择、冻结候选或 R2 候选。`Lift > 1` 只能写作同期描述性关联，不得写作层间因果、时序形成或预测增量。

## 输入与 Lineage

正式输入锁定 repaired R0 artifacts：

`dimension_score`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_dimension_score_results.duckdb`
`sha256`: `4a04fbada9ecac15936e3ab5d968cba8f1205db5dbe66a0491c7141e6fc5b8a5`
`row_count`: 20769228

`dimension_state`: `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_dimension_state_results.duckdb`
`sha256`: `bbbb49ea2056bf6f257c1821236eb2b657eb1490153dfc9e56acee8f33264e08`
`row_count`: 62307684

`nested_daily_state`: `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_nested_daily_state_results.duckdb`
`sha256`: `0c07f4897d76c0a729963118c2e75581bd71521a25245d6d3b650b4f32e68995`
`row_count`: 15576921

R1-T05 gate 必须为 `status=completed`、`scientific_review_status=passed`、`anomaly_resolution_status=passed`、`downstream_gate_allowed=true`，且 README 当前任务必须仍为 R1-T06、`R1-T07_allowed_to_start=false`。

## Grid 与 Denominator

固定 `W={120,250,500}`、`q={0.10,0.20,0.30}`、`K=not_applicable`、`weak_delta=0.10`、`dimension_rule=weak`，恰好输出 `3 steps × 3 W × 3 q = 27` 行 primary results。Primary baseline 为 `W=250/q=0.20`，四个 challengers 为 `W120/q20`、`W500/q20`、`W250/q10`、`W250/q30`。

Denominator 使用 step-specific minimal common-valid sample：`C_GIVEN_P` 只要求 P/C valid，`T_GIVEN_PC` 只要求 P/C/T valid，`V_GIVEN_PCT` 要求 P/C/T/V valid。不得对 C/T 统一使用 all-four common denominator，all-four 只能作为 denominator sensitivity sidecar。

## 输出

正式 run 目录为 `data/generated/r1/r1_t06/<RUN_ID>/`。必须提交 summary、primary profile、denominator sensitivity、year profile、security summary、R0 nested reconciliation、dimension state reconciliation、diagnostic summary、anomaly scan、engineering validation result、result package 和 author-draft GOV validation result。大型逐日 payload 不提交。

作者分析文档为 `docs/experiments/r1/R1-T06_contemporaneous_retention_lift_nested_increment_result_analysis.md`，evidence 文档为 `docs/evidence/r1/R1-T06_contemporaneous_retention_lift_nested_increment_evidence.md`。

## Author-Draft Stop Condition

首次执行必须停在 author-draft：

`status=author_analysis_complete`
`scientific_review_status=pending`
`review_phase=author_analysis_complete`
`downstream_gate_allowed=false`
`R1-T07_allowed_to_start=false`

Codex 首次执行不得生成 passed scientific review，不得推进 README 到 R1-T07，不得把 Draft PR 转 ready-for-review 或合并。
