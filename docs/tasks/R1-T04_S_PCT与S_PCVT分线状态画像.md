# R1-T04 S_PCT 与 S_PCVT 分线状态画像

## Task Class

`task_class = formal_experiment`。本任务建立预注册 `S_PCT` 与 `S_PCVT` 的 raw / confirmed 状态画像，不作状态冻结、参数选择、交易价值或因果判断。

## 研究问题与预注册 registry

固定 `q=0.20`，仅运行 7 个 profile：PCT 的 W250K3 reference、W120K3 fast challenger、W120K2 K sidecar；PCVT 的 W250K3 reference、W120K3 short-window challenger、W500K3 long-window sidecar、W250K5 K sidecar。任何运行后增删 profile、替换 reference 或追加 q 都是 blocker。

## 输入 Package 与不变量

输入经 R1-T01 manifest lock、R1-T02 lineage/PIT audit、R1-T03 profile gate 锁定。逐日和 confirmed interval 表必须由 R1-T03 summary 到 R1-T02 summary 再到 R0-T10-05 manifest 的 evidence chain 解析，逐个复核路径和 SHA-256。PCVT 必须是同 W/q/K PCT parent 的子集；unknown / blocked 不得转为 false；confirmed interval 必须与 daily confirmed state 对账。

## 输出与 Gate

小型结果包写入 `data/generated/r1/r1_t04/<run_id>/`，大型行级输入只在 summary/evidence 中记录。author-draft 只允许 `scientific_review_status=pending`、`review_phase=author_analysis_complete` 和 `downstream_gate_allowed=false`，README 指针保持 R1-T04，R1-T05 不放行。

## Supersession

R1-T01/T02/T03 evidence、R0-T10-05 manifest、per-config daily/interval artifact hash、config、schema、state/confirmation 语义或 eligibility/validity 契约发生变化，均使本任务结果自动 superseded。
