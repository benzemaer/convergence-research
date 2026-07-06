# D2-T18 provider coverage blocker 诊断与最小修复策略

## 状态

in_progress。本任务只做只读诊断与后续最小修复策略建议，不授权正式 ingestion，不修改 D2 acceptance 决策，不生成 D3 数据，不发布 data_version。

## 目标

D2-T18 基于 D2-T17 / D2-T15 产生的 candidate DuckDB staging，诊断当前阻塞 D2 acceptance 的 provider coverage gaps。脚本输出 gap 类型、证券维度、日期维度、证券-日期重叠、连续交易日区间、缺失 daily / adj_factor / stk_limit 明细、policy candidates 与 targeted repair candidates，用于判断下一步应走 D2-T19 targeted repair，还是需要单独 policy decision。

本任务的核心边界是只读。输入 DuckDB 必须来自 `data/generated/d2/` 下的候选 staging；输出只能写入 `data/generated/d2/` 下的诊断目录。诊断结果不得被追认为正式数据证据，也不得把 `blocked_pending_provider_coverage` 改写为 accepted。

## 非目标

本任务不重拉全量数据，不调用 provider，不写入或修改输入 DuckDB，不创建 formal DuckDB，不创建 run manifest、dataset manifest、source snapshot manifest 或 data_version，不生成 D3 rows，不计算 PCVT values，不定义 q、threshold 或 state machine，不生成 future return、label、backtest 或 portfolio 字段，不升级 BAOSTOCK、HITHINK、tnskhdata 或任何候选源为 formal source。

## 输入

输入为 D2-T17 / D2-T15 candidate staging DuckDB，例如：

```text
data/generated/d2/d2_t17_tnskhdata_endpoint_chunk_candidate/d2_t15_tnskhdata_staging.duckdb
```

脚本至少读取以下候选 staging 表：

```text
d2_quality_summary
d2_coverage_gaps
d2_expected_security_dates
d2_source_status
d2_factor_evidence
staging_daily_raw
staging_adj_factor
staging_stk_limit
staging_suspend_d
staging_stock_basic
staging_trade_calendar
staging_fetch_ledger
```

路径门禁禁止读取 `data/raw/`、`data/external/`、`MarketDB`、`.day` 文件，且输入必须是候选生成目录下的 DuckDB staging。

## 输出

脚本输出到 `data/generated/d2/d2_t18_provider_coverage_blocker_diagnostics/` 或等价 ignored candidate 诊断目录，包含：

```text
d2_t18_coverage_blocker_summary.json
d2_t18_gap_counts_by_type.csv
d2_t18_gap_counts_by_security.csv
d2_t18_gap_counts_by_date.csv
d2_t18_gap_rows.csv
d2_t18_gap_overlap_by_security_date.csv
d2_t18_missing_daily_rows.csv
d2_t18_missing_adj_factor_rows.csv
d2_t18_missing_stk_limit_rows.csv
d2_t18_missing_daily_intervals.csv
d2_t18_missing_adj_factor_intervals.csv
d2_t18_missing_stk_limit_intervals.csv
d2_t18_security_level_diagnosis.csv
d2_t18_date_level_diagnosis.csv
d2_t18_gap_policy_candidates.csv
d2_t18_targeted_repair_candidates.csv
d2_t18_recommended_actions.md
d2_t18_sql_manifest.sql
```

这些输出均为诊断产物，不是正式 dataset manifest，不是 released data product，也不是 D3 / R0 输入授权。

## 诊断规则

`listed_open_missing_daily` 生成 daily P0 targeted repair candidate。`daily_dependency_missing` 只能说明 price limit 依赖 daily 缺失，不得单独生成 stk_limit repair。`stk_limit_missing` 生成 stk_limit P1 targeted repair candidate。`unresolved_adjustment_factor` 若能被明确归入 carry-forward policy candidate，则只进入 policy candidates；否则生成 adj_factor P2 targeted repair candidate。

连续缺口区间按 `d2_expected_security_dates` 的交易日顺序压缩，不按自然日压缩。证券-日期重叠诊断必须识别 `listed_open_missing_daily` 与 `daily_dependency_missing` 同日出现的情况，并统计 `daily_missing_implies_price_limit_dependency_count`。

## 验收标准

`scripts/diagnose_d2_provider_coverage_blockers.py` 能在合成 DuckDB fixture 上生成完整输出文件，CSV 包含表头且排序稳定；summary 保持 `d2_acceptance_observed = blocked_pending_provider_coverage`，并显式声明 `d3_generation_authorized = false`、`r0_state_generated = false`、`data_version_published = false`。测试必须覆盖 gap counts、overlap、targeted repair、policy candidate、交易日区间压缩、路径门禁和不修改 acceptance 的只读语义。

## 阻塞条件 / 失败状态

若输入路径位于 `data/raw/`、`data/external/`、`MarketDB`、`.day` 或非 `data/generated/d2/` 候选目录，本任务失败。若输出目录不在 `data/generated/d2/` 下，或尝试写 formal DuckDB，本任务失败。若诊断脚本调用 provider、读取真实原始行情目录、修改输入 DuckDB、创建 manifest / data_version、生成 D3 / PCVT / labels / returns / backtest / portfolio，PR 必须回退。

若 `contract`、任务文档、README、测试或 validation 未通过，本 PR 失败。若诊断结果被描述为 D2 acceptance accepted，或暗示 D3-T07 / R0 已解锁，本 PR 失败。

## 回退方式

回退本 PR 新增的脚本、测试、任务文档和 README 索引更新即可。由于本任务不修改输入 DuckDB、不提交 generated 诊断输出、不创建 manifest 或 data_version，回退不需要数据迁移或产物冻结处理。

## Validation

本 PR 合并前需通过：

```bash
ruff format --check scripts tests
ruff check scripts tests
python scripts/validate_configs.py
python -m unittest discover -s tests -v
python scripts/build_compendium.py --check
git diff --check
```
