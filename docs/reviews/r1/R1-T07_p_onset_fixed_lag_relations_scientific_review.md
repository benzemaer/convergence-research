# R1-T07 P 首入锚定的固定滞后结构关系科学审阅

`reviewer_identity`: benzemaer
`reviewer_role`: independent_scientific_reviewer
`implementation_actor`: codex
`independence_attestation`: true
`reviewed_code_commit`: 100fb7a5a4f8107a22efcfbe38509fc5342ccc9e
`reviewed_summary_sha256`: d6bf46f110aaf1a86683e2a19d7fa89cf6ae8e115ac578086998a155cd91e1a1
`reviewed_analysis_sha256`: 0fbaea27431557e22d2510939d90d88e94a953ace353fb420f3aaff86bba8e84
`scientific_review_status`: passed
`downstream_gate_recommendation`: true

## 独立复算

已从 1915Z committed primary artifact 独立复算 reference W250/q20：P_TO_C@k1 为 `8750/25489 - 167952/1146574 = 0.1968037336`；P_TO_T@k10 为 `3953/26382 - 177972/1180548 = -0.0009167077`；P_TO_PCT@k5 为 `1723/25868 - 7665/1182218 = 0.0601238156`；P_TO_PCVT@k5 为 `353/25857 - 1257/1182165 = 0.0125887058`。W250/q20 anchor funnel 的互斥类别精确合计 1,730,769。P_TO_T@k10 的 security-cluster bootstrap CI 为 [-0.0053905530, 0.0035578156]，正确跨零；k20 CI 为 [-0.0189324321, -0.0103925079]。

## 审阅结论

上一轮的 bootstrap、anchor funnel、state reconciliation、security-year denominator、target-status matched estimand、formal package 章节与 generic author-draft validator 问题均已关闭。1915Z 的 target-status sensitivity 现在使用同一 `P_ONSET ∩ target@k valid ∩ target_anchor_valid` event subset，且直接报告 matched count、coverage、matched observed probability 和 standardized difference。primary point estimates、bootstrap interval 数量级和参数响应均未见新的公式错误或退化输出。

## 非阻断警告与边界

C/V 的短 lag relationship 对 target pre-existence 高度敏感；PCT/PCVT 仍须结合 P persistence 解释。PCVT 的 pooled positive difference 不代表多数证券同向，k20 的 per-security median 为负。继承的 C near-redundancy、V window-dependent identity、T q10 fragmentation、q onset transition non-nesting 与 pooled/security sign reversals 继续限制解释边界。

## Gate 建议

blocking findings 为空，科学审阅结论为 passed，并建议 downstream gate 最终可放行。该建议本身不推进 README、不授权 R1-T08，也不替代等待当前 HEAD Quality 通过、final result package、final-gate validator 与最终 gate commit。
