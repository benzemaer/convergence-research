# R0-T09 formal input manifest 生成记录

## 记录范围

本记录对应 PR #67 上的 R0-T09 formal input manifest 生成门禁修正。当前没有生成正式 `authorized_input_manifest.json`，因为本地尚未提供真实 R0-T04 至 R0-T07 上游 artifact 集合。

之前由 contract grid 构造的 payload 只能视为 synthetic coverage smoke，不得称为 formal input manifest，不得写成 `authorized_r0_input=true` 的正式输入，也不得用于 R0-T09 production full-grid materialization。

Production 27-config materialization has not been run by this step.
This step only tightens and validates the formal input manifest gate.

## Current Status

- `status`: `blocked`
- `reason_code`: `formal_upstream_inputs_missing`
- `authorized_input_manifest_written`: false
- `formal_upstream_inputs_missing`: true
- `production_full_grid_materialization_run`: false

R0-T09 production remains blocked until real R0-T04 -> R0-T07 upstream artifacts are provided:

- R0-T04 `raw_metric_results`
- R0-T05 `indicator_score_results` and `dimension_score_results`
- R0-T06 `nested_daily_state_results`
- R0-T07 `daily_confirmation_results` and `confirmed_interval_results`

## Gate Semantics

The formal builder now requires explicit upstream input paths in formal mode. Running `scripts/r0/build_r0_t09_input_manifest.py` without `--r0-t04-input`, `--r0-t05-input`, `--r0-t06-input`, and `--r0-t07-input` writes only `generation_summary.json` with `status=blocked`; it does not write `r0_t09_full_grid_payload.json` or `authorized_input_manifest.json`.

The contract-grid payload helper is retained only for explicit synthetic smoke mode and tests. Synthetic smoke manifests are not authorized for R0 production input and cannot target `data/generated/r0/r0_t09_inputs/`.

## Blocked Summary Shape

When upstream inputs are missing, the local summary must record:

```json
{
  "status": "blocked",
  "reason_codes": ["formal_upstream_inputs_missing"],
  "formal_upstream_inputs_missing": true,
  "authorized_input_manifest_written": false
}
```

## Production Guard

R0-T09 runner dry-run and tmpdir smoke tests may still use synthetic fixtures. A non-dry-run full-grid materialization targeting `data/generated/r0/r0_t09/...` must reject synthetic or contract-grid manifests with `synthetic_contract_grid_input_forbidden_for_production`.

No DuckDB, CSV.gz, DONE/FAILED marker, global output manifest, logs, audit report, or R1 handoff file is generated or committed by this correction.
