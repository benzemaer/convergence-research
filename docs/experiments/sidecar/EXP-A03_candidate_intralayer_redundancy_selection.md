# EXP-A03：A 层候选内部冗余与选择

## 研究目标

EXP-A03 是 A 层候选的内部探索性比较。它只在已接受的 EXP-A01 raw metrics 中选取 A1、A2、A2b 三者同时为 `valid` 的共同 key，比较 pooled raw 关系、年份稳定性、证券稳定性、低尾身份重合，以及 A2 离散 outside-rate 与 A2b 连续 gap 的条件关系。输出用于 EXP-A04 的 provisional internal down-selection，不构成 formal winner、正式指标冻结或 A-layer 注册。

## 非目标

本实验不修改 A1/A2/A2b 公式、A01 raw DuckDB、有效性状态或交易日 universe，不使用 A1-only 的额外 valid observations 扩大比较样本，不读取 D3，不使用未来收益、未来波动、未来方向、release label、回测或交易结果，也不定义 A-layer score/state、不创建 PCATV、不启动 EXP-A04。

## Accepted upstream

EXP-A03 只接受 immutable EXP-A02 handoff。handoff 固定绑定已接受的 EXP-A02 run、reviewed implementation SHA、result commit、Quality、validator/anomaly 状态和四项 A02 compact artifact SHA。A03 authorized input manifest 只允许五项 artifact：A02 accepted handoff、A02 manifest、A02 validator result、A02 anomaly scan 和 A01 raw metrics；不直接引入 D3 artifact。

## Frozen common universe

共同 universe 是 A01 raw 中 A1、A2、A2b 的 `valid` 三指标共同 key，key 为 `security_id`、`trading_date`、`observation_sequence`。正式契约固定为 1,602,937 个 common-valid keys；A2 与 A2b valid key set 必须相同，triple common-valid set 必须是 A1 valid set 的子集。A1 额外 valid keys只保留在上游事实中，不能扩张 A03 pairwise universe。

## Pair definitions

固定比较 `A1_A2`、`A1_A2b` 和 `A2_A2b`。三个指标都遵守 lower raw = more attached 的方向约定。A1 保留 current-distance anchor 语义，A2/A2b 仅作为 persistence alternatives 进行 provisional 比较。

## Correlation definitions

Pearson 作为辅助描述量，定义为 `corr(left_raw, right_raw)`，不进入 hard redundancy gate。主要关系量是 Spearman：每一列先使用 `RANK() + (COUNT(*) OVER (PARTITION BY value)-1)/2.0` 得到 tie-aware midrank，再对两个 midrank 的 `(midrank - 0.5) / N` 计算相关。该定义分别用于 pooled、calendar year 和 security 范围。证券 common row count 小于 100 时仍输出该证券，`eligible=false`、相关性为 NULL、reason 为 `insufficient_common_rows`。

## Tie policy

所有相同 raw value 必须共享 midrank，禁止 row-number、dense-rank 或任意 tie breaking。A2 的 21 个离散 levels 保持原值，不重新分箱；统计和尾部选择不通过 security/date 排序强制截断到名义行数。

## Tail policy

低尾 fractions 固定为 0.01、0.05、0.10。每个 pair 使用 `QUANTILE_DISC` 得到左右 threshold，低尾集合为 raw value 小于或等于 threshold，并包含 threshold 上的全部 ties。每行报告 threshold、选中数、实际比例、交集、并集、Jaccard 以及双向 containment；实际比例可以高于名义比例。

## Conditional profile

A2 levels 固定为 0.00、0.05、……、1.00，共 21 行。每个 level 报告 row count/share、A2b 的 min、q05、q25、median、q75、q95、max、mean、population standard deviation 和 distinct value count。空 level 也必须保留为零行和 NULL profile，不允许把 levels 合并或重新分箱。

## Variance decomposition

在共同 universe 内按 A2 level 将 A2b 的总平方和分解为 between-group 和 within-group 两部分，报告 global mean、total SS、between SS、within SS、eta-squared 和 within variance ratio。必须满足 `total_ss = between_group_ss + within_group_ss`，residual 允许的误差为 `1e-9 * max(1, total_ss)`。

## Pre-registered redundancy thresholds

A2/A2b 只有在以下 all-of 条件全部满足时才判作内部冗余：overall Spearman ≥ 0.95、minimum yearly Spearman ≥ 0.90、eligible-security Spearman 的 q10 ≥ 0.80、5% 和 10% low-tail Jaccard 均 ≥ 0.80、以及 eta-squared ≥ 0.90。Pearson 不得替代这些条件。A2 representation adequacy 同时要求 grid violation 为 0、levels 为 21、最大单 level share ≤ 0.25、5% tail realized rate ≤ 0.15、10% tail realized rate ≤ 0.25。

## Candidate disposition rules

如果 A2/A2b 未通过 hard gate，provisional candidate set 为 `[A1, A2, A2b]`，两者均 `retain_for_A04`，reason 为 `material_internal_difference`。如果通过 gate 且 A2 adequate，set 为 `[A1, A2]`，A2 是 `selected_persistence_representative`，A2b 是不带入 A04 的冗余备份。如果通过 gate 但 A2 inadequate，set 为 `[A1, A2b]`，A2 是 coarse backup，A2b 是 persistence representative。A1 collision flags 只生成 investigation item，不能自动删除 A1；所有处置均保持 `provisional_A03_recommendation`。

## Validator architecture

Producer 使用 DuckDB read-only source connection、temporary in-memory relation 和 set-based SQL，只返回 compact aggregates；不使用 pandas、逐 raw row Python iteration、full wide-table payload、new persistent DuckDB 或 Parquet。独立 validator 从磁盘重新校验 A02 handoff schema、五项输入、SHA、A01 raw schema/count/date/security binding，独立构造 common universe，并独立重算七张 CSV、处置规则、manifest、output hash、text contract 和 forbidden outputs。Producer 与 validator 不共享 query builder、correlation/tail/profile/decision implementation。runner 每次只执行一次 core validator、一次 anomaly scan 和一次 cheap final validation。

## Formal gate

正式模式必须使用 approved A03 manifest，并在打开 A01 raw 前验证 reviewed implementation SHA、exact HEAD、指定 branch、clean worktree、合法 run ID、输出目录不存在、manifest authorization 和 A03 reviewed SHA binding。正式运行保持 `formal_data_version=false`，只读打开上游 raw，单次 core validation，compact outputs 原子发布；implementation 阶段只允许 synthetic fixture，不创建真实 A03 manifest，也不打开真实 A01 raw。

## Failure policy

任何 lineage、common key/value、duplicate、nonfinite、A2 grid、row count、accepted year/security、tail reconciliation、variance residual、decision、producer/validator、output hash、input hash、forbidden output 或 governance mismatch 都 fail closed。失败发生在 staging 后时，保留 `<failure-root>/<RUN_ID>/package` 中已生成的 compact diagnostics 和 `failure_summary.json`，不复制 A01 raw，不将 failure package 当作正式结果。negative relationship、A1 collision、security coverage、阈值邻近和分布 spread 只作为 investigation items。

## Unsupported conclusions

EXP-A03 不判断未来表现、预测能力、交易价值、A-layer final winner、指标冻结、A-layer registration、PCATV 或 A04 结果。即使 redundancy gate 通过，处置也只是供用户审阅的 provisional recommendation，不能绕过后续 formal-result review 或下游门禁。
