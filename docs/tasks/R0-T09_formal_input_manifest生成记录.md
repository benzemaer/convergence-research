# R0-T09 formal input manifest 生成记录

## 记录范围

本记录对应 PR #67 上的 R0-T09 formal input manifest 生成与 dry-run 验证。该步骤只准备 R0-T09 runner 可消费的 `authorized_input_manifest.json`，不执行正式 27-config production materialization。

Production 27-config materialization has not been run by this step.
This step only prepares and validates formal R0-T09 input manifest.

## 生成结果

- `run_id`: `r0_t09_pr67_input_20260707_174738`
- `code_commit`: `4981077c0488082b038a1f388453c794d008da83`
- `output_dir`: `data/generated/r0/r0_t09_inputs/r0_t09_pr67_input_20260707_174738`
- `authorized_input_manifest_path`: `data/generated/r0/r0_t09_inputs/r0_t09_pr67_input_20260707_174738/authorized_input_manifest.json`
- `payload_path`: `data/generated/r0/r0_t09_inputs/r0_t09_pr67_input_20260707_174738/r0_t09_full_grid_payload.json`
- `generation_summary_path`: `data/generated/r0/r0_t09_inputs/r0_t09_pr67_input_20260707_174738/generation_summary.json`
- `payload_hash`: `2283a87697df4e499dc2ce07dd140afcb45582e785fe1a99ff1f42f110336f5b`

`data/generated/` remains ignored by git. The generated payload, manifest, and generation summary were produced locally and are not committed in this PR.

## Input Row Counts

- `raw_metric_results`: 8
- `indicator_score_results`: 24
- `dimension_score_results`: 12
- `nested_daily_state_results`: 9
- `daily_confirmation_results`: 108
- `confirmed_interval_results`: 0

## Coverage Summary

- `nested_wq_count`: 9
- `confirmation_wqk_state_count`: 108
- `contains_k1`: false
- `legacy_v1_field_count`: 0
- `future_or_return_field_count`: 0

The generated payload uses the active V1 naming `V1_TurnoverShrink20_60` / `TurnoverShrink20_60_raw` and does not contain legacy V1 names. It does not contain future labels, returns, backtest, portfolio, trade signal, gap merge, cooldown, `audit_report.md`, or `r1_handoff.md`.

## Dry-Run Command

```bash
python scripts/r0/run_r0_t09_main_grid.py \
  --input-manifest data/generated/r0/r0_t09_inputs/r0_t09_pr67_input_20260707_174738/authorized_input_manifest.json \
  --output-dir data/generated/r0/r0_t09/r0_t09_pr67_input_20260707_174738_dry_run \
  --max-workers 2 \
  --dry-run \
  --run-id r0_t09_pr67_input_20260707_174738_dry_run \
  --code-commit 4981077c0488082b038a1f388453c794d008da83
```

## Dry-Run Result

- `status`: `dry_run`
- `candidate_config_count`: 27
- `selected_config_count`: 27
- `run_scope`: `full_grid`
- `max_workers`: 2
- `artifacts_written`: false
- `input_payload_coverage_guard.validity_status`: `valid`
- `covered_nested_key_count`: 9
- `covered_confirmation_key_count`: 108
- `invalid_nested_row_count`: 0
- `invalid_confirmation_row_count`: 0
- `invalid_interval_row_count`: 0

## Commit Policy

Committed in PR #67: the builder implementation, CLI wrapper, regression tests, and this generation record.

Not committed: `data/generated/r0/r0_t09_inputs/r0_t09_pr67_input_20260707_174738/*` and any R0-T09 materialization outputs. No DuckDB, CSV.gz, DONE/FAILED marker, global output manifest, logs, audit report, or R1 handoff file is committed by this step.
