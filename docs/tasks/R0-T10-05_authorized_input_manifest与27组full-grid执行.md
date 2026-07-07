# R0-T10-05 authorized input manifest 与 27 组 full-grid 执行

状态：in_progress via PR #73。

本任务在 R0-T10 umbrella 下解锁 R0-T09 production full-grid 的正式输入和正式运行。旧 R0-T09 runner / contract / smoke 已经完成，但正式 full-grid 一直 blocked，原因是当时尚无真实 R0-T04 -> R0-T07 artifacts，也没有低内存 artifact-manifest 输入模式。本任务必须消费 PR #69 / #70 / #71 / #72 evidence 指向的真实 R0-T04、R0-T05、R0-T06、R0-T07 本地生成 artifacts，生成正式 `authorized_input_manifest`，并执行 27 组主网格 candidate artifact materialization。

本任务不修改 R0-T04、R0-T05、R0-T06 或 R0-T07 的语义，不重新生成这些上游 artifacts，不绕回 D3、raw、external、MarketDB 或 `.day`，不生成 R0 audit report，不生成 R1 handoff，不做 R1 分析，不生成 future label、future return、release direction、breakout direction、backtest、portfolio 或 trade signal，也不做 gap merge、cooldown 或策略回测。

## 输入与前置门禁

必须读取并校验以下 evidence 文件：`docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md`、`docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md`、`docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md`、`docs/evidence/r0/R0-T10-04_r0_t07_confirmation_interval_materialization_evidence.md`。只有四层 evidence 均为 completed、validator passed、downstream gate 打开、input artifact 路径存在且 SHA-256 可复算一致时，才能写正式 authorized manifest 和启动 full-grid。若任一条件不满足，只能写 blocked summary，不得写 authorized manifest，不得运行 full-grid，不得推进 README。

从本任务开始，所有新运行参数、authorized manifest、summary、validator result 和 evidence 中的 `code_commit` 必须是同一个 40 位完整 Git SHA。短 SHA 必须被拒绝，错误码包含 `short_code_commit_forbidden`。PR #71 中短 SHA 只作为历史事实保留，本任务不得新增短 SHA 兼容字段。

## 输入模式

正式 full-grid 必须使用 artifact-backed / streaming input mode。authorized manifest 只记录 R0-T04、R0-T05、R0-T06 和 R0-T07 DuckDB artifact 的路径、表名、hash、row count、coverage 和 evidence lineage，不嵌入行级 rows，不生成 `r0_t09_full_grid_payload.json`，不把上游行级数据合并成巨大 JSON，不在父进程 `json.load` 全量 payload，也不把完整 input payload 放入每个 worker task。

worker 只能接收 config id、authorized manifest path/hash、DuckDB paths/hash、table names、小型 config 和输出路径。worker 在本进程内按 W/q/K 从 DuckDB 读取必要切片，父进程只接收 config summary、row count、hash、路径和状态。

## 输出

正式 authorized manifest 建议输出到 `data/generated/r0/r0_t10/<run_id>/r0_t10_05_authorized_input_manifest.json`。full-grid 输出到 `data/generated/r0/r0_t10/<run_id>/r0_t09_full_grid/`，每个 config 独立目录包含 `candidate_config_snapshot.json`、`candidate_daily_state.duckdb`、`candidate_daily_state.parquet`、`candidate_confirmed_interval.duckdb`、`candidate_confirmed_interval.parquet`、`DONE.json` 或 `FAILED.json` 以及日志。全局输出包含 `r0_t10_05_full_grid_manifest.json`、`r0_t10_05_execution_summary.json` 和 `r0_t10_05_validation_result.json`。

大型 generated row artifacts 不提交到 git，包括 DuckDB、CSV.gz、Parquet、JSONL 等行级数据本体。PR 必须提交小型 evidence record：`docs/evidence/r0/R0-T10-05_authorized_input_manifest_full_grid_evidence.md`。evidence 只记录命令、路径、hash、row count、coverage、worker 参数、validator 结果、resume/marker 状态和 downstream gate，不嵌入 row payload。

## 主网格

主网格固定为 W = 120 / 250 / 500，q = 0.10 / 0.20 / 0.30，K = 2 / 3 / 5，`weak_delta = 0.10`，`dimension_rule = weak`，共 27 组。baseline config 固定为 `R0_W250_Q20_K3_WEAK_D010`。K=1 不属于本任务输出，不得出现。

每个 config 的 daily candidate state 只能来自 R0-T07 daily confirmation 中对应 W/q/K 的已物化正式结果；confirmed interval 只能来自 R0-T07 confirmed interval 中对应 W/q/K 的已物化正式结果。confirmed interval 为 0 行是合法情形，但必须记录真实分布和原因。若某 config 的 daily confirmation 中存在 `confirmed_state=true` 但 interval artifact 为 0，validator 必须失败。

## 并发与恢复

artifact-backed runner 默认允许 `--max-workers 16`，允许范围为 1..16，超过 16 必须拒绝。`ProcessPoolExecutor` 必须显式使用 `multiprocessing.get_context("spawn")`。每个 worker 默认 `duckdb_threads=1`，并设置明确的 per-worker memory limit，避免 Python worker 与 DuckDB 内部并行叠加。

每个 config 必须支持 resume。只有 DONE marker 存在、config hash 匹配、input manifest hash 匹配、output artifact 存在、output hash 可复算、row count 一致、无 partial 文件、无 FAILED marker，才允许 skip。partial 残留、FAILED marker、hash mismatch、schema mismatch、missing output、input manifest hash mismatch、code commit mismatch 或 config hash mismatch 必须触发重算。只要任一 config failed，或 completed+skipped config 数不等于 selected config count，不得写 completed global manifest，不得设置 downstream gate true。

## 验收

提交前必须通过 `python scripts/build_compendium.py --check`、`python scripts/validate_configs.py`、`python scripts/validate_manifests.py`、`ruff format --check scripts tests src`、`ruff check scripts tests src`、`python -m unittest discover -s tests -v` 和 `git diff --check`。真实运行后还必须运行 `python -m src.r0.r0_t10_full_grid_validator_cli --authorized-input-manifest ... --output-dir ...`，若 compatibility wrapper 存在，也必须运行 `python scripts/r0/validate_r0_t10_05_full_grid.py --authorized-input-manifest ... --output-dir ...`。

没有真实运行 evidence record，不得把本 task 标为 completed，不得推进 README 到 R0-T11。只有 authorized manifest、27 组 full-grid、validator 和 evidence 均 completed/passed 后，README 才能记录 `R0-T10-05 authorized input manifest 与 27 组 full-grid 执行：completed via PR #73`，并把 current task 推进到 `R0-T11 R0 审计报告与 R1 交接`。
