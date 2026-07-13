# R2-T04 Hard gate、Pareto 推荐、用户决策与 freeze plan

## 目标

在 R2-T03 的独立 scientific review、repository final gate 和 post-merge handoff 均通过后，对已提交的 72-cell 紧凑结果执行冻结前的硬门禁、Pareto 比较和自动推荐，并向用户请求四个 decision unit 的明确选择。Phase A 只生成可审计的比较证据，不生成 freeze decision、freeze plan、canonical state 或下游 R2-T05/R3 输入。

## 输入

输入仅来自 committed Git blobs：T03 compact profiles、T03 runtime/independent/anomaly/handoff validation、T02 v8 contract、T02 hard-gate registry、T02 metric dictionary、T02 risk-set/transition contracts，以及 T01/R1 已冻结的 shortlist 和结果包。大型 DuckDB、`data/interim/` rehearsal 数据和任何本地 decision input 都不属于正式输入。

T02 hard-gate registry 是唯一阈值权威来源；T04 不复制阈值。对于 registry 中的 upstream denominator，输入 binding 记录其来源和计算口径；缺失、解析失败、哈希不一致或 committed/worktree 不一致均 fail closed。

## Phase A 输出与停止条件

Phase A 必须保留全部 72 个 cell（四条 primary q-vector route 与四条 shared fallback route，各 9 个 d×g cell），并输出输入绑定、source readiness、hard-gate report、cell gate summary、objective registry、Pareto comparison、automatic recommendation、decision request、user-decision template、phase validation 和 experiment summary。

自动推荐严格按 `hard_gate_pass → Pareto non-dominated → pre-registered material advantage → neighborhood support → fewer warnings → lower complexity → baseline proximity` 的字典序执行，不使用加权分数。推荐不是用户决策；`selection_path_not_independently_confirmed=true` 必须保留。

Phase A 完成后状态固定为：`R2-T04_status=awaiting_user_decision`、`formal_task_completed=false`、`R2-T05_allowed_to_start=false`、`R3_allowed_to_start=false`。不得在没有显式用户决策的情况下生成最终 freeze decision/plan 或推进下游任务。

## Phase B：显式用户决策与作者阶段 freeze package

Phase B 不重跑 Phase A、T03 或 Pareto，不增加 T25/V30 interaction sidecar，也不重新打开参数搜索。它只在同一 run 目录中记录显式用户 override，重新从不可变 T02/T03 registry 和 runtime evidence 复核两个 W120 primary 及其 strict-core pair，生成 freeze decision、两条 planned state versions、结果分析、anomaly scan 和作者阶段 package。用户选择的两个 primary 为 `r2_s_pct_w120_qt25_primary__d2__g1` 与 `r2_s_pcvt_w120_qv30_primary__d2__g1`；对应 shared-q 只保留为 strict core，不产生独立版本；两个 W250 pair 均拒绝。

Phase B 的自动推荐仅作为历史 Phase A 产物，最终决策由 `decision_authority=user_explicit_instruction` 的用户记录提供；hard gate 不可被 override。作者阶段 package 必须保持 `scientific_review_status=pending_independent_scientific_review`、`formal_task_completed=false`、`R2-T05_allowed_to_start=false` 和 `R3_allowed_to_start=false`，直到独立 scientific review 和 repository final gate 完成。

## 验收

核心模块为 `src/r2/r2_t04_freeze_decision.py`、`src/r2/r2_t04_phase_b.py` 与 `src/r2/r2_t04_independent_validator.py`；薄入口分别位于 `scripts/r2/run_r2_t04_freeze_decision.py`、`scripts/r2/validate_r2_t04_freeze_decision.py` 和 `scripts/r2/validate_r2_t04_committed_artifacts.py`。独立 validator 必须重新读取 Phase A/B 文件，独立重算 cell 数、门禁归约、用户决策词汇、GLOBAL gate 继承、freeze plan 结构和 hash binding，不导入 production recommendation 或 freeze decision 逻辑。

## 失败与回退

任一正式输入缺失、哈希或 canonical text contract 不一致、硬门禁证据缺失、指标为空、异常扫描未通过或独立 validator 失败，均停止在 Phase A 并报告证据缺口。不得通过补写说明、重命名或手工设置 passed 来绕过门禁。
