# D2-T13 tnskhdata全量候选物化与D2验收交接

状态：in_progress via PR TBD

## 目标

从 PR #44 后的 tnskhdata primary candidate source 决策继续，按 DR-001 时间边界
`2016-01-01` 至 `2026-06-30` 调用 tnskhdata，物化 D1/D2 candidate evidence，并输出
D2 acceptance candidate decision 与 D3 handoff candidate decision。

## 非目标

不提交 generated artifacts、raw parquet、row-level prices、source symbols、security
mapping rows、vendor payload、token、DuckDB、D3 data_version、D3 rows、PCVT、R0、
labels、returns、backtest 或 portfolio outputs。

## 输入

- `configs/d2/tnskhdata_full_materialization_acceptance_contract.v1.json`
- `configs/d2/tnskhdata_source_level_asof_snapshot_revision_policy.v1.json`
- ignored local D2 candidate universe
- `.env.local` 或系统环境变量中的 `TNSKHDATA_TOKEN`，可显式 fallback 到 `TUSHARE_TOKEN`
- `docs/decisions/DR-001_G0静态中证800样本与时间边界.md`

## 输出

- tnskhdata source contract
- D2-T13 contract/schema
- full candidate materializer
- D2-T13 tests
- redacted summary
- ignored local generated outputs under `data/generated/d2/d2_t13_tnskhdata_full_candidate/`

## 验收标准

- contract 通过 JSON Schema 和 `scripts/validate_configs.py`。
- materializer 支持 sample、full、resume/checkpoint 和 remote fetch。
- provider fetch 优先按日期批量拉取 daily、stk_limit、adj_factor、stock_st、suspend_d。
- `adj_factor` 日期批量失败时支持按 `ts_code` 历史 fallback。
- 交易状态、停复牌、ST、涨跌停、复权 as-of/revision 和 adjusted price 规则有测试覆盖。
- D2 acceptance candidate decision 与 quality report 一致。
- D3/R0 不越权执行。

## 回退方式

完整回退 D2-T13 contract、schema、source contract、materializer、tests、README 更新和
redacted summary。不得通过提交 raw/generated artifacts、DuckDB、D3 rows 或 R0 outputs
追认失败结果。
