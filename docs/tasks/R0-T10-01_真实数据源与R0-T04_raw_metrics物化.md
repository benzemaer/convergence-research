# R0-T10-01 真实数据源与 R0-T04 raw metrics 物化

## 目标

本任务在不改变 R0-T04 指标语义的前提下，建立真实 D3 observation 到 R0-T04 raw metrics 的正式分层物化入口。R0-T04 的正式 upstream 产物必须采用 DuckDB 主产物加可流式审计的分片 JSONL.gz 交换产物，并由 manifest 记录 schema、row count、security count、date range、输入 hash、输出 hash、代码提交、engine version、分片 row count/hash 与全局内容 hash。

本任务属于 R0-T10 umbrella 下的 formal materialization 子任务。旧的 R0-T04 任务号代表 raw metric engine、contract 与 synthetic 测试已完成，不在本 PR 中重开。

## 非目标

本任务不生成 R0-T05 score、R0-T06 nested state、R0-T07 confirmation / interval，不生成 R0-T09 `authorized_input_manifest.json`，不执行 baseline 或 27 组 full-grid，不生成 R0 审计报告或 R1 交接，也不引入 release event、future label、direction、return、backtest、portfolio 或交易信号字段。

Synthetic/fixture/contract-grid payload 只可用于 smoke 或单元测试，不得伪装成 formal upstream artifact。生成的 DuckDB、JSONL.gz、CSV、summary 或 manifest 等运行产物不得提交到 git。

## 输入边界

输入必须来自已授权的 D3/R0 readiness 路径，默认读取 D3 generated DuckDB 中的 `d3_candidate_daily_observation` 或等价开放候选观测表。materializer 不得绕过到 `data/raw/`、`data/external/`、MarketDB、`.day` 或供应商原始文件。若输入 readiness、路径边界、key column 或 R0-T04 必需字段不满足，应输出 blocked summary，而不是生成部分伪正式产物。

## 输出契约

推荐输出目录为 `data/generated/r0/r0_t10/<run_id>/r0_t04/`。目录内至少包含 `r0_t04_raw_metric_results.duckdb`、`r0_t04_raw_metric_results_manifest.json`、`r0_t04_execution_summary.json`，以及 `shards/*.jsonl.gz` 分片交换产物与 `status/*.DONE.json` marker。DuckDB 是权威产物；JSONL.gz 分片仅作为交换与审计产物。

manifest 必须禁止嵌入 rows 本体。父进程 summary 只聚合 chunk status、row count、hash 与路径，不得包含 upstream rows 或 raw_metric_results 数组。

## 并发与内存策略

R0-T10-01 materializer 支持 `--max-workers`，默认 6，允许 1–8，超过 8 必须拒绝。该并发放开只适用于 R0-T10 formal upstream materialization worker，不适用于现有 R0-T09 full-grid runner。R0-T09 runner 在 artifact-manifest / streaming input 模式完成前，仍保留现有 JSON payload 与 worker 上限约束，并继续 blocked formal large upstream consumption。

materializer 的父进程不得持有全量 securities、全量 dates 或全量 upstream rows。worker 只能接收 security chunk、DuckDB 路径、表名、受控 DuckDB threads / memory limit 和小型配置；worker 不得返回 rows，只能返回 chunk summary。每个 chunk 写入 partial artifact，完成后 atomic rename；DuckDB 权威产物按 shard stream append 写入，不得先构造全市场 Python list。

默认参数为：`--max-workers 6`、`--duckdb-threads 1`、`--duckdb-memory-limit-per-worker 2GB`、`--chunk-size-securities 1`。`--resume` 必须按 chunk hash、DONE marker、schema 与 artifact hash 校验后跳过；partial、FAILED marker、hash mismatch 或 schema mismatch 必须重算。

## 验收标准

验收测试至少覆盖：`--max-workers 8` 小样本可运行；`--max-workers 9` 被拒绝；worker 返回值不包含 row payload；父进程 summary 只聚合 row count、hash、路径和状态；resume 通过 DONE/hash 跳过且不读取全量 artifact；formal large upstream 不允许进入 single JSON object / `json.load` 模式；forbidden future/return/backtest/portfolio/signal 字段与 legacy V1 字段仍被阻断。
