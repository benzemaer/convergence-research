# EXP-A01：价格—均线贴合候选指标

## 任务状态

```text
program_id: EXP-A
task_id: EXP-A01
research_route: sidecar_exploration
candidate_layer: A
candidate_layer_name: price_ma_attachment
workflow_mode: long_lived_same_pr
phase: implementation_review
implementation_review_status: pending
reviewed_implementation_sha:
formal_run_allowed: false
formal_run_status: not_started
formal_run_executed: false
result_review_status: not_started
program_phase: A01_candidate_raw_metric_implementation
mainline_task_unchanged: true
mainline_current_task: R3-T02
```

EXP-A01 只回答：能否用方向中性的 raw metric，稳定、无尺度地描述 K 线实体相对于 MA5/10/20/30/60 均线束的贴合程度。它不回答未来预测能力、收益提升、正式 PCVT/PCATV 纳入、候选 winner、现有 P/C/T/V 删除或交易价值。

## 输入与 lineage

价格语义复用仓库现有的 continuous research adjusted-OHLC 体系，不发明第二套 adjustment policy。权威字段契约是 `D3_DAILY_MARKET_OBSERVATION_VALUES_CONTRACT_V1`，对象为 `d3.daily_market_observation_values`；候选物化边界参考 `D3_T07_CANDIDATE_DAILY_OBSERVATION_CONTRACT_V1`。核心计算接受规范化的 `security_id`、`trading_date`、`adjusted_open`、`adjusted_close`，并兼容对应的 `ts_code`、`trade_date`、`adj_open`、`adj_close` 字段别名。

实现阶段只使用内存 synthetic rows，不打开真实大型 DuckDB。未来 formal runner 必须显式接收精确的 `--input-manifest`，校验 manifest 的 canonical UTF-8/LF 文本、绝对或 manifest-relative path、输入 SHA、完整 row count、table identity 和 required columns；当前只实现这些 fail-closed gate，不执行 formal run。

## 固定候选

所有均线都是 adjusted close 的当前日包含式简单移动平均。设：

```text
B_t = (log(adjusted_open_t) + log(adjusted_close_t)) / 2
L_k,t = log(SMA_k(adjusted_close)_t), k ∈ {5, 10, 20, 30, 60}
CloudLow_t = min(L_k,t)
CloudHigh_t = max(L_k,t)
CloudCenter_t = mean(L_k,t)
```

候选固定为：

- `A1_LogBodyCenterToMACloudCenter_5_60`：`abs(B_t - CloudCenter_t)`，最低 60 个交易观测，数值越低表示越贴合。
- `A2_BodyCenterOutsideMACloudRate20_5_60`：最近 20 个日点中 `B_s < CloudLow_s` 或 `B_s > CloudHigh_s` 的比例，严格等于边界时计为 inside，最低 79 个交易观测，数值范围为 `[0, 1]`。
- `A2b_BodyToMACloudGapMean20_5_60`：实体区间与均线云不相交时的最近端点 log 距离的最近 20 日均值，相交时 gap 为 0，最低 79 个交易观测，数值越低表示越贴合。

三者均只使用当前及过去观测，不使用 raw unadjusted OHLC、future row、centered MA、forward/backward fill，也不跨 suspension 压缩窗口或根据结果改变窗口。整体价格乘以任意正数时，log 差值、边界关系和 gap 保持不变。

## Validity contract

三个候选均 fail closed。以下情况不得产生 ordinary numeric raw value：窗口不足、缺少 adjusted open/close、缺少 required history、非正价格或 MA、adjustment failure、required window 内 suspension/listing pause、invalid trading status、duplicate security/date 或 non-monotonic security/date。A2/A2b 的 79 日窗口中任一 required observation 无效，整个当前输出即为非 valid；不得跳过、填充、压缩或将 Outside/Gap 改成 0。

输出字段固定为 `security_id`、`trading_date`、`indicator_id`、`raw_metric_name`、`raw_value`、`validity_status`、`reason_codes`、`input_window_start`、`input_window_end`、`required_observation_count`、`actual_valid_observation_count` 和 `metric_engine_version`。invalid/unknown 输出的 `raw_value` 必须为 NULL；不输出 percentile、score、state、winner、replacement、future outcome、backtest、portfolio 或 transaction cost 字段。

## 研究边界与后续阶段

A1/A2/A2b 目前只是候选，A 层尚未成立，没有正式指标选择，没有 PCATV，也没有正式 registry/freeze/state 变更。A02–A06 尚未开始：A02 为 W120 strict-past percentile/score 行为，A03 为 A 层内部冗余，A04 为跨层冗余，A05 为状态增量信息，A06 为最终决策。后续阶段必须由用户明确授权，不能由本 implementation 自动推进。
