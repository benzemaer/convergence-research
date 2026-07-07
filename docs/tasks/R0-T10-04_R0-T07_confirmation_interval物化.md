# R0-T10-04 R0-T07 confirmation / interval 物化

## 目标

本任务在 R0-T10 umbrella 下正式物化 R0-T07 confirmation、streak 与 confirmed interval layer。旧 `R0-T07` 代表 confirmation interval engine、contract 和 synthetic 测试已完成；本 PR 只新增 formal materializer、src CLI、validator、真实运行 evidence 和任务门禁，不重定义 K、streak、confirmation 或 interval 语义。

R0-T07 必须消费 PR #71 evidence 指向的 R0-T06 nested daily state artifact。不得重新计算 R0-T04 raw metrics、R0-T05 strict-past percentile / score 或 R0-T06 raw nested states，不得绕回 R0-T05、R0-T04、D3、raw、external、MarketDB 或 `.day` 数据源，不得用 synthetic、fixture 或 contract-grid payload 冒充正式 upstream。

## 非目标

本任务不修改 R0-T04、R0-T05 或 R0-T06 语义，不重新计算 R0-T06 indicator active / dimension weak / raw nested states / exclusive layer，不生成 R0-T09 authorized input manifest，不运行 baseline 或 27 组 full-grid，不做 gap merge，不引入 future label、future return、release direction、backtest、portfolio 或 trade signal。

大型 generated row artifacts 不提交到 git，包括 DuckDB、Parquet、JSONL.gz、CSV.gz 等行级数据本体；但真实运行后必须提交小型 evidence record。没有真实运行 evidence，不得把 R0-T10-04 标为 completed，也不得把 README current task 推进到 R0-T10-05。

## 输入与输出

输入必须来自 `docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md` 绑定的 R0-T06 nested daily state DuckDB。materializer 必须校验 evidence 中 `R0-T07_allowed_to_start=true`，本地 `r0_t06_nested_daily_state_results.duckdb` 存在，且 SHA-256 等于 evidence 记录的 hash。若缺失或 hash 不一致，只能写 blocked summary，不得重新生成 R0-T06 或绕回上游。

输出目录为 `data/generated/r0/r0_t10/<run_id>/r0_t07/`。目录至少包含 `r0_t07_daily_confirmation_results.duckdb`、`r0_t07_confirmed_interval_results.duckdb`、`r0_t07_confirmation_interval_results_manifest.json`、`r0_t07_execution_summary.json`、daily / interval shards、DONE/FAILED marker 和 logs。DuckDB 是权威产物；shards 只作为恢复、审计和交换产物。

## Code Commit 规则

从本任务开始，所有 R-stage formal materialization 的 `--code-commit` 必须为 40 位完整 Git SHA。短 SHA 必须 blocked / error，不能继续执行。generated manifest、summary 和 evidence 中的 `code_commit` 必须完全一致，且均为 40 位完整 SHA。不得再新增 `run_code_commit_argument` 加短 SHA 的历史兼容写法；PR #71 中短 SHA 只作为历史事实保留。

## Confirmation / Interval 规则

R0-T07 语义严格沿用现有 confirmation interval engine。固定参数为 `K=2/3/5`，baseline K 为 `3`。`K=1` 是 R0-T06 raw daily state reference，不属于 R0-T07 confirmed state；`K=1/0/4/6` 等非 2/3/5 的 K 必须被拒绝。

同一 `security_id / W / q / weak_delta / state_name` 按 `trading_date` 升序扫描。raw state 为 true 时 streak 增长并保留连续段起点；raw state 为 false 时 streak 归零；raw state 为 unknown、diagnostic_required、blocked 或 `None` 时 streak 为 `None` 并中断。unknown 不得当作 false，也不得延续 previous streak。

`confirmed_state = raw_streak >= K`，但只能在 raw state true、streak 非空且 status valid 时判断。confirmation date 是当前连续 true 段首次达到 K 的日期，`confirmation_start_date` 是该连续段 raw 起点。确认不得回填；K=3 时连续 true 的第 1、2 天仍为 confirmed false，第 3 天才 confirmed true。

R0-T07 只输出已经 confirmed 的 intervals。confirmed interval 从首次 confirmed 日期开始输出；`raw_start_date` 是 raw true 连续段第一天，`confirmation_date` 与 `confirmed_start_date` 是首次 confirmed 日期。遇到 raw false、unknown、diagnostic_required 或 blocked 会终止已 confirmed interval；输入结束仍未终止时 `is_open_interval=true` 且 `termination_reason=end_of_input_open`。duration 使用 observation count，不使用自然日差，不做 gap merge，也不回填 confirmed state 到 raw start date。

## 并发、恢复与失败

默认 `--max-workers 16`，允许 `1..16`，超过 16 必须拒绝。进程池必须显式使用 `multiprocessing.get_context("spawn")`。每个 worker 默认 `duckdb_threads=1`，并设置 per-worker memory limit，避免 Python worker 与 DuckDB 内部并行叠加。

父进程不得持有全量 rows；worker 只接收 security chunk、input DuckDB path、K 配置和小型运行参数；worker 不得返回 row payload，只能返回 chunk summary。每个 chunk 写 partial artifact，完成后 atomic rename。DuckDB 写入必须按 shard 批量 `CREATE TABLE AS SELECT * FROM read_parquet(...)` 或等价批量路径写入，不得逐行 Python 插入或先构造全市场 Python list。

`--resume` 只能在 DONE marker、schema、artifact hash、chunk hash 全部一致时跳过；partial、FAILED marker、hash mismatch、schema mismatch 必须触发重算。只要任一 chunk failed，或 `completed + skipped` chunk 数不等于 planned chunk count，本次执行只能写 execution summary 和 chunk marker，不得写最终 authoritative DuckDB / manifest，且必须记录 `downstream_gate_allowed=false` 与 `R0-T10-05_allowed_to_start=false`。

## Evidence Gate

第二阶段真实运行后必须提交 `docs/evidence/r0/R0-T10-04_r0_t07_confirmation_interval_materialization_evidence.md`。Evidence 至少记录输入 R0-T06 evidence/path/hash/count/date range，输出 daily confirmation 和 confirmed interval DuckDB path/hash，manifest/summary path/hash，row count、security count、date range、W/q/weak_delta/K/state coverage、confirmed/raw distribution、termination distribution、open/closed interval count、worker 参数、resume/failed marker 状态、validator 命令、validator 结果、forbidden/legacy/full-code-commit/no-backfill/nested-invariant checks 和 downstream gate。Evidence 不得嵌入行级 payload。

只有 R0-T07 completed 且 validator passed 时，`R0-T10-05_allowed_to_start=true`。否则 README 不得推进到 R0-T10-05。

## 验收与回退

验收测试覆盖 full SHA 通过、短 SHA 拒绝、manifest/summary/evidence code commit 一致性、`--max-workers 16`、`--max-workers 17`、spawn process pool、R0-T06 evidence missing/hash mismatch blocked、K/state coverage、K=1/0/4/6 拒绝、confirmation 不回填、streak 规则、unknown/diagnostic/blocked propagation、closed/open interval、false/non-ready termination、duration observation count、failed chunk 不写最终 DuckDB/manifest、resume、无 row payload、deterministic daily/interval recompute、tamper 后 validator 失败、forbidden field 与 legacy V1 guard、scripts/r0 thin wrapper。

回退本任务新增的 materializer、CLI、validator、tests、task 文档、README/evidence 更新即可。由于大型 generated artifacts 不提交到 git，回退不需要撤销行级数据；本地 ignored generated 输出可按 run_id 清理。
