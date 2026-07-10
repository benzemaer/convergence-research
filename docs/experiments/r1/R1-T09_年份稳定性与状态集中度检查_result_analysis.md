# R1-T09 年份稳定性与状态集中度检查 Result Analysis

## 1. 研究目标与预注册问题

本报告分析 formal run `R1-T09-20260710T1825Z`，代码 commit 为 `31e2533adcf1852d55ea8e5f16ac38e0a8453e97`。预注册问题是四个 S_PCT/S_PCVT candidate 的 raw/confirmed 状态、区间几何和 C/T/V 同期层间关系是否分布在多个年份，是否由单一年份驱动，以及删除任一年后 pooled 状态存在性或层间方向是否翻转。`observed_fact`：本 task 不重新执行 T08 permutation，不选择 winner，不冻结 W/q/K，也不读取未来结果。

## 2. 输入 package、lineage、时间与样本范围

输入只来自 R0-T10-05 authorized manifest 绑定的 dimension state、nested daily state、daily confirmation 和 confirmed interval，并绑定 R1-T04 `0835Z`、R1-T06 `1216Z`、R1-T08 `1629Z` 的 final packages、scientific reviews 与 final-gate validators。样本范围为 2016-01-04 至 2026-06-30，800 只证券；年份固定为 `YEAR(trading_date)`，2026 明确为部分年份。完整 interval 按 `YEAR(confirmation_date)` 唯一归属，calendar-year clipped segment 另表输出。`observed_fact`：全部输入 SHA-256 与 config 一致，891 项上游 reconciliation 的 mismatch 合计为 0。

运行环境为 Python 3.12.10、DuckDB 1.5.4、jsonschema 4.25.1，DuckDB threads=4、memory limit=12GB。实际 runtime 为约 18 秒。未读取 raw、MarketDB、行业、财务、外部指数或未来路径。

## 3. 参数网格与 reference baseline

机器 registry 恰好四条：S_PCT 与 S_PCVT 各包含 W250/q0.20/K3 reference 和 W120/q0.20/K3 challenger。K2、W500、K5、q0.10、q0.30 与 layer-specific q vector 均为 `not_executed`。年度 step 固定为 C_given_P、T_given_PC、V_given_PCT，使用 R1-T06 的 step-specific minimal common-valid denominator 和 same-W parent。`observed_fact`：44 条 candidate-year 行完整覆盖 2016-2026，两个 W250 的 2016 零状态年份没有被过滤。

## 4. 核心结果

`observed_fact`：四个 candidate 的 pooled confirmed coverage 与 T04/T08 完全一致。

| state | W | confirmed days | pooled coverage | nonzero years | max year share | top-two share | HHI | effective years |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S_PCT | 120 | 12,480 | 0.0072107 | 11 | 0.1775 | 0.3283 | 0.1146 | 8.73 |
| S_PCT | 250 | 10,854 | 0.0062712 | 10 | 0.2172 | 0.4336 | 0.1464 | 6.83 |
| S_PCVT | 120 | 2,941 | 0.0016992 | 11 | 0.1687 | 0.3196 | 0.1160 | 8.62 |
| S_PCVT | 250 | 2,143 | 0.0012382 | 10 | 0.2193 | 0.3840 | 0.1360 | 7.35 |

`independent_recomputation`：直接读取年度 CSV 后，以 confirmed days 除以 1,730,769 eligible rows，得到 W120 PCT `12480/1730769=0.0072106676`、W250 PCT `10854/1730769=0.0062712008`、W120 PCVT `2941/1730769=0.0016992447`、W250 PCVT `2143/1730769=0.0012381779`。逐年 share 的平方和复算 HHI，与 concentration artifact 完全一致。

## 5. 预期结果与实际结果对照

预注册的稳定性支持不要求年份频率相等，只要求状态在至少两个年份出现、没有单年过半、层间方向不由单一年份决定。实际 W120 两条 state line 在 11 年均非零；W250 两条在 2017-2026 的 10 年非零，2016 因 strict-past W250 availability 为零。四个 candidate 的最大年度 state share 为 16.9%-21.9%，均远低于 50%；六个 step 的最大 child share为 14.9%-22.4%。`research_judgment`：实际结果满足预注册的 `year_stability_supported`，但该状态是描述性年度分布判断，不是逐年 null pass。

## 6. coverage / NULL / unknown / blocked / denominator 检查

每个 candidate-year 都满足 raw true+false+NULL=eligible、confirmed true+false+NULL=eligible，以及 valid+unknown+blocked+diagnostic_required=eligible。`observed_fact`：diagnostic_required 为 0；unknown 与 blocked 保持 NULL，不进入 false。W120 PCT 在 2016 有 122,417 eligible、37,011 valid、85,347 unknown、59 blocked，confirmed coverage 为 0.0040926；W250 PCT 同年 eligible 仍为 122,417，但 valid=0、unknown=122,417、confirmed=0。2026 PCT coverage 为 W120 0.0024060、W250 0.0021902，均按部分年份 denominator 报告。

`independent_recomputation`：W120 PCT 2025 coverage=`2215/192701=0.01149449`；W250 PCT 2023 coverage=`2349/187126=0.01255304`。这些值与 artifact 一致。年份绝对 count 的差异不能脱离 eligible 和 valid denominator 解释。

## 7. baseline 与至少两个 challenger 对照

W120 对 W250 的 22 个 state-line/year 配对全部保留了 valid availability 差异。PCT coverage difference 在 2019 为 `+0.0000326`、2023 为 `-0.0024956`、2025 为 `-0.0007369`、2026 为 `+0.0002158`，不是每年同向；相应 fragment difference 也在正负之间变化。最大 valid-day availability difference 为 37,011，出现在 S_PCT 2016；到 2026 收窄至 424。

`material_warning`：W120 pooled coverage 较高不能自动解释成结构优越。2016 的窗口成熟度差异尤其大，其他年份也仍有 availability 差异。`research_judgment`：reference/challenger 对照说明两个 W 都具多年状态，不能据此输出 best window 或 freeze recommendation。

## 8. 参数响应与敏感性

W120 与 W250 对年份有非退化响应。W120 PCT 的 peak state year 为 2025，W250 PCT 为 2025，但 peak coverage year 分别为 2025 和 2023；W120 PCVT peak state/coverage year 为 2022，W250 PCVT为 2023。W120 的有效年份数更高，主要受 2016 availability 和较低 HHI 共同影响。`derived_statistic`：confirmed effective years 为 PCT 8.73/6.83、PCVT 8.62/7.35（W120/W250）。

本 task 固定 q 与 K，未做 q scan 或 K sidecar。`research_judgment`：这里只能支持 W sensitivity 的描述，不能把年度响应用于重新选择参数。

## 9. 层级、漏斗、守恒关系与不变量

66 条 step-year 行逐行满足 `n11+n10+n01+n00=N`，年度 cell 加总严格回到 R1-T06 pooled 2x2。`independent_recomputation`：C_given_P/W120 pooled cells为 145,033/175,677/216,341/1,026,507，得到 retention 0.452225、marginal 0.231123、Lift 1.95664、Delta 0.221102。T_given_PC/W250 得 Delta 0.112681，V_given_PCT/W250 得 Delta 0.099424。

各 step 的合法年度 Delta 全为正、Lift 全大于 1。以 2017/2026 为例，C/W250 Delta 为 0.259760/0.221818，T/W250 为 0.138433/0.148499，V/W250 为 0.070565/0.111786。W250 的 2016 denominator 为 0并保留 undefined，而不是删除后伪装为完整年份。PCVT confirmed days 在每个 W/year 均不超过同参数 PCT；confirmation-year interval duration 对四个 candidate 分别加总为 12,480、10,854、2,941、2,143，与 confirmed state days严格相等。

## 10. 异常结果及根因调查

通用 anomaly scan 的 18 个固定 checks 全部 passed，blocking anomalies 与 unresolved questions 均为空。`observed_fact`：四项 material warnings 被保留。第一，W250 PCT/PCVT 在 2016 的 confirmed state 为零；第二，同两行 valid denominator 为零；根因是 W250 strict-past 窗口在边界年份尚未成熟，不是查询过滤。第三，全部 22 个 W 配对存在 availability difference，最大为 37,011。第四，2026 仅观察至 6 月 30 日。

没有发现全零、全一、全 NULL、参数完全无响应、PCVT 超出 PCT、年度/interval/2x2 无法回到 pooled、confirmation-year 与 trading-year 混写、单年过半或 LOYO 方向翻转。`blocking_finding`：无。`material_warning`：边界年份和 availability 必须保留在科学审阅中，不能用 pooled 结果掩盖。

## 11. 替代解释与反证检查

年份频率不相等本身不构成不稳定。PCT/W250 的 2023 与 2025 状态份额较高，但其 denominator share 约 10.8%-11.1%，state share 约 21%，表明有年度状态富集；由于最大 share 仍低于 50%，它不是单年主导。共同市场 regime、横截面证券组成、strict-past availability 与状态定义共享输入都可能产生年度差异。

T08 pooled null separation 不能外推为每一年都通过 permutation null；R1-T09 未运行年度 permutation。年度 Delta 同向也不能证明单只证券同向，更不能证明 C/T/V 具有因果增量。`inference`：本结果反证“pooled 结构完全由一个年份单独驱动”，但没有排除少数 regime 共同贡献较大。

## 12. 研究限制

2016 对 W250 是零有效 denominator，2026 是部分年份，两者不能与完整成熟年份作无条件水平比较。年度样本仍为 pooled cross-sectional panel，没有行业、证券级或 regime 分层。LOYO 只删除自然年份，不检验连续多年 regime、替代时间分块或 family-level multiplicity。calendar-year clipped segment 描述年内连续性，不等同于完整 interval population。

R1-T09 不使用未来结果，不能回答预测、突破方向、收益、风险或交易可行性。年份稳定性也不等于样本外稳定性或交易稳定性。author analysis 不能替代独立 scientific review。

## 13. 可以支持的结论

`research_judgment`：可以支持四个正式 candidate 的 raw 与 confirmed 状态均分布在多个年份，最大年度 state/interval share 均低于 50%。C_given_P、T_given_PC、V_given_PCT 在所有合法年度均保持正 Delta 和 Lift>1；删除任一年后，六个 pooled step 的 Delta/Lift excess 均无方向翻转。PCVT/PCT parent-child、年度 partition、interval duration 和 2x2 守恒全部成立。因此可将四个 candidate 标记为 `year_stability_supported`，并将年度事实交给 R1-T10。

## 14. 不可以支持的结论

不能声称每一年都通过 T08 null，不能声称各年份频率应相等，不能把 W120 较高 pooled coverage 解释为优于 W250，不能从年度同向外推到多数证券同向，也不能输出 winner、best window、freeze candidate 或 R2 candidate。不能把同期 association 写成因果增量，也不能声称存在稳定交易优势。

## 15. 下游 gate 建议

`research_judgment`：author analysis 与 engineering validation 可以标记 passed，anomaly resolution 可标记 passed；科学审阅仍必须为 pending，`downstream_gate_allowed=false`。README 应继续停留在 R1-T09，`R1-T10_allowed_to_start=false`、`R2_allowed_to_start=false`。独立 reviewer 应重点复核 2016/W250 边界处理、2026 部分年份、availability-qualified W 对照、年度 2x2 与 LOYO 复算，以及“不将 pooled T08 null 外推为逐年 null”的结论边界。
