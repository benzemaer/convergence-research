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

## 非目标

- 不重新爬取中证指数官网。
- 不调用任何外部 API。
- 不新增行情 loader、API client 或 ETL worker。
- 不导入行情、日历、公司行为、价格或复权因子数据。
- 不生成 `d1.security_master`、`d1.trading_calendar`、`d1.corporate_actions`、
  `d1.raw_market_prices` 或 `d2.adjusted_market_prices` 实体数据。
- 不创建 committed DuckDB 文件。
- 不生成 raw snapshot、dataset manifest、run manifest 或 run artifact。

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
