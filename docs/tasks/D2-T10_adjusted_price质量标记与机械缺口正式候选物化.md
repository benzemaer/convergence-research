# D2-T10 adjusted price、质量标记与机械缺口正式候选物化

状态：in_progress via PR TBD

## 目标

基于 D2-T09 已生成的本地 `d1.raw_market_prices` formal candidate artifact，生成 D2 adjusted / continuous research price candidate、价格质量标记、机械缺口归因、交易约束 readiness、raw-vs-adjusted reconciliation 与候选文件哈希摘要。

本任务是 candidate-only formal enablement。它允许写入本地 ignored `data/generated/d2/d2_t10_adjusted_price_quality_gap/`，但不得发布 accepted formal dataset、`data_version`、DuckDB、accepted manifest、D3 rows、PCVT values、R0 状态、标签、收益、回测或组合产物。

## 输入

- D2-T09 local candidate raw market prices artifact。
- D2-T09 local candidate quality summary。
- HiThink adjustment factor / corporate action event 本地 parquet 或合成测试输入。
- D2-T09 probe report。
- `source_observed_at` ISO8601 时间戳。
- 可选本地交易日历 / 交易约束输入；缺失时必须保持 unknown / blocked。

## 输出

允许本地 ignored 输出：

- `adjusted_market_prices_candidate.parquet` 或 `.jsonl`
- `market_price_quality_flags_candidate.parquet` 或 `.jsonl`
- `mechanical_gap_attribution_candidate.parquet` 或 `.jsonl`
- `trading_constraint_readiness_candidate.json`
- `raw_adjusted_reconciliation_candidate.json`
- `adjusted_price_quality_gap_materialization_report.json`
- `candidate_file_hash_summary.json`

允许提交脱敏摘要：`docs/research/D2_T10_adjusted_price_quality_gap_redacted_summary.md`，仅包含 aggregate counts 与 SHA-256。

## 非目标

- 不提交真实 raw parquet、candidate artifact、security mapping rows、vendor payload 或 row-level prices。
- 不调用远程 API，不读取 MarketDB 或 `.day` 文件，不写 DuckDB。
- 不创建 accepted run / dataset / source snapshot manifest。
- 不发布 `data_version`。
- 不生成 D3 artifact、PCVT values、R0 状态、标签、未来收益、回测或组合输出。
- 不把 HiThink、BAOSTOCK、Tushare 标记为 accepted formal source。
- 不把 D2 acceptance 标记为 passed，不解锁 D3-T07 或 R0。

## D2-T09 依赖

D2-T10 依赖 D2-T09 的 HiThink raw OHLCV 探针、raw market prices candidate artifact contract、materialization report 与 redacted local run summary。D2-T09 已显示 `trading_status` 与 `price_limit_status` 全部 unknown，因此 D2-T10 必须保留交易状态和涨跌停状态 readiness blocking，除非后续可追溯本地输入显式补齐。

## HiThink adjustment event / factor 输入语义

adjustment event / factor 输入可以包含 `security_id`、`trading_date` / `event_date` / `ex_date`、`adjustment_factor`、`factor_as_of_time`、`adjustment_revision` 等字段。若缺少 `factor_as_of_time` 或 `adjustment_revision`：

- `history_revision_class = final_revised_history`
- `point_in_time_eligible = false`
- blocking reasons 包含 `factor_as_of_time_missing` / `adjustment_revision_missing`

`source_observed_at` 只能表示 local snapshot observed_at，不得静默充当 `factor_as_of_time`。

## Adjusted Price Candidate Artifact 设计

`adjusted_market_prices_candidate` 每行只保留 contract 声明的字段。计算规则为：

```text
adj_open = raw_open * adjustment_factor
adj_high = raw_high * adjustment_factor
adj_low = raw_low * adjustment_factor
adj_close = raw_close * adjustment_factor
```

当 adjustment factor 缺失或无法解析时，允许生成 raw-equivalent fallback candidate，但必须标记 `adjustment_factor_missing_or_unresolved` 并阻断 D2 acceptance。当前 factor direction 仍为 `candidate_requires_review`。

## Quality Flags 设计

质量标记覆盖：

- raw / adjusted OHLC null、非正数与 high/low 顺序。
- null / negative volume 和 amount。
- duplicate primary key。
- amount / volume unit unknown。
- daily VWAP range。
- trading status、price limit status、suspension status、ST status readiness。

`unknown` 不得静默改写为 normal、none、false 或 0。

## Mechanical Gap Attribution 设计

按证券和交易日排序，比较 raw gap 与 adjusted gap。若 raw gap 较大、adjusted gap 明显缩小且 factor change / corporate action event 存在，则标记 `candidate_mechanical_gap`。若缺少 adjustment event 或 as-of/revision 证据，则标记 `unknown_or_unverified`。

机械缺口不得解释为交易信号，不得生成 breakout、label、future outcome 或回测字段。

## Trading Status / Price Limit Readiness 设计

输出 `trading_constraint_readiness_candidate.json`，汇总交易状态、涨跌停状态、停复牌、ST、limit price 的 known / unknown counts。当前 D2-T09 结果中交易状态和涨跌停状态仍 unknown，因此 readiness 必须 blocked。

## Blocking Rules

关键 blocking reasons：

- `factor_as_of_time_missing`
- `adjustment_revision_missing`
- `adjustment_factor_missing_or_unresolved`
- `adjustment_factor_direction_unverified`
- `raw_ohlc_null_or_nonpositive`
- `adjusted_ohlc_null_or_nonpositive`
- `raw_ohlc_order_violation`
- `adjusted_ohlc_order_violation`
- `null_volume`
- `null_amount`
- `negative_volume`
- `negative_amount`
- `duplicate_key`
- `trading_status_unknown_blocks_d2_acceptance`
- `price_limit_status_unknown_blocks_d2_acceptance`
- `suspension_status_unknown_blocks_d2_acceptance`
- `st_status_unknown_blocks_d2_acceptance`
- `amount_volume_unit_unknown_blocks_d2_acceptance`
- `missing_adjustment_event_gap_unknown`

## D2-T11 Relationship

D2-T11 负责 D2 acceptance、source status resolution 与 D3 handoff candidate。D2-T10 只生成 formal candidate artifacts 与 readiness reports，不关闭 acceptance gate。

## D3 / R0 Boundary

D3-T07 remains blocked pending D2 formal materialization and D2 acceptance. R0 remains blocked. 本任务不生成 D3 rows、PCVT values、R0 状态、研究标签、未来收益或回测输出。

## 验收标准

- contract 与 schema 通过 `scripts/validate_configs.py`。
- materializer 支持 synthetic JSON/JSONL 和真实 parquet DataFrame 路径。
- parquet 路径不把全量输入转换为 Python dict row list。
- 测试覆盖 adjusted price 计算、as-of/revision 缺失、quality blockers、unknown trading constraints、mechanical gap、禁止字段、path guard 和 no row-level return report。
- 本地生成物只在 ignored `data/generated/` 下，不提交真实 artifact。
- README 指向 D2-T10 / D2-T11，D3-T07 与 R0 仍 blocked。

## 回退方式

若 contract、schema、测试、materializer 或脱敏摘要失败，完整回退 D2-T10 新增 contract、schema、脚本、测试、任务文档、README 更新和脱敏摘要。不得通过提交 raw data、generated artifacts、DuckDB、manifest、D3 rows、PCVT values 或补写文档追认失败结果。
