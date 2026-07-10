# R1-T05 Indicator Intralayer Diagnostics Result Analysis

## 1. 研究目标与预注册问题

observed_fact: 本次正式运行 `R1-T05-20260710T0918Z` 覆盖八项 active indicators、四个 layer pairs、W={120,250,500} 与 q={0.10,0.20,0.30}。输出表行数分别为 raw distribution 8、score distribution 24、indicator hit duration 72、intralayer correlation 12、threshold structure 36、diagnostic summary 12、R0-T06 reconciliation 72。

derived_statistic: 所有 layer x W 在 q=0.20 primary classification 下均为 `complementary_structure`。该分类来自正向 pooled Spearman、非零 both-hit、非零 A-only 与非零 B-only。

inference: 八项指标在方向统一后的 score 空间没有出现层内构念冲突；每层两个指标同时命中且各自保留独立约束样本。

research_judgment: 该结果支持继续请求 independent scientific review，并在 review 通过后进入 R1-T06 层间增量分析；它不支持指标删除、指标冻结或参数最优判断。

## 2. 输入 package、lineage、时间与样本范围

observed_fact: R1-T04 final gate 已通过，result package hash 为 `f347b30b05b7d6ceb99b814023841d3190e9b6054a942a87f9d2771e93a1252b`，scientific review hash 为 `1e25f676fcd48a0d7fd73069b9ffedc2c990a6d6615d23ec2acb1ed9790ff789`。R1-T05 使用 repaired R0-T10-01 raw metric DuckDB、R0-T10-02 strict-past score DuckDB 与 R0-T10-03 indicator-state DuckDB，row count 分别为 13,846,152、41,538,456 与 124,615,368，security_count 均为 800，date range 均为 20160104 至 20260630。

derived_statistic: C2 raw repaired counts 维持为 valid=1,659,385、unknown=38,879、blocked=32,505，domain violation=0。

inference: R1-T05 没有回退或替换 R0 artifact；C2 readiness repair 在本任务输入层仍保持有效。

## 3. 参数网格与 reference baseline

observed_fact: Grid 固定为 W={120,250,500}、q={0.10,0.20,0.30}、K=not_applicable。Raw distribution 不依赖 W/q；score distribution 与 Spearman 依赖 W；hit duration 与 threshold structure 使用 9 个 W x q profiles。

research_judgment: q=0.20 仅作为 diagnostic status 的 primary classification baseline，不是 optimized q。

## 4. 核心结果

observed_fact: q=0.20、W=250 下，C 层 pooled Spearman=0.9194，both=264,651，A-only=62,284，B-only=56,610，Jaccard=0.6900。P 层 pooled Spearman=0.7280，both=228,750，A-only=163,224，B-only=115,165，Jaccard=0.4511。T 层 pooled Spearman=0.6665，both=139,404，A-only=173,077，B-only=172,687，Jaccard=0.2873。V 层 pooled Spearman=0.5289，both=123,768，A-only=167,462，B-only=212,986，Jaccard=0.2455。

derived_statistic: C 层两个 spread 指标最接近近同义但仍有 A-only/B-only；P/T/V 的 Jaccard 更低，独立约束样本更明显。

inference: P1/P2、T1/T2、V1/V2 更偏互补结构；C1/C2 方向高度一致但未触发 redundancy warning。

## 5. 预期结果与实际结果对照

observed_fact: 所有 score formula mismatch、percentile bounds violation、current-value-in-reference-set true、non-midrank tie-method count 均为 0。所有 R0-T06 active reconciliation mismatch count 均为 0。W eligibility monotonicity 与 q hit nesting 均通过。

derived_statistic: Expected W availability response 与 q threshold response 均满足预注册条件。

research_judgment: 实际结果符合 author-draft ready 条件，没有 hard anomaly blocker。

## 6. coverage / NULL / unknown / blocked / denominator 检查

observed_fact: Raw valid_ratio 最低的是 C2=0.9588，其次 V1=0.9607；C2 blocked=32,505，V1 blocked=1,242。P1 valid_ratio=0.9935，P2/T2/V2=0.9912，T1=0.9908。所有 raw domain violation count 为 0。

derived_statistic: W=250 eligible_ratio 范围约为 C2 0.8438 至 P1 0.8784。所有 pair-common denominator 均为正数；q20 common_eligible_rows 在 W=250 下为 C 1,460,423、P 1,516,287、T 1,515,495、V 1,464,003。

inference: denominator 差异主要来自 upstream validity/eligibility，不是 unknown 或 blocked 被转成 false。

## 7. baseline 与至少两个 challenger 对照

observed_fact: C 层 pooled Spearman 随 W 从 0.9048 到 0.9264；P 层从 0.6848 到 0.7574；T 层从 0.6555 到 0.6695；V 层从 0.6195 降到 0.4581。q20 Jaccard 在 C/P 随 W 增大略升，在 T/V 随 W 增大下降。

derived_statistic: W120/W250/W500 对层内结构身份没有改变，12 行均保持 `complementary_structure`。

inference: W 改变影响强度和覆盖，但未改变层内方向一致与独立约束并存的基本判断。

## 8. 参数响应与敏感性

observed_fact: 每个 indicator 的 eligible_count 满足 W120 >= W250 >= W500；unknown ratio 满足 W120 <= W250 <= W500。每个 indicator x W 的 hit_days 满足 q10 <= q20 <= q30；每个 layer x W 的 both_hit 满足 q10 <= q20 <= q30，neither 满足 q10 >= q20 >= q30。

research_judgment: q sensitivity 是阈值宽松导致命中集合扩张的预期响应，不是参数选择证据。

## 9. 层级、漏斗、守恒关系与不变量

observed_fact: 所有 2x2 行满足 both + A-only + B-only + neither = common_eligible_rows。所有 indicator hit rows 满足 segment_count = strict_onset_count + left_censored_start_count 且 total_hit_duration = hit_true_day_count。所有 joint rows 满足 joint_segment_count = joint_strict_onset_count + joint_left_censored_start_count 且 joint_total_duration = both_hit。

derived_statistic: T1_ER20 在 q10 下出现高 single-day fragment ratio，W120=0.6303、W250=0.6465、W500=0.6559。

inference: T1 hit 更碎片化，可能与 ER20 的局部效率指标性质有关；该 finding 是 material warning，不是工程 blocker。

## 10. 异常结果及根因调查

observed_fact: anomaly scan blocking_anomalies 为空。nonblocking anomalies 包括继承自 R1-T04 的 window-dependent state identity、confirmation population K sensitivity、PCVT confirmed high fragmentation，以及 T1_ER20 q10 高碎片率。

inference: R1-T04 的低跨窗口状态重合可能部分对应指标层 W sensitivity，但 R1-T05 不能用该信息选择 W 或修改状态线。

## 11. 替代解释与反证检查

inference: 可替代解释包括 rolling-window availability、score ties 与有限 W 离散性、时间序列自相关、pooled sample 与 within-security 差异、V2 raw amount 的股票规模差异，以及 weak dimension rule 与 strict both-hit 的差异。

observed_fact: pooled Spearman 与 per-security median 符号一致，score/percentile Spearman reconciliation 全部通过，V2 使用 `V2_LogAmount20_base` raw source 且未重复计算 percentile。

research_judgment: 这些反证检查降低了机械方向错误和 V2 映射错误的可能，但不构成因果或有效性证明。

## 12. 研究限制

R1-T05 仅分析层内 indicator 结构，不分析层间 C_given_P/T_given_PC/V_given_PCT retention、Lift 或 Delta；不做 onset lag、global/nested null、年份稳定性、R2 decision matrix、未来标签、回测或交易价值。Spearman 与 2x2 均为描述性统计。

## 13. 可以支持的结论

observed_fact: 八项指标 raw/score 分布非退化，C2 repaired validity 维持，score formula 与 R0-T06 active reconciliation 均通过。derived_statistic: 四层在 q20 baseline 下均有 both/A-only/B-only，且 pooled Spearman 与 per-security median 均为正。inference: 层内两个指标方向一致，并保留独立约束。research_judgment: 可以进入 independent scientific review；review 通过后可进入 R1-T06。

## 14. 不可以支持的结论

本结果不支持任何指标最好、某 W/q 最优、某指标应删除或降权、某层已经通过零模型、某指标可预测上涨、状态参数可冻结、R2 可启动、交易价值存在或因果机制成立的结论。

## 15. 下游 gate 建议

author-draft gate 建议为 pending independent scientific review。`scientific_review_status=pending`，`downstream_gate_allowed=false`，README 不推进，`R1-T06_allowed_to_start=false`。若上游 R0 artifacts、R1-T04 final gate、config/schema 或统计语义变化，本 run 必须 superseded 并重新执行。
