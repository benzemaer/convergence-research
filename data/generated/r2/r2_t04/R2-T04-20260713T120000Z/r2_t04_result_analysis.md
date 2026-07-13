# R2-T04 Phase B result analysis

本任务的目标是可解释的 freeze，而不是在同一数据上寻找全局最优参数、
交易收益最优或方向预测最优。Phase A 的 automatic recommendation 只作为历史
比较产物；本次最终选择来自用户显式 override，hard-gate 仍不可被 override。

用户没有要求 T25/V30 interaction sidecar，也没有重新打开参数搜索。W120 被选择，
因为在两条 state line 上保持更高覆盖、证券广度和年份稳定性，同时 density、
bridge 和 merge geometry 没有退化；W250 的局部 persistence 或 short-drop 优势
不足以抵消这些差异。

S_PCT W120 d2/g1 的 retained、drop、bridge、merge、density、max-year、events、
securities 为 0.856501、0.382909、0.009528、0.036835、0.971416、0.171234、
4561、771；W250 对应为 0.856324、0.378378、0.009953、0.036993、0.970141、
0.215950、4163、772。S_PCVT W120 对应为 0.765776、0.491260、0.006178、
0.019337、0.981466、0.153775、1086、579；W250 对应为 0.776045、0.480574、
0.006338、0.021152、0.980986、0.206816、851、481。

d=2 是 persistence/coverage knee：d=1 保留短暂与 singleton 状态，d=3 带来明显
过度过滤。g=1 提供单日 gap 容忍，同时 bridged-day ratio 低于 1% 且 density
超过 97%；g=2 的边际合并收益不足以抵消额外 gap 污染与复杂度。

两个 primary 被选为 planned versions；对应 shared-q 只作为 strict core member，
不建立独立 state_version_id 或 event identity。W250 的两个 pair 均拒绝，因此最终
是两个版本而不是四个版本。S_PCT 与 S_PCVT 始终保持不同 state version 和 event
identity。

接受的 warnings 保留在 decision record：S_PCT 的 affected-lift deterioration、
q complexity、same-sample revalidation 和 selection-path limitation；S_PCVT 的
V security negative delta、V selectivity guard、q complexity、same-sample
revalidation 和 selection-path limitation。这些 warning 不构成交易效能证据。

Phase B 完成作者阶段收口，但 R2-T04 仍等待独立 scientific review 与 repository
final gate；因此 R2-T05 和 R3 继续关闭。没有生成 T05 canonical artifacts，也没有
运行 T03 或 Phase A。
