# tnskhdata 数据源契约：D1/D2 日频行情、交易约束与复权证据

## 1. 适用范围

本契约用于 D2-T13 之后的 D1/D2 candidate materialization。
tnskhdata 为 D1/D2 primary candidate source。
HiThink raw source 在 D2-T12 后降级为 deprecated/probe-only。
BAOSTOCK 与 Tushare 保留为 fallback/diagnostic only。

数据拉取日期边界继承 `docs/decisions/DR-001_G0静态中证800样本与时间边界.md`：
`2016-01-01` 至 `2026-06-30`，闭区间。正式交易日由 tnskhdata `trade_cal`
和后续冻结交易日历共同确定。

## 2. Token 与安全边界

- Token 只能来自 `.env.local`、系统环境变量或本地 secrets。
- 支持 `TNSKHDATA_TOKEN`。
- 可以显式 fallback 到 `TUSHARE_TOKEN`。
- 不得提交 token、打印 token、把 token 写入日志、PR body、测试、summary 或 generated report。

## 3. 实际使用接口矩阵

| 接口 | 用途 | 必需字段 | D1/D2 用法 |
|---|---|---|---|
| stock_basic | 股票基础信息、上市/退市/市场板块 | ts_code, symbol, name, market, exchange, list_status, list_date, delist_date | 代码映射、上市状态、交易状态归因 |
| trade_cal | 交易日历 | exchange, cal_date, is_open, pretrade_date | is_trading_day、trading_calendar_status |
| daily | 未复权日线 | ts_code, trade_date, open, high, low, close, pre_close, vol, amount | D1 raw OHLCV 主源 |
| stk_limit | 每日涨跌停价 | trade_date, ts_code, up_limit, down_limit, pre_close | limit_up_price、limit_down_price、price_limit_status 派生 |
| stock_st | 历史 ST 列表 | ts_code, name, trade_date, type, type_name | st_status 主源 |
| suspend_d | 每日停复牌 | ts_code, trade_date, suspend_type, suspend_timing | suspension_status |
| adj_factor | 复权因子 | ts_code, trade_date, adj_factor | adjustment_factor 主源 |
| pro_bar | 前/后复权行情 | ts_code, trade_date, OHLCV | qfq/hfq reconciliation only，不作为 D1/D2 主事实源 |
| stk_premarket | 盘前股本与涨跌停价 | ts_code, trade_date, up_limit, down_limit | stk_limit 缺失时的 diagnostic fallback |

## 4. 单位

tnskhdata daily:

- `vol` = 成交量，单位“手”
- `amount` = 成交额，单位“千元”

D2 canonical candidate 同时保存：

- `volume_lot`
- `volume_shares = volume_lot * 100`
- `amount_thousand_yuan`
- `amount_yuan = amount_thousand_yuan * 1000`

## 5. 复权口径

- `adj_factor` 为复权因子主源。
- 后复权候选价格：`hfq_price = raw_price * adj_factor`
- 前复权候选价格：`qfq_price = raw_price * adj_factor / anchor_adj_factor`
- qfq 必须显式记录 `qfq_anchor_trade_date` 和 `qfq_anchor_adj_factor`。
- `pro_bar(qfq/hfq)` 只用于 reconciliation，不作为唯一 source of truth。

## 6. as-of 与 revision policy

- `factor_as_of_time = trade_date 09:20:00 Asia/Shanghai`
- `factor_as_of_time_policy = tnskhdata_adj_factor_source_level_daily_ingestion_window`
- `row_level_factor_as_of_time_available = false`
- `adjustment_revision = source_snapshot_id`
- `adjustment_revision_class = snapshot_level_revision`
- `adjustment_revision_hash = artifact_sha256`
- `provider_row_level_revision_available = false`
- `point_in_time_eligibility_class = source_level_asof_snapshot_revision`
- `point_in_time_eligible_for_eod_research = true`
- `strict_provider_row_level_revision_eligible = false`

## 7. trading_status 派生规则

```text
if trading_date < list_date:
    trading_status = not_listed_yet
elif delist_date exists and trading_date > delist_date:
    trading_status = after_delist
elif trade_cal.is_open == 0:
    trading_status = market_closed
elif suspend_d has suspend_type == "S":
    trading_status = suspended
elif daily has row:
    trading_status = normal_trading
else:
    trading_status = provider_empty_or_unclassified
```

## 8. suspension_status 派生规则

```text
suspend_d.suspend_type == S -> suspended
suspend_d.suspend_type == R -> resumed
daily has row and no S -> not_suspended
not_listed_yet / after_delist / market_closed -> not_applicable
else -> unresolved
```

## 9. st_status 派生规则

```text
stock_st has ts_code on trade_date -> st
stock_st no ts_code on trade_date and listed/trading universe -> not_st
not_listed_yet / after_delist / market_closed -> not_applicable
```

`namechange` 只能作为 fallback，且必须标记：
`st_status_evidence_method = namechange_derived_candidate`。

## 10. price_limit_status 派生规则

主证据：`stk_limit + daily OHLC`

```text
if trading_status in not_listed_yet / after_delist / market_closed / suspended:
    price_limit_status = not_applicable
elif high >= up_limit - epsilon or close >= up_limit - epsilon:
    price_limit_status = limit_up_touched_or_closed
elif low <= down_limit + epsilon or close <= down_limit + epsilon:
    price_limit_status = limit_down_touched_or_closed
else:
    price_limit_status = not_limited
```

默认：`price_compare_epsilon = 0.001`。

禁止只凭板块 10% / 20% / 5% 规则替代 provider limit price。
板块规则只能做 diagnostic fallback。

## 11. 禁止事项

- 不提交 raw parquet
- 不提交 generated artifacts
- 不提交 row-level source symbols / mapping rows / vendor payload
- 不提交 token
- 不写 DuckDB
- 不发布 D3 data_version
- 不生成 D3 rows
- 不生成 PCVT / R0 / labels / returns / backtest / portfolio
