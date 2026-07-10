# R1-T05 单指标诊断与层内互补性分析科学审阅

`reviewer_identity`: benzemaer
`reviewer_role`: independent_scientific_reviewer
`implementation_actor`: codex
`independence_attestation`: true
`reviewed_code_commit`: 5a9de4d94f294e849fd9be87238917558d55ce54
`reviewed_summary_sha256`: 70276a55f7409674994bba9ddb3061c38b0c3f2dfc7834e42b1490de9c000028
`reviewed_analysis_sha256`: 5c9b930359e35724b55c9cb49f465065844da85ca3caa9fb5c923b2b2f220ab6
`scientific_review_status`: passed
`downstream_gate_recommendation`: true

## 独立复算

已独立复算 C/W250/q20 的 2x2 denominator 与 Jaccard：`264651 + 62284 + 56610 + 1076878 = 1460423`，`264651 / (264651 + 62284 + 56610) = 0.6900129059171675`。已复算 C1/W250/q20 的 eligible hit rate 与 total-row coverage：`330271 / 1484607 = 0.22246358800679236`，`330271 / 1730769 = 0.1908232698875471`。已复核 C1/W250 percentile bucket count 加总等于 eligible count `1484607`，以及 T/W250/q10 joint single-day fragment ratio `23446 / 30631 = 0.7654337109464269`。

## 审阅结论

修订后的 formal run `R1-T05-20260710T0959Z` 已关闭上一轮 blocking findings：individual hit denominator 已区分 hit_rate 与 coverage，joint both-hit segment 不再跨越 pair-ineligible gap，新增 240 行 percentile bucket artifact 并通过守恒检查，validity reason profile 已区分 row prevalence 与 reason occurrence share。核心 Spearman、2x2、R0-T06 reconciliation、q nesting 与 W availability response 没有发现阻断性错误。

## 非阻断警告

保留 nonblocking material warnings：继承自 R1-T04 的 window-dependent state identity、confirmation population K sensitivity 与 PCVT confirmed high fragmentation；R1-T05 新增 C layer near-redundancy、V layer W-dependent identity、T layer q10 joint high fragmentation、T2 AbsTrendT20 extreme right tail、strict-past percentile nonuniformity 与 nominal-q coverage divergence。这些警告限制解释边界，但不阻止进入 R1-T06。

## 替代解释与边界

strict-past percentile 非均匀可由时间自相关、regime drift、ties 与有限 rolling window 共同造成；C 层接近冗余反映两个 reference-price spread 构造相关但未达到预注册 redundancy 阈值；V 的 W sensitivity 和 T 的 q10 joint fragmentation 是下游解释材料，不构成在 R1-T05 内修改 W/q/indicator membership 的依据。本结果不支持交易价值、因果关系、参数最优、指标删除、R2 冻结或零模型结论。

## Gate 建议

无 blocking finding。建议 final-gate 允许 R1-T05 completed，并推进到 R1-T06；R1-T07、R1-T08、R2 继续按任务索引保持未授权状态。
