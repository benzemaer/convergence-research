# R1-T04 S_PCT 与 S_PCVT 分线状态画像结果分析

## 1. 研究目标与预注册问题

本报告只描述预注册的七个 `state_line × candidate_config_id` profile 的存在性、覆盖、onset、持续期、精确日重合和同参数 parent-child 几何。observed_fact 直接来自 committed CSV；derived_statistic 是 coverage、fragment rate、Jaccard 和年份集中度；inference 仅讨论描述性的敏感性与连贯性取舍；research_judgment 是保留后续阶段继续检验，不能据此推进下游 gate。

## 2. 输入 package、lineage、时间与样本范围

输入由 R1-T03 summary 反向解析至 R1-T02 summary 和 repaired R0-T10-05 full-grid manifest。R0 manifest SHA-256 为 `b031ae22a3cf396961bcefcf6479c18870b8206a348372cf87d4b9f73c1fd96b`；本运行对五个所需 config 的 daily/interval Parquet 均逐个复核哈希。样本年份画像覆盖有状态日的 2016–2026 年，详细分布见 `r1_t04_year_concentration_profile.csv`。

## 3. 参数网格与 reference baseline

q 固定为 0.20。PCT reference 为 W250K3、fast challenger 为 W120K3，K2 仅为 W120 sidecar；PCVT reference 为 W250K3、short-window challenger 为 W120K3，W500K3 和 W250K5 为描述性 sidecar。registry 在运行前锁定为七条，未增加其他 q 或 config。

## 4. 核心结果

observed_fact：PCT W250K3 的 raw/confirmed coverage 分别为 1.99998% 和 0.62712%，W120K3 分别为 2.29956% 和 0.72107%。PCVT W250K3 的 raw/confirmed coverage 分别为 0.45413% 和 0.12382%，W120K3 分别为 0.62215% 和 0.16992%。四条 primary raw 和 confirmed profile 均非空。

## 5. 预期结果与实际结果对照

observed_fact：PCT W120K3 相较 W250K3 增加 2,440 个 raw onset 与 644 个 confirmed onset；PCVT W120K3 相较 W250K3 增加 1,421 个 raw onset 与 402 个 confirmed onset。inference：短窗口在两条状态线上都呈现更广覆盖和更多开始点，但这只是与预注册敏感性方向相符的描述，不是参数推荐。

## 6. coverage / NULL / unknown / blocked / denominator 检查

derived_statistic：PCT W120K3 的 unknown/blocked day count 为 126,422/1,615，低于 W250K3 的 226,030/1,068；PCVT W500K3 的 unknown day count 为 417,046，明显高于 W120 与 W250，符合更长历史窗口需要更长 availability 的机械差异。所有 profile 满足 true + false + null = eligible；unknown 和 blocked 未并入 false 分母。

## 7. baseline 与至少两个 challenger 对照

observed_fact：PCT W120K3 raw fragment rate 为 0.44764，高于 W250K3 的 0.43017；confirmed fragment rate 为 0.45478，略低于 W250K3 的 0.46069，二者 confirmed median duration 均为 2。PCVT W120K3 的 raw/confirmed fragment rate 为 0.48607/0.49719，均高于 W250K3 的 0.47425/0.48047。PCVT W500K3 raw coverage 降至 0.35585%，raw fragment rate 降至 0.44495；confirmed coverage 降至 0.09799%，confirmed median duration 为 1。

## 8. 参数响应与敏感性

observed_fact：PCT W120 K2 与 K3 raw profile 完全相同；K2 confirmed coverage 为 1.28272%，高于 K3 的 0.72107%。PCVT W250 K5 与 K3 raw profile 完全相同；K5 confirmed coverage 为 0.03392%，低于 K3 的 0.12382%。这些 K 响应符合确认规则的机械过滤。W120/W250/W500 的 valid day count 单调不增，unknown ratio 单调不减。

## 9. 层级、漏斗、守恒关系与不变量

observed_fact：四个 PCVT config 在 raw 与 confirmed 两层均满足 child_outside_parent_day_count=0 和 child_interval_containment_mismatch_count=0。confirmed interval total days 与 daily confirmed true count 完全一致，duration quantile 顺序、raw segment/onset 对账和 raw/confirmed 包含关系均通过。T04 与 R1-T03 的共享计数逐项对账通过。

## 10. 异常结果及根因调查

异常扫描的 18 个 mandatory check 均为 passed，未产生 blocking anomaly。W500 confirmed median duration 低于 W250 不构成契约异常：其较低 coverage、较高 unknown exposure 与 open/termination 结构需要作为窗口 availability 和确认过滤的联合结果解释，而不能单独归因于状态机制。

## 11. 替代解释与反证检查

替代解释一：W120 的更高 coverage 部分可能来自更高 eligibility，而非状态语义本身；本任务报告了 valid/unknown 差异但未做因果分解。替代解释二：K2/K5 的 confirmed 差异可能完全来自确认门槛，raw 完全不变支持这一解释。替代解释三：年份集中度可能改变表观重合；W500 raw max_year_share 为 0.31450，高于 W120/W250 PCVT 的约 0.15/0.22。

## 12. 研究限制

本任务不检验单指标分布、层内互补、正式层间增量、固定滞后、零模型、年份稳定性判定、未来路径或交易结果。exact-day overlap 不允许 lag 搜索，年份数据仅为 descriptive concentration profile，不能替代后续稳定性评估。

## 13. 可以支持的结论

observed_fact：两条状态线在四个 primary profile 的 raw 与 confirmed 层均非空，且 PCVT 在同参数 PCT 内保持合法嵌套。inference：短窗口提高了两条状态线的状态覆盖与 onset，同时至少在 raw 层伴随更高 fragment rate；PCVT W500 显示 coverage 与 raw 连贯性之间存在描述性取舍。

## 14. 不可以支持的结论

本结果不能支持参数定夺、预测能力、交易价值、因果形成顺序、正式层间增量、零模型结论或 R2 状态冻结。overlap 和 parent-child 几何只说明同期描述关系，不能作为机制证明。

## 15. 下游 gate 建议

research_judgment：engineering 和作者分析完成后，科学审阅仍为 pending，`downstream_gate_allowed=false`，README 继续指向 R1-T04，R1-T05 不得启动。本结果会在 R1-T01/T02/T03 evidence、R0 full-grid manifest、daily/interval hash、config 或状态契约变更时自动 superseded。
