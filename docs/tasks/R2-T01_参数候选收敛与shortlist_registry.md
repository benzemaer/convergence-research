# R2-T01 参数候选收敛与 shortlist registry

## Task Class

`task_class = parameter_comparison`，`task_subclass = deterministic_candidate_convergence_and_registry`，属于 formal experiment。本任务虽然不重跑状态计算或统计实验，但会形成正式的参数候选角色处置，并决定哪些路线进入 R2-T03 事件几何建模。

## 研究问题

本任务只回答：R1-T10 合法交接的 12 行候选中，哪些登记为四条 primary q-vector route，哪些作为 shared-q strict-core/fallback reference，哪些保留为 sensitivity，哪些明确 excluded。它不回答哪个 W 最优、哪个状态线最优、哪个参数有未来收益优势、最终冻结哪个版本或最终选择哪个 d/g。

## 非目标

本任务不得运行 d/g 扫描，不重新扫描 K，不创建新 q-vector，不读取 MarketDB、raw price、未来标签、回测结果或 R3 以后产物，不生成 event_id、event geometry、state_version_id、freeze decision、future return、future volatility、precision/recall 或交易收益字段。

## 前置 gate

启动条件绑定 R1-T10 final gate package、final-gate validation、PR #90 merge lineage 和 12 行 R2 decision matrix。`r1_t10_final_gate_package.json` 必须显示 `formal_task_completed=true`、`scientific_review_status=passed`、`independent_review_status=passed`、`repository_final_gate_status=passed`、`R2_allowed_to_start=true`、`downstream_gate_scope=R2-T01_only`、`selection_path_not_independently_confirmed=true`、`blocking_findings=[]`。

## 输入 package 与 lineage

正式输入为 `data/generated/r1/r1_t10/R1-T10-20260711T2000Z/` 下的 final gate package、validation result、reviewed author package、scientific review、R2 decision matrix、handoff manifest、candidate registry、warning registry、decision recomputation 和 upstream reconciliation。运行前必须从实际文件复算 SHA-256；matrix SHA-256 必须为 `c3dddd698a0876743e822a55864be06074f94c14a4cd142b44de062a35d83134`。

## 固定候选处置

四条 primary route 固定为 `q_W120_K3_P20_C20_T25_V20_S_PCT`、`q_W250_K3_P20_C20_T25_V20_S_PCT`、`q_W120_K3_P20_C20_T20_V30_S_PCVT`、`q_W250_K3_P20_C20_T20_V30_S_PCVT`。四个 shared-q row 固定为 `strict_core_reference`，`fallback_eligible=true`，`independent_product_eligible=false`，`t03_geometry_role=shared_q_sidecar`，且必须唯一配对同 state_line x W 的 primary route。两个 qT=.30 row 固定为 `sensitivity`；两个 qV=.25 row 固定为 `excluded`。canonical registry 必须保持 12 行，不得复制 shared-q 生成 16 行。

## 预期结果

canonical registry 必须满足 total=12、primary=4、strict_core_reference=4、sensitivity=2、excluded=2。每个 W 必须恰有 2 primary、2 strict_core_reference、1 sensitivity、1 excluded。primary shortlist 必须恰好四行，并且四条 route 平等进入后续事件建模；不得产生 automatic winner、reference winner、preferred window 或排名。

## Invariants

R1 matrix、candidate registry、warning registry 和 canonical registry 的 12 行 handoff key 必须守恒。warning_codes、source_artifact_refs、source_artifact_hashes 和 selection_path_not_independently_confirmed 必须逐行传播。shared-q 行的 fallback capability 通过 boolean 和 role_capabilities 表达，不扩张 source row。W120/W250 是独立路线，窗口 track 固定为 short_reference 和 long_reference。

## Hard Anomaly Blockers

任一输入不是 12 行、handoff_row_id 重复、4/6/2/0 输入分布不符、输出角色不是 4/4/2/2、四条 primary 不精确、qT=.30 被列为 primary、qV=.25 未 excluded、shared-q 未唯一配对、warning 丢失、selection_path limitation 丢失、source path/hash 不一致、R1 final gate 不成立、存在 d/g/未来标签/回测/冻结字段、输出依赖运行后指标排序，均必须 fail closed。

## 输出 package

正式运行目录为 `data/generated/r2/r2_t01/<RUN_ID>/`，至少包含 input binding、source reconciliation、candidate disposition registry、shortlist registry、primary shortlist、role assignment audit、evidence snapshot、experiment summary、diagnostic summary、anomaly scan、engineering validation result、result analysis、evidence、result package、pending scientific review placeholder 和 author-draft package validation result。

## 作者结果分析要求

正式运行后必须直接读取 shortlist registry、primary shortlist、role assignment audit、source reconciliation、evidence snapshot、diagnostic summary、anomaly scan 和 engineering validation result，独立复算 12 行守恒、4/4/2/2 role counts、primary identity、shared-primary pairing、每个 W 的 2/2/1/1 分布、warning reconciliation、selection_path flag 分布和 source hash。

## 独立科学审阅要求

独立 reviewer 必须直接读取 R1-T10 matrix、R2-T01 actual registry、role assignment audit、warning reconciliation 和 result analysis，至少复算四条 primary、一个 shared-primary pairing、一个 sensitivity 处置、一个 excluded 处置、4/4/2/2 总数和 selection_path flag 传播。implementation actor 不得将 scientific review 标记为 passed。

## Supersession

R1-T10 final package、matrix bytes/hash/schema、candidate registry、warning registry、decision precedence、R0/R1 state identity、W/q/K、eligibility/validity/confirmation、R2 stage contract、T01 role mapping 或 source artifact hash 任一变化，都会使本任务结果自动 superseded。

## README Gate

author-draft 阶段可以把当前任务指针更新到 R2-T01，但必须保持 scientific review、independent review、repository final gate pending，`formal_task_completed=false`，`downstream_gate_allowed=false`，`R2-T02_allowed_to_start=false`，`R3_allowed_to_start=false`。

## 失败状态与回退

输入、lineage、schema、hash 或 R1 final gate 异常时标记 `blocked_return_to_R1`。T01 contract、role mapping、schema 或报告不完整时标记 `needs_revision`。actual artifacts 出现未解释异常时标记 `unresolved`，不得通过修改文档追认失败结果。
