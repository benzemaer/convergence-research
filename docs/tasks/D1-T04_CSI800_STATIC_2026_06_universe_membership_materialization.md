# D1-T04 CSI800_STATIC_2026_06 universe membership materialization

## 状态

in progress via PR

## 目标

本任务为 `CSI800_STATIC_2026_06` universe membership / `d2.membership_alignment`
建立 materialization contract 与受控边界。它只使用已通过 G0 配置审核的官方中证 800
静态成分证据链，不重新抓取官网，不调用外部 API，不写 DuckDB，不生成正式成员实体行。

## 当前结论

本 PR 不生成 membership rows。实际 row materialization 仍被阻塞，直到 approved
machine-readable G0 evidence 在受控运行环境中可用，并且 future materialization PR
能验证 raw evidence SHA-256、成员数量、成员映射字段、manifest 与 run authorization。
当前阻塞原因是 approved raw bytes / machine-readable evidence 位于 ignored `data/external/`
路径；当前仓库没有可提交、可复核的 materialization input。

## 受控本地 runner

D1-T04 后续 PR 增加 `scripts/validate_csi800_static_membership_materialization.py`
作为 dry-run validator。该脚本只读取 D1-T04 contract 与本地已存在的 approved raw
evidence，默认在证据缺失时失败；CI 或无本地 evidence 环境可使用
`--allow-missing-evidence` 得到 blocked 状态。脚本不访问网络，不调用外部 API，不写
DuckDB，不生成 manifest，不提交 membership rows，也不创建 `security_id`。
它只验证 raw evidence SHA-256、可解析性、`expected_member_count=800` 和后续
security_id mapping 所需字段是否存在。

## 受控 evidence validation report

D1-T04 后续 PR 增加 aggregate evidence validation report，只记录 validation status、
raw evidence SHA-256、observed member count、mapping readiness 汇总和 no-artifact
边界。该报告不包含 raw evidence bytes，不包含 `source_symbol`、`ticker`、`exchange`
或任何 member row 明细，不是 run manifest、dataset manifest 或 materialization
manifest。PR #15 的 initial aggregate evidence validation report 已确认 approved raw
evidence SHA-256 匹配 contract；由于当时 runner 尚未支持 binary Excel/OLE `.xls`，
report 原状态为 `failed_parse`。后续 PR #16 增加 binary Excel/OLE parser support，
PR #17 重新运行 validator 后将 aggregate report 刷新为 `failed_mapping_fields`。
actual membership row materialization 仍然 blocked。

## Field alias diagnostics

D1-T04 后续 PR 增加 aggregate field diagnostics，只记录真实 approved evidence 的列名、
列数量、列名哈希、aggregate row count、required field 匹配状态、缺失字段类别和候选别名。
该诊断不包含任何 `source_symbol`、`ticker`、`exchange` 或 member row 明细，不是
materialization manifest，也不授权正式 row materialization。当前诊断显示 raw evidence
SHA-256 匹配且 aggregate row count 为 800；`source_symbol` / `ticker` / `exchange`
存在候选列，但 `security_id_mapping_reference` 仍缺失，因此 D1-T04 actual membership
row materialization 继续 blocked。

## Field alias contract

D1-T04 后续 PR 增加 field alias contract，并让受控本地 validator 可选读取该契约来标准化
raw evidence 列名。该契约只解决 `source_symbol` / `ticker` / `exchange` 的列别名：
`成份券代码Constituent Code` 可作为 `source_symbol` 与六位 A 股 `ticker` 的来源，
`交易所Exchange` 可作为交易所主来源，`交易所英文名称Exchange(Eng)` 仅作为 fallback。
`security_id_mapping_reference` 不能从 CSINDEX raw evidence 取得，必须延后到 approved
D1 security master mapping。该 PR 不提交 raw evidence bytes，不提交 member rows，不写
DuckDB，不生成 manifest，不输出 `security_id` mapping，actual membership row materialization
仍然 blocked。

## 证券主表映射引用契约

D1-T04 后续 PR 增加 security mapping reference contract，只定义
`security_id_mapping_reference` 的来源和 materialization gate。Field alias contract
只解决 CSINDEX 原始列到 canonical `source_symbol` / `ticker` / `exchange` 的转换；
`security_id_mapping_reference` 必须来自 approved D1 security master / code mapping，
并以 `ticker + exchange` 和 `2026-06-12` effective date 作为映射键语义。本 PR 不执行
真实 800 行映射，不输出任何 `security_id` 或 mapping output，不提交 member rows、raw
evidence、DuckDB、manifest 或 CSV/Parquet artifact。actual membership row materialization
仍然 blocked。

## 证券映射输出契约

D1-T04 后续 PR 增加 security mapping output contract。PR #20 只定义
`security_id_mapping_reference` 的合法来源；本契约只定义未来
`CSI800_STATIC_2026_06` 成员代码到 D1 `security_id` 映射输出必须具备的 row schema、
800 行计数、`mapped` 状态、`ticker + exchange + membership_effective_date` 映射键、
`CN.{exchange}.{ticker}` security_id 格式和 materialization gate。本 PR 不实际生成
security_id mapping output，不生成 membership rows，不提交 raw evidence、DuckDB、
manifest、CSV/Parquet artifact 或任何行级 `source_symbol` / `ticker` / `exchange` /
`security_id` 值。actual membership row materialization 仍然 blocked。

## Binary Excel parser support

D1-T04 后续 PR 为受控本地 validator 增加 binary Excel/OLE `.xls` parser support。
实现使用 `xlrd==2.0.1` 作为只读 `.xls` 解析依赖；该库采用 BSD license，使用边界仅限
本地 dry-run evidence validation，不联网，不调用外部 API，不写 DuckDB，不生成
manifest，不输出或提交 member rows，也不创建 `security_id`。HTML-table `.xls` 仍保留
原有 HTML parser 分支。PR #15 的 aggregate validation report 原状态为 `failed_parse`；
PR #17 在 binary Excel/OLE parser support 合并后重新运行 validator，并将 aggregate
report 刷新为 `failed_mapping_fields`。

## Evidence validation report refresh

D1-T04 后续 PR 在 binary Excel/OLE parser support 合并后重新严格运行本地 validator。
approved raw evidence 存在且 SHA-256 匹配，parser 得到 aggregate `member_count_observed=800`，
但 mapping-readiness gate 仍失败：validator 未确认所有 required
`source_symbol` / `ticker` / `exchange` / `security_id_mapping_reference` 字段均满足契约，
且 approved `security_id` mapping 仍未生成。因此 aggregate report 状态更新为
`failed_mapping_fields`，不提交 raw bytes、member rows、DuckDB、manifest 或任何行级字段；
actual membership row materialization 仍然 blocked。

## 非目标

- 不重新爬取中证指数官网。
- 不调用任何外部 API。
- 不新增行情 loader、API client 或 ETL worker。
- 不导入行情、日历、公司行为、价格或复权因子数据。
- 不导入真实数据或 market data。
- 不生成 `d1.security_master`、`d1.trading_calendar`、`d1.corporate_actions`、
  `d1.raw_market_prices` 或 `d2.adjusted_market_prices` 实体数据。
- 不创建 committed DuckDB 文件。
- 不生成 raw snapshot、dataset manifest、run manifest 或 run artifact。
- 不 materialize membership rows。

## 输入

- `configs/g0/universe_time_boundaries.v1.json`
- `manifests/source_snapshots/G0-T01_csindex_000906_20260703T100909Z.json`
- `configs/d0/source_registry.v1.json`
- `configs/d0/data_product_contracts.v1.json`
- DR-001 静态中证 800 样本与时间边界

## 输出

- `configs/d1/csi800_static_2026_06_membership_contract.v1.json`
- `schemas/d1_csi800_static_membership_contract.schema.json`
- `tests/test_d1_csi800_static_membership_contract.py`
- `scripts/validate_csi800_static_membership_materialization.py`
- `tests/test_validate_csi800_static_membership_materialization.py`
- `configs/d1/csi800_static_2026_06_membership_validation_report.v1.json`
- `schemas/d1_csi800_static_membership_validation_report.schema.json`
- `tests/test_d1_csi800_static_membership_validation_report.py`
- `configs/d1/csi800_static_2026_06_membership_field_diagnostics.v1.json`
- `schemas/d1_csi800_static_membership_field_diagnostics.schema.json`
- `tests/test_d1_csi800_static_membership_field_diagnostics.py`
- `configs/d1/csi800_static_2026_06_membership_field_aliases.v1.json`
- `schemas/d1_csi800_static_membership_field_aliases.schema.json`
- `tests/test_d1_csi800_static_membership_field_aliases.py`
- `configs/d1/csi800_static_2026_06_security_mapping_reference_contract.v1.json`
- `schemas/d1_csi800_static_security_mapping_reference_contract.schema.json`
- `tests/test_d1_csi800_static_security_mapping_reference_contract.py`
- `configs/d1/csi800_static_2026_06_security_mapping_output_contract.v1.json`
- `schemas/d1_csi800_static_security_mapping_output_contract.schema.json`
- `tests/test_d1_csi800_static_security_mapping_output_contract.py`
- 本任务文档与 `docs/tasks/README.md` 索引更新

## 契约边界

- `universe_id` 固定为 `CSI800_STATIC_2026_06`。
- `index_code` 固定为 `000906`，`index_alias` 固定为 `CSI800`。
- `membership_mode` 固定为 `static_cohort`。
- `membership_effective_date` 使用 G0 approved evidence 中的 `2026-06-12`。
- `source_registry_id` 固定为 `CSINDEX_OFFICIAL`，且仅允许用于 universe membership evidence /
  `d2.membership_alignment`。
- `CSINDEX_OFFICIAL` 不得作为价格、交易状态、公司行为或复权因子来源。
- `HITHINK_FINANCIAL_API`、`BAOSTOCK`、`A_STOCK_DATA_RECON` 不得作为 membership evidence 正式来源。
- 本任务不扩展 universe，不补齐缺失股票，不处理 security_master 详情，不做行情可用性过滤。

## 偏差与下游边界

`CSI800_STATIC_2026_06` 是静态研究 cohort，不代表历史任意交易日可执行的中证 800
指数成分。后续 R0/R 阶段不得直接读取原始 G0 evidence；研究只能经 D3 标准入口和
declared `data_version` 使用对齐后的 membership reference。

## 阻塞条件

- actual member row materialization 不在本 PR 授权范围内。
- approved machine-readable evidence 未作为 Git 可复现输入提交。
- security_id mapping reference 尚未 materialized。
- run manifest 与 dataset manifest 未创建。
- DuckDB materialization 未授权。

## 验收标准

- D1-T03 状态更新为 `completed via PR #12`，当前任务推进到 D1-T04。
- D1-T04 contract 通过 JSON Schema。
- contract 与 G0 approved config 的 universe id、effective date、source path、SHA-256、
  review status 和 review commit 一致。
- contract 覆盖 `d2.membership_alignment` D0 required fields、primary key 与 nullable 规则。
- tests 验证 source boundary、静态 cohort 偏差警告、D3 下游边界、no-network/no-loader/no-DuckDB
  约束和 negative cases。

## 回退方式

若契约或测试未通过，回退本任务新增的 D1-T04 contract、schema、测试和任务索引更新。
不得通过补写说明、手工成员表或临时 DuckDB 文件追认失败结果。
