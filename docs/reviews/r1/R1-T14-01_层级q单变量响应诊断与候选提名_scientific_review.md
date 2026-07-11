# R1-T14-01 层级 q 单变量响应诊断与候选提名 Scientific Review

## 审阅身份与范围

独立审阅者为 `benzemaer`，角色为 `independent_scientific_reviewer`；implementation actor 为 `codex`，independence attestation 为 true。审阅对象是 run `R1-T14-01-20260710T2113Z`、implementation commit `9b7ff557e7bf5f01f0984b7d89f9e51b3ba8778b`、PR head `2e2cc2931a4c3ff1ab427966bc78f79a0f69c151`、诊断摘要、结果分析、冻结 request 及提交 artifacts。

## 复算与结论

审阅确认 34 组 OFAT 网格与 diagnostic-only 边界符合预注册，32 项 baseline reconciliation 均为零。W120/W250 的 T=.25 与 V=.30 四个 center 的 coverage 和 affected Delta 改善均超过各自的 LOYO/MAD robust envelope；T=.30 虽有更大数值，但按“距离 baseline 更近”的冻结 tie-break 由 T=.25 胜出并保留 T=.30 neighbor。V=.30 通过 material-advantage 和 selectivity guard，V=.25 未过 material gate，只作为 neighbor。V=.30 的 `selectivity_retained=(1-R_candidate)/(1-R_baseline)` 在 W120/W250 约为 0.8105/0.8107，均高于 0.50。

Scientific review 结论为 `passed`，blocking findings 为空。两项 nonblocking finding 必须保留：config 中的 `protocol_version` 是仍写 R1 v0.3 的 task schema label；T14-01 的 minimal-common-valid denominator 与 T14-02 的 state-specific short-circuit denominator 不同，后者必须显式对账。结果只证明四个 center 值得进入 R0-T15 正式物化，不证明 best q、独立确认、因果结构、预测能力或交易优势。

## Gate 建议

本审阅只放行冻结的 R0-T15 request。R1-T14-02、R1-T10 和 R2 继续关闭，`selection_path_not_independently_confirmed=true` 继续保留。审阅原始记录见 [PR #87 comment](https://github.com/benzemaer/convergence-research/pull/87#issuecomment-4941866339)。
