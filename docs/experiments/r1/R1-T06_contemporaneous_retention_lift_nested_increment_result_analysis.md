# R1-T06 Contemporaneous Retention Lift Nested Increment Result Analysis

## 1. 研究目标与预注册问题

observed_fact: 本次 formal run 只计算 `C_GIVEN_P`、`T_GIVEN_PC`、`V_GIVEN_PCT` 三个同期 step 的 2x2、retention、target marginal rate、Lift、Delta、non-anchor contrast 和 joint excess。derived_statistic: Lift 定义为 retention / target marginal rate，Delta 定义为 retention - target marginal rate。inference: 这些统计量只说明同一合法样本内 anchor 与 target 的同期共同出现关系。research_judgment: 结果可作为 R1-T07/R1-T08 的输入线索，但不支持形成顺序、因果、预测增量、统计显著性或参数冻结。

## 2. 输入 package、lineage、时间与样本范围

本 run 绑定 implementation commit `be1ee9946855f0b4b3eb25de23bcc14a999041da`，run_id 为 `R1-T06-20260710T1216Z`。旧 run `R1-T06-20260710T1155Z` 因 q nesting artifact 的 symmetric-difference 字段语义被本 run supersede；更早的 `R1-T06-20260710T1058Z` 已由 1155Z supersede。上游 R1-T05 final package 已完成，`scientific_review_status=passed`、`anomaly_resolution_status=passed`、`downstream_gate_allowed=true`。正式输入是 repaired R0 dimension score、dimension state 和 nested daily state：score hash `4a04fbada9ecac15936e3ab5d968cba8f1205db5dbe66a0491c7141e6fc5b8a5`，state hash `bbbb49ea2056bf6f257c1821236eb2b657eb1490153dfc9e56acee8f33264e08`，nested hash `0c07f4897d76c0a729963118c2e75581bd71521a25245d6d3b650b4f32e68995`。样本范围为 20160104 至 20260630，输入 security_count 为 800。

## 3. 参数网格与 reference baseline

参数网格固定为 `W={120,250,500}`、`q={0.10,0.20,0.30}`、`K=not_applicable`，共 27 条 primary rows。Reference baseline 是 `W=250/q=0.20`，四个预注册 challenger 是 `W120/q20`、`W500/q20`、`W250/q10`、`W250/q30`。这些配置只用于描述敏感性，不表示最优参数。

## 4. 核心结果

observed_fact: baseline `W250/q20` 下，`C_GIVEN_P` 的 2x2 为 n11=132775、n10=155269、n01=176618、n00=995761，N=1460423；retention=0.4609538820，target marginal=0.2118516348，Lift=2.1758334910，Delta=0.2491022473。`T_GIVEN_PC` 的 2x2 为 n11=34615、n10=98160、n01=181561、n00=1146087，N=1460423；retention=0.2607041988，target marginal=0.1480228673，Lift=1.7612427289，Delta=0.1126813315。`V_GIVEN_PCT` 的 2x2 为 n11=7860、n10=26450、n01=179168、n00=1228934，N=1442412；retention=0.2290877295，target marginal=0.1296633694，Lift=1.7667883425，Delta=0.0994243601。

derived_statistic: baseline 的 Lift 排序为 `C_GIVEN_P` > `V_GIVEN_PCT` > `T_GIVEN_PC`，Delta 排序为 `C_GIVEN_P` > `T_GIVEN_PC` > `V_GIVEN_PCT`。因此 Lift 与 Delta 对 T/V 的相对强度判断不同，主要来自 target marginal rate 与 anchor rate 的差异。

## 5. 预期结果与实际结果对照

实际输出满足 27 primary rows、27 denominator sensitivity rows、270 year rows、27 security summary rows、36 dimension reconciliation rows、36 nested reconciliation rows 和 78 q nesting reconciliation rows。baseline 三个 step 的 N、anchor count 和 child count 均非零。所有 primary rows 的 association_direction 均为 `positive_same_time_association`，这只是数值方向标签，不是显著性、因果或冻结判断。

## 6. coverage / NULL / unknown / blocked / denominator 检查

Dimension weak rule 从 R0-T05 score 独立重算后与 R0-T06 dimension state 完全一致，36 行 reconciliation 的 `active_mismatch_count=0`。Nested daily state reconciliation 使用与 R0 相同的顺序三值 AND 重建 `S_P/S_PC/S_PCT/S_PCVT`，并对全部 security/date/W/q key 做 full outer join；36 行 `missing_key_count=0`、`row_mismatch_count=0`，true/false/null 三类 count 均无 mismatch。W250/q20 下 `S_PC` 的 derived/R0 count 为 true=132775、false=1370896、null=227098；`S_PCVT` 为 true=7860、false=1495506、null=227403。C/T step 使用 step-specific denominator；baseline all-four restriction 对 C/T 的 denominator ratio 为 0.9876672717，C 的 retention difference 为 -0.0002134683，T 的 retention difference 为 0.0002103328。V step primary 与 all-four denominator 完全一致。

## 7. baseline 与至少两个 challenger 对照

`C_GIVEN_P` 在 W120/q20 的 retention=0.4522247513、Lift=1.9566422259、Delta=0.2211018892；W500/q20 的 retention=0.4799361002、Lift=2.2811046970、Delta=0.2695397511。`T_GIVEN_PC` 在 W120/q20 的 retention=0.2744203043、Lift=1.7890749752、Delta=0.1210336055；W500/q20 的 retention=0.2486454967、Lift=1.6998664035、Delta=0.1023719448。`V_GIVEN_PCT` 在 W120/q20 的 retention=0.2778121775、Lift=1.6755455792、Delta=0.1120081666；W500/q20 的 retention=0.2027988146、Lift=1.9518790767、Delta=0.0988995429。

## 8. 参数响应与敏感性

q response 的 row-level nesting 与 count monotonicity checks passed，W availability monotonicity passed，同一 step/W 的 denominator 在 q=0.10/0.20/0.30 下保持一致。`r1_t06_q_nesting_reconciliation.csv` 覆盖 24 条 dimension active set、18 条 anchor active set、18 条 child active set 和 18 条 denominator key-set check。所有 active-set 的 `lower_not_in_higher_count=0`，说明 q10 set 是 q20 set 的子集、q20 set 是 q30 set 的子集；active-set 的 `higher_not_in_lower_count` 和 `symmetric_difference_count` 可为正，表示高 q 合法扩张。所有 denominator key-set 的 `lower_not_in_higher_count=0`、`higher_not_in_lower_count=0` 且 `symmetric_difference_count=0`。例如 `C_GIVEN_P/W120/anchor_active/q10-to-q20` 为 lower=184998、higher=320710、lower_not_in_higher=0、higher_not_in_lower=135712、symmetric_difference=135712；对应 child set 的 symmetric difference 为 88236。observed_fact: q 从 0.10 到 0.30 时，baseline W250 的 retention 上升，但 Lift 下降；这说明较宽阈值提高共同出现比例的同时，也提高 target marginal rate。research_judgment: Lift 与 Delta 需要同时报告，否则会放大低 base-rate step 的相对比例。

## 9. 层级、漏斗、守恒关系与不变量

所有 primary rows 满足 n11+n10+n01+n00=N、child_true_count<=anchor_true_count、child_true_count<=target_true_count。所有 rows 满足 `child_joint_rate = anchor_rate * retention`、`joint_excess = anchor_rate * Delta`、`retention = Lift * target marginal rate`，误差在 validator 容差内。Nested invariants `S_PC subset P`、`S_PCT subset S_PC`、`S_PCVT subset S_PCT` 通过 R0 nested reconciliation 间接确认。

## 10. 异常结果及根因调查

blocking anomalies 为空。Material warnings 包括继承 R1-T05 的 C layer near-redundancy、V layer W-dependent identity、T q10 joint high fragmentation、T2 extreme right tail、strict-past percentile nonuniformity 与 nominal q / actual hit-rate divergence。此外，security summary 显示 `V_GIVEN_PCT W250/q10` 与 `W500/q10` 存在 pooled/security median sign reversal warning，提示 V step 的 pooled 正向 Delta 不代表多数证券层面都同向。

## 11. 替代解释与反证检查

可能替代解释包括 rolling-window availability、target base-rate difference、strict-past percentile 非均匀、cross-sectional heterogeneity、time-series persistence、C 指标近冗余、V 的窗口依赖和 T 的高碎片率。本 run 已通过 all-four denominator sidecar、year summary、security summary、dimension weak recomputation、nested reconciliation 和 row-level q nesting anti-join 做反证检查；这些检查不能替代后续 null model。

## 12. 研究限制

本任务不含 fixed-lag、onset、global/nested null、P-fixed circular shift、经验 p-value、z-score、未来收益、释放路径、交易约束或 R2 decision matrix。Security-level 结果只提交 summary，不提交全量逐证券 payload。Year sidecar 只用于描述集中度和符号反转，不构成 R1-T09 年份稳定性判断。

## 13. 可以支持的结论

observed_fact: 在 repaired R0 weak dimension state 上，三个预注册 step 的 baseline retention 均高于同一 step-specific denominator 内 target marginal rate。inference: anchor risk set 内 target 的同期出现率高于同一合法样本中的边际发生率。research_judgment: 这些正向同期关联值得进入后续滞后与 null-model 检查。

## 14. 不可以支持的结论

本结果不支持 P 导致 C、C 在 P 之后形成、T 对 PC 有预测增量、V 是最有效维度、Lift 最大的 step 应被冻结、层间关系已显著、嵌套顺序已被证明、任何参数应进入 R2，或任何交易价值判断。

## 15. 下游 gate 建议

author-draft gate 建议为：`status=author_analysis_complete`、`scientific_review_status=pending`、`review_phase=author_analysis_complete`、`downstream_gate_allowed=false`、`R1-T07_allowed_to_start=false`。本 PR 不推进 README 到 R1-T07。Merge-ready 需要独立 scientific review 复算通过后再进入 final-gate。
