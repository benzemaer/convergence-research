# R1-T07 P 首入锚定的固定滞后结构关系结果分析

## 1. 研究目标与预注册问题

observed_fact: 本次正式运行 `R1-T07-20260710T1510Z` 回答 P 从合法非活跃状态进入活跃状态后，在第 1、3、5、10、20 个后续观测交易日，C、T、V、S_PCT、S_PCVT 的出现概率是否高于共享 `P_{t-1}=false` 风险集但当日未进入 P 的 stay-out control。输出为 descriptive fixed-lag event study，`K=not_applicable`，primary rows 为 225。

research_judgment: 结果只能支持固定滞后结构关系的描述性证据。它不支持因果、预测增量、参数选择、交易信号或 R2 候选判断；这些问题仍需后续 R1-T08 至 R1-T10 以及 R2 之后的预注册任务回答。

## 2. 输入 package、lineage、时间与样本范围

observed_fact: 输入锁定 R1-T06 final-gate package，并读取 repaired R0 artifacts：dimension state `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_dimension_state_results.duckdb`，SHA-256 为 `bbbb49ea2056bf6f257c1821236eb2b657eb1490153dfc9e56acee8f33264e08`，62,307,684 行；nested daily state `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_nested_daily_state_results.duckdb`，SHA-256 为 `0c07f4897d76c0a729963118c2e75581bd71521a25245d6d3b650b4f32e68995`，15,576,921 行。日期范围为 20160104 至 20260630，证券数 800。

research_judgment: lineage 与 R1-T06 final gate 一致，工程 validator 只证明输入、schema、row counts、lag alignment 和不变量通过，不等于科学结论通过。

## 3. 参数网格与 reference baseline

observed_fact: 网格为 `W={120,250,500}`、`q={0.10,0.20,0.30}`、`lag={1,3,5,10,20}`、5 条 transition path，共 225 行。reference baseline 是 `W=250, q=0.20`，challenger 是 `W=120/q=0.20`、`W=500/q=0.20`、`W=250/q=0.10`、`W=250/q=0.30`。cluster bootstrap 配置为 `security_id` cluster、`B_boot=2000`、seed `20260710`，不生成显著性判定。

research_judgment: 本分析不按效果大小排序，也不选择最佳 lag 或最佳参数。所有参数响应只作为口径敏感性与异质性线索。

## 4. 核心结果

observed_fact: reference W250/q20 的 anchor event count 为 26,385。P_TO_C 在 k1/k5/k20 的 observed probability 分别为 0.3433、0.3367、0.2983，stay-out baseline 为 0.1465、0.1565、0.1784，absolute difference 为 0.1968、0.1802、0.1199。P_TO_T 对应 observed probability 为 0.1997、0.1806、0.1375，baseline 为 0.1346、0.1437、0.1523，absolute difference 为 0.0652、0.0369、-0.0148。P_TO_V 对应 observed probability 为 0.2618、0.2641、0.1938，baseline 为 0.0783、0.0867、0.1178，absolute difference 为 0.1835、0.1774、0.0760。

observed_fact: P_TO_PCT 在 k1/k5/k20 的 observed probability 为 0.0782、0.0666、0.0459，baseline 为 0.0015、0.0065、0.0149，absolute difference 为 0.0766、0.0601、0.0310。P_TO_PCVT 对应 observed probability 为 0.0118、0.0137、0.0114，baseline 为 0.0002、0.0011、0.0036，absolute difference 为 0.0116、0.0126、0.0077。relative lift 在 PCT/PCVT 短 lag 上很大，主要受 baseline base rate 很低影响。

research_judgment: reference 结果显示 P onset 后 C、V、PCT、PCVT 的固定滞后目标概率高于 stay-out control，且多数差异随 lag 拉长而收敛；T 的差异在 k20 转为负值，说明不能概括为所有维度均持续高于 control。

## 5. 预期结果与实际结果对照

observed_fact: 同一 W/q 下五条 path 的 anchor event count 完全一致，且不随 lag 改变。lag available anchor count 与 P continuous survival true count 均随 lag 非递增。q 提高时 active set 合法扩张，但 onset set 不要求嵌套，q transition sidecar 明确标记 `onset_set_not_required_nested`。

research_judgment: 预注册 expected parameter response 没有被违反。观察到的 effect、observed probability 与 relative lift 不要求对 W、q 或 lag 单调，因此不能把非单调响应解释为参数优选。

## 6. coverage / NULL / unknown / blocked / denominator 检查

observed_fact: `r1_t07_lag_alignment_reconciliation.csv` 有 45 行，offset mismatch 为 0；`r1_t07_state_reconciliation.csv` 有 54 行，missing key 与 row mismatch 为 0；primary target true + target false + invalid + right-censored 等于 anchor event count，control 侧同样守恒。工程 validator status 为 `passed`。

research_judgment: target-specific validity 被保留，unknown/blocked 没有被静默转为 false。right censor 与 target invalid 分开计数，因此 observed probability 的 denominator 是 target@t+k valid，而不是全部 onset。

## 7. baseline 与至少两个 challenger 对照

observed_fact: lag5 challenger 显示，P_TO_C absolute difference 在 W120/q20、W500/q20、W250/q10、W250/q30 分别为 0.1795、0.1903、0.1420、0.2106。P_TO_V 对应为 0.2013、0.1605、0.1246、0.2182。P_TO_PCT 对应为 0.0662、0.0609、0.0160、0.1221。P_TO_PCVT 对应为 0.0191、0.0085、0.0017、0.0345。

observed_fact: reference lag5 baseline sensitivity 中，P_TO_C primary absolute difference 为 0.1802，target-status standardized 为 0.0839，security-year standardized 为 0.1523；P_TO_V primary 为 0.1774，target-status standardized 为 0.0551，security-year standardized 为 0.1586；P_TO_PCT primary 为 0.0601，target-status standardized 为 0.0607，security-year standardized 为 0.0555。

research_judgment: target-status standardization 显著削弱 C 与 V 的差异，说明一部分 P_TO_C/P_TO_V 表观关系来自 target 在 anchor 日已经 active 的构成差异。PCT/PCVT 的 standardized differences 与 primary 更接近，但仍需结合 P run survival 和 anchor target pre-existence 分解阅读。

## 8. 参数响应与敏感性

observed_fact: lag5 下 q 从 0.10 到 0.30 时，reference W250 的 P_TO_PCT observed probability 从 0.0173 升至 0.1377，P_TO_PCVT 从 0.0018 升至 0.0382；absolute difference 同步扩大。W 变化对 P_TO_V 和 P_TO_PCVT 的 magnitude 有明显影响，但不产生统一单调结论。

research_judgment: q 与 W 改变会改变 onset 构成、continuing-P 构成和 target base rate，不应被解释为某个参数更优。q10 下 PCT/PCVT 有较多 pooled/security sign reversal warning，保留为 material warning。

## 9. 层级、漏斗、守恒关系与不变量

observed_fact: anchor funnel 9 行守恒；P_ONSET 与 STAY_OUT 互斥。reference W250/q20 的 anchor event count 为 26,385。P run survival probability 从 k1 的 0.8126 下降到 k3 的 0.6256、k5 的 0.5121、k10 的 0.3380、k20 的 0.1731。P_active_at_k probability 在 k20 仍为 0.3571，reentered_after_exit_count 为 4,855。

research_judgment: P_TO_PCT 和 P_TO_PCVT 的表观关系不能简单理解为 P onset 后新形成联合状态；P 自身持续性与退出后再进入都对后续 PCT/PCVT 概率有贡献。k20 时 surviving P run 已不足两成，但 P active at k 仍超过三成，说明 re-entry 是重要分解项。

## 10. 异常结果及根因调查

observed_fact: anomaly scan 无 blocking anomaly，material warnings 包括继承 R1-T06/R1-T05 的 C near-redundancy、V window-dependent identity、T q10 fragmentation、q onset set not nested，以及 PCT/PCVT 多个 pooled/security sign reversal。reference 年份集中度最高为 2023 年，单年 anchor share 约 0.1712，不存在单年主导全部 denominator 的情况。

research_judgment: 当前 warnings 不阻塞 author-draft，但它们限制解释边界。尤其是 PCT/PCVT 的 security-level median 与 pooled sign reversal，提示 pooled result 可能由大权重证券或年份构成驱动，不能直接外推到所有证券。

## 11. 替代解释与反证检查

observed_fact: target already active at anchor 的比例在 reference W250/q20 下分别为 C 0.3331、T 0.1747、V 0.2503、PCT 0.0867、PCVT 0.0122。k1 target probability among target-active-at-anchor onsets 分别为 C 0.9371、T 0.6299、V 0.9493、PCT 0.5011、PCVT 0.4677；among target-inactive-at-anchor onsets 分别为 C 0.0467、T 0.1087、V 0.0323、PCT 0.0386、PCVT 0.0063。

research_judgment: C 与 V 的高 k1 observed probability 很大程度可由 target 在 anchor 日已经 active 并持续解释。PCT/PCVT 在 target-inactive-at-anchor onsets 中仍有正概率，但比例较低，不能把它写成 P 领先产生目标状态。T 在长 lag 转负也反证了“P onset 后所有目标都持续提高”的宽泛叙述。

## 12. 研究限制

observed_fact: 本任务只使用 raw dimension/nested daily state 与固定 lag，不使用 confirmed K、不搜索 first passage、不做累计窗口、不做经验零模型。bootstrap 输出不生成显著性结论，`empirical_p` 固定为空。

research_judgment: 结果对 target base rate、anchor target pre-existence、security/year composition 和 P-run persistence 敏感。R1-T08 的 global/nested null model 仍是必要的后续检验，本任务不能替代。

## 13. 可以支持的结论

observed_fact: 在 repaired R0 输入与 reference W250/q20 下，P onset 后 C、V、PCT、PCVT 在固定 lag1、lag5、lag20 的 observed probability 均高于 stay-out control；T 在 lag1、lag5 高于 control，但 lag20 低于 control。P run survival 随 lag 快速下降，target already active at anchor 对 C/V/PCT/PCVT 的短 lag 结果有明显解释力。

research_judgment: 可以支持的有限结论是：P onset 是一个与后续若干 fixed-lag state occurrence 相关的描述性锚点，但这种关系由 P 持续性、target pre-existence 和构成差异共同塑造。

## 14. 不可以支持的结论

observed_fact: 本 run 没有执行 R1-T08 零模型，没有执行 R1-T09 稳定性任务，没有使用未来收益、释放方向、组合或交易约束评价。

research_judgment: 不可以宣称 P 导致 C/T/V/PCT/PCVT，不可以宣称存在预测优势、交易优势、最佳 W/q/lag 或 R2 candidate。也不可以把 PCT/PCVT 的高 relative lift 解读为强结构证据而忽视 baseline 极低和 target pre-existence。

## 15. 下游 gate 建议

observed_fact: author-draft package 应保持 `scientific_review_status=pending`、`review_phase=author_analysis_complete`、`downstream_gate_allowed=false`、`R1-T08_allowed_to_start=false`、`readme_gate_updated=false`。README 不应推进到 R1-T08。

research_judgment: 建议进入独立科学审阅，而不是下游放行。审阅重点应包括 reference 行独立复算、anchor target pre-existence 分解、P survival 分解、baseline sensitivity、PCT/PCVT pooled/security reversal，以及继承 R1-T06 warnings 的解释边界。
