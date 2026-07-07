# D3-T07 从 D2-T20 evidence-verified candidate 生成标准日频观测表

## 状态

completed via PR #53；D3-T12 对 candidate gate 语义作后续修正。本任务是 D3 第一段真实 candidate observation 生成，只读取 D2-T20 research candidate，并输出 D3 标准日频观测表 candidate。本任务不发布 formal data_version，不生成 D3 formal release，不生成 PCVT、R0、labels、returns、backtest 或 portfolio。

## 目标

D3-T07 新增 `scripts/generate_d3_t07_candidate_daily_observation.py`，从 D2-T20 candidate DuckDB 读取 `staging_daily_raw`、`d2_source_status`、`d2_factor_evidence`、`staging_stk_limit`、`staging_adj_factor` 和 D2 policy evidence tables，生成 `d3_candidate_daily_observation` candidate DuckDB。生成逻辑必须排除 listing_pause 日期，保留 D2/D3 provenance、policy flags 与 evidence status，并输出 quality report、handoff report、row-count report、gap report 和 candidate file hash summary。

## 非目标

本任务不读取 `data/raw/`、`data/external/`、MarketDB 或 `.day` 文件，不调用 provider，不修改 D2-T20 source DuckDB，不回写 `staging_daily_raw`、`staging_adj_factor`、`staging_stk_limit`、`d2_source_status` 或 `d2_factor_evidence`。本任务不创建 run manifest、dataset manifest、source snapshot manifest 或 formal data_version，不生成 labels、returns、future outcome、backtest、portfolio、PCVT values 或 R0 state。

## 输入

必需输入：

```text
--d2-t20-duckdb data/generated/d2/d2_t20_fast_coverage_policy_candidate/d2_t15_tnskhdata_staging.duckdb
--d2-t20-acceptance-report data/generated/d2/d2_t20_fast_coverage_policy_candidate/d2_t20_acceptance_candidate_report.json
--d2-t20-handoff-report data/generated/d2/d2_t20_fast_coverage_policy_candidate/d2_t20_handoff_candidate_report.json
--output-dir data/generated/d3/d3_t07_candidate_daily_observation
```

可选输入：

```text
--contract configs/d3/d3_t07_candidate_daily_observation_contract.v1.json
--sample-securities 20
--start-date YYYYMMDD
--end-date YYYYMMDD
```

## 输出

允许输出到 ignored local candidate 目录：

```text
data/generated/d3/d3_t07_candidate_daily_observation/
```

输出文件包括：

```text
d3_t07_candidate_daily_observation.duckdb
d3_t07_generation_summary.json
d3_t07_quality_report.json
d3_t07_handoff_candidate_report.json
d3_t07_row_count_by_security.csv
d3_t07_policy_usage_summary.csv
d3_t07_excluded_listing_pause_rows.csv
d3_t07_unresolved_rows.csv
d3_t07_candidate_file_hash_summary.json
```

禁止输出 `data_version.json`、`formal_manifest.json`、`labels.csv`、`returns.csv`、`backtest.csv`、`portfolio.csv` 或 `r0_state.csv`。

## Gate 规则

脚本必须先读取 D2-T20 acceptance 与 handoff report。D3 candidate generation 是开放候选层门禁，只 hard block 无法形成基础 candidate observation、上游未授权、试图发布 formal data_version、试图生成 PCVT/R-state/labels/returns/backtest/portfolio、输出越界、主键不可形成、重复主键不可消解、OHLC 无效或 effective adjusted fields 无法形成等情况。`policy_evidence_pending_hash` 是 candidate warning，不是 D3 candidate hard blocker；当其他 hard gate 均通过时，应输出 `accepted_candidate_observation_with_warnings`，并继续生成可追溯 candidate rows。

D3-T07 不判断该 candidate row 是否可供 R0、R1、R2、R3、R4、R5 或 R6 使用。报告必须用通用 `consumer_readiness` / `consumer_profiles` 结构表达下游消费审计由具体 consumer task 负责；若保留旧兼容字段，不得让它决定 D3 candidate generation。D3 candidate generation 不等于 formal release，formal use 仍必须由后续 release gate 严格授权。

## 生成规则

只生成可交易 daily rows。`trading_status = listing_pause`、`daily_status = not_applicable_or_expected_empty`、`price_limit_status = not_applicable_or_expected_empty` 的日期不得进入 observation table；这不是缺样本、不是 0 价格、不是 NaN 价格，而是不可交易状态，D3 不参与事件和收益计算。

`effective_adj_factor` 的解析规则为：`adjustment_factor_status = resolved` 时读取 `staging_adj_factor.adj_factor`；`neutral_factor_1_policy` 使用 `1.0`；`factor_interval_policy` 必须按 `d2_policy_corporate_action_evidence` 的 `start_date <= trade_date <= end_date` 唯一匹配 interval。若找不到唯一 interval，该 row 不得被 accepted，quality report 记录 `factor_interval_unresolved_count` 并阻塞。

`adjusted_open/high/low/close` 分别等于 raw OHLC 乘以 `effective_adj_factor`。policy rows 不是 provider raw rows；D3-T07 只读取 D2-T20 policy evidence tables，不写入任何 D2 staging/provider table。

## 验收标准

`d3_t07_quality_report.json` 必须至少报告 input row count、generated row count、listing_pause excluded count、OHLC 质量计数、effective factor 缺失计数、factor interval unresolved 计数、duplicate key 计数、policy usage 计数、candidate generation hard blockers、soft warnings、candidate quality tier、policy evidence readiness status、formal use authorization 和通用 consumer readiness。若 duplicate observation key、null OHLC、non-positive price、high-low violation、missing effective factor 或 factor interval unresolved 任一计数大于 0，`d3_t07_generation_decision` 必须为 blocked，`d3_candidate_observation_accepted = false`。

验收时必须证明 D2-T20 source DuckDB 未被修改，`staging_adj_factor` 未新增伪 provider rows，输出不包含 formal data_version、R0、labels、returns、backtest 或 portfolio。

## 阻塞条件 / 失败状态

若 D2-T20 acceptance/handoff hard gate 不满足，生成必须阻塞为 `blocked_pending_d2_t20_handoff`。若 factor interval policy 找不到唯一 interval，生成必须阻塞为 `blocked_pending_factor_interval_resolution`。若存在 duplicate key、invalid OHLC、missing effective factor 或其他 quality blocker，生成必须阻塞为 `blocked_pending_quality_resolution`。policy evidence 尚未 formal verified、company-action evidence pending、limit_status 缺失、R-stage readiness 不满足或 formal release 条件不满足，只能写入 warning / quality / evidence / consumer readiness 状态，不得阻止 D3 candidate row generation。若 PR 提交 generated outputs、DuckDB、PDF、formal manifest、data_version、labels、returns、backtest、portfolio、PCVT 或 R0 输出，PR 必须回退。

## 回退方式

回退本 PR 新增的 D3-T07 generator、contract config、JSON Schema、tests、任务文档和 README 更新即可。本任务不提交 generated outputs，不修改 D2-T20 source DuckDB，不发布 formal data_version。

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
