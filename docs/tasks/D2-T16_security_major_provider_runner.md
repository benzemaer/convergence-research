# D2-T16 按证券主轴的 tnskhdata 远程拉取 runner

## 状态

in_progress via current PR。D2-T16 只建立按证券主轴的候选远程拉取 runner、resume ledger、进度报告、单写入 DuckDB staging 和 D2-T15 质量门禁复用路径。它不发布正式 source snapshot、manifest 或 data_version，也不授权 D3/R0 使用。

## 目标

本任务基于 D2-T15 的 DuckDB candidate staging 和质量门禁，补齐可实际执行的 tnskhdata 远程拉取 runner。runner 以证券为主轴构造 `daily`、`adj_factor`、`stock_st`、`suspend_d`、`stk_limit` 拉取任务，支持 year/month/full-range chunk，支持 resume、retry-failed-only、失败分类、进度文件和 provider error summary。

远程执行路径必须使用 fetch worker 并发拉取、single writer 串行写 DuckDB 的模式，worker 不得直接写 DuckDB。全局 request limiter 在所有 worker 之间共享，默认从 200 requests/minute 开始，健康窗口每分钟最多增加 100 requests/minute，最高 500 requests/minute；发生 `rate_limit`、`timeout` 或 provider error 时按 0.5 系数降速，最低 100 requests/minute。失败任务按分类记录 ledger，可按任务 hash resume。

## 非目标

本任务不提交任何生成的 DuckDB 文件或 `data/generated/` 产物；不读取 `data/raw/`、`data/external/`、MarketDB 或 `.day` 文件；不创建 run manifest、dataset manifest、source snapshot manifest 或 data_version；不生成 D3 rows；不计算 PCVT；不定义 q、threshold、state machine；不生成 returns、labels、future outcome、backtest 或 portfolio；不将 tnskhdata、BAOSTOCK、HITHINK 或任何候选源升级为 formal source。

## 输入

输入包括 `configs/d2/csi800_static_2026_06_membership_alignment.v1.json`、D2-T15 的 `scripts/materialize_d2_tnskhdata_security_major_duckdb_candidate.py`、D2-T13/D2-T15 的 tnskhdata candidate staging 与质量门禁契约，以及本 PR 新增 runner CLI 参数。远程执行时 token 只能从 `--env-file`、`TNSKHDATA_TOKEN` 或 `TUSHARE_TOKEN` 读取；测试必须使用 fake client，不调用真实 provider。

## 输出

代码输出为 `scripts/run_d2_tnskhdata_security_major_provider_runner.py`、fake-client 单元测试、任务文档和 README 索引更新。手工远程执行时，runner 只允许写入被忽略的 candidate 输出目录，典型文件包括 `d2_t15_tnskhdata_staging.duckdb`、`d2_t16_fetch_plan.jsonl`、`d2_t16_fetch_ledger.jsonl`、`d2_t16_progress_status.json`、`d2_t16_provider_error_summary.json`、`d2_t16_run_summary.json` 以及 D2-T15 质量与 handoff 报告。

## CLI 与手工运行

smoke test 与 full run 必须使用不同输出目录，不得共用同一个 DuckDB。smoke test 使用独立目录：

```powershell
$smokeBase = "data/generated/d2/d2_t15_tnskhdata_security_major_candidate_smoke"
```

full run 使用正式 candidate 输出目录：

```powershell
$base = "data/generated/d2/d2_t15_tnskhdata_security_major_candidate"
```

建议先执行小样本 smoke；该命令会调用远程 provider，不能在 CI 或普通 Codex 验证中执行：

```bash
python scripts/run_d2_tnskhdata_security_major_provider_runner.py \
  --sample-securities 5 \
  --start-date 20260101 \
  --end-date 20260131 \
  --security-universe configs/d2/csi800_static_2026_06_membership_alignment.v1.json \
  --output-dir data/generated/d2/d2_t15_tnskhdata_security_major_candidate_smoke \
  --env-file .env.local \
  --max-workers 2 \
  --chunk-policy month \
  --fresh
```

首次 full run 建议使用 `--fresh` 重建当前 output-dir 下的 D2-T16 generated files 和 DuckDB staging：

```bash
python scripts/run_d2_tnskhdata_security_major_provider_runner.py \
  --full \
  --start-date 20160101 \
  --end-date 20260630 \
  --security-universe configs/d2/csi800_static_2026_06_membership_alignment.v1.json \
  --output-dir data/generated/d2/d2_t15_tnskhdata_security_major_candidate \
  --env-file .env.local \
  --max-workers 4 \
  --chunk-policy year \
  --fresh
```

中断后继续执行时改用 `--resume`，不得与 `--fresh` 同时使用：

```bash
python scripts/run_d2_tnskhdata_security_major_provider_runner.py \
  --full \
  --start-date 20160101 \
  --end-date 20260630 \
  --security-universe configs/d2/csi800_static_2026_06_membership_alignment.v1.json \
  --output-dir data/generated/d2/d2_t15_tnskhdata_security_major_candidate \
  --env-file .env.local \
  --max-workers 4 \
  --chunk-policy year \
  --resume
```

限流和重试参数可按 provider 反馈调整，默认值为 `--initial-requests-per-minute 200`、`--rate-increase-per-minute 100`、`--max-requests-per-minute 500`、`--min-requests-per-minute 100`、`--rate-decrease-factor 0.5`、`--retry-max-attempts 3`、`--retry-backoff-seconds 5.0`、`--retry-jitter-ratio 0.2`。若出现限流、超时或 provider error，runner 会降速并按 exponential backoff + jitter 重试；参数不兼容会记录 `unsupported_param_variant`，其中 full mode 的 `daily` range 参数不做逐日降级，以避免静默放大为 800 个证券 × 全交易日的调用量。

可用以下 PowerShell 命令监控 full run 进度：

```powershell
Get-Content data/generated/d2/d2_t15_tnskhdata_security_major_candidate/d2_t16_progress_status.json -Wait
Get-Content data/generated/d2/d2_t15_tnskhdata_security_major_candidate/d2_t16_fetch_ledger.jsonl -Tail 20 -Wait
```

## 验收标准

`--dry-run-plan` 必须只生成 fetch plan 和 no-remote summary，且 `remote_provider_called=false`。fake-client 测试必须覆盖 endpoint 参数、`stk_limit` fallback 过滤、`suspend_d` 日期归一化、并发 fetch 与 single-writer DuckDB 写入、resume skip、retry-failed-only、progress atomic write、错误脱敏、data validation error 不写坏行、D2-T15 quality gate 复用，以及 README 阶段索引推进。验证命令必须通过：

```bash
ruff format --check scripts tests
ruff check scripts tests
python scripts/validate_configs.py
python -m unittest discover -s tests -v
python scripts/build_compendium.py --check
git diff --check
```

## 失败状态

若 token 缺失、provider client 不可用、任务出现 `rate_limit`、`timeout`、`provider_error`、`failed` 或 `data_validation_error`，候选验收必须保持 blocked。若 security universe 存在未解析映射，D2-T15 质量门禁的 `unmapped_security_count` 必须阻塞 acceptance。若 trade calendar、stock basic、daily、adj_factor、stk_limit、stock_st 或 suspend_d 覆盖不足，D2-T15 质量报告和 handoff 报告必须保持阻塞。

若 PR 引入真实数据读取、提交 DuckDB 或 `data/generated/` 产物、创建 manifest/data_version、生成 D3/R0/PCVT/labels/backtest/portfolio 字段，或将任何候选源升级为 formal source，本 PR 失败并应回退。

## 回退方式

回退本 PR 的代码、测试和文档即可。由于本 PR 不提交生成产物、不发布 manifest、不创建 data_version，回退不需要撤销正式数据；本地手工执行产生的 ignored candidate 输出目录可在确认不含用户需要的调试证据后删除。
