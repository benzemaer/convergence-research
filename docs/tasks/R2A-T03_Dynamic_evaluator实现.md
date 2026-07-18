# R2A-T03 Dynamic evaluator 实现

## 1. 定位与状态

本任务把已接受协议 `pcavt_dynamic_state_protocol.v1` 实现为一次只处理一个 canonical
request 的参数化 evaluator。当前产物是 implementation candidate，等待代码与协议一致性
审阅；它不是正式 dynamic evaluation package，不注册 evaluator version，也不接受任何动态
状态研究结论。

```text
task_id: R2A-T03
status: implementation_candidate_pending_review
base_main_sha: 83750e7d09188a2f69456bb4f3d7c966adc0ab0a
evaluator_version: r2a_t03_dynamic_evaluator.v1
output_schema_version: r2a_t03_dynamic_evaluation_output.v1
real_score_data_read: false
formal_dynamic_evaluation_executed: false
DONE: absent
R2A-T04_allowed_to_start: false
```

## 2. 不可变绑定

Evaluator 只接受 T02 canonical envelope，并直接调用 T02 的
`validate_canonical_request`；CLI 通过 `load_canonical_request` 加载请求。T03 不复制、不旁路
request schema、canonicalization、request hash 或 request ID 算法。

```text
score_release_id: pcavt-score-w120-v1-c7e04f11a2cd09aa
dynamic_protocol_version: pcavt_dynamic_state_protocol.v1
accepted T02 handoff SHA-256:
f8ff97543b95ba3676acd36ea3d48adb06dfb1f9ab51a7ee7b8413003e1b5082
accepted protocol config SHA-256:
bd57b1c90a340fe19e52450676b48f3d9f8cba20b93e344da429b5f378540d99
```

上述 accepted 文件在每次 evaluation 前重新计算 SHA-256 并核对状态、协议和 Score release
绑定。这里的 evaluator/output 版本仅是 T03 候选，不替代 R2A-T07 的统一版本注册。

## 3. 输入与执行边界

生产 evaluator 只读 `security_observation_spine` 和 `daily_dimension_scores`。它先在 source
connection 上 fail closed 核对所需列、兼容类型、唯一 Score release、0-based 连续 sequence、
严格递增日期、status 域、selected-dimension cardinality、key、sequence 和 availability，随后
按确定性顺序以固定批次流入独立 output connection。Source 不创建表或 view，也不依赖 pandas、
随机数、wall-clock 或绝对路径。

Scope 只能是全部证券或显式证券列表。显式列表拒绝空值、重复和未知证券，并在内部排序；每只
证券始终读取完整 observation history。Scope 不进入 request identity。T03 没有 `date_from`、
`date_to`、as-of、截断历史或 warm-up 补齐。

路径入口要求 source 只读、output 父目录已存在、source/output 路径不同且 output 不存在。
Evaluator 写入同目录临时 DuckDB，经独立 validator 全部通过并关闭连接后，才以原子文件创建
发布；任一失败都会删除临时文件，不留下部分 output。

## 4. 状态算法

对每个 selected dimension，`q=q_bp/10000`，主阈值为 `1-q`，弱阈值为
`1-q-0.10`，浮点边界 epsilon 为 `1e-12`。只有 expected status 为 present、dimension
eligible、validity 为 valid 且 mean/min 均 finite 时 dimension ready；ready 后 mean 和 min
分别通过主/弱阈值才 active。Not ready 的 active 必须为 NULL。

Joint state 是完整案例 AND。所有 selected dimensions 都会被计算并保留 reason，某一维 false
不能隐藏另一维异常。任一维 not ready 或 observation 为 missing/listing pause 时，joint ready
为 false，raw state、streak 和 confirmed state 均为 NULL。Ready 时 raw state 才是全部 active
的 AND。Joint validity 独立按 `blocked > diagnostic_required > unknown > valid` 聚合，因此
“全部 validity valid 但不 eligible/非有限”仍保持 validity=valid、ready=false、raw=NULL。

Streak 只按 `security_id + observation_sequence`：true 连续累加，false 为 0，NULL 为 NULL 并
切断 run。第 K 个连续 true observation 产生一次 confirmation event，confirmed interval 从该日
开始，不回填此前 K−1 日。Public request 的 K 域仍是 2..7；纯数学 helper 单独验证 K=1 时首日
true 即确认。

Interval 持续到最后一个 confirmed=true observation。紧随其后的 false 或 NULL observation 是
termination observation，但不进入 interval。输入结束仍 true 时标记
`input_end_open_right_censored`。不实现 d/g、退出延迟、gap tolerance、跨 NULL 延续或自动合并。
Primary termination reason 严格采用以下优先级：

1. `expected_observation_missing`
2. `expected_observation_listing_pause`
3. `selected_dimension_blocked`
4. `selected_dimension_diagnostic_required`
5. `selected_dimension_unknown`
6. `selected_dimension_not_eligible`
7. `selected_dimension_score_non_finite`
8. `raw_false`

完整 joint reasons 另存于 `termination_reason_codes`，不因 primary reason 丢失细节。

## 5. Reason code 规则

Expected-observation reason 位于所有维度 reason 之前。上游 reason 只取 selected dimensions，
加入维度前缀后与派生 reason 合并、去重，并在维度内按字典序、维度间按 P/C/A/V/T 排序。
派生 reason 覆盖 blocked、diagnostic_required、unknown、not eligible 和 NULL/NaN/±Inf。未选择
维度既不读取到 staging，也不出现在 output 或 reason 中。

## 6. 开发期输出契约

每个 output DuckDB 只含以下五张正式表：

- `dynamic_request`：canonical identity、协议/实现版本、selected dimensions、canonical q JSON、
  K、weak delta 与 epsilon；
- `evaluation_scope`：all/explicit scope、确定性证券列表、日期与 cardinality；
- `daily_dimension_states`：spine × selected dimensions 的 ready/active/reason；
- `daily_joint_states`：三值 raw、streak、confirmation 与 confirmed ordinal；
- `confirmed_intervals`：raw start、confirmation、confirmed end、termination、参数和计数。

列顺序、DuckDB 类型、nullable 和 primary key 冻结在
`configs/r2a/r2a_t03_dynamic_evaluator.v1.json`、对应 JSON Schema 与 Python
`TABLE_CONTRACTS`，测试要求三者一致。`q_by_dimension` 使用 compact、sorted-key JSON 字符串，
不使用 dict repr。合法 request 可以产生零 interval；其余四张表仍完整，interval 表存在且为零行。

独立 output validator 不信任 evaluator summary。它重新检查五表 inventory、schema/nullability、
primary key、request hash/ID、scope、request ID、joint/dimension key 和 cardinality、未选维度隔离、
ready/NULL 关系、streak、K confirmation、confirmed state、interval ordinal、daily/interval 对账、
termination observation/reason、closed/right-censored 边界及不重叠约束。

## 7. Synthetic 与 property 验证范围

测试数据只写入 pytest 临时或内存 DuckDB，至少三只证券和 P/A 两个 selected dimensions，另含
未选择 T。样本覆盖 present、missing、listing pause、active true/false、valid-but-ineligible、
unknown、diagnostic、blocked、NULL/NaN/±Inf、确认前中断、raw-false/blocked 终止、多 interval、
right-censored 和 zero-event。

Failure tests 覆盖错误 release、缺表/列、spine duplicate、非 0-based/gap、非递增日期、selected
dimension 缺失/重复、sequence/availability 不一致、非法 explicit scope、output 冲突、raw spec、
篡改 hash 和非法 K。Property tests 使用测试侧集合 oracle 验证 q 放宽不收缩 true set、增加维度
只收缩 raw true set、增加 K 不提前确认且不扩大 confirmed true set，以及 insertion order、scope
order 和 DuckDB thread count 改变时 schema、row count 与 canonical row content 一致。

## 8. 非目标与停止点

本 PR 不读取真实 4.25 GB Score DuckDB，不运行 800 证券，不选择 q/K 或 dimensions，不创建
cache、manifest、validation receipt、result analysis、formal package、accepted handoff 或 DONE，
也不注册 evaluator、物化 canonical dynamic state 或启动 R2A-T04。审阅通过后的下一步仍需由
用户单独授权；当前停止点为 `R2A-T03 implementation review`。
