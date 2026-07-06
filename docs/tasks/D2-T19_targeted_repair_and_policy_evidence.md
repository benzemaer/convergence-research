# D2-T19 定向补拉与 coverage policy 证据诊断

## 状态

in_progress。本任务基于 D2-T18 诊断输出，只处理 targeted repair candidates 与 coverage policy candidates；默认不访问 provider，CI 只使用 synthetic DuckDB 与 fake provider。

## 目标

D2-T19 分为两部分。D2-T19A 从 `d2_t18_targeted_repair_candidates.csv` 生成最小范围 repair plan，并在人工显式传入 `--execute-provider-repair` 时，只对 D2-T18 已识别的 daily / stk_limit 缺口执行定向补拉。D2-T19B 从 `d2_t18_gap_policy_candidates.csv` 生成 unresolved adjustment factor policy evidence，判断是否应进入 neutral factor、carry-forward、targeted adj_factor repair、manual review 或 keep blocked。

补拉必须写入新的 D2-T19 candidate DuckDB 副本，不得修改 D2-T17 源 DuckDB。D2-T19 输出 post-repair quality report、acceptance candidate report、handoff candidate report、remaining gaps、repair delta、policy evidence 与 next actions，但不授权 D2 acceptance、D3 generation 或 R0。

## 非目标

本任务不做全量 provider refetch，不在 CI 访问真实 provider，不写 formal DuckDB，不发布 manifest 或 data_version，不生成 D3 rows，不生成 R0 states，不计算 PCVT，不生成 labels、returns、backtest 或 portfolio，不把 D2 acceptance 从 blocked 硬改为 accepted，不静默删除 coverage gaps，不把 `pro_bar(qfq/hfq)` 写入 canonical staging。

`pro_bar(qfq/hfq)` 如由人工传入 `--allow-diagnostic-pro-bar` 启用，只能作为 diagnostic evidence，不得写入 `staging_adj_factor`，不得生成 adjusted price，也不得作为 formal source。

## 输入

必需输入：

```text
--source-duckdb data/generated/d2/d2_t17_tnskhdata_endpoint_chunk_candidate/d2_t15_tnskhdata_staging.duckdb
--d2-t18-dir data/generated/d2/d2_t18_provider_coverage_blocker_diagnostics
--output-dir data/generated/d2/d2_t19_targeted_repair_candidate
```

`--source-duckdb` 与 `--output-dir` 必须位于 `data/generated/d2/` 下。路径门禁禁止 `data/raw/`、`data/external/`、`MarketDB`、`.day` 和 formal DuckDB 路径。

## 输出

D2-T19 输出以下 ignored candidate 诊断文件：

```text
d2_t19_repair_plan.jsonl
d2_t19_repair_ledger.jsonl
d2_t19_repair_run_summary.json
d2_t19_provider_error_summary.json
d2_t19_post_repair_quality_report.json
d2_t19_post_repair_acceptance_candidate_report.json
d2_t19_post_repair_handoff_candidate_report.json
d2_t19_remaining_coverage_gaps.csv
d2_t19_repaired_gap_delta.csv
d2_t19_policy_evidence.csv
d2_t19_policy_recommendations.md
d2_t19_recommended_next_actions.md
```

输出目录内的 `d2_t15_tnskhdata_staging.duckdb` 是源 DuckDB 的文件级副本。所有 endpoint repair 写入都必须先按 task scope 删除复制库中的旧 rows，再插入 provider 返回且通过目标过滤的 rows。

## Repair Plan 规则

`listed_open_missing_daily` 生成 daily P0 repair，参数策略为 `primary_ts_code_start_end_then_trade_date_fallback`。`stk_limit_missing` 生成 stk_limit P1 repair，参数策略为 `primary_ts_code_start_end_then_date_range_fallback_filtered_to_ts_code`。`daily_dependency_missing` 不生成独立 stk_limit repair，它必须依赖 daily repair 后重跑 quality gate 再判断。

daily fallback by `trade_date` 和 stk_limit fallback by date range / trade date 都必须过滤到目标 `ts_code` 与目标日期，不得扩大写入范围。

## Policy Evidence 规则

对 D2-T18 policy candidates 中的 unresolved adjustment factor 证券输出：

```text
ts_code
list_date
delist_date
first_daily_date
last_daily_date
daily_row_count
adj_factor_row_count
first_adj_factor_date
last_adj_factor_date
missing_adj_factor_gap_count
has_any_adj_factor
nearest_provider_factor_evidence
diagnostic_pro_bar_available
diagnosis
recommended_policy
```

`recommended_policy` 只可作为后续 D2-T20 policy acceptance 或 second pass repair 的证据，不得直接修改 quality gate 或 acceptance。

## 验收标准

脚本默认不调用真实 provider；`--dry-run-plan` 只输出 repair plan；`--no-remote-fetch` 只复制 DuckDB 并重跑 quality/report；`--execute-provider-repair` 只处理 D2-T18 targeted repair candidates。测试必须证明源 DuckDB 不被修改、fallback 会过滤非目标证券、`daily_dependency_missing` 不生成独立 repair、policy evidence 不写入 `staging_adj_factor`、provider failure 不会把 acceptance 改成 accepted，且 D3/R0/PCVT/labels/returns/backtest/portfolio 不生成。

## 阻塞条件 / 失败状态

若输入或输出路径违反 D2-T19 路径门禁，本任务失败。若脚本在未传 `--execute-provider-repair` 时调用真实 provider，本任务失败。若 PR 修改 D2-T17 源 DuckDB、写 formal DuckDB、提交 generated outputs、创建 manifest 或 data_version、生成 D3/R0/PCVT/labels/returns/backtest/portfolio，PR 必须回退。

若 repair 后仍存在 unresolved adjustment factor、listed-open missing daily、price-limit unresolved、provider error 或其他 quality blocker，acceptance 必须保持 blocked。即使 synthetic 或人工 targeted repair 使底层 quality gate 暂时可通过，D2-T19 仍不得直接授权 D3/R0，必须由后续 D2-T20 acceptance / policy PR 显式处理。

## 回退方式

回退本 PR 新增脚本、任务文档、README 更新和测试即可。D2-T19 不提交 generated outputs、不修改源 DuckDB、不创建 manifest 或 data_version，因此回退不需要迁移正式产物。

## 人工运行方式

先 dry-run：

```powershell
$t17Dir = "data/generated/d2/d2_t17_tnskhdata_endpoint_chunk_candidate"
$t18Dir = "data/generated/d2/d2_t18_provider_coverage_blocker_diagnostics"
$t19Dir = "data/generated/d2/d2_t19_targeted_repair_candidate"

python scripts/run_d2_t19_targeted_provider_repair.py `
  --source-duckdb "$t17Dir/d2_t15_tnskhdata_staging.duckdb" `
  --d2-t18-dir $t18Dir `
  --output-dir $t19Dir `
  --dry-run-plan
```

人工确认后再执行定向补拉：

```powershell
python scripts/run_d2_t19_targeted_provider_repair.py `
  --source-duckdb "$t17Dir/d2_t15_tnskhdata_staging.duckdb" `
  --d2-t18-dir $t18Dir `
  --output-dir $t19Dir `
  --env-file .env.local `
  --execute-provider-repair `
  --max-workers 2 `
  --initial-requests-per-minute 50 `
  --max-requests-per-minute 100 `
  --min-requests-per-minute 20
```

## Validation

合并前必须通过：

```bash
ruff format --check scripts tests
ruff check scripts tests
python scripts/validate_configs.py
python -m unittest discover -s tests -v
python scripts/build_compendium.py --check
git diff --check
```
