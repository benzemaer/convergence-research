# R1-T07 P 首入锚定的固定滞后结构关系结果分析

## 1. 研究目标与运行状态

observed_fact: 本次当前 author-draft 运行更新为 `R1-T07-20260710T1800Z`，代码提交为 `eb800a828eda028d07913c143eb995169ab626a7`，配置哈希为 `04e77933c94bee8356d6e3a02aed4a2b88094cc77aa764952f7db5af8357bbff`。旧运行 `R1-T07-20260710T1510Z` 因 bootstrap、anchor funnel 与 state reconciliation 缺陷被标记为 superseded，不再作为当前 evidence 或 formal input。

research_judgment: 本任务仍只回答 P 从合法非活跃状态首入活跃状态后，在固定 lag 1、3、5、10、20 上与 C、T、V、S_PCT、S_PCVT 出现概率的描述性关系。它不支持因果、预测增量、参数选择、交易信号或 R2 候选判断。

## 2. 输入、网格与工程修复

observed_fact: 输入仍锁定 R1-T06 final-gate package 引用的 repaired R0 artifacts：dimension state `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_dimension_state_results.duckdb`，SHA-256 为 `bbbb49ea2056bf6f257c1821236eb2b657eb1490153dfc9e56acee8f33264e08`，62,307,684 行；nested daily state `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_nested_daily_state_results.duckdb`，SHA-256 为 `0c07f4897d76c0a729963118c2e75581bd71521a25245d6d3b650b4f32e68995`，15,576,921 行。日期范围为 20160104 至 20260630，证券数 800。

observed_fact: 本次修复后，security-cluster bootstrap 真实执行 `B_boot=2000`、cluster key 为 `security_id`、seed 为 `20260710`，225 行均写入 percentile CI，不生成 empirical p 或 replicate 明细。anchor funnel 改为互斥 `CASE` 分类，9 行均精确守恒。state reconciliation 按 `security_id × trading_date × W × q × state` full outer join，并用 R0 的有序 chain-AND 语义独立重建 S_PCT/S_PCVT 后逐行比较，54 行 missing key 与 row mismatch 均为 0。

research_judgment: engineering validator passed 只表示当前输出满足修复后的工程与契约检查，不等于 scientific review passed。当前 author-draft 仍应进入独立科学审阅，不得推进 downstream gate。

## 3. Reference 核心结果

observed_fact: reference W250/q20 的 P anchor event count 为 26,385。P_TO_C 在 k1/k5/k20 的 observed probability 分别为 0.3433、0.3367、0.2983，stay-out baseline 为 0.1465、0.1565、0.1784，absolute difference 为 0.1968、0.1802、0.1199。P_TO_V 对应 absolute difference 为 0.1835、0.1774、0.0760。P_TO_PCT 对应 absolute difference 为 0.0766、0.0601、0.0310。P_TO_PCVT 对应 absolute difference 为 0.0116、0.0126、0.0077。

observed_fact: P_TO_T 的 k1/k5/k20 absolute difference 分别为 0.0652、0.0369、-0.0148。特别是 P_TO_T@k10 的点估计为 -0.0009167，security-cluster bootstrap CI 为 [-0.0053906, 0.0035578]，descriptive status 为 `interval_overlaps_zero`；P_TO_T@k20 的 CI 为 [-0.0189324, -0.0103925]，status 为 `negative_interval_separated`。

research_judgment: reference 结果显示 P onset 后 C、V、PCT、PCVT 的 pooled fixed-lag target probability 高于 stay-out control，且多数差异随 lag 拉长而收敛。T 不能表述为稳定正向关系，k10 已不能排除零差异，k20 为负。

## 4. Baseline Sensitivity 与替代解释

observed_fact: 修复后 security-year standardization 只使用同一 lag 的 target-valid event risk set。W250/q20 下，P_TO_C@k5 primary absolute difference 为 0.1802，target-status standardized 为 0.0840，security-year standardized 为 0.1517；P_TO_V@k5 分别为 0.1774、0.0551、0.1589。P_TO_C@k1 从 0.1968 降至 target-status standardized 的 0.0374，P_TO_V@k1 从 0.1835 降至 0.0249。

observed_fact: P_TO_PCT 的 standardized difference 与 primary 较接近，k1 primary 为 0.0766，target-status standardized 为 0.0768；k5 primary 为 0.0601，target-status standardized 为 0.0607。P_TO_PCVT k1/k5 primary 分别为 0.0116、0.0126，target-status standardized 分别为 0.0116、0.0126。

research_judgment: C/V 的短滞后表观关系很大一部分来自 target 在 P onset 当日已经 active 并延续，而不是 onset 后新形成。PCT/PCVT 的 target-status standardization 不明显削弱 pooled difference，但这不构成因果或预测结论，仍需结合 P survival、security heterogeneity 与后续零模型。

## 5. 参数响应与异质性

observed_fact: lag5 challenger 显示，P_TO_C absolute difference 在 W120/q20、W500/q20、W250/q10、W250/q30 分别为 0.1795、0.1903、0.1420、0.2106；P_TO_V 分别为 0.2013、0.1605、0.1246、0.2182；P_TO_PCT 分别为 0.0662、0.0609、0.0160、0.1221；P_TO_PCVT 分别为 0.0191、0.0085、0.0017、0.0345。

observed_fact: W250/q20 的 P_TO_PCVT pooled effect 在五个 lag 全部为正，但证券层面 median 在 k1/k3/k5/k10 为 0，k20 为 -0.0006417。k20 有 235 只证券为正、430 只为负、123 只为 0，pooled 与 median sign 不一致。

research_judgment: q 与 W 改变会同时改变 onset 构成、target base rate 和 P persistence，不能作为参数优选证据。PCVT 尤其只能表述为 pooled descriptive association，不能外推为多数证券同向。

## 6. P Survival、Anchor Target Status 与解释边界

observed_fact: reference W250/q20 的 P run survival probability 从 k1 的 0.8126 下降到 k3 的 0.6256、k5 的 0.5121、k10 的 0.3380、k20 的 0.1731。P_active_at_k probability 在 k20 仍为 0.3571，reentered_after_exit_count 为 4,855。PCT_target_given_surviving_P_run_probability 从 k1 的 0.0968 上升到 k20 的 0.1320。

observed_fact: target already active at anchor 的比例在 reference W250/q20 下分别为 C 0.3331、T 0.1747、V 0.2503、PCT 0.0867、PCVT 0.0122。k1 target probability among target-active-at-anchor onsets 分别为 C 0.9371、T 0.6299、V 0.9493、PCT 0.5011、PCVT 0.4677；among target-inactive-at-anchor onsets 分别为 C 0.0467、T 0.1087、V 0.0323、PCT 0.0386、PCVT 0.0063。

research_judgment: P_TO_PCT 和 P_TO_PCVT 的表观关系不能简单理解为 P onset 后新形成联合状态；P 自身持续性、退出后再进入、target pre-existence 与构成差异共同塑造 observed probability。

## 7. Gate 建议

observed_fact: `R1-T07-20260710T1800Z` 的 engineering validator status 为 `passed`，anomaly scan 无 blocking anomaly，material warnings 包括继承 R1-T06/R1-T05 的 C near-redundancy、V window-dependent identity、T q10 fragmentation、q onset set not nested，以及多个 PCT/PCVT pooled-security sign reversal。

research_judgment: 当前 author-draft package 应保持 `scientific_review_status=pending`、`review_phase=author_analysis_complete`、`downstream_gate_allowed=false`、`R1-T08_allowed_to_start=false`、`R2_allowed_to_start=false`、`readme_gate_updated=false`。README 不应推进到 R1-T08。独立审阅重点应包括 bootstrap CI、state reconciliation 语义、baseline standardization denominator、C/V target pre-existence、P survival 分解和 PCVT 横截面异质性。
