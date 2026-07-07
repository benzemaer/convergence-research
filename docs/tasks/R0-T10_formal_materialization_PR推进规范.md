# R0-T10 formal materialization PR 推进规范

## 适用范围

本规范适用于 R0-T10 后续 formal materialization / execution PR：PR #70 / R0-T10-02 R0-T05 strict-past score 物化，PR #71 / R0-T10-03 R0-T06 nested state 物化，PR #72 / R0-T10-04 R0-T07 confirmation / interval 物化，PR #73 / R0-T10-05 authorized input manifest 与 27 组 full-grid 执行。

PR #69 evidence 中使用的输入应继续表述为 `D3-T11 candidate generated with warnings; D3 formal data version remains unpublished`。这是在 R-stage consumer readiness 下授权消费的 candidate observation，不得误写成 D3 formal release。

## 两阶段推进

每个 PR 允许分两阶段提交，但不能只停在第一阶段。第一阶段提交代码、契约、CLI、validator、resume/failed marker、单元测试、小样本测试和任务文档；第一阶段通过 code review 后，第二阶段必须执行真实数据运行，并提交 evidence record。

大型 generated row artifacts 不提交到 git，包括 DuckDB、JSONL.gz、CSV.gz 等行级数据本体；但 evidence record 必须提交到 git。没有 evidence，不得把 task 标为 completed，不得推进 task index，不得启动下一层物化。

## Evidence 最小字段

每个 evidence record 至少必须包含：`task_id`、`run_id`、`code_commit`、input artifact 路径或 registry id、input hash、input row count、input security count、input date range、输出目录、输出 DuckDB/hash、manifest/hash、summary/hash、row count、security count、date range、shard count、worker 参数、DuckDB threads、memory limit、chunk size、运行命令、validator 命令、validator 结果、forbidden field check、legacy V1 check、coverage summary、resume/failed marker 状态，以及 downstream gate 是否允许启动。Evidence 不得嵌入行级 payload。

## R 阶段入口分层硬规则

R 阶段 materializer、validator、adapter、manifest builder 和 runner 的核心逻辑必须位于 `src/r0` 到 `src/r6`。CLI main 优先放在 `src/r0/*_cli.py`、`src/r1/*_cli.py` 等阶段目录内；`scripts/r0` 到 `scripts/r6` 只允许保留兼容 wrapper，用于设置仓库根路径并调用 `src` CLI `main()`。

PR body 和后续 evidence 优先记录 `python -m src.r0...` 形式的命令。若为了兼容历史命令继续保留 `scripts/r0/...`，必须说明该脚本只是 wrapper。PR #71 到 PR #73 不得再在 `scripts/r0` 中新增 validator、materializer、DuckDB/JSONL 扫描、coverage 校验、schema 常量、indicator/dimension 规则或其他 R 阶段业务实现。

## Resume、失败与监控

每个真实运行必须具备监控与自动恢复。runner/materializer 必须支持 resume；每个 chunk 或 shard 必须有 DONE/FAILED marker；partial 文件不得被当作完成；hash mismatch、schema mismatch、FAILED marker、partial 残留必须触发重算。

父进程只聚合路径、row count、hash 和状态，不得聚合 rows；worker 不得返回 row payload。长任务运行中应周期性写 progress summary，至少记录 completed/skipped/failed/pending chunk count、当前吞吐、最近失败、可重试命令和当前输出目录。

只要存在 failed chunk，或 `completed + skipped` chunk 数不等于计划 chunk 数，本次执行只能写 execution summary 和 chunk marker，不得写最终 authoritative DuckDB/manifest，也不得允许 downstream gate 为 true。

## 并发与 DuckDB 写入

对按证券独立的 R0-T05/R0-T06/R0-T07 upstream 量化计算，默认允许 `--max-workers 16`，建议允许范围 `1..16`，超过 16 必须拒绝，除非另开性能 PR 证明更高并发安全。每个 worker 默认 `duckdb_threads=1`，并设置明确的 per-worker memory limit，避免 Python worker 与 DuckDB 内部并行叠加。

对 R0-T09 full-grid runner，在 streaming/artifact-manifest 模式完成前，不得沿用旧的 full JSON payload 并发模型，也不得把完整 upstream payload 复制给多个 config worker。

DuckDB 写入策略必须避免逐行 Python 插入。大规模正式运行中禁止以 Python 逐行解压 JSONL、逐行 canonicalize、每 1000 行 `executemany` 插入作为主写入路径。优先使用 DuckDB 原生批量路径，例如 `CREATE TABLE AS SELECT * FROM read_json_auto(...)`、`COPY FROM`、Parquet/Arrow 中间产物、按 shard 批量 `INSERT INTO SELECT`，或者每 50–100 只证券一个批次事务。不得每只证券一个高频 commit 写最终 DuckDB。若设置 WAL autocheckpoint 或显式 checkpoint，必须在 evidence 中记录 WAL/checkpoint 策略和异常恢复方式。

## 后续 PR 特别要求

PR #70 / R0-T10-02 必须消费 PR #69 evidence 指向的 R0-T04 DuckDB artifact，不得重新从 D3 绕过 R0-T04。Strict-past percentile 必须有 validator 证明没有使用当前日或未来日；输出至少分 indicator score 和 dimension score 两类 artifact；evidence 必须记录 W=120/250/500 的覆盖、indicator coverage、dimension coverage、eligible/unknown 分布和 row count。

PR #71 / R0-T10-03 必须消费 R0-T05 evidence 指向的 score artifacts，不得绕过 score 层。必须覆盖 W=120/250/500、q=0.10/0.20/0.30、weak_delta=0.10；evidence 必须记录 nested state coverage、exclusive_state_layer 分布、eligible/unknown 分布、row count/security count/date range 和 no K=1 confirmation 输出。

PR #72 / R0-T10-04 必须消费 R0-T06 evidence 指向的 nested state artifact。必须覆盖 W=120/250/500、q=0.10/0.20/0.30、K=2/3/5、state_name=S_P/S_PC/S_PCT/S_PCVT；K=1 不得出现在 confirmation 输出中；evidence 必须记录 daily confirmation row count、confirmed interval row count、open/closed interval 分布、state_name coverage、W/q/K coverage 和 interval consistency checks。

PR #73 / R0-T10-05 只有在 R0-T04 到 R0-T07 四层 evidence 全部 completed 且 validator passed 后，才允许生成 authorized input manifest。PR #73 必须先 dry-run，再 baseline 单组，再 27 组 full-grid；每一步都要有 evidence。R0-T09 不得再使用 single giant JSON payload 作为正式输入；必须使用 artifact-manifest / streaming input 模式或等价低内存模式。Full-grid evidence 必须记录 27 个 config 的 DONE/FAILED 状态、row count、interval count、hash、resume 结果、global manifest hash 和 forbidden output guard。
