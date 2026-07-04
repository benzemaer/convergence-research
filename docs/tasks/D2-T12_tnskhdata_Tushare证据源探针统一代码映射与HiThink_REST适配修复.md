# D2-T12 tnskhdata/Tushare证据源探针、统一代码映射与HiThink REST适配修复

状态：in_progress via PR TBD

## 目标

修复 D2-T11 暴露出的 provider adapter 与代码映射问题，新增 tnskhdata 作为
Tushare-compatible candidate provider，并对 HiThink REST、BAOSTOCK、Tushare 和
tnskhdata 做真实 provider-specific probe。输出只包含聚合覆盖率、缺失率、冲突统计和
blocked / partially resolved 的可审计结论。

## 输入

- D2-T09 local raw candidate artifact 的必要列：`security_id`、`trading_date`、
  `universe_id`、`time_segment_id`。
- D2-T10 local adjusted candidate / readiness / reconciliation summary。
- `.env.local` 中的本地 `HITHINK_API_KEY`、`TUSHARE_TOKEN`、可选
  `TNSKHDATA_TOKEN`。
- D2-T11 redacted summary 和 blocking reasons。

## 输出

- `configs/d2/tnskhdata_tushare_hithink_provider_remediation_contract.v1.json`。
- `schemas/d2_tnskhdata_tushare_hithink_provider_remediation_contract.schema.json`。
- `scripts/resolve_security_provider_codes.py`。
- `scripts/run_d2_t12_provider_remediation_probe.py`。
- D2-T12 provider adapter / code mapping / capability matrix tests。
- `docs/research/D2_T12_tnskhdata_tushare_hithink_provider_remediation_redacted_summary.md`。
- ignored local reports under `data/generated/d2/d2_t12_provider_remediation/` only.

## 非目标

不提交 raw parquet、generated evidence artifacts、row-level prices、source symbols、
security mapping rows、vendor payload、API token、DuckDB、accepted manifest、
published data version、D3 rows、PCVT values、R0 state、labels、returns、backtests 或
portfolio outputs。

## Provider 边界

HiThink 仍为 primary candidate source；tnskhdata、BAOSTOCK 和 Tushare 只能 missing-only
repair，不得静默覆盖更高优先级非空字段。任何 provider endpoint 不可用、权限不足、空返回
或字段缺失都必须进入 capability matrix，不得伪造 resolved。

## 代码映射边界

统一支持 `XSHE.000001`、`XSHG.600000`、`SZSE.000001`、`SHSE.600000`、
`CN.SZSE.000001`、`CN.SSE.600000`、`000001.SZ`、`600000.SH`、`sz.000001` 和
`sh.600000`。无法映射时 `mapping_status = unresolved`，不得发起 provider query。

## 验收标准

- D2-T12 contract 通过 JSON Schema 和 `scripts/validate_configs.py`。
- provider code mapping 多格式测试通过。
- tnskhdata / Tushare-compatible adapter 使用 fake pro client 测试，不依赖真实 token。
- HiThink REST adapter 使用 fake HTTP client 测试，包含 `X-api-key` header 且不输出 key。
- capability matrix 能记录成功、空返回、字段缺失、权限不足或异常。
- `adj_factor` 缺少 as-of/revision 时 `point_in_time_eligible = false`。
- ST namechange 推断必须标记 `namechange_derived_candidate`。
- 输出报告不含 row-level payload、token、DuckDB、data_version、D3 或 R0。
- 若 `factor_as_of_time` / `adjustment_revision` 仍不可得，D2 acceptance 必须继续 blocked。

## 回退方式

完整回退 D2-T12 contract、schema、scripts、tests、task docs、README 和 redacted summary。
不得通过提交 raw/generated artifacts、DuckDB、manifest、D3 rows 或 PCVT/R0 outputs 追认失败结果。
