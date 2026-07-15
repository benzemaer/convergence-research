# EXP-C01：C 层 C1/C2 单指标消融（W120）

## 任务边界

EXP-C01 是独立 sidecar exploration，只研究 W=120、q=0.20 下 C1/C2 weak-dimension 身份是否高度重合。它不消费或推进 R3 task gate，不修改 `docs/tasks/README.md`、R0–R6 正式状态定义、现有指标定义、formal artifacts、freeze manifest、`state_version_id` 或 canonical DuckDB。

本实验只输出 raw daily dimension/indicator states 的描述性身份、availability、持续性、年份稳定性和证券稳定性。它不生成 confirmed state、confirmed interval、event zone，也不读取或生成未来收益、未来波动、未来方向、release/path label、backtest、portfolio 或 transaction cost。

固定参数只有：`W=120`、`q=0.20`、`weak_delta=0.10`；`K`、`d`、`g` 均为 `not_applicable`。禁止 W250/W500、q grid、threshold search、coverage-matched threshold、运行后调参以及根据结果新增 candidate。

## 固定 variant 与 denominator

`baseline_pair` 使用 `pair_valid AND score_C_mean >= 0.80 AND score_C_min >= 0.70`；`c1_only` 使用 C1 valid 且 `score_C1 >= 0.80`；`c2_only` 使用 C2 valid 且 `score_C2 >= 0.80`。单指标 variant 只用于 diagnostic comparison，不得称为当前双指标规则的等价替换，也不得生成 C v2 或 replacement decision。

所有身份比较都使用同一组 `security_id × trading_date` 的 `pair_common_valid`。C1/C2 的 native-valid 计数只在 availability sidecar 中报告。`unknown`、`blocked`、`diagnostic_required`、`eligible=false`、NULL score 和 missing row 都会中断 active run；它们不会被转成 false、0、均值或前值。

## 输入与 lineage

正式运行只读现有 strict-past indicator score：`C1_LogMASpread_5_60`、`C2_AdjVWAPSpread_5_60`，并以现有 manifest/config 解析输入。机器相关路径不得写入代码；runner 接受 `--input-root`，也支持 `CONVERGENCE_RESEARCH_INPUT_ROOT`。baseline reconciliation 额外读取 C dimension score/state，仅用于独立重建校验。

Implementation 阶段只读取配置、schema、manifest 文本；不打开正式大型 DuckDB。synthetic fixtures 是当前唯一运行数据来源。

## Implementation review gate

当前阶段必须保持：

```text
implementation_review_status: pending
reviewed_implementation_sha:
formal_run_allowed: false
formal_run_status: not_started
result_review_status: not_started
```

未来 formal run 必须在批准的 implementation commit 上执行，并显式提供：

```text
--input-root <path>
--output-root data/generated/sidecar/exp_c01/<RUN_ID>
--run-id <RUN_ID>
--allow-formal-run
--reviewed-implementation-sha <exact-40-character-sha>
```

runner 会拒绝未提供批准 SHA、当前 `HEAD` 与批准 SHA 不一致、输出目录已存在或输入无法唯一解析的运行。上述命令现在不执行。

## Formal output 与 readback

未来正式结果目录必须包含六个小型 CSV：variant profile、overlap profile、score comparison、year profile、security profile 和 availability profile，以及 `exp_c01_manifest.json`、`exp_c01_validator_result.json`、`exp_c01_anomaly_scan.json`、`exp_c01_result_analysis.md`。原则上不生成新的大型 DuckDB。

formal runner 写出 CSV 后必须从实际文件 read back，再生成 result analysis；随后独立 validator 检查固定参数、variant set、denominator、2×2 守恒、segment 守恒、score 范围、manifest hash/row count 和 baseline reconciliation。reconciliation 的 key count、mean/min、eligible、active、validity mismatch 必须全部为 0。

若异常扫描发现全零、全 NULL、全一、三个 variant 无差异、availability 不一致、年份或证券异常集中、层级计数不守恒、数量级异常或 baseline mismatch，必须停止，不得解释消融结果、请求 accepted、更新本目录为 completed 或推进下一项 sidecar task。

## 结果解释边界

R1-T05 redundancy reference 的 pooled Spearman≥0.95、Jaccard≥0.90、双向条件重合下界≥0.95 只能作为描述性 strong-substitutability reference。runner 和 validator 不自动选择 winner、不删除 C1/C2、不输出 replacement approval；最终是否删除某个指标由 Formal-result 审阅决定。
