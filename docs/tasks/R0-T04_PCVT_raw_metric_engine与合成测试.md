# R0-T04 PCVT raw metric engine 与合成测试

状态：completed via PR #62。

## 目标

本任务实现 R0 的纯内存 PCVT raw metric engine，用合成样本计算八个 raw/base 观测对象：`P1_NATR14`、`P2_LogRange20`、`C1_LogMASpread_5_60`、`C2_AdjVWAPSpread_5_60`、`T1_ER20`、`T2_AbsTrendT20`、`V1_TurnoverShrink20_60` 和 `V2_LogAmount20_base`。其中 V1 以 R0-T03 固定的 turnover baseline 为准；V2 在本任务只生成 `LogAmount20` base object，`AmountLevel20Pct` 的严格过去历史位置留给 R0-T05。

## 非目标

本任务不读取真实 DuckDB、MarketDB、`.day`、`data/raw/` 或 `data/external/`，不生成正式 `data_version`、manifest、readiness audit 真实输出文件或 generated artifact。本任务不生成 strict-past percentiles、scores、states、state intervals、future labels、future returns、breakout direction、backtest 或 portfolio，不修改 R0-T01 weak baseline，不进入 R0-T05 的 eligible 样本和分位体系。

## 输入

输入为调用方传入的 synthetic in-memory rows，每行包含 `security_id`、`trading_date` 和各指标所需字段。P/C/T 价格类指标使用连续研究价格字段；C2 额量 VWAP 口径必须先通过 R0-T02 readiness 语义；V1 turnover shrink 必须先通过 R0-T03 readiness 语义；V2 amount base 使用 D3-T11 标准 `amount_yuan`、单位状态和 `zero_amount_flag` 语义。输入顺序不得影响输出排序，输出按证券、日期和固定指标顺序稳定返回。

## 输出

输出为 `RawMetricResult` 对象序列，每条包含 `security_id`、`trading_date`、`indicator_id`、`raw_metric_name`、`raw_value`、`validity_status`、`reason_codes`、`input_window_start`、`input_window_end`、`required_observation_count`、`actual_valid_observation_count`、`source_field_names` 和 `metric_engine_version`。有效 raw metric 使用 `valid`；无法合法计算时必须返回 `unknown`、`diagnostic_required` 或 `blocked`，并携带固定 reason code；不得把 unknown 填成 `False`、`0`、前值或均值。

## 契约与门禁语义

`NATR14` 使用 adjusted high/low/close 和前一日 adjusted close 计算 TR，并以 14 日 Wilder ATR 除以当前 adjusted close，至少需要 15 个有效交易日。`LogRange20` 使用 20 日 adjusted high 最大值与 adjusted low 最小值。`LogMASpread_5_60` 使用 adjusted close 的 MA5/10/20/30/60 后取 log 的总体标准差。`AdjVWAPSpread_5_60` 使用 daily VWAP 与 volume shares 的 5/10/20/30/60 日加权 VWAP，并传播 R0-T02 C2 readiness reason；公司行为窗口缺少共同基准时不得硬算。

`ER20` 使用 21 个 adjusted close 计算 20 日效率比；完全平价路径 denominator 为零时输出 `0` 并记录 reason。`AbsTrendT20` 使用 20 日 log close 的 OLS 斜率 t 统计量绝对值；residual SE 为零且斜率为零时输出 `0`，residual SE 为零但斜率非零时返回 `diagnostic_required` 和 `residual_se_zero_slope_nonzero`，不得输出 `inf` 或静默设为 `0`。`TurnoverShrink20_60` 使用 recent 20 日平均 `turnover_float` 除以 prior non-overlapping 60 日平均 `turnover_float`，并传播 R0-T03 V1 readiness；`volume_unit` 不属于 active V1 required field。`LogAmount20` 使用 recent 20 日 `amount_yuan` 均值取 log，并传播 amount unit、zero amount 和 suspension reason；`AmountLevel20Pct` 不在本任务生成。

## 验收标准

验收要求包括：R0-T04 contract/schema 通过 `validate_configs.py`；raw engine 对八个指标的正常路径返回稳定 raw value；窗口不足、缺字段、非正价格、高低价异常、停牌、单位失败、zero volume、公司行为共同基准缺失、provider crosscheck fail、zero amount 和 T2 退化路径均返回固定非 ready reason；forbidden output guard 拒绝 percentile、score、state、future label、backtest 和 portfolio；lineage guard 拒绝直接 D1/D2、raw/external、MarketDB 和 `.day` 来源；README 将 R0-T04 标记为 completed via PR #62，并推进到 R0-T05 / R0-T06。

## 失败状态

若实现读取真实数据、写 DuckDB 或提交 generated artifact，若 V1 回退到 `V1_VolShrink20_60` 或把 `volume_unit` 作为 active V1 required field，若 V2 直接生成 `AmountLevel20Pct` 或 strict-past percentile，若缺少 readiness reason 仍返回 `valid`，或若 unknown 被填成低参与/未触发/0，本任务失败。

## 验证命令

```bash
python scripts/build_compendium.py --check
python scripts/validate_configs.py
python scripts/validate_manifests.py
ruff format --check scripts tests src
ruff check scripts tests src
python -m unittest discover -s tests -v
git diff --check
```

## 回退方式

若本任务需要回退，应移除 `src/r0/raw_metric_engine.py`、R0-T04 contract/schema 和对应测试，将 README 中 R0-T04 状态退回 planned 或 in progress，并停止后续 R0-T05 消费 raw/base metric 输出。若已基于 R0-T04 输出设计 R0-T05 分位体系，必须先回退或重开 R0-T05 contract，使其不引用未通过门禁的 raw engine。
