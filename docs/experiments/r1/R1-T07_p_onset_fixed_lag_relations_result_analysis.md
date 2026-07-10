# R1-T07 P 首入锚定的固定滞后结构关系结果分析

## 1. 研究目标与预注册问题

observed_fact: 本次 formal run 固定计算有效 P 从 false 到 true 的首入后，C、T、V、S_PCT、S_PCVT 在精确 lag={1,3,5,10,20} 的出现概率，并与同一 P_{t-1}=false 风险集内 STAY_OUT control 比较。research_judgment: 结果仅描述固定滞后关联，不支持因果、预测增量、参数选择、交易信号或 R2 候选判断。

## 2. 输入 package、lineage、时间与样本范围

observed_fact: 当前 run 是 `R1-T07-20260710T1915Z`，implementation commit 为 `100fb7a5a4f8107a22efcfbe38509fc5342ccc9e`，config hash 为 `2353cf6cc55131025d21c82d6b6a5708af0fc1428f94f54ccc238a822c30f117`。输入为 repaired R0 dimension state（62,307,684 行，SHA-256 `bbbb49ea2056bf6f257c1821236eb2b657eb1490153dfc9e56acee8f33264e08`）及 nested daily state（15,576,921 行，SHA-256 `0c07f4897d76c0a729963118c2e75581bd71521a25245d6d3b650b4f32e68995`）；样本日期为 20160104 至 20260630、800 只证券。`R1-T07-20260710T1800Z` 因第二轮审阅指出的 governance package 与 target-status estimand 问题而 superseded。

## 3. 参数网格与 reference baseline

observed_fact: 网格冻结为 W={120,250,500}、q={0.10,0.20,0.30}、K=`not_applicable`、lag={1,3,5,10,20}，共 225 条 primary rows；reference baseline 为 W250/q20，challenger 为 W120/q20、W500/q20、W250/q10、W250/q30。bootstrap 固定为 `security_id` cluster、B=2000、seed=20260710、percentile interval，且 `max_failed_replicates=0`。

## 4. 核心结果

observed_fact: W250/q20 的 P anchor event count 为 26,385。P_TO_C 在 k1/k5/k20 的 primary absolute difference 为 0.1968037/0.1802182/0.1198920；P_TO_V 为 0.1834506/0.1773645/0.0760319；P_TO_PCT 为 0.0766298/0.0601238/0.0310346；P_TO_PCVT 为 0.0115968/0.0125887/0.0077256。P_TO_T 在 k10 为 -0.0009167，cluster bootstrap CI 为 [-0.0053906, 0.0035578]，在 k20 为 -0.0148111，CI 为 [-0.0189324, -0.0103925]。

## 5. 预期结果与实际结果对照

observed_fact: 实际输出满足 225 条 fixed-lag rows、225 条 baseline sensitivity rows、45 条 survival rows、45 条 anchor-target rows、9 条 funnel rows、2,250 条 year rows、225 条 security summary rows、54 条 state reconciliation rows、66 条 q transition rows和45 条 lag alignment rows。所有 primary count 可由 true/false/invalid/right-censored 分解复算；bootstrap 实际写入 225 条 interval，failed_replicates=0。research_judgment: 参数响应非退化，但这不是任一 W、q 或 lag 优选的证据。

## 6. coverage / NULL / unknown / blocked / denominator 检查

observed_fact: primary observed probability 仍只以 `target@t+k valid` 为 denominator。target-status sensitivity 现额外要求 anchor 日 target valid，并输出 `target_status_matched_event_count`、coverage、matched observed probability 和同一 matched subset 的 standardized difference。W250/q20 下，C@k1 matched count=25,472/25,489、coverage=0.9993330；V@k1=25,393/25,409、coverage=0.9993703；PCT@k5=25,473/25,868、coverage=0.9847302；PCVT@k5=25,454/25,857、coverage=0.9844143。security-year matched counts 均不超过 primary target-valid denominator。

## 7. baseline 与至少两个 challenger 对照

observed_fact: reference W250/q20 的 P_TO_C@k5 primary difference=0.1802182；W120/q20、W500/q20、W250/q10、W250/q30 分别为 0.1795、0.1903、0.1420、0.2106。P_TO_V@k5 对应为 0.1773645、0.2013、0.1605、0.1246、0.2182；P_TO_PCT@k5 为 0.0601238、0.0662、0.0609、0.0160、0.1221。research_judgment: 这些并列对照只描述 sensitivity，不构成 post-hoc 参数选择。

## 8. 参数响应与敏感性

observed_fact: W 增大时 availability 与 onset 数减少；lag availability 和连续 P run survival 随 lag 非递增。reference P run survival 从 k1 的 0.8125829 降至 k5 的 0.5121092、k20 的 0.1730740；k20 P active probability 为 0.3571429，其中退出后重入 count=4,855。q active set 可扩张，但 transition-defined onset set 不要求 nested。

## 9. 层级、漏斗、守恒关系与不变量

observed_fact: W250/q20 anchor funnel 的 800+214,474+0+26,385+1,188,450+274,012+26,648+0=1,730,769，与 total_rows 精确相等。state reconciliation 对所有 `security_id × trading_date × W × q × state` 做 full outer join；54 行均有 r0_key_count=derived_key_count、missing_key_count=0、row_mismatch_count=0，并以有序三值 chain-AND 独立重建 S_PCT/S_PCVT。lag alignment 的 offset_mismatch_count 均为 0。

## 10. 异常结果及根因调查

observed_fact: hard anomaly checks 均通过；bootstrap hard gate 同时校验 B=2000、seed、225 interval rows 与 failed_replicates=0。material warnings 保留 inherited C near-redundancy、V window-dependent identity、T q10 fragmentation、q onset-set non-nesting 与 pooled/security sign reversals。P_TO_T@k10 的区间跨零并非运行异常，而是实际 cluster bootstrap 不确定性；k20 区间完全为负。

## 11. 替代解释与反证检查

observed_fact: W250/q20 的 target-status matched difference 显示 C@k1 从 primary 0.1968037 降至 0.0373076，V@k1 从 0.1834506 降至 0.0249873；PCT@k5 为 0.0615226，PCVT@k5 为 0.0128178。research_judgment: C/V 的短 lag pooled association 很大部分可由 target 在 P onset 当日已活跃及其持续性解释；PCT/PCVT 的 matched sensitivity 较接近 primary，但仍不能排除 persistence、base-rate、样本构成和横截面集中等替代解释。

## 12. 研究限制

observed_fact: 本任务不含 null model、经验 p-value、未来收益、未来波动、突破方向、交易成本或回测。P survival profile 中的 target 明确是 PCT，而非五条 path 的通用 target。security summary 仅报告 pooled 与证券层面摘要，未形成多数证券同向的结论。

## 13. 可以支持的结论

observed_fact: reference 下 C、V、PCT、PCVT 的 primary fixed-lag difference 多数为正，T 在 k10 区间跨零且 k20 为负。P_TO_PCVT pooled effect 虽在五个 lag 为正，但其证券层面 median 在 k1-k10 为 0、k20 为 -0.0006417，k20 有 235 只证券为正、430 只为负。inference: 可支持“这些是 pooled descriptive fixed-lag association，并具有明显 target-pre-existence 和横截面异质性”的有限结论。

## 14. 不可以支持的结论

research_judgment: 本结果不支持 P 导致 C/T/V/PCT/PCVT、target 在 P onset 后新形成、任何 lag 有预测增量、C/V/PCT/PCVT 对多数证券同向、任意参数应被冻结、R2 candidate、统计显著性、交易价值或稳定收益优势。

## 15. 下游 gate 建议

observed_fact: 当前 author-draft package 的 engineering validator 已通过，通用 governance author-draft validator 待本次 artifact package 生成后执行。research_judgment: 新 run 必须保持 `scientific_review_status=pending`，`downstream_gate_allowed=false`，`R1-T08_allowed_to_start=false`，`R2_allowed_to_start=false`，README 不推进，PR 保持 Draft；1800Z 应记录为 `scientific_review_status=needs_revision`、`anomaly_resolution_status=unresolved` 且 superseded。
