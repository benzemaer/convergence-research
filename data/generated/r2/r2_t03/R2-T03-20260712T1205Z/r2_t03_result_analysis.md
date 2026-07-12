# R2-T03 实际结果合理性与异常扫描

工程 runtime gate：`passed`；异常扫描：`passed`。本报告是 author-draft，未设置 scientific PASS，R2-T04 与 R3 均保持关闭。

## 直接统计事实

- `S_PCT` 的 36 个 cell 中，事件数范围为 1403–7673，confirmed-event coverage 范围为 0.573061–1.000000。
- `S_PCVT` 的 36 个 cell 中，事件数范围为 272–2179，confirmed-event coverage 范围为 0.530565–1.000000。

## 有限推断与边界

本扫描只审计状态机、区间几何、参数响应和守恒关系，不使用未来收益、方向或回测指标。primary 与 shared-q sidecar 的比较用于集合与几何诊断，不构成参数选择。上游日表未物理提供 `available_time` 与 `eligible` 字段，本任务按照冻结配置分别由交易日 15:00（Asia/Shanghai）和 `validity_status=valid` 派生；该事实是适用边界，不应改写为源字段已被独立确认。

## 异常结论

异常项：无阻断异常。无论本项结果如何，本 author-draft 都不授权推进 R2-T04；后续仍需独立 scientific review。

## 冻结 scientific gate 诊断

共有 14 个非工程阻断的冻结 gate 失败；这些结果全部保留为 scientific review 输入，不用于选取或排除 cell。

- `r2_s_pct_w250_qt25_primary__d2__g2`：`s_pct_duration_q95_ratio` observed=3.6666666666666665，规则 `<=3.0`。
- `r2_s_pct_w120_qt25_primary__d1__g0`：`s_pct_duration_q95_ratio` observed=3.5，规则 `<=3.0`。
- `r2_s_pct_w120_qt25_primary__d2__g2`：`s_pct_duration_q95_ratio` observed=3.3333333333333335，规则 `<=3.0`。
- `r2_s_pct_w250_qt25_primary__d1__g0`：`s_pct_duration_q95_ratio` observed=3.5，规则 `<=3.0`。
- `r2_s_pct_w250_qt25_primary__d1__g1`：`s_pct_duration_q95_ratio` observed=4.0，规则 `<=3.0`。
- `r2_s_pct_w120_qt25_primary__d1__g1`：`s_pct_duration_q95_ratio` observed=4.5，规则 `<=3.0`。
- `r2_s_pct_w250_q20_shared__d1__g2`：`s_pct_duration_q95_ratio` observed=4.0，规则 `<=3.0`。
- `r2_s_pct_w250_qt25_primary__d1__g2`：`s_pct_duration_q95_ratio` observed=5.0，规则 `<=3.0`。
- `r2_s_pct_w120_q20_shared__d1__g1`：`s_pct_duration_q95_ratio` observed=3.5，规则 `<=3.0`。
- `r2_s_pct_w120_q20_shared__d1__g2`：`s_pct_duration_q95_ratio` observed=4.0，规则 `<=3.0`。
- `r2_s_pct_w120_qt25_primary__d1__g2`：`s_pct_duration_q95_ratio` observed=5.0，规则 `<=3.0`。
- `r2_s_pct_w250_q20_shared__d1__g1`：`s_pct_duration_q95_ratio` observed=3.5，规则 `<=3.0`。
- `r2_s_pcvt_w120_qv30_primary__d1__g2`：`s_pcvt_duration_q95_ratio` observed=3.5，规则 `<=3.0`。
- `r2_s_pcvt_w250_qv30_primary__d1__g2`：`s_pcvt_duration_q95_ratio` observed=3.5，规则 `<=3.0`。
