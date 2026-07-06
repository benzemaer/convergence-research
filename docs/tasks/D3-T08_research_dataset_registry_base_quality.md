# D3-T08 研究基础数据集 registry 与路线无关质量审计

## 状态

in_progress。本任务是 D3 dataset layer 任务，用于为 D3-T07 candidate daily observation 建立路线无关的 research dataset registry、schema catalog、field catalog、dataset fingerprint 和基础质量审计。本任务不是 PCVT layer，不生成 PCVT-specific readiness、PCVT values、R0 state、labels、returns、backtest 或 portfolio。

## 目标

D3-T08 新增 `scripts/audit_d3_t08_research_dataset_registry.py`，只读取 D3-T07 candidate observation DuckDB 与 D3-T07 quality/handoff reports，生成 D3 research dataset registry candidate audit。输出包括 dataset registry、schema catalog、field quality、security/date coverage、policy usage、window capacity 和 candidate file hash summary。window capacity 只描述路线无关的历史窗口容量，不绑定任何 indicator_id。

## 非目标

本任务不计算 `P1_NATR14`、`C1_LogMASpread`、`V1_VolShrink` 等具体 PCVT 指标，不生成 indicator-specific readiness，不定义 `q`、threshold、state machine、PCVT value、PCVT score、PCVT state、future return、label、breakout direction、backtest signal 或 portfolio return。本任务不读取 D2/D1、`data/raw/`、`data/external/`、MarketDB 或 `.day` 文件，不修改 D3-T07 source DuckDB，不重新引入 listing_pause observation rows，不发布 formal data_version。

## 输入

必需输入：

```text
--d3-t07-duckdb data/generated/d3/d3_t07_candidate_daily_observation/d3_t07_candidate_daily_observation.duckdb
--d3-t07-quality-report data/generated/d3/d3_t07_candidate_daily_observation/d3_t07_quality_report.json
--d3-t07-handoff-report data/generated/d3/d3_t07_candidate_daily_observation/d3_t07_handoff_candidate_report.json
--output-dir data/generated/d3/d3_t08_research_dataset_registry
```

可选输入：

```text
--contract configs/d3/d3_t08_research_dataset_registry_contract.v1.json
--sample-securities 20
--start-date YYYYMMDD
--end-date YYYYMMDD
```

## 输出

允许输出到 ignored local candidate 目录：

```text
data/generated/d3/d3_t08_research_dataset_registry/
```

输出文件包括：

```text
d3_t08_research_dataset_registry.duckdb
d3_t08_generation_summary.json
d3_t08_quality_report.json
d3_t08_handoff_candidate_report.json
d3_t08_schema_catalog.csv
d3_t08_field_quality.csv
d3_t08_coverage_by_security.csv
d3_t08_coverage_by_date.csv
d3_t08_policy_usage_summary.csv
d3_t08_window_capacity_summary.csv
d3_t08_candidate_file_hash_summary.json
```

DuckDB audit tables 包括 `d3_research_dataset_registry`、`d3_research_dataset_schema_catalog`、`d3_research_dataset_field_quality`、`d3_research_dataset_coverage_by_security`、`d3_research_dataset_coverage_by_date`、`d3_research_dataset_policy_usage` 和 `d3_research_dataset_window_capacity`。

## Gate 规则

脚本必须先读取 D3-T07 handoff 与 quality report。只有 `d3_t07_generation_decision = accepted_candidate_observation`、`d3_candidate_observation_generated = true`、`formal_data_version_published = false`、`labels_generated = false`、`returns_generated = false`、`pcvt_values_generated = false`、`r0_state_generated = false`，且 D3-T07 quality blockers 均为 0 时，才允许执行 registry audit。任一条件不满足时，输出 `blocked_pending_d3_t07_candidate_observation`，不得绕过。

## 审计规则

基础质量审计必须检查 `(ts_code, trade_date)` 是否重复、raw/adjusted OHLC 是否为正、high/low 关系是否有效、`effective_adj_factor > 0`、adjusted OHLC 是否与 raw OHLC 乘以 factor 一致、listing_pause rows 是否不存在、`is_listing_pause` 是否全 false、policy rows 是否有 provenance、`source_task_id = D2-T20`、`generated_by_task = D3-T07`，以及 `row_provenance` 是否非空。

核心质量失败时，`d3_t08_generation_decision = blocked_pending_research_dataset_quality` 且 `research_dataset_registry_generated = false`。核心质量通过但存在路线无关警告时，例如 amount/volume unit contract 尚未声明，decision 为 `accepted_research_dataset_registry_with_warnings`。无警告时为 `accepted_research_dataset_registry`。

## 阻塞条件 / 失败状态

若 D3-T07 handoff/quality gate 不满足，本任务阻塞为 `blocked_pending_d3_t07_candidate_observation`。若 D3-T07 observation table 存在 duplicate key、invalid raw/adjusted OHLC、invalid effective factor、adjusted factor mismatch、listing_pause row、policy provenance 缺失或 lineage 缺失，本任务阻塞为 `blocked_pending_research_dataset_quality`。若 PR 引入 D2/D1/raw/external/MarketDB/.day 读取、D3-T07 source DuckDB 修改、PCVT values/scores/states、indicator-specific readiness、q/threshold/state machine、labels、returns、backtest、portfolio、R0 或 formal data_version，本 PR 失败并应回退。

## 验收标准

合并前必须证明 D3-T08 只读取 D3-T07 candidate observation，不读取 D2/D1/raw/external/MarketDB/.day；D3-T07 handoff/quality gate 被严格执行；输出 route-agnostic registry/schema/quality/coverage/window-capacity tables；输出 schema 不包含 PCVT value/score/state、q threshold、state、label 或 future return；不生成 labels、returns、backtest、portfolio、R0 或 formal data_version。

## 回退方式

回退本 PR 新增的 D3-T08 audit script、contract config、JSON Schema、tests、任务文档和 README 更新即可。本任务不提交 generated outputs，不修改 D3-T07 source DuckDB，不发布 formal data_version。

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
