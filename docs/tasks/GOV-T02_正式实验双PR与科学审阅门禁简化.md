# GOV-T02 正式实验双 PR 与科学审阅门禁简化

## 任务定位

本 task 是跨阶段治理与 CI 修正，不改变 `current_stage`、`current_task`、R2-T08 状态、研究参数、科学结论或冻结产物。治理规则在本 PR 合并后生效，并且只从下一项尚未启动的 R3-R6 formal experiment 开始执行。已经执行过的 R1/R2 formal experiment 不迁移、不重跑、不补写新门禁记录。

## 目标

R-stage formal experiment 固定采用两个相互独立的 PR：

```text
Implementation PR
→ 代码审阅并合并到 main
→ Formal-result PR
→ formal run
→ 结果分析
→ 独立 SCIENTIFIC PASS
→ generic formal-result gate
→ 合并并开放下游
```

Implementation PR 只提交代码、config、schema、runner、validator、测试和 runbook，不执行 formal run，不提交正式结果，也不要求 SCIENTIFIC PASS。Formal-result PR 必须绑定已经合入 `main` 的 implementation merge SHA，执行 formal run 并提交 compact artifacts、manifest、hash、作者分析和审阅材料；该 PR 不得修改 implementation protected paths。

## 适用边界

- GOV-T02 合并前创建或已经运行的任务继续按照其原有历史规则处理。
- GOV-T02 不追溯重构 R1/R2，不修改历史 author package、scientific review、final gate、handoff 或 R2-T02 专用 evidence。
- GOV-T02 合并后，R3-R6 下一项尚未启动的 formal experiment 才必须使用本双 PR 流程。
- contract-only、schema-only、synthetic-only、smoke-only 和不产生研究结论的纯 materialization 不因本 task 自动变成 formal experiment；是否属于 formal experiment 仍由任务定义决定。

## Formal-result gate

`.github/workflows/formal-result-gate.yml` 只允许手动触发，输入 PR number 和 task-specific submission manifest path。workflow 从 GitHub API 读取 PR head、base、labels、state 和 reviews；不接受手工输入 head SHA、review ID、run ID 或 artifact hash。它在当前 PR head 上运行完整工程验证和 `full` profile，再调用 `src/governance/formal_result_gate.py` 生成 generic evidence。

Submission manifest 必须使用 `schemas/governance/formal_result_submission.schema.json`，列出实际文件路径和 SHA-256，不得使用 `...`、glob、隐式默认路径或目录外推。`implementation_merge_sha` 必须是 `formal_execution_sha` 和 `artifact_commit_sha` 的 ancestor；`artifact_commit_sha` 必须是当前 PR head 的 ancestor。Formal-result PR 从 implementation merge 到 artifact commit 之间不得修改 implementation protected paths。

独立 reviewer 的 review body 必须包含以下单行 marker：

```text
[SCIENTIFIC PASS] task_id=<TASK_ID> run_id=<RUN_ID> artifact_commit=<40_SHA> result_package_sha256=<64_SHA> independence_attestation=true
```

SCIENCE PASS 绑定 artifact commit、run ID 和 result package hash，不要求 review commit 等于当前 PR head；review commit 只需是当前 PR head 的 ancestor。Artifact commit 之后只允许 manifest 中列出的治理 metadata 路径变化；README、task index、review evidence、final-gate evidence 和 PR 文本的变化不会使 PASS 失效。受保护的实现、配置、schema、正式结果、输入 manifest 或结果分析变化必须重新生成 artifact commit 并重新审阅。

## 验收标准

- 普通 PR 不因 Draft/Ready 状态、缺少 SCIENTIFIC PASS 或 R2-T02 evidence 而失败。
- `quality.yml` 保留普通工程 CI，`full` 仅在 `main` push 运行。
- 新 generic workflow、schema、validator 和模板不包含具体历史任务 ID、run ID 或结果目录。
- 合法 fixture 通过；每个 failure path 通过单点 mutation 失败并返回明确 error code。
- 历史 GOV-T01、R2-T02 validator、schema、artifacts 和 review 记录仍存在且未修改。

## 非目标与回退

本 task 不修改 R2-T08、R3 研究定义、P/C/T/V、W/q/K/d/g、状态机、事件区间、freeze、正式结果或 branch protection，不启用测试并行，也不执行真实数据采集或 formal run。

回退时 revert GOV-T02 合并提交并删除新 workflow、config、schema、validator 和模板；历史 GOV-T01 与 R2-T02 evidence 保持不变。
