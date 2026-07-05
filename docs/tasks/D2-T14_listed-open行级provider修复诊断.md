# D2-T14 listed-open 行级 provider 修复诊断

状态：in_progress；local generated artifacts only；formal DuckDB / D3 / R0 not authorized。

## 目标

实现 D2-T14 row-level provider repair 能力：从 D2-T13 本地 generated artifacts 导出
listed-open missing daily、unresolved price limit、unresolved adjustment factor 明细；按
`(ts_code, date)` 调用 tnskhdata primary endpoints 做精准修复；对 daily 仍缺失的
listed-open security-date 做 `suspend_d` 补查；将修复行 merge 回 date-level partition；
并在 repair 后执行 no-remote verify / assemble / finalize，比较 repair 前后 quality blockers。

## 非目标

- 不重跑 full calendar-domain fetch。
- 不写 formal DuckDB。
- 不提交 `data/generated/**`。
- 不提交 raw parquet、provider payload、token 或 source symbol 明细。
- 不生成 D3 rows、D3 `data_version`、PCVT、R0 state、labels、returns、backtest 或 portfolio outputs。
- 不把 `pro_bar` 升级为 canonical source。
- 不修改 DR-001 时间边界或 `CSI800_STATIC_2026_06` universe 边界。
- 不通过硬编码本地 blocker count 通过测试。

## 输入

默认读取 PR #45 后的本地 ignored artifacts：

- `data/generated/d2/d2_t13_tnskhdata_full_candidate/tnskhdata_source_status_candidate.jsonl`
- `data/generated/d2/d2_t13_tnskhdata_full_candidate/tnskhdata_factor_evidence_candidate.jsonl`
- `data/generated/d2/d2_t13_tnskhdata_full_candidate/partitions/**`
- `data/generated/d2/d2_t13_tnskhdata_full_candidate/tnskhdata_quality_report.json`
- `data/generated/d2/d2_t13_tnskhdata_full_candidate/tnskhdata_d2_acceptance_candidate_report.json`

Token 只允许来自 `.env.local`、系统环境变量或现有 token loading path。不得打印或写入 token。

## 输出

- `d2_t13_listed_open_missing_daily_rows.csv`
- `d2_t13_unresolved_price_limit_rows.csv`
- `d2_t13_unresolved_adj_factor_rows.csv`
- `d2_t13_provider_blocker_summary.json`
- `d2_t13_listed_open_provider_repair_report.json`
- `d2_t13_remaining_listed_open_missing_daily_rows.csv`
- `d2_t13_remaining_unresolved_price_limit_rows.csv`
- `d2_t13_remaining_unresolved_adj_factor_rows.csv`
- `d2_t13_remaining_provider_blocker_summary.json`
- `d2_t13_pro_bar_missing_row_diagnostic_report.json`

所有输出均位于 ignored `--output-dir`。本 PR 不提交 generated artifacts。

## CLI

导出 blocker：

```bash
python scripts/materialize_d2_tnskhdata_full_candidate.py \
  --full \
  --fetch-date-domain calendar \
  --output-dir data/generated/d2/d2_t13_tnskhdata_full_candidate \
  --export-listed-open-provider-blockers
```

精准修复 blocker：

```bash
python scripts/materialize_d2_tnskhdata_full_candidate.py \
  --full \
  --fetch-date-domain calendar \
  --output-dir data/generated/d2/d2_t13_tnskhdata_full_candidate \
  --enable-remote-fetch \
  --env-file .env.local \
  --repair-listed-open-provider-blockers
```

`pro_bar` diagnostic-only：

```bash
python scripts/materialize_d2_tnskhdata_full_candidate.py \
  --full \
  --fetch-date-domain calendar \
  --output-dir data/generated/d2/d2_t13_tnskhdata_full_candidate \
  --enable-remote-fetch \
  --env-file .env.local \
  --diagnose-missing-with-pro-bar
```

## Repair Algorithm

1. 从 blocker CSV 读取并按 `(ts_code, trade_date)` 去重。
2. 对 daily / stk_limit / adj_factor 优先调用 row-level primary endpoint 参数。
3. 仅当 row-level 参数出现明确 provider 参数错误时，daily / stk_limit 才允许 date-only fallback。
4. date-only fallback 返回行必须过滤到 blocker key，unrelated rows 不得写入 canonical partition。
5. daily 仍无 row 的 listed-open key 可补查 `suspend_d`，写入前必须保留 `suspend_date`。
6. 修复行 merge 回 `partitions/{endpoint}/{YYYYMMDD}.jsonl`，仅新增或替换 target key。
7. 不直接 patch candidate aggregate JSONL；repair 后由 no-remote assemble 重新生成。
8. repair 后自动执行 no-remote verify / assemble / finalize，导出 remaining blockers。

## pro_bar Diagnostic-Only Rule

`pro_bar` 仅用于诊断 missing rows 是否可由 provider 返回。不得写入 `partitions/daily/**`、
不得生成 `tnskhdata_adjusted_price_candidate.jsonl`，不得改变 D2 acceptance，不得绕过
adj_factor source evidence。若未来要升级为 secondary repair source，必须另开 source-contract PR。

## 验收标准

- blocker exporter 能从 source_status / factor_evidence 导出三类 blocker 和 summary。
- repair 只请求 blocker key，优先 row-level params，date-only fallback 必须过滤 unrelated rows。
- repair merge 只影响 target key，不覆盖 unrelated rows，并按 endpoint key 去重。
- `suspend_d` repair 写入 `suspend_date`，可被现有 assemble 识别。
- repair report 统计 provider call、fallback、merge、quality before/after/delta 和 remaining blockers。
- `pro_bar` diagnostic 不写 canonical artifacts，不改变 D2 acceptance。
- 测试使用 fake client，不访问网络或真实 token。

## 失败状态

- blocker CSV 不存在时 repair / pro_bar diagnostic fail fast。
- provider 返回空行不算成功修复，计入 still_missing / still_unresolved。
- provider exception 必须 redacted，不得泄露 token。
- repair 后 blocker 未归零时仍保持 blocked，并输出 remaining blocker 明细。
- 任何 DuckDB、D3、R0、labels、returns、backtest 或 portfolio 产物生成均视为失败。

## 回退方式

回退本 PR 新增的 D2-T14 task doc、README 索引更新、CLI mode / helper functions 和 tests。
不得删除或回滚 PR #45 的 D2-T13 materializer、contract、schema、source contract 或 existing
local-only assemble/finalize 能力。
