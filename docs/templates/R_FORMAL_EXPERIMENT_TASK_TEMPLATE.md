# R Formal Experiment Task Template

## Task Class

填写 `task_class = formal_experiment`，或说明为何属于 contract-only / schema-only / refactor-only / synthetic-only / smoke-only / pure materialization exemption。

## 研究问题

描述预注册研究问题、样本范围和该任务要回答的最小问题。

## 预注册假设

列出 expected direction、expected null behavior、expected parameter response，以及不能在运行后调整的判断标准。

## 输入 Package

记录 input package path、sha256、lineage、date_min/date_max、security_count、row_count 和上游 evidence。

## 参数网格

列出参数网格、固定参数、禁止后验调整的参数、worker / thread 设置和 reference baseline。

## Expected Parameter Response

说明理论上哪些输出应随参数变化，哪些输出可以不变，以及完全不响应参数时的调查路径。

## Invariants

列出 nested invariant、funnel accounting、denominator integrity、样本守恒和必须成立的上下游一致性。

## Hard Anomaly Blockers

列出适用 anomaly checks、具体阈值、hard blocker 条件和异常调查顺序。

## 结果包清单

列出 experiment_summary、primary_results、diagnostic_summary、anomaly_scan、engineering_validation_result、result_analysis、scientific_review、formal evidence 的路径和提交策略。

## 作者分析要求

要求作者在正式运行后立即读取真实结果 artifacts，并完成结果分析报告。

## 独立 Review 要求

要求 reviewer 与 implementation actor 不同，独立复算至少一个核心统计并记录替代解释。

## Supersession 规则

说明哪些上游 hash 或契约变化会使本任务结果自动 superseded。

## README Gate

说明 author-draft 阶段 README 不得推进，final-gate validator passed 后才可推进。
