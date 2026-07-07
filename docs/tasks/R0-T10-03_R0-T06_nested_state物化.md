# R0-T10-03 R0-T06 nested state 物化

## 目标

本任务在 R0-T10 umbrella 下正式物化 R0-T06 nested state layer。旧 `R0-T06` 代表 weak dimension 与 nested state engine、contract 和 synthetic 测试已完成；本 PR 只新增 formal materializer、CLI、validator、真实运行 evidence 和任务门禁，不重定义 W、q、weak_delta、P/C/T/V 维度或 nested state 语义。

R0-T06 必须消费 PR #70 evidence 指向的 R0-T05 indicator score、dimension score 与 common eligible DuckDB artifacts。不得重新计算 R0-T04/R0-T05，不得绕回 D3、D2、raw 或 external 数据源，不得读取 synthetic、fixture 或 contract-grid payload 冒充正式 upstream。

## 非目标

本任务不修改 R0-T04 raw metric 或 R0-T05 strict-past score 语义，不生成 R0-T07 confirmation / interval，不生成 R0-T09 authorized input manifest，不运行 baseline 或 27 组 full-grid，不引入 K、confirmation、interval、future label、future return、release direction、backtest、portfolio 或 trade signal。

大型 generated row artifacts 不提交到 git，包括 DuckDB、Parquet、JSONL.gz、CSV.gz 等行级数据本体；但真实运行后必须提交小型 evidence record。没有真实运行 evidence，不得把 R0-T10-03 标为 completed，也不得把 README current task 推进到 R0-T10-04。

## 输入与输出

输入必须来自 `docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md` 绑定的 R0-T05 artifacts。materializer 必须校验 evidence 中 `R0-T06_allowed_to_start=true`，本地 indicator score、dimension score 与 common eligible DuckDB 均存在，且 SHA-256 分别等于 evidence 记录的 hash。若缺失或 hash 不一致，只能写 blocked summary，不得从更上游重算。

输出目录为 `data/generated/r0/r0_t10/<run_id>/r0_t06/`。目录至少包含 `r0_t06_indicator_state_results.duckdb`、`r0_t06_dimension_state_results.duckdb`、`r0_t06_nested_daily_state_results.duckdb`、`r0_t06_nested_state_results_manifest.json`、`r0_t06_execution_summary.json`、三类 shards、DONE/FAILED marker 和 logs。DuckDB 是权威产物；shards 只作为恢复、审计和交换产物。

## Nested State 规则

R0-T06 语义严格沿用现有 contract：`W=120/250/500`，`q=0.10/0.20/0.30`，`weak_delta=0.10`，dimension 为 P/C/T/V。Indicator active 使用 R0-T05 indicator score 判断 `score >= 1 - q`；dimension weak 使用 dimension mean score 与 minimum component score 判断 `score_dimension >= 1 - q` 且 `score_dimension_min >= 1 - q - weak_delta`。

Nested daily state 必须按 P -> C -> T -> V 顺序构造 `S_P`、`S_PC`、`S_PCT`、`S_PCVT`，并输出唯一 `exclusive_state_layer`。任一 upstream score 为 unknown、diagnostic 或 blocked 时不得静默转为 false；必须传播 validity status 与 reason，不得填 0、false、前值或均值。R0-T06 不得输出 K=1 confirmation，也不得输出任何 confirmation、streak 或 interval 字段。

## 并发、恢复与失败

默认 `--max-workers 16`，允许 `1..16`，超过 16 必须拒绝。进程池必须显式使用 `multiprocessing.get_context("spawn")`，避免 Linux fork 继承 DuckDB runtime state。每个 worker 默认 `duckdb_threads=1`，并设置 per-worker memory limit。

父进程不得持有全量 rows；worker 只接收 security chunk、input DuckDB paths、q/W/weak_delta 配置和小型运行参数；worker 不得返回 row payload，只能返回 chunk summary。每个 chunk 写 partial artifact，完成后 atomic rename。DuckDB 写入必须按 shard 批量 `CREATE TABLE AS SELECT * FROM read_parquet(...)` 或等价批量路径写入，不得逐行 Python 插入或先构造全市场 Python list。

`--resume` 只能在 DONE marker、schema、artifact hash、chunk hash 全部一致时跳过；partial、FAILED marker、hash mismatch、schema mismatch 必须触发重算。只要任一 chunk failed，或 `completed + skipped` chunk 数不等于 planned chunk count，本次执行只能写 execution summary 和 chunk marker，不得写最终 authoritative DuckDB / manifest，且必须记录 `downstream_gate_allowed=false` 与 `R0-T07_allowed_to_start=false`。

## Evidence Gate

第二阶段真实运行后必须提交 `docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md`。Evidence 至少记录输入 R0-T05 evidence/path/hash/count/date range，三类输出 DuckDB path/hash，manifest/summary path/hash，row count、security count、date range、W/q/weak_delta coverage、indicator/dimension/nested coverage、exclusive_state_layer 分布、eligible/unknown 分布、resume/failed marker 状态、validator 命令、validator 结果、forbidden/legacy/K/confirmation field check 和 downstream gate。Evidence 不得嵌入行级 payload。

只有 R0-T06 completed 且 validator passed 时，`R0-T07_allowed_to_start=true`。否则 README 不得推进到 R0-T10-04。

## 验收与回退

验收测试覆盖 `--max-workers 16`、`--max-workers 17`、spawn process pool、R0-T05 input missing/hash mismatch blocked、W/q/weak_delta coverage、indicator active threshold、weak dimension mean/min threshold、unknown/blocked/diagnostic propagation、nested invariant、exclusive_state_layer uniqueness、K/confirmation/interval absence、failed chunk 不写最终 DuckDB/manifest、resume、无 row payload、forbidden field 与 legacy V1 guard、validator deterministic recompute。

回退本任务新增的 materializer、CLI、validator、tests、task 文档、README/evidence 更新即可。由于大型 generated artifacts 不提交到 git，回退不需要撤销行级数据；本地 ignored generated 输出可按 run_id 清理。
