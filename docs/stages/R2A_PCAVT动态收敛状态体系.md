# R2A 阶段纲领：PCAVT 动态收敛状态体系

## 一、阶段定位

R2A 是在加入 A 维度后，对 P/C/A/V/T 评分与状态体系进行的一次独立重建。

R2A 不继承旧 R2-T08 的固定状态版本、q 向量、K/d/g 参数、PCT/PCVT 区间或 R3 handoff。旧实现只能作为工程模式参考，不能作为 R2A 的科学结论。

R2A 不再以“选择一套固定的 PCAVT 参数并物化固定事件表”为最终目标，而是建立两层分离的基础设施：

```text
不可变 canonical PCAVT Score release
                ↓
参数化 dynamic state evaluator
                ↓
按请求生成 daily state 和 interval
```

其中：

```text
PCAVT = 可供用户选择的维度全集
PCAVT ≠ 固定嵌套顺序
PCAVT ≠ 固定 PCT/PCVT/PCAVT 状态线
PCAVT ≠ 固定 q 向量
PCAVT ≠ 预先物化的全部事件区间
```

## 二、冻结的基础研究边界

### 1. Score 口径

```text
percentile_window_W = 120
```

评分必须使用同一证券、同一指标的严格过去 120 个 valid 且 finite 的 observation：

```text
当前 observation 不进入参考集合
tie method = midrank
score = 1 - percentile
```

禁止计算 W250 或 W500，禁止使用横截面排名替代 strict-past percentile。

### 2. A 维度

A 层只包含：

```text
A1_LogBodyCenterToMACloudCenter_5_60
A2_BodyCenterOutsideMACloudRate20_5_60
```

A2b 不重新进入研究。

A 层计算为：

```text
A_Score_W120 = mean(A1_Score_W120, A2_Score_W120)
A_Min_W120   = min(A1_Score_W120, A2_Score_W120)
```

A1、A2 权重均为 0.5。只有两个组件均 eligible、valid 且 score finite 时，A Score 和 A Min 才能生成。

禁止单组件 fallback、填零、前向填充、缩短窗口或忽略缺失组件。

### 3. 动态 q 参数域

每个被选择维度可以独立指定 q：

```text
qD ∈ {0.10, 0.15, 0.20, 0.25}
```

建议在数据 contract 中使用整数基点：

```text
q_bp ∈ {1000, 1500, 2000, 2500}
q = q_bp / 10000
```

未选择维度不参与联合条件，也不得被赋予默认 q。

### 4. weak dimension gate

```text
weak_delta = 0.10
```

对被选择维度 D：

```text
dimension_active(D,t)
=
eligible_dimension
AND validity_status = valid
AND score_dimension >= 1 - qD
AND score_dimension_min >= 1 - qD - 0.10
```

浮点比较统一为：

```text
score >= threshold - 1e-12
```

weak_delta 在首版协议中固定，不作为用户参数。

### 5. 联合 raw state

设用户选择的维度集合为 S：

```text
raw_state(t)
=
AND(
  dimension_active(D,t)
  for D in S
)
```

必须先检查所有被选择维度是否完整可计算，再执行 AND。

如果任一被选择维度为 missing、unknown、diagnostic_required、blocked、not eligible 或 score non-finite，则：

```text
raw_state = NULL
```

并保留聚合后的 validity 和 reason codes。

联合 validity 优先级为：

```text
blocked
> diagnostic_required
> unknown
> valid
```

不得因为某个维度已经为 false，就通过短路计算隐藏其他被选择维度的异常。

### 6. confirmation_k 参数域

```text
confirmation_k 类型：整数
允许集合：{2,3,4,5,6,7}
最小值：2
最大值：7
```

非法值必须在请求校验阶段直接拒绝，包括：

```text
K=1
K=8
K=3.5
K="5"
K=NULL
```

不得自动取整、截断或使用默认值替代。

K=1 的数学语义仍应在算法说明和 synthetic test 中定义：

```text
raw_state=true
→ 当日立即确认
```

但 K=1 不属于 dynamic-state-v1 的正式研究参数域。

### 7. 连续确认和区间规则

连续性按同一证券的 `observation_sequence` 相邻关系计算，不能跳过缺失行。

```text
valid raw=true  → streak + 1
valid raw=false → streak = 0
non-ready       → streak = NULL，并中断此前 streak
```

确认发生在连续 raw=true 的第 K 个 observation：

```text
confirmation_date = streak 的第 K 日
confirmed_start_date = confirmation_date
```

不回填前 K−1 日。

区间退出规则：

```text
第一个 valid raw=false
或第一个 unknown
或第一个 diagnostic_required
或第一个 blocked
或第一个 expected observation missing
→ 区间结束在此前最后一个 confirmed true observation
```

首版不使用：

```text
d=2
g=1
退出延迟
gap tolerance
区间自动合并
```

输入结束时仍处于 confirmed 状态的区间标记为 open/right-censored。

### 8. 零事件行为

合法参数请求可能没有任何 confirmed interval。

此时运行仍然应正常完成：

```text
run_status = completed
confirmed_interval_count = 0
```

逐日维度状态表和联合状态表仍必须完整输出，区间表是合法零行表。

只有在确认：

```text
存在足够 evaluable observations
raw_state 对 q 有响应
max_raw_streak < K
上游 availability 与下游 evaluability 一致
```

后，零事件才可以被认定为合理科学结果。

全 NULL、全 false、参数无响应或上游 valid 很多但下游 evaluable 接近零，不能简单解释为“没有事件”。

## 三、数据物化原则

长期物化的数据只有 canonical PCAVT Score release。

动态 q/K 联合状态和区间只在以下情况下物化：

```text
正式研究运行
需要复现的请求
用户明确要求保存的请求
```

普通查询由 evaluator 即时计算，不默认落库。

不得预先物化全部维度/q/K 组合，也不得把动态结果写回 Score release。Canonical Score release 是所有动态请求唯一允许读取的评分事实输入。

## 四、R2A 任务路线

### R2A-T01：Canonical PCAVT Score release

目标：

```text
冻结 A-layer W120 Score contract
物化不可变 canonical PCAVT Score release
```

P/C/V/T 优先复用已接受的 R0-T05 W120 Score artifacts，但必须独立验证：

```text
schema
primary keys
component definitions
row counts
security coverage
date coverage
score semantics
sample recomputation
artifact hashes
```

A Score 必须由 accepted A1/A2 raw observations 在 R2A 中新计算。

Canonical release 至少应包含：

```text
securities
trading_sessions
security_observation_spine
dimension_definitions
dimension_components
daily_component_scores
daily_dimension_scores
```

每个 expected security-observation 行必须恰好存在 P/C/A/V/T 五个维度记录。无法评分时保留显式 NULL 和 validity，不得直接缺行。

T01 不计算 q、raw state、K、confirmed state 或 interval。

T01 formal 被接受后，应立即向另一个项目发布：

```text
score_release_id
DuckDB 路径或正式分发位置
schema
manifest
validation receipt
结果分析报告
数据使用边界
```

### R2A-T02：动态状态协议冻结

冻结：

```text
dynamic request schema
selected dimensions
q_by_dimension
confirmation_k ∈ {2,3,4,5,6,7}
complete-case joint validity
raw state AND
streak reset
confirmation date
interval start/end
termination reasons
zero-event behavior
ID/hash protocol
```

T02 只冻结协议，不选择唯一 q/K 组合。

### R2A-T03：Dynamic evaluator 实现

实现参数化 evaluator：

```text
Score release
→ dimension active
→ joint raw state
→ K confirmation
→ confirmed interval
```

完成 synthetic、边界和属性测试，包括：

```text
q 单调性
增加维度约束的集合单调性
K 响应
未选维度隔离
no-backfill
invalid interruption
无 d/g
零事件
K=1 数学边界测试
非法 K 请求拒绝
```

### R2A-T04：真实数据参数响应与结果合理性审核

在真实 Score release 上选择有代表性的维度、q 和 K 请求进行研究运行。

审核：

```text
joint evaluability
raw coverage
max streak
confirmed coverage
interval count
duration
security breadth
year stability
q response
K response
维度增加后的收缩关系
人工图形抽样
```

该阶段不是寻找唯一最佳参数，而是确认动态协议在允许参数域内响应合理、不发生退化。

### R2A-T05：CA q20 退出机制与跨 q 结构分解

T05 的唯一问题是：已确认 CA 区间为何终止、终止时 C/A 距离门槛多远、是否在同一 q 的后续状态中快速重入，以及 q20 在 q10/q15/q25 严格嵌套梯度中的核心、外壳、边界和碎片结构。q20 固定为研究锚点 `q=0.20`，但 `q_selection_status=not_selected`，不注册 canonical dynamic request，不选择最佳 q。

T05 必须在 accepted v1 interval 语义上工作，不增加 d/g、退出延迟、hysteresis、gap tolerance 或自动合并。输出包括：

```text
raw_false / quality_or_availability_termination / input_end_open_right_censored
C-only / A-only / CA-both raw-false decomposition
signed C/A endpoint threshold margins and gate-failure classes
observation_sequence-based raw/confirmed quick re-entry
q10 -> q15 -> q20 -> q25 unique parent-child interval mapping
mutually exclusive daily Q10/Q15/Q20/Q25 hierarchy identities
```

正式 T05 将来可以生成 request identity、input manifest、run summary、validation receipt、result analysis 和 compact review tables；逐区间 inventory、逐日身份和 mapping 只能保存在 repository-local git-ignored detail storage。本 implementation PR 只包含 candidate code、contract、schema、synthetic tests 和 runner，不能执行真实 formal run、读取真实 Score 或创建 DONE。

### R2A-T06：CA 连续失效退出确认与迟滞规则选择

T06 在 accepted `[C,A]`、K=5 daily state facts 上比较 M=1/2/3 连续 valid raw-false 退出确认。它只新增退出生命周期，不修改 accepted v1 raw/confirmed state，不读取价格、收益或未来路径，也不预选 winner。强制验收包括：

```text
M=1 精确复现 accepted v1 valid raw-false exit
recognition lag 分别为 0/1/2 observation
quality interruption 不被 M 延后
accepted daily facts 逐行不变
跨 q 与 M 集合关系一致
逐 observation replay 与批量计算一致
缺失 observation 不被跳过
不同执行并行度结果一致
```

对每个相同 M，candidate lifecycle 还必须满足 `active_or_pending(q10) ⊆ active_or_pending(q15) ⊆ active_or_pending(q20) ⊆ active_or_pending(q25)`，其中 active-or-pending 仅含 `ACTIVE` 与 `EXIT_PENDING`。每个 stricter-q episode 必须唯一映射到一个 looser-q parent episode，禁止 unmapped、跨 parent 或多对多 mapping；该检查与 raw/confirmed input nesting 分开报告。

未来价格路径与 release onset/direction/intensity 标签不属于 T06；如后续需要，必须单独立项并重新通过 PIT/no-lookahead 设计审核。T06 implementation SHA `2710d282fadcb998b80b9a482a5d55a4facc775a` 与 formal-execution SHA `462dc56271fe09e5b116dacc2422a342556ef1a0` 已通过 owner review。当前只提交 authorization-contract transition，状态为 `formal_run_authorized_pending_execution`；该新 commit 获 owner 批准前，不得生成权威 manifest/authorization、创建 attempt marker、读取真实 Score、执行 formal run、生成正式结果或创建 DONE。

### R2A-T07：版本注册与消费者契约冻结

注册：

```text
score_release_id
dimension_definition_version
dynamic_protocol_version
engine version
schema version
artifact hashes
```

不注册唯一 canonical state version，也不把某个 q/K 请求提升为全局状态结论。

注册 accepted Score release、T03 evaluator/protocol identity、T05 result package schema、版本和消费者契约；不把 q20 提升为 canonical，也不在未完成 T05/T06 验收前发布冻结状态。

### R2A-T08：阶段验收与 R3 handoff

只有在：

```text
Score release 通过
动态协议通过
真实参数响应合理
T05 exit decomposition、T06 consecutive-failure exit confirmation 和独立结果分析均通过
独立结果分析通过
```

后，才能形成新的 R3 handoff。

新的 handoff 应提供动态状态查询接口，而不是单一固定 PCT/PCVT/PCAVT 事件表。

## 五、正式验收原则

完成 runner 和 validator 不代表 task 完成。

### 1. 所有 formal 任务共同要求

任何 formal 运行后，必须立即读取实际 artifacts，完成：

```text
实际 artifact 和结果表检查
关键字段独立复算
结果合理性分析
异常扫描
独立 result_analysis.md
```

### 2. Score release formal，包括 R2A-T01

必须完成：

```text
strict-past percentile 样本复算
component Score 复算
dimension mean/min 复算
P/C/V/T source reconciliation
spine coverage
五维 cardinality
validity 和 availability reconciliation
全零
全一
全 NULL
数量级突变
score domain 和组件数量异常
```

R2A-T01 不执行也不要求 q response、K response、streak、interval 或集合层级分析。

### 3. Dynamic evaluation formal，包括 R2A-T04、R2A-T05 与 R2A-T06

除共同要求外，T04/T05 必须完成：

```text
q response
K response
增加 selected dimensions 后的集合收缩
streak/confirmation/interval 关系
invalid interruption
zero-event 合理性
未选维度隔离
```

T06 另需完成 M=1 baseline reconciliation、trigger/recognition/cancellation/quality termination、逐 observation replay 与 batch 等价、并行一致和 M 集合关系的独立复算。T06 不得反向修改 T05 accepted daily state 或 interval 事实。

如果发生全零、全一、全 NULL、数量级突变、与上游 availability 不一致，或属于当前任务验收范围的复算/响应/集合关系异常，必须停止下游推进。异常未解释前，不得标记 completed，不得推进 README gate，不得发布数据。
