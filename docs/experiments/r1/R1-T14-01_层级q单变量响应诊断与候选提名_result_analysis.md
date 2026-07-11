# R1-T14-01 层级 q 单变量响应诊断与候选提名 result analysis

## 1. 结论与证据边界

本报告分析 diagnostic run `R1-T14-01-20260710T2113Z`，绑定代码 commit `9b7ff557e7bf5f01f0984b7d89f9e51b3ba8778b`。author-side decision 为 `q_vector_materialization_request`：按冻结硬门槛、包含 baseline 的 Pareto 比较和确定性 tie-break，提名 W120/W250 各一个 T=.25 的 PCT center，以及各一个 V=.30 的 PCVT center，并完整保留其 immediate neighbors 与 shared-baseline references。冻结 registry 共 2 个 baseline references、4 个 centers 和 4 个 nonbaseline neighbors，即 8 个需由 R0-T15 物化的 nonbaseline vectors。

该结论只说明这些 q-vector 值得进入 R0 正式物化与 same-sample 结构复验，不说明它们是最优 q、冻结状态定义、独立 confirmation、可交易信号或 R2 候选。本报告是 implementation actor 的 author-side scientific analysis；`scientific_review_status=pending`、`reviewer_identity=unassigned`、`independence_attestation=false`，不得解释为独立科学审阅。

## 2. 预注册问题与冻结 grid

运行严格使用 `W={120,250}`、`K=3`、`Q={.10,.15,.20,.25,.30}` 和 shared baseline `(.20,.20,.20,.20)`。每个 W 包含一个 baseline 与 P/C/T/V 四层各四个 nonbaseline OFAT 点，共 17 个 vectors；两个 W 合计 34 个。没有运行 Q^4 全排列、W500、K2/K5、连续小数搜索、运行后加点或未来结果选择。

候选硬门槛和 fallback tolerances 在运行前写入版本化配置。存在性 floor 为 confirmed days≥100、unique securities≥20、confirmed intervals≥20、nonzero years≥5、max-year share≤.50；material advantage 以 baseline LOYO envelope、年度 MAD 和预注册 fallback 的最大值判定。

## 3. 输入 lineage 与 diagnostic namespace

唯一状态派生输入是 R0-T05 已授权 strict-past dimension score DuckDB，SHA-256 为 `4a04fbada9ecac15936e3ab5d968cba8f1205db5dbe66a0491c7141e6fc5b8a5`。baseline reconciliation 读取 R0-T07 daily confirmation 与 confirmed interval，SHA-256 分别为 `e9bcaafbd60229b6d9e01967cedb2739efb3407159a66d1ef47b3d779689b4e3` 和 `583187e213edc7b9796d5db5ef0b5484ad4b3fb17624212796ea1b9a721208ad`。运行没有读取 raw metric、未来标签、收益、波动、方向、路径、回测或交易结果。

所有派生均属于 `r1_t14_01_diagnostic_only`，且永久标记 `authoritative=false`、`formal_candidate_state=false`。日频派生只在运行时临时表存在，提交产物为可审核汇总与冻结 request；它们不能替代 R0-T15 formal materialization。

## 4. Baseline reconciliation

W120/W250 的 S_PCT/S_PCVT 在 raw days、confirmed days、valid/unknown/blocked rows、interval count、confirmed duration 和 open intervals 上形成 32 项 reconciliation。直接事实是 `mismatch_count=0`，并且 interval confirmed-duration 之和逐 vector/state 等于 confirmed-state days。

baseline 状态画像如下：W120 S_PCT 为 12,480 confirmed days、coverage 0.0077867、777 只证券、5,528 个区间；W120 S_PCVT 为 2,941 days、coverage 0.0018362、617 只证券、1,426 个区间。W250 S_PCT 为 10,854 days、coverage 0.0072183、773 只证券、4,884 个区间；W250 S_PCVT 为 2,143 days、coverage 0.0014255、520 只证券、1,024 个区间。四条 baseline state line 均跨 10–11 年，max-year share 为 0.169–0.219，未出现单年过半。

## 5. 共同 denominator 漏斗与 attrition

all-four-common-valid denominator 在同一 W 的 17 个 vectors 间保持完全不变：W120 为 1,545,035，W250 为 1,442,412。baseline W120 漏斗为 P=313,253、PC=140,954、PCT=38,760、PCVT=10,768；W250 为 285,408、131,499、34,310、7,860。

基于共同 denominator 的 baseline attrition share 显示 P 在两个 W 都是最大约束层：W120 的 P/C/T/V 分别为 0.3213/0.1608/0.2600/0.2579，W250 为 0.3108/0.1487/0.2578/0.2827。P 的 coverage 响应在四层排第二，coverage、interval、security 和 identity 均为非平坦，因此两个 W 均分类为 `dominant_bottleneck|material_constraint`。这是一项漏斗描述事实，不是 P 的因果机制证明。

## 6. q 响应与影响分类

T 是两个 W 中 confirmed PCT coverage 响应最大的层。W120 T 从 q=.10 到 .30 的 coverage 为 0.0010938→0.0184154，W250 为 0.0008147→0.0180113；fragment rate 同时从 0.6399→0.3274 和 0.6574→0.3089。T=.25 相对 baseline 已产生超过稳定性 envelope 的 coverage/Delta 改善，并比 T=.30 更接近 baseline，因此在两个 PCT archetype 中由 tie-break 选为 center。

V 的 coverage 响应排名第四，但 V nested Delta 随 q 放宽持续增加。W120 V nested Delta 从 .0561 增至 .1672，W250 从 .0387 增至 .1682。V=.25 未超过预注册 material-advantage gate，V=.30 通过，因此两个 PCVT archetype 均选择 V=.30，邻域保留 V=.25。W120 T/V、W250 C/P/V 的至少一项响应曲线存在 direction reversal 或 isolated-spike warning，已在 layer response classification 中标记 `unstable_response`；该 warning 不被选择过程删除。

C 层存在通过硬门槛但未被 tie-break 选中的 Pareto 点，包括 W120 C=.10/C=.30 与 W250 C=.30。P 层 W250 P=.10 也通过硬门槛但未胜出。它们保留在 selection audit，不因未入 frozen request 而删除。

## 7. Baseline 稳定性 envelope

关键 robust envelopes 为：W120 S_PCT coverage 0.0035405、S_PCVT 0.0005587、T Delta 0.0113126、T Lift 0.0993115、V Delta 0.0417270、V Lift 0.3014231；W250 对应为 0.0032724、0.0006861、0.0249046、0.1593163、0.0416974、0.3794693。material advantage 判定使用这些 envelope，而不是运行后设定的加权总分。

## 8. 四个中心的存在性、身份与几何

W120 T=.25 S_PCT 有 20,479 confirmed days、coverage 0.0127776、783 只证券、7,673 个区间、fragment rate 0.3830、max-year share 0.1816；相对 baseline retention=1、Jaccard=0.6094、新增 7,999 days、无 lost day。W250 T=.25 有 18,328 days、coverage 0.0121888、782 只证券、6,958 个区间、fragment rate 0.3784、max-year share 0.2268；retention=1、Jaccard=0.5922、新增 7,474 days。

W120 V=.30 S_PCVT 有 4,567 confirmed days、coverage 0.0028514、704 只证券、2,179 个区间、max-year share 0.1570；retention=1、Jaccard=0.6440、新增 1,626 days。W250 V=.30 有 3,591 days、coverage 0.0023886、640 只证券、1,674 个区间、max-year share 0.2050；retention=1、Jaccard=0.5968、新增 1,448 days。四个中心均为 baseline 的宽松超集；这不等同于 identity 改善，而是 T14-02 必须正式检验的状态身份变化。

## 9. 描述性层间关系、security 与年份

W120/W250 T=.25 的 `T_GIVEN_PC` pooled Delta 分别为 0.1574630/0.1473146，Lift 为 1.77198/1.73924；security-level median Delta 为 0.15709/0.14632。W120/W250 V=.30 的 `V_GIVEN_PCT` Delta 为 0.1672197/0.1681558，Lift 为 1.67574/1.81299；security median Delta 为 0.16533/0.15971。四组 pooled 与 security median 均同向。

四个中心所有可计算年度 Delta 均为正；年度 Delta 范围依次为 T-W120 [0.1360,0.1832]、V-W120 [0.0725,0.2887]、T-W250 [0.1271,0.2166]、V-W250 [0.1229,0.2682]。LOYO Delta 与 Lift-excess 也无方向翻转。上述结果仍是描述性 contemporaneous association，不是 R1-T08 permutation null pass。

## 10. V 构念保护

V=.30 的 selectivity-retained 为 W120 0.8105、W250 0.8107，均高于 .50；PCVT 仍严格窄于同参数 PCT，V nested Delta>0、Lift>1。与此同时 selectivity 相对 baseline 有所降低，因此两个 V center 永久携带 `V_selectivity_reduced_but_guard_passed`，不得把 coverage 增加写成无代价改善。

## 11. Pareto、确定性选择与 frozen request

共有 10 个 nonbaseline 点通过全部硬门槛。每个 archetype 先保留 Pareto frontier，再按 changed-component 数、与 .20 的距离、baseline overlap、max-year share、fragment rate、Delta 和 vector id 的固定顺序选择。最终 centers 为：

- `W120_K3_P20_C20_T25_V20`，PCT_fast_W120；
- `W250_K3_P20_C20_T25_V20`，PCT_q_decoupled_W250；
- `W250_K3_P20_C20_T20_V30`，PCVT_depletion_W250；
- `W120_K3_P20_C20_T20_V30`，PCVT_short_window_or_state_line_specific_W120。

mandatory neighbors 为对应 W 的 T=.30 与 V=.25；shared q=.20 baseline 只绑定既有 lineage，不要求重复物化。request 没有删除不利 neighbor，也没有在物化前缩小 family。T=.25 的 Lift 低于 baseline，携带 `affected_lift_deterioration_vs_baseline`；V=.30 携带前述 selectivity warning。

## 12. 异常扫描与独立复算

工程 anomaly scan 的 9 项强制检查全部通过：34-vector cardinality、baseline mismatch=0、非全 NULL/全零/全一、parent-child invariant、interval duration conservation、同 W availability 常量和合法 decision enum。`blocking_findings=[]`、`unresolved_questions=[]`。

author-side 独立复算没有调用 runner 的汇总函数，而是直接从不可变 dimension-score DuckDB 重算四个中心的 raw true counts：W120 T=.25 PCT=52,420、W120 V=.30 PCVT=16,073、W250 T=.25 PCT=46,019、W250 V=.30 PCVT=12,866，均与 state-profile 完全一致。另由 2×2 counts 独立复算四组 Delta/Lift，均与 interlayer artifact 完全一致。上一完整 run `R1-T14-01-20260710T2109Z` 与当前 run 的 14 个核心 artifact SHA-256 逐项相同，centers 也相同；差异仅为当前 request 增加预注册 lineage/metric/warning metadata。

## 13. 有限推断、替代解释与不可支持结论

有限推断是：P 是 shared-q 漏斗的主要 baseline attrition 层，但 T 阈值对 confirmed PCT existence/fragmentation 的响应最大；V 放宽到 .30 在保留大部分 V selectivity 的同时提高 PCVT existence 和 V nested Delta，因此四个 center 值得正式物化。替代解释包括共同市场 regime、threshold mechanics、跨证券 pooling、有效样本构成和同一样本选择偏差；T14-01 不能区分这些机制。

当前不可支持：best/final q、参数最优性、统计显著性、因果增量、未来预测、交易优势、R2 approval，以及把 diagnostic daily states 当作正式 R0 candidate。T14-02 即使通过 family correction，仍必须永久携带 `selection_path_not_independently_confirmed=true`。

## 14. Goal 内部 continuation 建议

工程 validator passed，author result analysis passed，anomaly resolution passed，reconciliation mismatch=0，候选选择遵循预注册确定性规则，且无 blocking findings 或 unresolved questions。因此 author-side `goal_internal_continuation_gate_status=passed`，允许在 stacked Draft PR 中构建 R0-T15。该状态不改变 README current task，不把 `R0_q_vector_materialization_allowed_to_start` 正式写为 true，也不表示 PR-A scientific review 或 repository final gate 已通过。
