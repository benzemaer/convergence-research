# R1-T06 层间同期留存、关联 Lift 与嵌套增量科学审阅

`reviewer_identity`: benzemaer
`reviewer_role`: independent_scientific_reviewer
`implementation_actor`: codex
`independence_attestation`: true
`reviewed_code_commit`: be1ee9946855f0b4b3eb25de23bcc14a999041da
`reviewed_summary_sha256`: 71f95c5bb9c414ab4deb0c50afc641f1d2a7dfa95681b508ffce15541a01f5f6
`reviewed_analysis_sha256`: 7ae2872ab5b36e962420caf3007d297ae3e7dda8509986277a3f5e2bc517bd98
`scientific_review_status`: passed
`downstream_gate_recommendation`: true

## 独立复算

已独立复算 W250/q20 baseline。`C_GIVEN_P` 的 retention 为 `132775 / (132775 + 155269) = 0.46095388204579857`，target marginal rate 为 `(132775 + 176618) / 1460423 = 0.21185163476609173`，Lift 为 `2.1758334909935626`，Delta 为 `0.24910224727970684`。`T_GIVEN_PC` 的 retention 为 `34615 / (34615 + 98160) = 0.26070419883261153`。`V_GIVEN_PCT` 的 retention 为 `7860 / (7860 + 26450) = 0.22908772952491985`。

## 审阅结论

修订后的 formal run `R1-T06-20260710T1216Z` 已关闭 nested 三值链式 reconciliation、row-level q nesting artifact 字段语义和 R1-T07/R1-T08 路线指针问题。R0 nested reconciliation 现在按顺序三值 AND 复算并对全量 key 做 full outer join；q nesting artifact 正确区分 `lower_not_in_higher_count`、`higher_not_in_lower_count` 和真实 symmetric difference。主 27 行 Retention/Lift/Delta 结果没有发现阻断性错误。

## 非阻断警告

保留 nonblocking material warnings：继承自 R1-T05 的 C layer near-redundancy、V layer W-dependent identity、T q10 joint fragmentation、T2 extreme right tail、strict-past percentile nonuniformity、nominal q / actual hit-rate divergence，以及 V q10 pooled/security sign reversal。这些警告限制解释边界，但不阻止进入 R1-T07。

## 替代解释与边界

C 的同期绝对增量最大可能部分来自 C 层近冗余和同日结构，不构成因果或形成顺序证据。V 的 Lift 与 Delta 排序差异来自 base-rate effect；V q10 的 pooled/security 异质性说明 pooled 正向结果不能解释为多数证券层面同向。本结果不支持交易价值、因果关系、参数最优、R2 冻结或零模型结论。

## Gate 建议

无 blocking finding。建议 final-gate 允许 R1-T06 completed，并推进到 R1-T07 P 首入锚定的固定滞后结构关系；R1-T08、R2 继续按任务索引保持未授权状态。
