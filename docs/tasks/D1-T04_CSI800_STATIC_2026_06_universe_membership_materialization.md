# D1-T04 CSI800_STATIC_2026_06 universe membership materialization

## 状态

completed via completion PR

## 目标

本任务为 `CSI800_STATIC_2026_06` universe membership / `d2.membership_alignment`
建立 materialization contract 与受控边界。它只使用已通过 G0 配置审核的官方中证 800
静态成分证据链，不重新抓取官网，不调用外部 API，不写 DuckDB，不生成 run manifest 或
dataset manifest。

## 当前结论

D1-T04 已提交标准化 `CSI800_STATIC_2026_06` membership reference。该 reference
由受控本地 runner 读取 ignored `data/external/` 下的 approved CSINDEX evidence 生成，
并通过 raw evidence SHA-256、800 行成员数、field alias、D1 security master 映射引用、
`CN.{exchange}.{ticker}` security_id 格式、唯一键和 no-artifact 边界校验。raw
evidence bytes、raw CSINDEX payload、standalone security mapping output、DuckDB、run
manifest、dataset manifest、CSV/Parquet artifact 均未提交。D1-T04 completed；D2-T01
可在单独 PR 中启动，但本 PR 未执行 D2。

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

## 证券映射输出聚合报告

D1-T04 后续 PR 增加 security mapping output aggregate validation report。PR #21
只定义未来 security mapping output contract；本报告只记录该 output 是否具备可用的
aggregate validation evidence。当前仓库与受控运行输入中没有 approved row-level
security mapping output，因此报告状态为 `blocked_missing_security_mapping_output`。
本 PR 不提交 security_id mapping output，不提交 membership rows，不生成 `security_id`，
不提交 raw evidence、DuckDB、manifest、CSV/Parquet artifact 或任何行级
`source_symbol` / `ticker` / `exchange` / `security_id` / `security_id_mapping_reference`
值。actual membership row materialization 仍然 blocked。

## 受控证券映射执行与聚合报告

D1-T04 后续 PR 增加受控 security mapping runner，并首次执行 approved evidence 到
D1 `security_id` 的 aggregate-only 映射检查。Runner 读取 approved CSINDEX raw evidence、
field alias contract、security mapping reference contract、security mapping output contract
和 D1 security master contract，在内存中标准化 `source_symbol` / `ticker` / `exchange`，
按 `CN.{exchange}.{ticker}` 规则检查 800 个 aggregate mapping。即使 aggregate mapping
为 `passed`，本 PR 也不提交 row-level security_id mapping output，不提交 membership rows，
不写 DuckDB，不创建 run manifest 或 dataset manifest，不进入 D2-T01。D1-T04 actual
membership row materialization 仍然 blocked，等待单独 PR 授权。

## 成员行物化与完成报告

D1-T04 收尾 PR 提交标准化 membership reference 与 completion report。Membership
reference 只包含 canonical row fields：`member_ordinal`、`universe_id`、
`membership_effective_date`、`source_registry_id`、`source_snapshot_id`、
`source_symbol`、`ticker`、`exchange`、`security_id`、
`security_id_mapping_reference`、`mapping_method`、`mapping_status` 和
`membership_status`。它不包含 CSINDEX 原始名称、英文名、权重、行情、价格、行业、
财务、停复牌、公司行为或复权字段。Completion report 记录 D1-T04 completed、
`member_count_observed=800`、security mapping output aggregate report 为 `passed`、
所有 failure counts 为 0，并明确 D2 只能通过 committed D1-T04 membership reference
使用该静态 cohort；D2 不得直接读取 G0 raw evidence 或 `data/external`。

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
- 不导入 market data。
- 不生成 `d1.security_master`、`d1.trading_calendar`、`d1.corporate_actions`、
  `d1.raw_market_prices` 或 `d2.adjusted_market_prices` 实体数据。
- 不创建 committed DuckDB 文件。
- 不生成 raw snapshot、dataset manifest、run manifest 或 run artifact。
- 不提交 raw CSINDEX payload、standalone security mapping output、CSV/Parquet artifact
  或 DuckDB。
- 不在本 PR 中启动 D2-T01。

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
- `configs/d1/csi800_static_2026_06_security_mapping_output_report.v1.json`
- `schemas/d1_csi800_static_security_mapping_output_report.schema.json`
- `tests/test_d1_csi800_static_security_mapping_output_report.py`
- `scripts/build_csi800_security_mapping_output.py`
- `tests/test_build_csi800_security_mapping_output.py`
- `configs/d1/csi800_static_2026_06_membership_reference.v1.json`
- `schemas/d1_csi800_static_membership_reference.schema.json`
- `tests/test_d1_csi800_static_membership_reference.py`
- `configs/d1/csi800_static_2026_06_membership_completion_report.v1.json`
- `schemas/d1_csi800_static_membership_completion_report.schema.json`
- `tests/test_d1_csi800_static_membership_completion_report.py`
- `scripts/build_csi800_static_membership_reference.py`
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

- D1-T04 membership reference 已完成；raw evidence bytes 仍不提交。
- D2-T01 尚未启动，后续 D2 membership alignment 必须在单独 PR 中读取 committed
  D1-T04 membership reference，不得直接读取 G0 raw evidence 或 `data/external`。
- run manifest、dataset manifest 与 DuckDB materialization 仍未在 D1-T04 中创建。

## 验收标准

- D1-T03 状态更新为 `completed via PR #12`，当前任务推进到 D1-T04。
- D1-T04 contract 通过 JSON Schema。
- contract 与 G0 approved config 的 universe id、effective date、source path、SHA-256、
  review status 和 review commit 一致。
- contract 覆盖 `d2.membership_alignment` D0 required fields、primary key 与 nullable 规则。
- tests 验证 source boundary、静态 cohort 偏差警告、D3 下游边界、no-network/no-loader/no-DuckDB
  约束和 negative cases。
- membership reference 包含 800 行 canonical rows，`security_id` 唯一且满足
  `CN.{exchange}.{ticker}`，不包含 raw CSINDEX payload 或 market/company-action fields。
- completion report 标记 D1-T04 completed 与
  `ready_for_d2_membership_alignment`，但不启动 D2-T01。

## 回退方式

若契约或测试未通过，回退本任务新增的 D1-T04 contract、schema、测试和任务索引更新。
不得通过补写说明、手工成员表或临时 DuckDB 文件追认失败结果。
