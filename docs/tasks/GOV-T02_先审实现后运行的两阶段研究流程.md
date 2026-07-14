# GOV-T02 先审实现后运行的两阶段研究流程

## 1. 核心原则

GOV-T02 将新研究任务分为两个逻辑阶段：先审阅 Implementation，再执行 formal run 并审阅 Formal-result。两个阶段不等于必须两个 PR；同一 PR 分两次提交是默认模式，两个独立 PR 是复杂任务、长时间运行或需要分离代码与结果时的可选模式。

formal run 的必要条件是代码 commit 已被用户明确审阅通过，不是 PR 已合并。用户批准必须明确给出 `reviewed_implementation_sha` 和 `formal_run_allowed: true`。

## 2. 同一 PR 两阶段模式

```text
Commit A: implementation
→ 用户审阅 Commit A
→ 用户批准 Commit A SHA
→ 基于 Commit A 执行 formal run
→ Commit B: results / manifest / analysis
→ 用户审阅结果
→ accepted 后更新 README 并合并
```

同一 PR 中，用户批准 implementation 后应立即基于批准 SHA 执行 formal run，再追加结果提交。

## 3. 两个 PR 模式

```text
Implementation PR
→ 用户审阅并合并
→ 基于已审阅 implementation commit 执行 formal run
→ Formal-result PR
→ 用户审阅结果
→ accepted 后更新 README 并合并
```

两个 PR 也是合法模式，但不是默认要求。

## 4. Implementation 审阅

Implementation 阶段可以提交代码、config、schema、runner、validator、tests、task 文档和 formal run runbook。必须说明研究问题与边界、输入 lineage、参数和统计定义、输出字段、运行资源和预计产物，并明确尚未执行 formal run。

Implementation 阶段禁止提交正式运行结果、正式结果 analysis、正式结果 manifest、基于正式结果的科学结论、README 下一任务推进或 `formal_task_completed=true`。

PR body 至少记录：

```text
workflow_mode: same_pr | split_pr
phase: implementation_review
implementation_review_status: pending
reviewed_implementation_sha:
formal_run_allowed: false
formal_run_status: not_started
result_review_status: not_started
readme_advanced: false
```

## 5. Formal run 授权

用户批准时记录：

```text
implementation_review_status: approved
reviewed_implementation_sha: <40-character SHA>
formal_run_allowed: true
```

formal run 必须晚于用户实现审阅。运行时记录 `reviewed_implementation_sha` 和 `formal_execution_sha`；正常情况下二者相等。用户批准后，如果实现、scripts、configs、schemas、研究参数、统计定义、输入选择、runner 或 validator 发生变化，原批准自动失效，必须提交新的 implementation commit 并重新审阅。

## 6. Formal-result 审阅

Formal-result 阶段提交小型 CSV/JSON 结果、manifest 和 hashes、result analysis、validator 输出，以及大型本地产物的路径、SHA-256、文件大小、表/schema、row count、security count 和日期范围。不强制全局 result package schema 或 generic manifest gate。

Result analysis 只需说明实际运行内容、reviewed implementation SHA、核心结果、数据质量与异常、支持和不支持的结论，以及是否建议进入下一 task。

## 7. 用户结果决定

结果是否通过由用户直接决定，不使用自动 SCIENTIFIC PASS、GitHub review marker、独立 reviewer 身份或 exact-head 绑定。

接受时记录：

```text
phase: formal_result_review
implementation_review_status: approved
formal_run_status: completed
result_review_status: accepted
next_task_allowed: true
readme_advanced: true
```

需要修订时记录 `result_review_status: needs_revision`、`next_task_allowed: false` 和 `readme_advanced: false`，不得推进 README。analysis 表述问题修改 analysis；输入或运行参数问题重新 formal run；实现错误返回 Implementation 阶段并重新审阅。

## 8. README 推进

只有用户明确接受 Formal-result 后，才更新 `docs/tasks/README.md`、将当前 task 标记 completed、推进下一 task 并补充最终结果分析。原始结果数据不得改写。推进前运行基础质量检查和 task-specific validator；不把 unittest profile 或自动 workflow 当作科学接受条件。

## 9. 实现变化后的重新审阅

formal run 前的实现变化会使旧 approval 失效，旧 SHA 的结果不得支持新实现。formal run 后的结果和 analysis 可以在同一审阅阶段修订；如果实现、输入或参数变化，必须回到 Implementation 审阅并重新运行。纯 PR body 修改不影响 implementation approval。

## 10. 历史 R1/R2 legacy 边界

GOV-T01 的 formal package、SCIENTIFIC PASS、author package、scientific review、repository final gate 和 post-merge handoff 仅作为已完成 R1/R2 研究的 legacy workflow 保留。历史 records、R2-T02 evidence 和 formal artifacts 不删除、不重写；新的 R3-R6 task 不得依赖、调用或复制这些历史 gate。
