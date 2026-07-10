# GOV-T01 R1-R6 formal 实验结果包、异常门禁与科学审阅治理

## 问题背景

PR #77 / #78 暴露了一个流程缺口：formal runner、validator、hash 和 manifest 全部通过，只能证明工程链路闭合，不能证明实验结果在科学语义上合理。PR #77 基于修复前的 R0 zero-package 生成了 `S_PC/S_PCT/S_PCVT=0` 与 `confirmed=0` 的 profile，但该结果已被 PR #78 的 repaired nonzero package 推翻。因此，后续 R1-R6 formal experiment 必须把工程门禁和科学结果门禁拆开，避免 reviewer 只审核代码、hash 和 evidence，而没有审核真实实验结论。

## 双门禁定义

工程门禁覆盖代码、配置、lineage、hash、manifest、determinism、validator 和无前视。科学结果门禁覆盖结果包完整性、作者结果分析、异常解释、独立科学审阅和结论边界。下游放行必须同时满足 `engineering_validator_status = passed`、`result_artifact_status = passed`、`author_result_analysis_status = passed`、`scientific_review_status = passed`、`anomaly_resolution_status = passed` 或 `not_applicable`、`superseded = false`、`downstream_gate_allowed = true`。

## formal experiment 与非 experiment 分类

参数比较、状态画像、统计检验、Lift / retention / conditional probability、零模型、稳定性分析、敏感性分析、事件研究、预测评估、模型评估、组合或策略评估均为 formal experiment。contract-only、schema-only、refactor-only、synthetic-only、smoke-only，以及不产生研究结论的纯 materialization 可以豁免，但豁免任务不得声称完成 formal experiment。

## 三阶段工作流

formal experiment PR 先进入 author analysis 阶段：执行代理提交代码、正式运行、结果包、anomaly scan 和 `result_analysis.md`，此时 PR 必须保持 draft，`scientific_review_status = pending`，`downstream_gate_allowed = false`。随后进入 independent review 阶段，由非实现者直接读取 committed artifacts 并复算至少一个核心统计。最后进入 final gate 阶段，只有 scientific review record 提交且 final-gate validator 通过后，README 和下游 gate 才能推进。

## 结果包目录

每个 formal experiment 需要 clean-checkout 可审核的结果包，包括 experiment summary、primary results、diagnostic summary、anomaly scan、engineering validation result、author result analysis、scientific review record 和 formal evidence。大型行级 DuckDB/Parquet 不提交，但必须在结果包中记录 path、sha256、schema、row_count、security_count、date_min/date_max 和 input manifest。

## 异常检查

通用 anomaly scan 必须覆盖非空、全零、全一、全 NULL、validity rate、coverage、参数响应、baseline/challenger、nested invariant、funnel accounting、denominator integrity、sample size、upstream consistency、scale shift、time alignment、future leakage、post-hoc selection 和 conclusion support。具体数值阈值不在通用治理里设定，必须由 future formal experiment task config 预注册。

## 独立审阅

独立 reviewer 必须与 implementation actor 不同，并声明 independence attestation。review 必须读取 artifacts 和 analysis，复算至少一个核心 count / ratio / statistic，检查 baseline 与至少两个 challenger、参数响应、coverage / NULL / unknown / blocked、状态漏斗和不变量，提出至少一个替代解释，并记录 blocking / nonblocking findings。

## Supersession

上游 data package、字段契约、指标定义、eligibility、validity、状态生成、confirmation、manifest、config、schema 或 formal input hash 发生变化时，依赖结果自动 superseded。Superseded 结果不得作为当前 evidence、formal input、参数选择依据、冻结依据、研究结论或 README gate 依据；旧 PR 应关闭而不是 rebase，并明确 `superseded_by`。

## 验收标准

本治理 task 完成后，工程标准新增 12.8-12.14，新增治理 config/schema、formal experiment 结果包 validator、四个文档模板、formal experiment PR 模板、incident review、governance evidence 和覆盖 author-draft/final-gate/supersession/anomaly blocker 的测试。`docs/tasks/README.md` 只新增跨阶段治理说明，当前研究指针必须保持 R1-T04。

## 不改变 R1 当前 task

GOV-T01 是跨阶段治理 sidecar，不是 R1-T04。本任务不运行 R1-T04，不重新运行 R1-T03，不修改 W/q/K/weak_delta，不修改状态定义、零模型、R0/R1 formal artifacts 或 PR #78 的研究结果。
