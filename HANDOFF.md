# R2A / PCAVT 研究交接

> 本文写给一个完全没有此前会话上下文的新会话。
>
> 阅读完本文后，应能准确知道：当前研究在做什么、EXP-A 已完成什么、R2A 为什么存在、现在停在哪里、下一步应做什么，以及哪些错误绝对不能重犯。

## 0. 当前状态快照

```text
repository: benzemaer/convergence-research
local_repository: D:\Code\convergence-research
current_branch: codex/r2a-pcavt-research
remote_branch: origin/codex/r2a-pcavt-research
base_main_sha_before_HANDOFF_commit: 7e6da62235d823b4258d45f583d2918820f92496
worktree_status_at_handoff: clean
open_PR_for_R2A: none
R2A_T01_started: false
A_layer_score_contract_defined: false
A_layer_registered: false
PCAVT_created: false
```

`HANDOFF.md` 是 R2A 分支上的纯文档提交。创建本文件不表示 `R2A-T01` 已经启动，也不授权真实数据物化、状态计算或创建 PCAVT。

主分支在建立 R2A 分支时的 HEAD 为：

```text
7e6da62235d823b4258d45f583d2918820f92496
```

该提交是 cleanup PR #107 的 merge commit；它位于 EXP-A merge commit 之后。

---

## 1. 我们正在做什么

项目原有研究已经完成到 `R2-T08`，并冻结过一套旧的收敛状态版本与 R3 handoff。

之后完成了独立的 `EXP-A` sidecar 研究，目标是寻找一个新的“价格—均线附件/贴合”维度 A。研究最终接受：

```text
A1: A1_LogBodyCenterToMACloudCenter_5_60
A2: A2_BodyCenterOutsideMACloudRate20_5_60
```

并按用户研究范围决策排除：

```text
A2b: A2b_BodyToMACloudGapMean20_5_60
```

现在准备启动一个新的完整研究阶段：

```text
stage: R2A
research_object: PCAVT
first_task: R2A-T01
```

R2A 的最终目的与旧 R2 类似：从参数/协议研究、状态扫描、用户决策、正式物化、无前视回放、版本冻结，最终形成新的 R3 handoff。

但 R2A 的研究对象是加入 A 层后的新架构 PCAVT，而不是对旧 R2-T08 结果做小修补。

### 1.1 R2A 的核心边界

R2A 是一次独立的 full PCAVT restudy：

```text
R2A_inherits_R2_T08_frozen_results: false
R2A_inherits_R2_T08_state_versions: false
R2A_inherits_R2_T08_parameter_decisions: false
R2A_inherits_R2_T08_R3_handoff: false
```

允许参考或复用旧 R2/R0 已验证的代码模式、原始数据接口和成熟的严格过去分位算法。

不允许把旧 R2-T08 的以下内容直接当成 R2A 结论：

- frozen state versions；
- K/d/g 参数；
- q 向量；
- canonical daily state；
- event-zone interval；
- version registry；
- R3 handoff。

“可以复用工程资产”与“继承旧研究结论”是两件不同的事，不能混淆。

---

## 2. 已经完成了什么

## 2.1 EXP-A 已正式关闭

EXP-A 研究已完成到已接受的 `EXP-A04`。

关键提交：

```text
EXP-A04 formal result commit:
11a99cb8a34814a0f3412d8012fdc0130074e436

EXP-A closure commit:
96d7da4c45d87089063521fd690f66a8a53c9a4b

EXP-A closure Quality:
29612587939 / success
```

PR #106 已 merge：

```text
PR: #106
merge commit: baf37f64eb59cf0a6fb96e2a42e23b25f0e8662a
```

随后 PR #107 只修复了一个既有 JSON 文件末尾多余换行：

```text
PR: #107
merge commit: 7e6da62235d823b4258d45f583d2918820f92496
```

PR #107 没有改变任何研究语义、配置字段、artifact 或运行行为。

## 2.2 EXP-A 最终 handoff 已提交

路径：

```text
data/generated/sidecar/exp_a/exp_a_final_research_handoff.json
```

该 handoff 冻结了：

```text
EXP-A status: completed_accepted
completed through: EXP-A04
accepted A raw components: [A1, A2]
excluded A raw components: [A2b]
A-layer Score contract defined: false
A-layer Score contract owner: R2A-T01
next stage: R2A
next task: R2A-T01
```

A2b 的排除语义必须保持为：

```text
user_research_scope_decision_after_A04
```

不得改写为：

```text
statistically redundant
invalid indicator
proven no increment
hard collision
```

EXP-A04 证明的是 24 个 A-vs-PCVT raw pair 中没有达到预注册 hard-collision gate；它没有证明 A2b 完全无效。A2b 是因为预期增量较低、与 P/C 关系最强且研究资源需要收缩，被用户直接排除。

## 2.3 EXP-A 的关键科学结论

### A2

A2 是三个候选中对 P/C/T/V 最低相关的候选，跨层增量信号最强。

它测量的是过去 20 日价格实体位于均线云外的频率，属于 persistence topology，而不是简单的高波动或低参与度代理。

### A1

A1 是瞬时 attachment anchor，测量当前实体中心与均线云中心的距离。

A1 与 P/C/T 有中等且较均衡的关系，但低尾身份仍明显不同，因此保留为独立的瞬时机制视角。

### A2b

A2b 与 P2、C1、C2、P1 的相关性最高，较多继承 P/C 尺度信息。它未被证明统计冗余，但用户决定不再投入后续研究资源。

最终组合为：

```text
A-layer raw components: A1 + A2
```

机制解释：

```text
A1 = instantaneous attachment
A2 = persistence topology
```

---

## 3. 本地 artifact 迁移已完成

原有三个待删除实体目录中的本地文件已迁入主仓库的 ignored archive。

归档根目录：

```text
D:\Code\convergence-research\data\external\local_research_archive\exp_a_to_r2a
```

迁移 manifest：

```text
D:\Code\convergence-research\data\external\local_research_archive\exp_a_to_r2a\migration-control\migration_manifest.json
```

manifest SHA256：

```text
7d0dbea61387d3bfdf02a9a3ce80429038418b22caa27c1a074b84599805d407
```

迁移 inventory：

```text
shared inputs: 164 files / 635,418,087 bytes
EXP-C01 inputs: 8 files / 4,488 bytes
EXP-C01 local-only: 10 files / 4,929 bytes
inventory comparison: passed
```

当前策略：

```text
archive inputs: retained
main worktree: retained
historical A01/A04 old-path replay: closed
```

### 3.1 重要后果

不要再依赖以下旧绝对路径或兼容 junction：

```text
D:\Code\convergence-research-inputs
D:\Code\convergence-research-exp-c01-inputs
D:\Code\convergence-research-exp-c01
```

旧历史 manifest 保持不可变，即使其中记录的绝对路径已经不再用于直接重放，也不得编辑旧 manifest 来适配新位置。

R2A 必须创建新的 authorized input manifest，并记录当前 archive 中实际使用文件的路径、SHA256、表名、row count、security count 和日期范围。

migration manifest、inventory CSV、大型 DuckDB、外部 authorized manifest 和 failure package 都是 local-only，不得提交 Git。

---

## 4. 当前停在哪里

当前没有技术阻塞，也没有正在运行的 formal task。

准确状态：

```text
branch: codex/r2a-pcavt-research
remote branch: established
branch base before HANDOFF.md: 7e6da62235d823b4258d45f583d2918820f92496
worktree: clean
R2A PR: not created
R2A-T01: not started
A-layer Score contract: not defined
canonical PCAVT Score artifact: not materialized
A-layer: not registered
PCAVT: not created
```

当前暂停点是 **R2A-T01 启动前的协议设计边界**。

新会话不能直接运行数据。必须先把 R2A-T01 的职责、输入绑定、Score contract、输出 contract、validator 和 formal gate 定义清楚。

---

## 5. R2A-T01 的唯一目标

R2A-T01 应当完成两件紧密相关、但必须按顺序执行的工作：

1. 冻结 A-layer W120 Score contract；
2. 在该 contract 通过 implementation review 后，物化新的 canonical PCAVT Score artifact。

R2A-T01 不研究 q、确认天数或区间。

### 5.1 已达成一致的 A-layer Score contract 方向

Active components：

```text
A1_LogBodyCenterToMACloudCenter_5_60
A2_BodyCenterOutsideMACloudRate20_5_60
```

唯一窗口：

```text
W = 120
```

禁止计算：

```text
W = 250
W = 500
```

对同一 `security_id`、同一 `indicator_id`，当前 observation 的参考集合是：

```text
当前 observation_sequence 之前
最近 120 个 validity_status=valid
且 raw_value finite 的 observation
```

当前值不进入参考集合。

Tie method：

```text
midrank
```

设过去 120 个 eligible values 中：

```text
N_less  = raw_value < current raw_value 的数量
N_equal = raw_value = current raw_value 的数量
```

则：

```text
percentile = (N_less + 0.5 * N_equal) / 120
score      = 1 - percentile
```

两个 raw indicator 都是越低越贴合，因此 Score 越高表示 attachment 越强。

组件分数：

```text
A1_Score_W120
A2_Score_W120
```

Layer 分数：

```text
A_Score_W120 = mean(A1_Score_W120, A2_Score_W120)
A_Min_W120   = min(A1_Score_W120, A2_Score_W120)
```

权重固定：

```text
A1 = 0.5
A2 = 0.5
```

只有 A1、A2 均 eligible 时，A-layer Score 和 A-Min 才能生成。禁止单组件 fallback、填零、前向填充、缩短窗口或忽略缺失组件。

### 5.2 Score 与 State 必须分离

R2A-T01 只定义连续 Score，不定义：

```text
q threshold
raw state
confirmation streak
confirmed state
interval
exit rule
PCAVT state version
```

W=120 决定分数如何计算。

q、连续天数和区间规则决定如何从分数生成状态。

这两层绝对不能在同一个 contract 中混为一谈。

### 5.3 R2A-T01 的最终数据目标

目标是得到 800 只股票、W=120 条件下新的 canonical PCAVT 各维度连续分数：

```text
P Score
C Score
A Score
V Score
T Score
```

新 artifact 必须拥有 R2A 自己的：

```text
run_id
input manifest
input hashes
schema
logical table names
primary keys
row counts
security count
date range
validator result
artifact manifest
```

不能把旧 R2-T08 state outputs 改名后当成新 PCAVT Score artifact。

---

## 6. R2A-T01 尚需明确的工程决策

以下问题尚未正式冻结，新会话必须在写 Codex 指令前逐项决策。

## 6.1 P/C/V/T Score 的来源

需要在两种方案中作出明确选择：

### 方案 A：复用已接受的 R0-T05 W120 Score rows

前提：

- independently validate bytes、schema、semantic hashes、row counts；
- 只取 W120；
- 不消费旧 R2 状态或 interval；
- 在 R2A 中创建新的统一 PCAVT binding 和 artifact identity。

优点：避免重复计算成熟的 P/C/V/T Score。

### 方案 B：从 authoritative raw metrics 重新计算 P/C/V/T W120 Score

优点：所有五层在同一次 R2A materialization 中生成，lineage 更统一。

缺点：计算成本和实现范围更大，也可能无意义地重做已验证逻辑。

当前推荐倾向：

> 可以复用已接受的 P/C/V/T W120 Score artifact，但必须在 R2A-T01 中独立验证并重新建立 canonical PCAVT Score interface；A Score 必须由 accepted A1/A2 raw 新计算。不要继承任何 R2-T08 state result。

这只是推荐，不是已冻结结论。

## 6.2 PCAVT 维度顺序和命名

用户当前目标名称为：

```text
PCAVT
```

不要随意写成：

```text
PCATV
PCTAV
PCVT+A
```

旧代码和旧 artifact 中 dimension order、变量命名与缩写并不总是直观一致。R2A-T01/T02 必须在 registry 中显式声明：

```text
dimension IDs
dimension order
component registry
output field names
state nesting order（后续 T02）
```

绝对不能只根据旧变量名推断顺序。

## 6.3 Formal 800-security gate 与 synthetic tests

正式物化必须要求：

```text
security_count = 800
calendar years = 2016..2026
```

但不要把“必须恰好 800”硬编码到通用单序列 Score 函数，导致小型 synthetic unit tests 无法运行。

正确分层：

```text
generic score engine:
可处理任意 synthetic security count

formal runner / formal validator:
强制 security_count = 800
```

---

## 7. R2A 后续建议路线

下面是建议路线，与旧 R2 的职责结构同构，但所有 task 都使用独立的 `R2A-*` identity。

### R2A-T01

```text
A-layer W120 Score contract
canonical PCAVT Score materialization
```

### R2A-T02

```text
PCAVT state / event-zone protocol freeze
```

在这一阶段才定义：

- q vector；
- A layer 的 mean/min gate；
- V/T 是否参与 raw gate；
- dimension order / nesting；
- confirmation streak；
- interval start/end；
- validity propagation。

### R2A-T03

```text
candidate parameter scan
event-zone geometry audit
manual chart sampling
```

检查：

- coverage；
- interval count；
- duration；
- fragmentation；
- security breadth；
- year stability；
- boundary cases；
- 人工图形合理性。

### R2A-T04

```text
hard gate
Pareto comparison
user decision
freeze plan
```

### R2A-T05

```text
canonical daily state / event zone / membership materialization
```

### R2A-T06

```text
no-lookahead replay
consistency acceptance
```

### R2A-T07

```text
state version registry
final freeze manifest
```

### R2A-T08

```text
R2A stage acceptance
new R3 handoff
```

只有 R2A-T08 被正式接受后，新的 PCAVT handoff 才能取代旧 R2-T08 handoff，成为新的 R3 入口。

旧 R2-T08 artifacts 不删除、不改写，只在新 handoff 中明确 superseded relationship。

---

## 8. 当前参数意图，但尚未冻结

用户当前研究意图：

```text
W = 120
qP = 0.2
qC = 0.2
qA = 0.2
kdg parameters: 暂不使用
raw=true 连续 >= 5 天：初步确认区间方案
```

这些内容需要正确理解。

## 8.1 q 的方向

当前 Score 定义为 `1 - percentile`，因此若 q=0.2 表示最低 20% raw tail，则通常对应：

```text
Score >= 0.8
```

但这个映射必须在 R2A-T02 contract 中正式写出，不能仅靠口头约定。

## 8.2 qV 与 qT 未决

目前只提出了：

```text
qP, qC, qA
```

尚未明确：

```text
qV
qT
V/T 是否参与 raw gate
```

不能在实现中默认为旧 R2 值，也不能静默排除 V/T。

## 8.3 “不使用 K”与“连续 5 天”不能自相矛盾

即使不沿用旧参数名 K，连续 5 天本质上仍是一个确认 streak 参数。

建议后续使用明确字段：

```text
confirmation_streak_observations = 5
```

不要一边声明“不使用 K”，一边在代码中硬编码 `>=5` 而不进入 contract。

## 8.4 五天方案只是候选

“raw=true 连续 >=5 天视为收敛区间”目前需要人工筛选验证。

它不是已冻结规则。R2A-T03 必须通过统计分布和图形抽样验证，再由 R2A-T04 作用户决策。

---

## 9. 新会话的第一步

新会话开始后，先做只读核对，不要直接写代码。

建议核对：

```powershell
cd D:\Code\convergence-research

git status --short
git branch --show-current
git rev-parse HEAD
git fetch origin --prune
git rev-parse origin/codex/r2a-pcavt-research
git log --oneline --decorate -5
```

确认：

```text
branch = codex/r2a-pcavt-research
local branch = remote branch
worktree clean
base main ancestor includes 7e6da62235d823b4258d45f583d2918820f92496
no R2A PR exists
```

然后读取：

```text
HANDOFF.md
data/generated/sidecar/exp_a/exp_a_final_research_handoff.json
docs/experiments/sidecar/README.md
R0-T05 strict-past Score contract/materializer
R2-T01..R2-T08 task route and accepted artifacts
```

下一条真正的 Codex 指令应只做：

```text
R2A-T01 protocol / implementation planning
```

推荐先输出完整的 R2A-T01 plan，明确输入、输出、复用边界、formal gates 和任务拆分，再决定是否立即实现。

不要在没有计划审阅的情况下直接运行真实数据。

---

## 10. 绝对不要再踩的坑

## 10.1 不要过度治理

此前出现过为很小风险提出大规模 manifest lineage 扩展、十项运行时 hash 等方案，用户明确认为这是矫枉过正。

原则：

```text
只为真实风险增加门禁
不为形式完整性堆叠机制
不重复已有独立验证
不扩大用户明确限定的 scope
```

新会话不要重新提出已经撤回的：

```text
manifest lineage expansion
ten-input runtime hashing
preliminary manifest architecture
无必要的多层 validator
```

## 10.2 不要把 Score 与 State 混在一起

错误做法：

```text
在 R2A-T01 同时定义 W、q、五天确认和区间结束
```

正确做法：

```text
R2A-T01: Score
R2A-T02+: State / confirmation / interval
```

## 10.3 不要继承 R2-T08 研究结论

可以参考旧代码，但不能默认复用旧：

```text
K3
d2/g1
qT/qV
state versions
R3 handoff
```

R2A 是 full restudy，不是旧版本加一列 A。

## 10.4 不要重新研究 A2b

A2b 已由用户直接排除。

禁止：

```text
A2b challenger test
A2-vs-A2b dominance gate
A2b score materialization
A1+A2b / A2+A2b combination search
```

同时禁止虚构结论“已证明 A2b 统计冗余”。

## 10.5 不要在 EXP-A sidecar 中补做 Score contract

EXP-A 已关闭。

A-layer Score contract 的 owner 是：

```text
R2A-T01
```

不要再创建 EXP-A05 或在 `src/sidecar/exp_a*` 下继续扩展正式 Score 研究。

## 10.6 不要计算 W250/W500

A-layer 已定调：

```text
W = 120 only
```

不要因为旧 R0-T05 支持 120/250/500，就自动继承三个窗口。

## 10.7 不要使用横截面分位替代 strict-past percentile

A-layer Score 口径是：

```text
same security
same indicator
last 120 valid finite historical observations
current excluded
midrank
score = 1 - percentile
```

禁止：

```text
cross-sectional rank
current included
calendar-day window
last 120 physical rows
future rows
dense rank
random tie breaking
```

## 10.8 不要把 invalid row 放入历史窗口

当前 row invalid 时：

- 当前不生成 score；
- 该 row 也不得进入后续 valid history。

不能把 unknown/diagnostic/blocked 当成低分、零分或有效历史。

## 10.9 不要复用旧 absolute path

历史 A01/A04 旧路径回放已关闭。

不要假设旧目录或 junction 仍可用。

R2A 必须用 archive 的实际路径创建新 manifest。不要编辑旧历史 manifest。

## 10.10 不要提交大型本地 artifacts

禁止提交：

```text
*.duckdb
*.parquet
data/external/**
migration manifest
inventory CSV
external authorized manifest
failure package
logs
```

Git 只提交 compact contract、schema、code、tests、evidence summary 和小型 result package。

## 10.11 不要混用阶段/门禁标识符

R2-T08 历史结果中已经存在类似 `R2A01...R2A08` 的 gate ID。

新阶段 task ID 必须使用：

```text
R2A-T01
R2A-T02
...
```

新 gate 建议使用：

```text
R2A-T01-G01
R2A-T01-G02
...
```

不要创建裸 `R2A01` task，避免与历史 gate 冲突。

## 10.12 不要自动推进到 PR、formal 或下一阶段

当前没有 R2A PR。

任何 implementation 完成后都应停在 implementation review；formal 必须经过独立授权。

任何 formal result 完成后都应停在 formal-result review；不得自动接受、自动注册 A-layer 或自动创建 PCAVT。

---

## 11. 重要引用

### Git / PR

```text
EXP-A04 result commit:
11a99cb8a34814a0f3412d8012fdc0130074e436

EXP-A closure commit:
96d7da4c45d87089063521fd690f66a8a53c9a4b

PR #106 merge:
baf37f64eb59cf0a6fb96e2a42e23b25f0e8662a

PR #107 cleanup merge / R2A base main:
7e6da62235d823b4258d45f583d2918820f92496
```

### EXP-A handoff

```text
data/generated/sidecar/exp_a/exp_a_final_research_handoff.json
```

### Local archive

```text
D:\Code\convergence-research\data\external\local_research_archive\exp_a_to_r2a
```

### Migration manifest

```text
D:\Code\convergence-research\data\external\local_research_archive\exp_a_to_r2a\migration-control\migration_manifest.json
SHA256: 7d0dbea61387d3bfdf02a9a3ce80429038418b22caa27c1a074b84599805d407
```

---

## 12. 最简接手结论

```text
EXP-A 已结束。
A1+A2 已选定。
A2b 已按研究范围排除。
A-layer Score 尚未定义。
R2A 是 PCAVT 的独立完整重研，不继承 R2-T08 结果。
当前分支已建立并推送，但没有 PR，R2A-T01 尚未开始。
下一步先设计并审阅 R2A-T01，再冻结 W120 A Score contract，最后物化新的 canonical PCAVT Scores。
不要直接跑数据，不要混入 q/五天区间，不要重开 A2b，不要依赖旧绝对路径。
```
