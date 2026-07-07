# R0-T10-02 R0-T05 strict-past score 物化

## 目标

本任务在 R0-T10 umbrella 下正式物化 R0-T05 strict-past score layer。旧 `R0-T05` 代表 engine、contract 与 synthetic 测试已完成；本 PR 只新增 formal materializer、CLI、validator、真实运行 evidence 和任务门禁，不重定义 R0-T05 指标、分位、score 或 dimension 语义。

R0-T05 必须消费 PR #69 evidence 指向的真实 R0-T04 DuckDB artifact，不得重新计算 R0-T04，不得绕回 D3，不得读取 synthetic、fixture 或 contract-grid payload 冒充正式 upstream。

## 非目标

本任务不修改 R0-T04 raw metric 语义，不生成 R0-T06 nested state、R0-T07 confirmation / interval，不生成 R0-T09 authorized input manifest，不运行 baseline 或 27 组 full-grid，不引入 q、K、state、interval、future label、future return、release direction、backtest、portfolio 或 trade signal。

大型 generated row artifacts 不提交到 git，包括 DuckDB、JSONL.gz、CSV.gz 等行级数据本体；但真实运行后必须提交小型 evidence record。没有真实运行 evidence，不得把 R0-T10-02 标为 completed，也不得把 README current task 推进到 R0-T10-03。

## 输入与输出

输入必须来自 `docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md` 绑定的 R0-T04 DuckDB。materializer 必须校验 evidence 中 `R0-T05_allowed_to_start=true`，本地 R0-T04 DuckDB 存在，且 SHA-256 等于 evidence 的 `output_duckdb_sha256`。若缺失或 hash 不一致，只能写 blocked summary，不得重新从 D3 生成。

输出目录为 `data/generated/r0/r0_t10/<run_id>/r0_t05/`。目录至少包含 `r0_t05_indicator_score_results.duckdb`、`r0_t05_dimension_score_results.duckdb`、`r0_t05_common_eligible_sample_results.duckdb`、`r0_t05_score_results_manifest.json`、`r0_t05_execution_summary.json`、三类 shards、DONE/FAILED marker 和 logs。DuckDB 是权威产物；shards 只作为恢复、审计和交换产物。

## Strict-Past 规则

R0-T05 strict-past 语义严格沿用现有 contract：`W=120/250/500`；参考集只使用同一证券、同一指标、当前日前最近 W 个 valid raw observations；当前日 raw value 不得进入 reference set；不得使用未来日；W 是 valid historical observation count，不是 calendar days。

有效历史不足 W 时，`eligible=false`、`percentile=None`、`score=None`、`validity_status=unknown`，reason 包含 `insufficient_strict_past_history`。上游 raw metric 非 valid 时必须传播 upstream status / reason，不得填 0、false、前值或均值。Tie method 固定为 midrank，indicator score 为 `1 - percentile`。`V2_LogAmount20_base` 映射为 `V2_AmountLevel20Pct`，不得重复 percentile。

Dimension score 为 P/C/T/V 各自两个 component score 的均值与最小值；任一 component unknown、diagnostic 或 blocked 时 dimension 不 eligible。Common eligible sample 只表达同一 security-date 在 W=120/250/500 下八个 active indicators 是否均 eligible。

## 并发、恢复与失败

默认 `--max-workers 16`，允许 `1..16`，超过 16 必须拒绝。进程池必须显式使用 `multiprocessing.get_context("spawn")`，避免 Linux fork 继承 DuckDB runtime state。每个 worker 默认 `duckdb_threads=1`，并设置 per-worker memory limit。

父进程不得持有全量 rows；worker 只接收 security chunk、input DuckDB path、W 配置和小型配置；worker 不得返回 row payload，只能返回 chunk summary。每个 chunk 写 partial artifact，完成后 atomic rename。`--resume` 只能在 DONE marker、schema、artifact hash、chunk hash 全部一致时跳过；partial、FAILED marker、hash mismatch、schema mismatch 必须触发重算。

只要任一 chunk failed，或 `completed + skipped` chunk 数不等于 planned chunk count，本次执行只能写 execution summary 和 chunk marker，不得写最终 authoritative DuckDB / manifest，且必须记录 `downstream_gate_allowed=false`。不得让 R0-T06 消费部分 R0-T05 产物。

## Evidence Gate

第二阶段真实运行后必须提交 `docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md`。Evidence 至少记录输入 R0-T04 evidence/path/hash/count/date range，三类输出 DuckDB path/hash，manifest/summary path/hash，row count、security count、date range、W/indicator/dimension coverage、eligible/unknown distribution、strict-past validator status、forbidden/legacy check、resume/failed marker 状态和 downstream gate。Evidence 不得嵌入行级 payload。

只有 R0-T05 completed 且 validator passed 时，`R0-T06_allowed_to_start=true`。否则 README 不得推进到 R0-T10-03。

## 验收与回退

验收测试覆盖 `--max-workers 16`、`--max-workers 17`、spawn process pool、R0-T04 input missing/hash mismatch blocked、strict-past 当前日和未来日隔离、W coverage、midrank tie、insufficient history、upstream invalid propagation、V2 映射、dimension score、common eligible sample、failed chunk 不写最终 DuckDB/manifest、resume、无 row payload、forbidden field 与 legacy V1 guard。

回退本任务新增的 materializer、CLI、validator、tests、task 文档、README/evidence 更新即可。由于大型 generated artifacts 不提交到 git，回退不需要撤销行级数据；本地 ignored generated 输出可按 run_id 清理。
