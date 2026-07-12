# R2-T03 四路线 d×g event-zone 状态机扫描与区间几何审计

## 1. 当前状态

```text
task_id: R2-T03
startup_status: blocked_missing_authoritative_t02_final_gate_binding
formal_scan_started: false
candidate_cells_executed: 0
R2-T04_allowed_to_start: false
```

本记录只保存 R2-T03 启动审计结论，不是运行授权、正式输入绑定、final-gate evidence 或研究结果。由于前置门禁未在当前 `main` 中形成可供下游机器绑定的持久化证据，本次不得编写或运行正式 72-cell 扫描，不得生成部分 cell 结果，也不得推进 README gate。

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

## 5. 阻断解除条件

只有在后续独立治理变更把 PR #94 exact-head scientific review、exact tested head、premerge full result、repository final-gate verdict、merge ancestry和下游授权形成 committed、schema-valid、hash-bound、不可变且可由当前 `main` 直接读取的证据后，R2-T03 才能重新执行启动审计。该证据必须明确绑定 `R2-T02-20260712T1700Z`、PR #94、head `a98d2a14e8828585e6b4283efee6afdf2db8672d` 与 merge commit `04530181e7cd80b8805f279dbac5eb5afb70c21d`，并给出 `R2-T03_allowed_to_start=true` 或等价不可歧义授权。

解除阻断不是 R2-T03 自身可以补写的工作。不得在本 task 内生成新的 T02 formal run、修改 T02 科学语义、改写 author package、从临时下载目录绑定证据，或仅凭 PR 已合并而启动扫描。

## 6. 本次停止边界

本次未读取 loose DuckDB 作为正式输入，未执行单线程 baseline，未执行任何 candidate cell，未创建 R2-T03 formal run 目录，未生成 compact/large result artifacts，未作参数排名、选择或冻结判断。后续恢复时必须从完整启动门禁重新开始，而不是把本次审计视为可 resume 的 scan cell。
