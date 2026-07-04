# D2-T06 候选行情快照探针：raw/qfq/hfq/factor/as-of/revision 覆盖

状态：

contract-only pending separately authorized probe execution via PR #30

## 目标

建立候选行情快照探针的 contract、report、schema、validator 和合成验收测试，用于固定未来
真实 probe 需要检查的 raw/qfq/hfq/factor/as-of/revision/retrieved_at/source snapshot/hash
证据结构。

本 PR 属于 D2，不属于 D3。本 PR 不执行真实 API 请求，不采集真实行情，不生成正式
D1/D2 数据，不写 DuckDB，不创建正式 manifest。

## 非目标

- 不采集行情；
- 不调用真实 API；
- 不导入公司行为；
- 不计算真实复权因子；
- 不构造真实连续研究价格；
- 不生成 adjusted prices；
- 不生成正式 `d1.raw_market_prices` 或 `d2.adjusted_market_prices` 实体数据；
- 不写 DuckDB；
- 不创建正式 run manifest、dataset manifest 或 source snapshot manifest；
- 不读取 G0 raw evidence、`data/external`、MarketDB 或 `.day` 文件；
- 不计算 gap attribution、PCVT、状态、事件、标签、收益或回测；
- 不推进 D3。

## 输入

- `configs/d0/source_registry.v1.json`
- `configs/d2/raw_ohlcv_source_contract.v1.json`
- `configs/d2/raw_market_prices_materialization_contract.v1.json`
- `configs/d2/adjustment_factor_asof_contract.v1.json`
- `configs/d2/continuous_price_construction_contract.v1.json`
- `configs/d2/csi800_static_2026_06_membership_alignment.v1.json`
- `configs/g0/universe_time_boundaries.v1.json`

## 输出

- `configs/d2/candidate_market_snapshot_probe_contract.v1.json`
- `schemas/d2_candidate_market_snapshot_probe_contract.schema.json`
- `configs/d2/candidate_market_snapshot_probe_report.v1.json`
- `schemas/d2_candidate_market_snapshot_probe_report.schema.json`
- `scripts/validate_d2_candidate_market_snapshot_probe.py`
- `tests/test_d2_candidate_market_snapshot_probe_contract.py`
- `tests/test_d2_candidate_market_snapshot_probe_validator.py`

## 契约边界

- 候选 source 仅限 `HITHINK_FINANCIAL_API` 与 `BAOSTOCK`；
- `CSINDEX_OFFICIAL`、`A_STOCK_DATA_RECON` 和
  `PUBLIC_A_SHARE_ENDPOINTS_REVIEW_BUCKET` 不得作为候选行情 probe source；
- 未来真实 probe 必须记录 `retrieved_at`、`observed_at`、`source_snapshot_id` 和
  `raw_response_sha256`；
- 供应商前复权 K 线可用于 exploration-only，但必须带 final-revised / unknown revision 标记；
- qfq/hfq 不得冒充 raw trading fact；
- vendor factor 缺失时，implied factor 只能标记为 candidate implied factor，不得冒充
  vendor official factor；
- 正式 point-in-time 回测仍被 terms、snapshot、factor_as_of_time、revision comparison 阻塞；
- D3 不因本 PR 自动解锁。

## 验收标准

- contract 与 report 通过 JSON Schema；
- report 明确 API、raw snapshot、DuckDB、manifest、formal ingestion 全部 false；
- validator 只验证内存对象或合成 fixture；
- 合成测试覆盖 required fields、禁止来源、membership、snapshot/hash、implied factor、
  revision class、research use tier、qfq/hfq 不替代 raw、future/label/event 字段；
- README 将原 D2-T06/D2-T07 顺延为 D2-T07/D2-T08；
- 不推进 D3。

## 回退方式

若 contract、report、validator、schema、测试或任务索引失败，完整回退本 PR 新增的
D2-T06 文档、contract、report、schema、validator、tests 和 README 索引更新。
不得通过真实 API 请求、读取真实行情、写 DuckDB、创建 manifest 或修改上游 D2 产物来
追认失败结果。
