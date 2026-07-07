# R0-T09 smoke 验证记录

状态：completed for PR #67 smoke update。

## commit_sha

`3125b1f430ba1e540b4a585261cf05db942c19a5`

该 commit 是本次 smoke 执行时的 PR #67 head。Smoke 输入 fixture 来自 `tests/fixtures/r0/r0_t09_smoke/`，输出写入系统临时目录，未提交 runner 输出 artifact。

## run_id

- dry-run：`R0-T09-SMOKE-DRY-RUN`
- baseline materialization / resume：`R0-T09-SMOKE-BASELINE`

## dry_run_command

```bash
python scripts/r0/run_r0_t09_main_grid.py \
  --input-manifest tests/fixtures/r0/r0_t09_smoke/full_grid_authorized_input_manifest.json \
  --output-dir "$R0_T09_SMOKE_DIR/dry_run_out" \
  --max-workers 6 \
  --dry-run \
  --run-id R0-T09-SMOKE-DRY-RUN \
  --code-commit "$R0_T09_COMMIT" \
  > "$R0_T09_SMOKE_DIR/dry_run.json"
```

## dry_run_summary

Dry-run smoke passed with `status=dry_run`, `candidate_config_count=27`, `selected_config_count=27`, `run_scope=full_grid`, and `artifacts_written=false`. The task list contains `R0_W250_Q20_K3_WEAK_D010`, contains no `K=1` config, and `input_payload_coverage_guard.validity_status=valid`.

## baseline_smoke_command

```bash
python scripts/r0/run_r0_t09_main_grid.py \
  --input-manifest tests/fixtures/r0/r0_t09_smoke/full_grid_authorized_input_manifest.json \
  --output-dir "$R0_T09_SMOKE_DIR/baseline_out" \
  --max-workers 1 \
  --only-config R0_W250_Q20_K3_WEAK_D010 \
  --resume \
  --run-id R0-T09-SMOKE-BASELINE \
  --code-commit "$R0_T09_COMMIT" \
  > "$R0_T09_SMOKE_DIR/baseline.json"
```

Resume smoke reran the same command and wrote `$R0_T09_SMOKE_DIR/baseline_resume.json`.

## baseline_smoke_summary

Baseline materialization smoke passed with `status=completed`, `run_scope=single_config`, `selected_config_count=1`, `completed_config_count=1`, `failed_config_count=0`, `pending_config_count=0`, and `baseline_candidate_config_id=R0_W250_Q20_K3_WEAK_D010`.

Baseline resume smoke passed with `skipped_config_count=1` and `per_config_status.R0_W250_Q20_K3_WEAK_D010.status=skipped`.

## expected_output_files

The baseline smoke produced these files in the temporary output directory:

- `status/R0_W250_Q20_K3_WEAK_D010.DONE.json`
- `daily_states/R0_W250_Q20_K3_WEAK_D010.daily_states.duckdb`
- `daily_states/R0_W250_Q20_K3_WEAK_D010.daily_states.csv.gz`
- `confirmed_intervals/R0_W250_Q20_K3_WEAK_D010.confirmed_intervals.duckdb`
- `confirmed_intervals/R0_W250_Q20_K3_WEAK_D010.confirmed_intervals.csv.gz`
- `manifest.json`

`status/R0_W250_Q20_K3_WEAK_D010.FAILED.json` was absent.

## manifest_summary

The baseline manifest records `run_scope=single_config`, `selected_config_count=1`, `selected_config_ids=["R0_W250_Q20_K3_WEAK_D010"]`, and the expected per-config artifact hashes. Resume validation used the DONE marker and artifact hashes rather than treating the single-config run as a 27-config full-grid production materialization.

## forbidden_absence_checks

Smoke checks confirmed that `audit_report.md` and `r1_handoff.md` were not generated. The daily CSV contains `TurnoverShrink20_60_raw` and `AmountLevel20Pct`, does not contain `AmountLevel20Pct_raw`, and the serialized smoke result / manifest / daily CSV do not contain legacy V1 names: `VolShrink20_60_raw`, `V1_VolShrink20_60`, `VolShrink20_60`, or `volume_shrink_20_60`.

No future labels, returns, future volatility, breakout direction, backtest, portfolio, trade signal, gap merge, cooldown, provider call, direct `data/raw`, direct `MarketDB`, or direct `.day` read was introduced by this smoke.

## cleanup_note

Smoke outputs are generated in a temporary directory and are not committed. Full 27-config production materialization is not performed by this PR. The fixture files under `tests/fixtures/r0/r0_t09_smoke/` are committed input fixtures only, not runner output artifacts.
