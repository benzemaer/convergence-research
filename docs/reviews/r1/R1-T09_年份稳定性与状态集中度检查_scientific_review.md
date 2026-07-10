# R1-T09 年份稳定性与状态集中度检查 Scientific Review

## 审阅身份与范围

独立审阅者为 `benzemaer`，角色为 `independent_scientific_reviewer`；implementation actor 为 `codex`，independence attestation 为 true。审阅对象是 formal run `R1-T09-20260710T1825Z`、implementation commit `31e2533adcf1852d55ea8e5f16ac38e0a8453e97`、PR head `45e85ef7899e4f604e9e563950d493e4deec8e09`、实际 artifacts、15 节分析、anomaly scan 和 validators。

## 独立复算

四个 pooled confirmed coverage 复算为 W120/W250 PCT `0.0072106676/0.0062712008`、W120/W250 PCVT `0.0016992447/0.0012381779`。W120 PCT confirmed HHI 为 `0.1145961359`，effective years 为 `8.7263`。C/W120/2016 Delta 为 `0.2744466`，V/W120/2016 最弱合法年度 Delta 为 `0.0169100`，仍为正且 Lift>1。C/W250 删除 2023 后重建 2x2 得 Delta `0.2539517`；110 条 LOYO 均无 Delta 或 Lift-excess 方向翻转。

## 结论与保留事项

Scientific review 结论为 `passed`，blocking findings 为空，downstream recommendation 为 true。必须保留以下非阻断限制：W250/2016 是 strict-past 零有效 denominator；W120/2016 和 W250/2017 仍处窗口成熟过渡；2026 是部分年份；年度 pooled 同向不代表多数证券同向；`evaluable_year_count` 按 eligible 而非 valid denominator 命名；candidate registry 的 T08 metadata 未显式列出 S_PCT 的 C nested，但实际 reconciliation 已覆盖全部 C/T/V。

README 只允许推进至 R1-T10，R2 继续保持关闭。审阅原始记录见 [PR #85 comment](https://github.com/benzemaer/convergence-research/pull/85#issuecomment-4938516039)。
