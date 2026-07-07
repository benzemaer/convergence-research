# R0-T10 execution record

记录状态：in_progress；R0-T10 正在由真实 D3 源生成 R0-T04 -> R0-T07 upstream artifacts，并准备执行 R0-T09 dry-run、baseline 与正式 27 组 full-grid。

## 本提交记录

第一段提交已停止在“八、正式 27 组 full-grid”之前。第二段代码已解除固定的 `full_grid_requires_second_submission` 阻断，改为真实 upstream、dry-run 和 baseline 前置门禁：只有正式 `authorized_input_manifest.json`、R0-T09 dry-run 和 baseline 单组 materialization 均通过后，`--full-grid-r0-t09` 才会执行 27 组 full-grid。

本次修正进一步补齐 R0-T10 的 upstream 生成职责：当调用方未显式提供 R0-T04 至 R0-T07 artifacts 时，R0-T10 会从真实 D3-T11 成交额/换手率/股本候选 DuckDB 与 D3-T07 调整价格 DuckDB 读取数据，依次调用 R0-T04、R0-T05、R0-T06、R0-T07 engine 生成正式 upstream artifacts。该路径不使用 `tests/fixtures/*`、`synthetic_smoke_fixture`、`_contract_grid_payload()`、tmpdir test outputs 或手工伪造 JSON。

## 当前本地数据判断

本地存在 R0-T10 可读取的真实 D3 源：

```text
D3-T11 source DuckDB: data/generated/d3/d3_t11_volume_amount_share_turnover_candidate_clean_rerun/d3_t11_volume_amount_share_turnover_candidate.duckdb
D3-T07 adjusted price DuckDB: data/generated/d3/d3_t07_candidate_daily_observation/d3_t07_candidate_daily_observation.duckdb
D3-T11 source rows: 1,730,769
source securities: 800
date range: 20160104 -> 20260630
```

单证券真实源探针已通过：`000596.SZ` 读取 2,546 行 D3 source observations，生成 20,368 行 R0-T04 raw metrics、61,104 行 R0-T05 indicator scores、30,552 行 R0-T05 dimension scores、22,914 行 R0-T06 nested daily states、274,968 行 R0-T07 daily confirmations；`K=1` 未出现，`V1_TurnoverShrink20_60` 每个观察日均有 raw result。

## 执行字段

```text
run_id: pending_formal_execution
code_commit: pending_phase_2_commit
real_data_source_paths: D3-T11 candidate DuckDB + D3-T07 adjusted price DuckDB
r0_t04_upstream_artifact: pending_generation
r0_t05_upstream_artifact: pending_generation
r0_t06_upstream_artifact: pending_generation
r0_t07_upstream_artifact: pending_generation
authorized_input_manifest_path: pending_generation
r0_t09_output_dir: pending_execution
r0_t09_output_manifest_path: pending_execution
dry_run_result: pending
baseline_result: pending
full_grid_result: pending
completed_config_count: 0
skipped_config_count: 0
failed_config_count: 0
pending_config_count: 27
failed_json_exists: false
partial_file_exists: false
audit_report_generated: false
r1_handoff_generated: false
can_enter_r0_t11: false
```

## 继续条件

正式执行完成后，本记录只登记路径、hash、row count、manifest summary 与最终状态；不得提交 `data/generated/r0/r0_t10/**` 下的 generated artifacts。只有 R0-T09 authorized input manifest 的 generation summary 显示 `authorized_r0_input=true`、`synthetic_smoke_fixture=false`、coverage valid、legacy V1 count 为 0、future/return count 为 0，且 dry-run 与 baseline 单组 materialization 通过，才能启动正式 27 组 full-grid。
