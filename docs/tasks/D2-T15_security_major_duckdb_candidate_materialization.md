# D2-T15 按证券主轴的 tnskhdata DuckDB 候选物化

状态：in_progress；candidate / staging only；formal DuckDB publication、D3 generation 与 R0 均未授权。

## 目标

D2-T15 接受 D2-T14 row-level repair 路线被替代的结论，改为按 `ts_code` 主轴重建 tnskhdata candidate materialization。核心目标是为每个 CSI800 static security 在 DR-001 闭区间内按证券全区间或年度 chunk 拉取 `daily`、`adj_factor`、`stock_st`、`suspend_d` 和 `stk_limit`，写入 ignored local DuckDB staging，并由 DuckDB SQL quality gate 生成 D2 acceptance candidate report 与 D3 handoff candidate decision。

## 非目标

本 PR 不合并 PR #46 的 row-level repair CLI，不提交 `data/generated/**`、DuckDB 文件、raw parquet、provider payload 或 token，不生成 D3 rows、D3 `data_version`、PCVT、R0 state、labels、returns、backtest 或 portfolio outputs，不把 `pro_bar` 升级为 canonical source，也不绕过 D2 acceptance gate。D2-T15 可以创建 ignored local DuckDB candidate / staging，但不得声称 formal DuckDB 已发布。

## 输入

输入边界为 `configs/d2/csi800_static_2026_06_membership_alignment.v1.json`、`configs/d2/tnskhdata_full_materialization_acceptance_contract.v1.json`、DR-001 时间边界和 tnskhdata source contract。时间边界固定为 `20160101` 至 `20260630` 的 closed calendar interval，证券宇宙固定为 `CSI800_STATIC_2026_06` membership / security mapping。真实 provider token 只能来自 `.env.local` 或环境变量，脚本和测试不得打印 token。

## 输出

所有运行输出均位于 ignored `data/generated/d2/d2_t15_tnskhdata_security_major_candidate/`。预期输出包括 `d2_t15_tnskhdata_staging.duckdb`、`d2_t15_fetch_ledger.jsonl`、provider error summary、coverage gap CSV、DuckDB quality report、D2 acceptance candidate report、D3 handoff candidate report 和 candidate file hash summary。本 PR 只提交脚本、测试、README 和任务文档，不提交 generated artifacts。

## CLI

主命令为：

```bash
python scripts/materialize_d2_tnskhdata_security_major_duckdb_candidate.py \
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

当前 PR 实现 dry-run plan、resume ledger primitives、single-writer DuckDB staging 和 no-remote quality gate/report path。真实 provider remote runner 需要在运行授权下单独审阅；在未接入受控 provider runner 前，CLI remote execution 会明确失败而不是静默执行。

## Fetch / Staging 设计

Fetch plan 以 `ts_code` 为主轴，默认按年度 chunk 生成 `daily`、`adj_factor`、`stock_st`、`suspend_d`、`stk_limit` tasks。并发模型要求 worker 只负责 fetch，DuckDB 写入只能由 single writer connection 完成。Resume ledger 以 `task_id` 和 `task_hash` 判断可跳过任务，`succeeded`、`empty_resolved` 与 `unsupported_param_variant` 可被视为已完成状态。

DuckDB staging 至少包含 security universe、stock basic、trade calendar、daily raw、adj factor、stock ST、suspend、stk limit、fetch ledger、provider errors、expected skeleton、source status、factor evidence、adjusted price、coverage gaps 和 quality summary 表。`suspend_d` 写入前必须把 provider 返回的 `trade_date` normalize 为 `suspend_date`。

## Quality Gate

Quality gate 从 DuckDB 计算 `CSI800 static universe × trade_cal open dates × stock_basic lifecycle filter` skeleton，并左连接 daily、adj factor、suspend、stk limit 和 stock ST。若 daily missing 但 `suspend_d.suspend_type == "S"`，该行重分类为 suspended expected empty，不计入 `listed_open_missing_daily_count`。daily missing 导致的 price-limit unresolved 标记为 `daily_dependency_missing`，不误判为 `stk_limit` source missing。

## 验收标准

测试必须证明 security-major fetch plan 覆盖五个 endpoint，年度 chunk 正确覆盖 2016-2026，resume ledger 可跳过已完成 task，provider 参数不支持时可记录 unsupported / fallback，single writer 能将 fake provider rows 写入 DuckDB staging，quality gate 能识别 missing daily、suspend 重分类、adj factor missing、price-limit daily dependency、duplicate key、null OHLC、非正价格和 high/low violation。D2 accepted 时只允许 D3 handoff candidate decision，不生成 D3 rows、R0、PCVT、labels、returns、backtest 或 portfolio。

## 失败状态

若输出路径指向 `data/raw`、`data/external`、MarketDB 或 `.day`，任务失败。若 remote CLI 在未授权 runner 下尝试执行，任务失败。若 DuckDB quality gate、README、tests、lint 或 config validation 未通过，PR 失败。若 PR 引入 generated artifacts、formal DuckDB publication、D3 rows、data_version、PCVT、R0、future labels、backtest、portfolio 或 formal source promotion，PR 失败并应回退。

## 回退方式

回退本 PR 只移除 D2-T15 task doc、README D2-T15 index update、security-major DuckDB materializer script 和 D2-T15 tests。不得回滚 PR #45，也不得恢复或合并 PR #46 的 row-level repair route。
