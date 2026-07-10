# R1-T04 S_PCT 与 S_PCVT 分线状态画像科学审阅

`reviewer_identity`: benzemaer
`reviewer_role`: independent_scientific_reviewer
`implementation_actor`: codex
`independence_attestation`: true
`reviewed_code_commit`: 936188f9ee865def9f4238a54490ed0b0a487ae3
`reviewed_summary_sha256`: dfa621228f867aa0ce4657150558226a5bc4185b884b69fd4493f26fc8f97de5
`reviewed_analysis_sha256`: 0b8327a5c7bf007b64b9f3685522cb1c461ed8f2c28378e4f0bec84b9c3fe8f5
`scientific_review_status`: passed
`downstream_gate_recommendation`: true

## 独立复算

已独立复算 PCT W250K3 raw coverage、PCT W250K3/W120K3 raw onset Jaccard、PCVT W120K3 strict onset 与 left-censored start 对账，以及 PCVT W250K3 confirmed count。复算结果与 committed artifact 一致。

## 审阅结论

此前 onset overlap、parent-child geometry 和 strict raw onset 的语义问题已修复。四个 primary profile 非空，R1-T03 reconciliation、K/W response、raw/confirmed 漏斗、PCVT parent-child containment 和异常扫描均通过。低跨窗口重合、K 敏感性和 PCVT confirmed 高碎片率作为 nonblocking material warnings 被保留。

## 替代解释与边界

W 的 eligibility 差异、K 的机械确认过滤和跨窗口状态身份差异均可能影响描述性比较。结果不支持参数定夺、交易价值、因果关系、正式层间增量、零模型结论或 R2 冻结。

## Gate 建议

无 blocking finding。建议 final-gate 允许推进到 R1-T05；R1-T08 与 R2 继续不放行。
