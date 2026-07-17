# EXP-A01：价格—均线贴合候选指标

## 任务状态

```text
program_id: EXP-A
task_id: EXP-A01
research_route: sidecar_exploration
candidate_layer: A
candidate_layer_name: price_ma_attachment
workflow_mode: long_lived_same_pr
phase: formal_result_review
implementation_review_status: needs_revision
reviewed_implementation_sha: 89d120c053e2376feaca5085dbc4ad5acef788f0
formal_run_allowed: true
formal_run_status: completed
formal_run_executed: true
formal_artifacts_generated: true
formal_run_id: EXP-A01-20260717T040145984Z
execution_sha: c9a52dc29f7d41c85ab416e99bb9ef8cc6411b9d
authorized_input_manifest_sha256: 44ef2e18ae6edff5dce18702f9290867382c12e114b392668358b28c10b29057
result_review_status: not_started
formal_result_review_status: pending
EXP-A02_started: false
program_phase: A01_formal_result_review
mainline_task_unchanged: true
mainline_current_task: R3-T02
```

EXP-A01 只回答：能否用方向中性的 raw metric，稳定、无尺度地描述 K 线实体相对于 MA5/10/20/30/60 均线束的贴合程度。它不回答未来预测能力、收益提升、正式 PCVT/PCATV 纳入、候选 winner、现有 P/C/T/V 删除或交易价值。

## 输入与 lineage

价格语义唯一复用 D3-T07 research candidate：`D3_T07_CANDIDATE_DAILY_OBSERVATION_CONTRACT_V1` 的 `d3_t07_candidate_daily_observation.duckdb` / `d3_candidate_daily_observation`。它的角色是 `exploration_research_candidate`，不是 formal D3 data version。A01 直接使用 D3-T07 的 `ts_code`、`trade_date`、`adjusted_open`、`adjusted_close` 和 `effective_adj_factor`；不再混用 D3 value-layer，也不把 `adjustment_method`、`factor_as_of_time`、`corporate_action_flag` 或其他不同语义字段强行映射进来。

未来 formal manifest 必须绑定 D3-T07 candidate、D3-T07 handoff/quality evidence，以及独立授权的 `expected_price_observation_index`。在 owner-approved 的四项输入契约中，D3-T08 不作为 EXP-A01 输入；它没有 A1/A2/A2b 计算字段，相关质量约束由 D3-T07 gate、主表检查、dense-index reconciliation 和 full persisted invariant validation plus deterministic stratified independent oracle 覆盖。后者至少包含 `security_id`、`trading_date`、`observation_sequence`、`expected_observation_status`、`source_contract` 和 `source_ref`；状态只能是 `present`、`listing_pause`、`missing` 或 `unresolved`。A01 不通过 civil-date 连续性猜测交易日，不把缺失或 listing-pause 行压缩掉。`present` expected key 必须与 D3-T07 主表逐 key 双向 reconcile，非 `present` key 不得出现在主表。没有真实、授权且可复核的 expected index 时，formal run 继续 blocked。

本 implementation commit 已实现 formal execution package，并在 approved exact execution SHA `c9a52dc29f7d41c85ab416e99bb9ef8cc6411b9d` 上完成 real formal run `EXP-A01-20260717T040145984Z`。runner 显式接收 `--input-manifest`，校验 manifest 的 canonical UTF-8/LF 文本、授权 schema、四项 artifact 的绝对或 manifest-relative path、输入 SHA、完整 row count、table identity、required columns、D3-T07 gate 和 dense reconciliation。正式执行使用单一 Python 进程、单一 DuckDB 连接和单一 writer；仅启用 DuckDB 内部 12 threads 并设置 12GB memory limit，不引入 Python worker 或多 writer。结果校验采用 `r0_t10_full_invariants_plus_stratified_oracle_v1`：全量 persisted invariants 与 compact profiles，加上确定性分层独立 oracle；大输入不执行全量 Python raw-row 复算，小输入仍执行完整 oracle。owner governance override 保留原科学授权连续性。结果先写入 `<RUN_ID>.partial-<pid>`，core validation、anomaly 和 cheap final-package binding 检查通过后原子发布到 external formal-results；compact package 已复制到 `data/generated/sidecar/exp_a01/EXP-A01-20260717T040145984Z/`，raw DuckDB 保留在 local-only 外部路径，不提交到 Git。当前 `formal_run_allowed=true`、`formal_run_executed=true`、`formal_artifacts_generated=true`，`result_review_status=not_started`，等待用户 Formal-result 审阅。

本次 formal run 的 persisted raw table 为 5,253,198 行，覆盖 800 只证券和 2016-01-04 至 2026-06-30；三指标各占 1,751,066 行，expected-key 双向独立对账、重复 key、状态 profile、A2/A2b valid-key 重合和 A2 outside-count 整数不变量均通过。A1/A2/A2b valid count 分别为 1,632,073、1,602,937、1,602,937；601077.SH sequence 539 的 A2 raw value 为 0.65、outside count 为 13。validator 为 `passed`，anomaly 为 `passed` 且无 blocking/investigation item；这些是工程与描述性结果，尚不构成 A 层注册、winner 选择或 downstream 结论。

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
- `A2_BodyCenterOutsideMACloudRate20_5_60`：最近 20 个日点中 `B_s < CloudLow_s` 或 `B_s > CloudHigh_s` 的比例，边界采用统一的 scale-aware 8-ULP equality zone，最低 79 个交易观测，数值范围为 `[0, 1]`。
- `A2b_BodyToMACloudGapMean20_5_60`：实体区间与均线云不相交时的最近端点 log 距离的最近 20 日均值；使用与 A2 相同的 scale-aware 8-ULP equality zone，相交时 gap 为 0，最低 79 个交易观测，数值越低表示越贴合。

三者均只使用当前及过去观测，不使用 raw unadjusted OHLC、future row、centered MA、forward/backward fill，也不跨 expected observation slot 压缩窗口或根据结果改变窗口。A1 使用当前 observation sequence 加前 59 个连续 slot 的精确 60 行；A2/A2b 使用当前 sequence 加前 78 个连续 slot 的精确 79 行。任一 slot 为 `listing_pause`、`missing`、`unresolved` 或其他 invalid 状态时，当前结果非 valid；不得跳过、填充、使用更旧的现有行或以 Outside/Gap=0 掩盖。整体价格乘以任意正数时，log 差值、边界关系和 gap 保持不变。

A2/A2b 的边界容差不是 validity-status 放宽，也不是固定价格 epsilon：`boundary_tolerance(left, right) = 8 × 2.220446049250313e-16 × max(1, abs(left), abs(right))`。生产 DuckDB SQL 和独立 Python oracle 使用同一规则；A2 仍以 `outside_count` 整数精确对账，A1 不使用该边界规则。选择 8 ULP 的理由是：`The observed production/oracle disagreement is one floating-point ULP. Eight ULPs provide a narrow execution-order allowance while remaining many orders of magnitude below any economically or statistically meaningful A2/A2b distance.`

## Validity contract

三个候选均 fail closed。以下情况不得产生 ordinary numeric raw value：窗口不足、缺少 adjusted open/close、缺少 required history、非正价格或 MA、adjustment failure、required window 内 suspension/listing pause、invalid trading status。`listed_open_resolved_daily` 是 D2/D3 已解析的上市开放交易日状态，对 EXP-A01 价格指标而言属于可用的 present observation；`normal_trading`、`limit_up`、`limit_down`、`one_price_limit_up` 和 `one_price_limit_down` 也属于允许的价格观察状态。`reopen_after_suspension` 为 diagnostic-required；`suspended`、`unknown` 或未注册值不得当作正常交易。该兼容修复不把 suspended、listing_pause、missing 或 unresolved 转换为有效状态。输入的 duplicate security/date、duplicate security/sequence、non-monotonic sequence/date 或 sequence gap 直接抛出 `InputContractError`，不得排序修复后继续。A2/A2b 的 79 个 expected slot 中任一 required observation 无效，整个当前输出即为非 valid。

输出字段固定为 `security_id`、`trading_date`、`indicator_id`、`raw_metric_name`、`raw_value`、`validity_status`、`reason_codes`、`input_window_start`、`input_window_end`、`required_observation_count`、`actual_valid_observation_count` 和 `metric_engine_version`。invalid/unknown 输出的 `raw_value` 必须为 NULL；不输出 percentile、score、state、winner、replacement、future outcome、backtest、portfolio 或 transaction cost 字段。正式运行失败且尚未发布时，runner 将 staging 原子转移到 local-only failed package，保留 raw DuckDB 和已生成的 compact/diagnostic 文件；该包固定标记为 `published=false`、`formal_artifacts_generated=false`、`usable_as_formal_result=false`，不得提交到 Git。

standalone validator 的 `--existing-package` 仅用于对 preserved failed package 做只读诊断，并将新的 validation JSON 写入独立目录；它不修改 raw、不发布 final output，也不能把旧 raw 批准为 formal result。本次 A2/A2b 生产边界语义发生变化，因此旧 raw 即使能够被重新读取，也必须重新物化后才能进入 formal run。

## 研究边界与后续阶段

A1/A2/A2b 目前只是候选，A 层尚未成立，没有正式指标选择，没有 PCATV，也没有正式 registry/freeze/state 变更。A02–A06 尚未开始：A02 为 W120 strict-past percentile/score 行为，A03 为 A 层内部冗余，A04 为跨层冗余，A05 为状态增量信息，A06 为最终决策。后续阶段必须由用户明确授权，不能由本 implementation 自动推进。
