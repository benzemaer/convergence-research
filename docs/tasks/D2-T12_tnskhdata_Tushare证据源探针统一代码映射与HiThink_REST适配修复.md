# D2-T12 tnskhdata/Tushare证据源探针、统一代码映射与HiThink REST适配修复

状态：in_progress via PR TBD

## 目标

修复 D2-T11 暴露出的 provider adapter 与代码映射问题，新增 tnskhdata 作为
D1/D2 candidate 主路径，接受 tnskhdata source-level as-of 与 snapshot-level revision
policy，并将 HiThink raw 降级为 D1/D2 candidate materialization 的 deprecated /
probe-only 路径。输出只包含聚合覆盖率、缺失率、冲突统计和 blocked / partially
resolved 的可审计结论。

## 输入

- D2-T09 local raw candidate artifact 的必要列：`security_id`、`trading_date`、
  `universe_id`、`time_segment_id`。
- D2-T10 local adjusted candidate / readiness / reconciliation summary。
- `.env.local` 中的本地 `HITHINK_API_KEY`、`TUSHARE_TOKEN`、可选
  `TNSKHDATA_TOKEN`。
- D2-T11 redacted summary 和 blocking reasons。

## 输出

- `configs/d2/tnskhdata_tushare_hithink_provider_remediation_contract.v1.json`。
- `configs/d2/tnskhdata_source_level_asof_snapshot_revision_policy.v1.json`。
- `schemas/d2_tnskhdata_tushare_hithink_provider_remediation_contract.schema.json`。
- `schemas/d2_tnskhdata_source_level_asof_snapshot_revision_policy.schema.json`。
- `scripts/resolve_security_provider_codes.py`。
- `scripts/run_d2_t12_provider_remediation_probe.py`。
- `scripts/materialize_d2_tnskhdata_candidate_evidence.py`。
- D2-T12 provider adapter / code mapping / capability matrix tests。
- `docs/research/D2_T12_tnskhdata_tushare_hithink_provider_remediation_redacted_summary.md`。
- ignored local reports under `data/generated/d2/d2_t12_provider_remediation/` only.
- ignored local evidence under
  `data/generated/d2/d2_t12_tnskhdata_candidate_evidence/` only.

## 非目标

不提交 raw parquet、generated evidence artifacts、row-level prices、source symbols、
security mapping rows、vendor payload、API token、DuckDB、accepted manifest、
published data version、D3 rows、PCVT values、R0 state、labels、returns、backtests 或
portfolio outputs。

## Provider 边界

tnskhdata 是 D1/D2 candidate 主数据源：`daily` 用作 raw OHLCV candidate，
`adj_factor` 用作 adjustment factor candidate，`stk_limit`、`trade_cal`、
`stock_basic`、`stock_st`、`suspend_d` 用作 status / constraint candidate。BAOSTOCK
和 Tushare 仅为 fallback / diagnostic；HiThink REST 仅为 diagnostic / probe；HiThink
raw 在 D2-T12 后标记为
`deprecated_for_d1_d2_candidate_materialization_after_D2-T12`。任何 provider endpoint
不可用、权限不足、空返回或字段缺失都必须进入 capability matrix，不得伪造 resolved。

## As-of / Revision 边界

tnskhdata `adj_factor` 采用 source-level policy：
`factor_as_of_time = trade_date 09:20:00 Asia/Shanghai`。provider row-level
revision 不可得时，采用 snapshot-level revision：
`adjustment_revision = source_snapshot_id`，`adjustment_revision_hash =
artifact_sha256`，`adjustment_revision_class = snapshot_level_revision`。
`point_in_time_eligibility_class = source_level_asof_snapshot_revision`，允许
EOD research candidate 使用，但 `strict_provider_row_level_revision_eligible = false`。

## 代码映射边界

统一支持 `XSHE.000001`、`XSHG.600000`、`SZSE.000001`、`SHSE.600000`、
`CN.SZSE.000001`、`CN.SSE.600000`、`000001.SZ`、`600000.SH`、`sz.000001` 和
`sh.600000`。无法映射时 `mapping_status = unresolved`，不得发起 provider query。

## 验收标准

- D2-T12 contract 通过 JSON Schema 和 `scripts/validate_configs.py`。
- provider code mapping 多格式测试通过。
- tnskhdata / Tushare-compatible adapter 使用 fake pro client / FakeFrame 测试，不依赖
  pandas、真实 token 或真实 API。
- HiThink REST adapter 使用 fake HTTP client 测试，包含 `X-api-key` header 且不输出 key。
- capability matrix 能记录成功、空返回、字段缺失、权限不足或异常。
- `adj_factor` 可在 source-level as-of 与 snapshot-level revision 下 resolved。
- ST namechange 推断必须标记 `namechange_derived_candidate`。
- ST 主证据优先使用 `stock_st`。
- `price_limit_status` 必须由 `stk_limit + daily` 推导，不得仅凭板块规则或 limit 字段存在
  直接推断。
- 输出报告不含 row-level payload、token、DuckDB、data_version、D3 或 R0。
- 若 full tnskhdata candidate evidence、snapshot hash、accepted manifest 或 data_version
  仍未完成，D2 acceptance 必须继续 blocked。

## 回退方式

完整回退 D2-T12 contract、schema、scripts、tests、task docs、README 和 redacted summary。
不得通过提交 raw/generated artifacts、DuckDB、manifest、D3 rows 或 PCVT/R0 outputs 追认失败结果。
