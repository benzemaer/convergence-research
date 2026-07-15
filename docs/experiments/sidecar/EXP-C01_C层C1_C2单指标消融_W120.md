# EXP-C01：C 层 C1/C2 单指标消融（W120）

## 任务边界

EXP-C01 是独立 sidecar exploration，只研究 W=120、q=0.20 下 C1/C2 weak-dimension 身份是否高度重合。它不消费或推进 R3 task gate，不修改 `docs/tasks/README.md`、R0–R6 正式状态定义、现有指标定义、formal artifacts、freeze manifest、`state_version_id` 或 canonical DuckDB。

本实验只输出 raw daily dimension/indicator states 的描述性身份、availability、持续性、年份稳定性和证券稳定性。它不生成 confirmed state、confirmed interval、event zone，也不读取或生成未来收益、未来波动、未来方向、release/path label、backtest、portfolio 或 transaction cost。

固定参数只有：`W=120`、`q=0.20`、`weak_delta=0.10`；`K`、`d`、`g` 均为 `not_applicable`。禁止 W250/W500、q grid、threshold search、coverage-matched threshold、运行后调参以及根据结果新增 candidate。

## 固定 variant 与 denominator

`baseline_pair` 使用 `pair_valid AND score_C_mean >= 0.80 AND score_C_min >= 0.70`；`c1_only` 使用 C1 valid 且 `score_C1 >= 0.80`；`c2_only` 使用 C2 valid 且 `score_C2 >= 0.80`。单指标 variant 只用于 diagnostic comparison，不得称为当前双指标规则的等价替换，也不得生成 C v2 或 replacement decision。

所有身份比较都使用同一组 `security_id × trading_date` 的 `pair_common_valid`。C1/C2 的 native-valid 计数只在 availability sidecar 中报告。`unknown`、`blocked`、`diagnostic_required`、`eligible=false`、NULL score 和 missing row 都会中断 active run；它们不会被转成 false、0、均值或前值。

## 输入与 lineage

正式运行只读现有 strict-past indicator score：`C1_LogMASpread_5_60`、`C2_AdjVWAPSpread_5_60`，并要求显式提供一个精确的 `--input-manifest <path>`。runner 只接受该 manifest 声明的 artifact path；相对路径相对 manifest 所在目录解析，只有 manifest 明确声明 `basename_local_only` relocation policy 时才允许把 basename 映射到 `--input-root` 的根目录。不得扫描、递归搜索或在同名文件之间静默选择。runner 在打开表后核对声明的 SHA-256、完整表 row count、table identity、required columns，以及 manifest 声明的 security/date 范围（若存在），并同时记录完整表行数与本次过滤查询行数。机器相关路径不得写入代码；`--input-root` 仍可由 `CONVERGENCE_RESEARCH_INPUT_ROOT` 提供。baseline reconciliation 额外读取 C dimension score/state，仅用于独立重建校验。

Implementation 阶段只读取配置、schema、manifest 文本；不打开正式大型 DuckDB。synthetic fixtures 是当前唯一运行数据来源。

## Implementation review gate

当前阶段必须保持：

```text
implementation_review_status: needs_revision
reviewed_implementation_sha: b495201b04da9aaf1bc1b35d53586db036632489
formal_run_allowed: false
formal_run_status: blocked_preflight
result_review_status: not_started
formal_run_executed: false
blocked_preflight_run_ids:
- EXP-C01-20260715T175346Z
- EXP-C01-20260715T175920Z
```

未来 formal run 必须在批准的 implementation commit 上执行，并显式提供：

```text
--input-root <path>
--input-manifest <exact-authorized-manifest-path>
--output-root data/generated/sidecar/exp_c01/<RUN_ID>
--run-id <RUN_ID>
--allow-formal-run
--reviewed-implementation-sha <exact-40-character-sha>
```

runner 会拒绝未提供批准 SHA、当前 `HEAD` 与批准 SHA 不一致、未提供精确 source manifest、输出目录已存在、manifest 声明不一致或输入无法按声明解析的运行。上述命令现在不执行。

## 统计口径与异常门禁

`valid_step_count` 固定为所有 valid block 的 `(block_length - 1)` 之和，即 `eligible_row_count - valid_block_count`；`transition_rate_per_100_valid_steps` 的分母是该值，若为零则为 NULL。`max_year_active_share` 是 dominant calendar year 的 `active_true_count / 全部年份 active_true_count`，而 `max_year_active_rate` 才是各年份 `active_true_count / valid_count` 的最大值。两者都必须从 year profile 独立复算。

异常扫描使用预注册阈值：`year_active_concentration > 0.50`；对每个 candidate 分别按 baseline/candidate active count 检查 security concentration `> 0.10`；candidate active count 相对 baseline 的比值低于 `0.25` 或高于 `4.0` 时记录数量级异常。baseline 与 `c1_only`、baseline 与 `c2_only` 分别检查零 symmetric difference，代码分别为 `candidate_no_identity_response:c1_only` 和 `candidate_no_identity_response:c2_only`。全零输出不重复生成 concentration anomaly。

## Formal output 与 readback

未来正式结果目录必须包含六个小型 CSV：variant profile、overlap profile、score comparison、year profile、security profile 和 availability profile，以及 `exp_c01_manifest.json`、`exp_c01_validator_result.json`、`exp_c01_anomaly_scan.json`、`exp_c01_result_analysis.md`。原则上不生成新的大型 DuckDB。

formal runner 固定执行：读取并验证 source manifest 与输入 → 查询 → baseline reconciliation → 写六个 CSV → 磁盘 readback → preliminary manifest → preliminary validator/anomaly → 从实际六个 CSV、reconciliation、year/security profile 和 anomaly 生成完整 analysis → 绑定最终 analysis bytes 重建 manifest → 写 anomaly/validator governance 文件 → `require_governance_files=true` 的最终验证与只读复验。独立复算必须覆盖 n2x2、Jaccard、retention、precision、symmetric-difference rate、active rate、transition rate、segment duration sum、singleton ratio、max-year share/rate 和 availability gain。reconciliation 的 key count、mean/min、eligible、active、validity mismatch 必须全部为 0。

result analysis 必须包含实际运行与 reviewed SHA/input lineage、固定参数与 variants、cardinality/date range、core counts、overlap、score correlation/difference、duration/fragment/transition、availability、年度 profile、证券 profile、reconciliation、anomaly、independent recomputation、alternative explanations、supported conclusions、unsupported conclusions 和 user-review readiness。年度部分报告 Jaccard range、retention/precision 的 min/median/max；证券部分报告 Jaccard q25/median/q75、retention/precision median、最大 year/security active share，以及 pooled 与 security median 的方向关系。analysis 只允许输出 `ready_for_user_formal_result_review` 或 `needs_investigation_before_user_review`。

若异常扫描发现全零、全 NULL、全一、三个 variant 无差异、availability 不一致、年份或证券异常集中、层级计数不守恒、数量级异常或 baseline mismatch，必须停止，不得解释消融结果、请求 accepted、更新本目录为 completed 或推进下一项 sidecar task。

## 结果解释边界

R1-T05 redundancy reference 的 pooled Spearman≥0.95、Jaccard≥0.90、双向条件重合下界≥0.95 只能作为描述性 strong-substitutability reference。runner 和 validator 不自动选择 winner、不删除 C1/C2、不输出 replacement approval；最终是否删除某个指标由 Formal-result 审阅决定。
