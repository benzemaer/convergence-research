# D2-T17 按 endpoint 配置 D2 runner chunk 策略

## 状态

in_progress via current PR。D2-T17 只新增 endpoint-aware chunk runner，不改变 D2-T16 已有脚本的默认行为。

## 目标

本任务新增 `scripts/run_d2_tnskhdata_endpoint_chunk_provider_runner.py`，复用 D2-T16 的 provider client、reference fetch、ledger、progress、fresh/resume、DuckDB staging、single-writer 写入与 D2-T15 quality gate 逻辑，但把主 endpoint task planning 改为按 endpoint 配置 chunk 策略。默认策略为 `daily=3year,adj_factor=5year,stk_limit=3year,stock_st=full-range,suspend_d=full-range`，并支持 `month`、`year`、`2year`、`3year`、`5year`、`full-range`。

## 非目标

本任务不运行真实 provider，不读取 `data/raw/`、`data/external/`、MarketDB 或 `.day` 文件；不提交 DuckDB 或 `data/generated/` 产物；不创建 manifest 或 data_version；不生成 D3 rows；不计算 PCVT；不定义 q、threshold、state machine；不生成 labels、returns、future outcome、backtest 或 portfolio；不升级任何候选源为 formal source。

## 输入

输入包括 D2-T16 runner、D2-T15 DuckDB staging writer 与 quality gate、`configs/d2/csi800_static_2026_06_membership_alignment.v1.json`，以及新 CLI 参数 `--endpoint-chunk-policy`。示例：

```text
--endpoint-chunk-policy "daily=year,adj_factor=5year,stk_limit=year,stock_st=full-range,suspend_d=full-range"
```

## 输出

代码输出包括新 runner 脚本、任务文档、README 索引更新和测试。D2-T17 默认生成文件使用 `d2_t17` 前缀：`d2_t17_fetch_plan.jsonl`、`d2_t17_fetch_ledger.jsonl`、`d2_t17_progress_status.json`、`d2_t17_run_summary.json`、`d2_t17_provider_error_summary.json`。DuckDB staging 文件仍为 `d2_t15_tnskhdata_staging.duckdb`，因此 D2-T17 必须使用独立 output-dir，不得与 D2-T16 正式 run 共用目录。

## Benchmark Runbook

不建议并行跑 D2-T16 与 D2-T17 benchmark；应顺序各跑约 5 分钟，比较速度、失败率、provider error 和 progress。D2-T16 year chunk benchmark 使用：

```bash
python scripts/run_d2_tnskhdata_security_major_provider_runner.py \
  --full \
  --start-date 20160101 \
  --end-date 20260630 \
  --security-universe configs/d2/csi800_static_2026_06_membership_alignment.v1.json \
  --output-dir data/generated/d2/benchmark_d2_t16_year_chunk \
  --env-file .env.local \
  --max-workers 4 \
  --chunk-policy year \
  --fresh
```

D2-T17 endpoint-aware chunk benchmark 使用：

```bash
python scripts/run_d2_tnskhdata_endpoint_chunk_provider_runner.py \
  --full \
  --start-date 20160101 \
  --end-date 20260630 \
  --security-universe configs/d2/csi800_static_2026_06_membership_alignment.v1.json \
  --output-dir data/generated/d2/benchmark_d2_t17_endpoint_chunk \
  --env-file .env.local \
  --max-workers 4 \
  --endpoint-chunk-policy "daily=3year,adj_factor=5year,stk_limit=3year,stock_st=full-range,suspend_d=full-range" \
  --fresh
```

## 验收标准

`--dry-run-plan` 必须输出 `endpoint_task_counts`、`endpoint_chunk_policy`、`endpoint_chunk_counts`、`total_task_count` 和 `remote_provider_called=false`。测试必须覆盖 `stock_st` 与 `suspend_d` 每证券 full-range 只生成 1 个任务、`adj_factor=5year` 在 `20160101-20260630` 生成 3 个 chunk、`daily=year` 生成 11 个 chunk、task hash 随 endpoint chunk policy 改变、不同 output-dir 下 D2-T17 DuckDB/ledger/progress 不混、D3/R0/PCVT/labels/returns/backtest/portfolio 仍不生成。

## 失败状态

若 endpoint chunk policy 含未知 endpoint 或未知 chunk 粒度，本 PR 失败。若 D2-T17 复用 D2-T16 正式 output-dir、覆盖 D2-T16 文件名、修改 D2-T16 默认行为、生成真实数据产物、创建 manifest/data_version、生成 D3/R0/PCVT/labels/returns/backtest/portfolio，或绕过 D2-T15 quality gate，本 PR 失败。

## 回退方式

回退本 PR 的新脚本、测试和文档即可。由于本 PR 不提交生成产物、不发布 manifest、不创建 data_version，回退不需要撤销正式数据。
