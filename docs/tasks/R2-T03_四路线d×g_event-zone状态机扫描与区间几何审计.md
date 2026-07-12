# R2-T03 四路线 d×g event-zone 状态机扫描与区间几何审计

## 1. 当前状态

```text
task_id: R2-T03
initial_startup_status: blocked_missing_authoritative_t02_final_gate_binding
resolution_status: resolved
startup_status: passed
resolved_by: r2_t02_repository_final_gate_handoff.json
formal_scan_started: true
formal_run_id: R2-T03-20260712T1205Z
candidate_cells_executed: 72
execution_status: executed_author_draft
engineering_validation_status: passed
independent_validation_status: passed
anomaly_scan_status: passed
scientific_review_status: pending_independent_scientific_review
formal_task_completed: false
R2-T04_allowed_to_start: false
```

本记录中的初始阻断结论保留为历史审计事实。该阻断已由 `R2-T02-20260712T1700Z/r2_t02_repository_final_gate_handoff.json` 及其 validation sidecar 解决；handoff 是正式启动授权，本文档本身仍不替代运行 manifest、正式输入绑定或研究结果。R2-T03 已完成 72-cell author-draft 扫描、工程验证和独立复算，但尚未取得独立 scientific review 或 repository final gate，因此不得推进 R2-T04。

## 2. 目标与非目标

R2-T03 的授权目标是在 R2-T02 冻结契约和 72 个既定 `candidate_cell_id` 上执行四条 primary route 与四条 shared-q reference 的 `d={1,2,3}`、`g={0,1,2}` 状态机扫描，生成事实层、区间几何、状态转移、strict-core/shell、窗口 overlap、独立复算和异常审计。

本任务不包含 T04 的 hard-gate 候选处置、Pareto 推荐、参数选择或 freeze plan，也不包含 T05 的 selected-only canonical 物化。启动门禁未闭合时，不得以 contract-only、synthetic-only 或局部真实数据运行冒充 T03 正式执行。

## 3. 启动审计事实

审计基于 `main@04530181e7cd80b8805f279dbac5eb5afb70c21d`，得到以下事实：

1. PR #94 的合并记录指向 exact PR head `a98d2a14e8828585e6b4283efee6afdf2db8672d`，merge commit 为 `04530181e7cd80b8805f279dbac5eb5afb70c21d`。GitHub review `4679909839` 在 exact head 上包含 `[R2-T02 scientific PASS]`。
2. GitHub Actions `Quality` run `29189876487` 的 `premerge-full` job 成功，外部 artifact `r2-t02-premerge-full-evidence` 报告 1200 个测试、0 failure、0 error，并在 workflow 内执行 final-gate consumer。
3. R2-T02 v8 committed-artifact validator 可在 artifact commit `a34f3f6c5ad0afece49b1c9a237e21eb032e35a2` 上复验通过，18 个登记 artifact 的 Git blob 与 SHA-256 闭合；protocol validator 也通过。
4. 当前 `main` 未包含上述 premerge-full evidence 或等价 repository final-gate authorization artifact。`git ls-tree -r main` 只能定位 builder、schema 和 author-stage review，不能定位持久化 final-gate 结果。
5. 仓库内 `R2-T02-20260712T1700Z/r2_t02_result_package.json` 仍声明 `scientific_review_status=pending`、`independent_review_status=pending`、`repository_final_gate_status=pending`、`formal_task_completed=false` 和 `R2-T03_allowed_to_start=false`。这是正确的 author-stage fail-closed 状态，不得重写以追认外部 workflow 结果。

外部 workflow 成功和 PR 合并事实不足以替代当前 `main` 中可由 T03 formal input binding 消费的不可变授权。Actions artifact 可能受保留期约束，且未被当前 Git tree 的 committed bytes 绑定，因此不满足本任务规定的持久化下游授权条件。

## 4. 已核对的冻结输入

R2-T02 v8 冻结输入位于 `data/generated/r2/r2_t02/R2-T02-20260712T1700Z/`。本次只读复验确认以下关键 committed artifact 哈希：

| Artifact | SHA-256 |
|---|---|
| `r2_t02_confirmed_state_machine_contract.json` | `6c0d5822416e5e8fef6392a8d97703d0ad9b5c46774029e13a363be6feb2d57c` |
| `r2_t02_event_zone_machine_contract.json` | `e7d877885b3cfe31bf685803f939cdcf56037d02a46d40314a304435dc1ecaed` |
| `r2_t02_transition_registry.csv` | `e2656afa07244b5fb2219327dda48dc9a6968e61a87c40662fb882208ca5440e` |
| `r2_t02_metric_dictionary.csv` | `aa56c49dce9484e7031fde9f345cc918bba70cb8b4cdc222e37ea63582cca00c` |
| `r2_t02_hard_gate_registry.csv` | `533978218585c510693d4236261b23d7a42834786a699412200e9d5f0d2012f5` |
| `r2_t02_r3_risk_set_contract.json` | `cb19687a112ba5ceba23c09fdd6923814d6159a088bff1dc78a322c8e5d1250f` |
| `r2_t02_t03_cell_registry.csv` | `7d8f82c189d0c96ba3091ca142d8612e31aeef36ecf20ff9c832009bd41e6ead` |
| `r2_t02_t03_output_contract.json` | `7587891bd2b705f0f5af90dc3c4faf672c9c8191bd912f92052932c2c7ac4a3c` |

这些哈希证明 contract/artifact bytes 可复验，不证明 T03 已获得启动授权。旧 T02 runs 不得替代 v8；author-stage package 不得被修改为 post-author PASS。

## 5. 阻断解除记录

阻断解除证据已明确绑定 `R2-T02-20260712T1700Z`、PR #94、review ID `4679909839`、head `a98d2a14e8828585e6b4283efee6afdf2db8672d`、workflow run `29189876487`、job `86642565197`、artifact ID `8259206209`、artifact digest 和 merge commit `04530181e7cd80b8805f279dbac5eb5afb70c21d`。handoff validator 重新调用既有 `validate_final_gate()`，校验 GitHub review snapshot、author package、committed-artifact sidecar、exact head、merge ancestry、远端 artifact/job metadata 与所有 committed SHA，并给出 `R2-T03_allowed_to_start=true`。

T02 author package 未被修改，继续保持 immutable author-stage lifecycle；科学 PASS 和 repository final-gate PASS 只记录在非循环 post-merge handoff。T04–R3 继续关闭。

## 6. 历史初始停止边界

初始阻断阶段未读取 loose DuckDB 作为正式输入，未执行单线程 baseline，未执行任何 candidate cell，未创建 R2-T03 formal run 目录，未生成 compact/large result artifacts，未作参数排名、选择或冻结判断。该阶段不构成可 resume 的 scan cell；解除后从完整正式输入绑定开始执行。

## 7. 正式执行与实际结果

正式运行 `R2-T03-20260712T1205Z` 绑定 execution commit `4dc46e061b72d60f6a34f50f1b35f659a9a28dce`，单线程 baseline 与 formal run 的七张核心表在 row count 和 XOR row hash 上完全一致。运行校验了 R0-T15 与 R0-T10 正式 manifest、登记 SHA 和实际文件 bytes；上游日表没有物理 `available_time` 与 `eligible` 字段，本任务按冻结配置分别由交易日 15:00（Asia/Shanghai）和 `validity_status=valid` 派生，该限制已写入 source readiness 和结果分析。

实际数据库包含 13,846,152 条 route daily rows、31,346 个 atomic intervals、282,114 个 component rows、173,253 个 event zones、574,299 条 membership rows、135,480 个 bridge segments 和 1,068,562 条 transition rows。72 个 cell 均有非零事件，事件数范围为 272–7,673；`confirmed_event_coverage` 范围为 0.530565–1.0。全部 24 个 route×d 参数响应组在三个 g 值上均产生 3 个不同 event count 和 3 个不同 bridge count；strict-core comparison 共 62,307,684 个共同日期键，subset violation 为 0。availability、risk-set、主键和 confirmed-day 守恒检查均为 0 violation，独立 validator 的 360 项复算比较全部通过。

工程 anomaly scan 未发现全零、全一、全 NULL、参数无响应、subset、availability 或 risk-set 异常。不过冻结 scientific gates 报告 14 个非工程阻断失败，全部是 `duration_q95_ratio > 3.0`：对应 cell 的绝对中位 duration 为 2–3 日、q95 为 7–11 日、最大值为 18–28 日，表现为短中位数下的右尾延长，而不是数量级爆炸或守恒破坏。这些失败保留在 `r2_t03_runtime_gate_results.csv` 和 author-draft 分析中，未用于选择或排除任何 cell；是否可接受只能由后续独立 scientific review 决定。

正式结果位于 `data/generated/r2/r2_t03/R2-T03-20260712T1205Z/`。321.7 MB DuckDB 由 manifest 记录 SHA-256、size 和 `local_large_artifact_not_committed` lifecycle，不进入 Git；compact profiles、validators、analysis、package、input binding 和 manifest 进入 committed-artifact 校验。当前 package 保持 `scientific_review_status=pending_independent_scientific_review`、`author_package_lifecycle=author_draft`、`R2-T04_allowed_to_start=false` 和 `R3_allowed_to_start=false`；工程 validator 通过不构成科学 PASS 或任务 final gate。
