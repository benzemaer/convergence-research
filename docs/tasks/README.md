# 任务记录与阶段索引

本目录保存可审核任务契约，并维护当前阶段任务索引。任务记录不是决策记录、运行授权、
数据 manifest 或研究证据，不得替代 G0–G7 门禁。

每个任务必须明确目标、非目标、输入、输出、验收标准、失败状态和回退方式。任务关闭后
仍保留记录；实质变更创建新版本，不覆盖原记录。

## 使用规则

- 每进入一个新阶段，先明确阶段目标、输入、输出、非目标和完成标准。
- 每个 task 都必须挂在阶段索引下。
- 每个 PR 只实现一个 task。
- task 完成后更新本索引状态，不在 PR 内临时扩大范围。
- 当只剩标题级 task、或下一步将引入新的数据源/运行/研究范围时，先确认下一个 PR 边界，再继续实现。

## 当前阶段

```text
current_stage: R1
current_task: R1-T06 层间同期留存、关联 Lift 与嵌套增量
next_planned_task: R1-T07 S_PCT/S_PCVT 预注册配置的同步性零模型
R1-T04 completed via PR #80
R1-T05 completed via PR #81
R1-T05_allowed_to_start: true
R1-T06_allowed_to_start: true
R1-T07_allowed_to_start: false
R1-T08_allowed_to_start: false
R2_allowed_to_start: false
```

## 命名与路径规则

从 D3-T09 / R0 开始，task、branch、task 文档和 PR 标题采用以下规范：

```text
branch: codex/d3-t09-r-stage-engineering-layout-task-as-step-governance
task file path: docs/tasks/D3-T09_R阶段工程分层与Task-as-Step规范收敛.md
task H1: # D3-T09 R阶段工程分层与 Task-as-Step 规范收敛
PR title: [codex] D3-T09 R阶段工程分层与 Task-as-Step 规范收敛
```

branch 使用英文 slug。task 文件路径使用中文任务标题，可保留必要英文术语，例如 `Task-as-Step`、`PCVT`、`registry`。task H1 使用中文标题。PR 标题使用 `[codex] 阶段-任务号 中文标题`。

不批量重命名历史 task 文件。历史英文或中英混排 task 文件继续保留，除非未来单独开 rename-only PR。`docs/tasks/` 继续平铺管理，不拆成 `d0/`、`d1/`、`d2/`、`d3/`、`r0/` 等子目录。

跨阶段治理 task 使用 `GOV-Txx`。GOV task 不改变 current_stage/current_task，只有直接推进研究阶段的 task 才能修改 current_task。

## 跨阶段研究治理

- `GOV-T01` R1-R6 formal 实验结果包、异常门禁与独立科学审阅治理：completed via this PR。该治理 task 不改变当前 R1 task 指针。draft PR #77 is superseded by PR #78 / merge commit `8694cba4ddbd5a18e43ab18454dfc19cfb9903cd`；PR #77 不合并、不 rebase、不 cherry-pick，其结果不得作为当前 evidence、参数选择依据或后续 formal input。

历史索引：D2-T01 完成后曾推进到 `current_task: D2-T02`、
`next_planned_task: D2-T03`；D2-T02 完成本 PR 后当前索引继续推进到 D2-T03 / D2-T04。
D2-T02 完成时的任务队列仍为：`D2-T03` 原始行情价格落账：planned。
D2-T03 进入阻塞门禁时的任务队列仍为：
`D2-T04` 复权因子与 `factor_as_of_time` 契约：planned。
D2-T04 进入阻塞门禁时的任务队列仍为：
`D2-T05` 连续研究价格构建与反推校验：planned。
D2-T05 进入阻塞门禁时的任务队列仍为：
`D2-T06` 跳空归因与价格质量标记：planned。
D2-T06 contract-only PR 合并时的任务队列仍为：
`D2-T06` 候选行情快照探针：contract-only pending separately authorized probe execution via PR #30。
D2-T06 候选探针执行前的任务队列仍为：
`D2-T07` 跳空归因与价格质量标记：planned。
D2-T07 进入契约门禁前的任务队列仍为：
`D2-T08` D2 阶段验收与 D3 交接：planned。
D2-T08 完成后曾进入 D3 contract queue；D2 formal materialization 未完成前，
`D3-T07` remained blocked pending D2 formal materialization，`R0` remained blocked。
D3-T07 was later unblocked for research candidate generation by D2-T20 evidence-verified candidate acceptance; formal data_version remains blocked.
D3-T06 发布门禁 PR 合并时的阶段索引仍为：
```text
current_stage: D3
current_task: D3-T06
next_planned_task: D3-T07
```
D3-T07 candidate observation PR 合并前的阶段索引仍为：
```text
current_stage: D3
current_task: D3-T07 candidate daily observation from D2-T20
next_planned_task: D3-T08 PCVT input readiness and feature-base quality checks
```
D3-T07 PR 合并前的任务队列曾包含：
`D3-T07` 从 D2-T20 evidence-verified candidate 生成标准日频观测表：in_progress；
`D3-T08` PCVT input readiness and feature-base quality checks：planned。
R0 remains blocked until D3 output is accepted by later gates.
R0 历史状态快照：状态：blocked until D3 output is accepted by later gates。
D3-T08 research dataset registry PR 合并前的阶段索引仍为：
```text
current_stage: D3
current_task: D3-T08 research dataset registry and route-agnostic base quality
next_planned_task: R0-T01 PCVT candidate indicator specification
```
D3-T08 research dataset registry PR 合并前的任务队列曾包含：
`D3-T08` 研究基础数据集 registry 与路线无关质量审计：in_progress。
formal data_version remains blocked until explicit release gate.
R0 state remains blocked until PCVT candidate indicators and later gates are accepted.
D3-T08 合并后进入 D3-T09 governance convergence；R0 仍未开始，R0-T01 将在 D3-T09 合并后单独开启。

## G0：样本宇宙与时间边界

状态：completed

- `G0-T01` 官方中证 800 成分证据获取与审核：completed
- `G0-T02` 原始快照受控交付与独立哈希复核：completed
- `G0-T03` 配置落账 verified / approved / eligible_for_d0：completed via PR #5

完成标准：

- 官方成分证据完成获取；
- 独立审核完成原始字节复算；
- G0 配置写回 `verified / approved / eligible_for_d0`；
- G0 后续不再新增流程 PR。

## D0：数据源资格审查、原始快照与基础审计

状态：completed

目标：

- 建立 DuckDB 架构边界；
- 明确数据源资格、原始快照和基础审计要求；
- 定义 D1/D2/D3 数据产品契约。

非目标：

- 不采集行情；
- 不运行 D0 装载；
- 不创建正式 DuckDB 文件；
- 不计算 PCVT、事件、标签或回测。

任务列表：

- `D0-T01` DuckDB 数据架构设计：completed via PR #6
- `D0-T02` 数据源资格审查与 source registry：completed via PR #7
- `D0-T03` D1 / D2 / D3 数据产品契约：completed via PR #8

完成标准：

- `D0-T01`、`D0-T02`、`D0-T03` 合并；
- D0 的设计、来源资格、原始快照审计要求和数据产品契约均固定；
- 仍未进入研究运行。

## D1：证券主数据、交易状态、公司行为与交易日历

状态：completed

- `D1-T00` DuckDB 依赖、空 schema 与契约测试：completed via PR #9
- `D1-T01` `security_master` 与代码映射：completed via PR #10
- `D1-T02` 交易日历与交易状态主表：completed via PR #11
- `D1-T03` 公司行为与复权因子主表：completed via PR #12
- `D1-T04` `CSI800_STATIC_2026_06` universe membership materialization：completed via completion PR

## D2：时点一致的原始价格、连续研究价格和跳空归因

状态：planned

目标：

- 建立原始交易事实、复权/因子、连续研究价格和跳空归因的分层边界；
- 保证 raw price facts 与 continuous research prices 并存、可追溯、不可覆盖或混用；
- 在 source/as-of/snapshot/manifest 阻塞条件关闭前，只做契约、探针和小样本验收设计，不启动全量正式行情拉取。

非目标：

- 不从 D2-T01 直接开始全市场数据采集；
- 不绕过 D0 source registry 和 D1/D2 数据产品契约；
- 不将候选来源返回的历史修订价格、复权价或供应商标签直接升级为正式研究证据。

任务列表：

- `D2-T01` 价格来源与 raw OHLCV 探针契约：completed via PR #25
- `D2-T02` 成员对齐层物化：completed via PR #26
- `D2-T03` 原始行情价格落账：blocked pending source authorization via PR #27
- `D2-T04` 复权因子与 `factor_as_of_time` 契约：blocked pending factor source authorization via PR #28
- `D2-T05` 连续研究价格构建与反推校验：blocked pending raw and factor authorization via PR #29
- `D2-T06` 候选行情快照探针：small-sample redacted execution report via PR #32; formal ingestion and D1/D2/D3 materialization remain blocked
- `D2-T07` 价格质量、交易约束、机械缺口与 PCVT 底层依赖契约：contract-only via PR #33
- `D2-T08` D2 阶段验收与 D3 交接契约：contract-only via PR #34; D3 contract work may proceed, but formal D3 generation remains blocked
- `D2-T09` HiThink 主行情源、补充源与 raw OHLCV 探针契约：completed via PR #41; candidate raw market prices remain superseded diagnostic output and do not define D2-T13 date domain
- `D2-T10` adjusted price、质量标记与机械缺口正式候选物化：completed via PR #42
- `D2-T11` 来源状态与复权证据补齐、D2验收与D3交接候选：completed via PR #43; D2/D3 remained blocked
- `D2-T12` tnskhdata/Tushare证据源探针、统一代码映射与HiThink REST适配修复：completed via PR #44
- `D2-T13` tnskhdata全量候选物化与D2验收交接：completed via PR #45; D2 acceptance remained blocked by listed-open provider coverage
- `D2-T14` listed-open 行级 provider 修复诊断：closed / superseded by D2-T15; not merged
- `D2-T15` 按证券主轴的 DuckDB 候选物化骨架与质量门禁：completed via PR #47
- `D2-T16` 按证券主轴的 tnskhdata 远程拉取 runner：completed via PR #48
- `D2-T17` 按 endpoint 配置 D2 runner chunk 策略：completed / runner available after PR #49
- `D2-T18` provider coverage blocker 诊断与最小修复策略：completed / diagnostics available after PR #50
- `D2-T19` targeted repair and coverage policy evidence：completed / stk_limit targeted repair succeeded; daily repair empty due to listing pause
- `D2-T20` fast coverage policy acceptance：completed via PR #52; evidence-verified research candidate accepted for D3 candidate generation
- `D3-T07` 标准日频观测表 candidate 生成：completed via PR #53; reads D2-T20 evidence-verified candidate only
- `D3-T08` 研究基础数据集 registry 与路线无关质量审计：completed via PR #54

D3-T07 candidate generation may read D2-T20 candidate output. Formal data_version remains blocked until explicit release gate. R0 state remains blocked until PCVT candidate indicators and later gates are accepted.

完成标准：

- D2-T01 至 D2-T08 均完成对应 PR 级验收；
- `d1.raw_market_prices`、`d2.adjusted_market_prices`、`d2.market_price_quality_flags` 和
  `d2.membership_alignment` 的来源、as-of、snapshot、manifest 和 revision 边界均通过审核；
- 原始交易事实层、连续研究价格层、交易约束引用和公司行为/机械缺口归因之间的使用边界可测试、可追溯；
- D3 可以仅通过引用已验收的 D1/D2 事实构建 `daily_market_observations`。

## D3：跨研究复用的标准日频观测表与基础质量指标

状态：in_progress

D2-T08 已完成 D2 acceptance 与 D3 handoff contract-only 验收。D2-T20 已完成
evidence-verified research candidate acceptance，并只授权 D3 candidate generation。
formal data_version、formal source promotion 与 R0 交接仍未授权。

- `D3-T01` `daily_market_observations` 语义与字段契约：completed via PR #35
- `D3-T02` D3 标准数值观测 view/table 契约：completed via PR #36
- `D3-T03` 组件引用、source lineage 与 no-bypass 校验器：completed via PR #37
- `D3-T04` 基础质量指标与 PCVT input readiness 契约：completed via PR #38
- `D3-T05` 标准日频观测合成构建与最小集成测试：completed via PR #39
- `D3-T06` `data_version`、quality report 与 manifest 发布门禁：completed via PR #40
- `D3-T07` 从 D2-T20 evidence-verified candidate 生成标准日频观测表：completed via PR #53
- `D3-T08` 研究基础数据集 registry 与路线无关质量审计：completed via PR #54
- `D3-T09` R阶段工程分层与 Task-as-Step 规范收敛：completed
- `D3-T10` D3 字段可用性探针与字段缺口补全：completed via PR #58
- `D3-T11` 量额股本换手字段全量候选物化与数据更新：completed via PR #59
- `D3-T12` 开放候选层门禁与下游消费审计解耦：completed via PR #60

D3 是跨研究开放 candidate observation layer。D3 candidate generation 不等于 formal release，也不等于任一 R-stage readiness。R0-R6 或未来研究路线由各自消费 task 定义 consumer readiness profile；D3 只记录通用质量、evidence 和 lineage 状态。`policy_evidence_pending_hash` 是 candidate warning，不是 D3 candidate hard blocker。formal release gate 和下游 research consumer gate 后续仍可严格阻塞消费。

PR #60 的 D3-T11 full-run 摘要以 canonical local output-dir `data/generated/d3/d3_t11_volume_amount_share_turnover_candidate/` 为准；该目录已由 clean rerun compact artifact 覆盖回默认路径。retry-patched artifact 仅作为本地备份/审计，不作为最终摘要来源，generated DuckDB/CSV/JSON 仍不得提交。

## R0：PCVT 候选观测量与候选状态定义

状态：in_progress

- `R0-T01` PCVT 候选指标规格、状态族与 candidate spec contract：completed via PR #56
- `R0-T02` 输入 readiness gate 与 C2/V1 公司行为口径审计：completed via PR #57
- `R0-T03` V层 turnover 替代指标可行性、口径决策与输入门禁：completed via PR #61
- `R0-T04` PCVT raw metric engine 与合成测试：completed via PR #62
- `R0-T05` 严格过去分位、eligible 样本与 Score 体系：completed via PR #63
- `R0-T06` weak 维度规则、嵌套状态与互斥分层：completed via PR #64
- `R0-T07` 联合确认层、streak 与确认区间表：completed via PR #65
- `R0-T08` 主网格 candidate 状态日表与 manifest：completed via PR #66
- `R0-T09` runner/contract/smoke：completed via PR #67
- `R0-T09` formal input manifest：blocked / superseded by R0-T10-05 pending real R0-T04 -> R0-T07 upstream artifacts
- `R0-T09` production full-grid materialization：blocked until R0-T10-05 authorized input manifest and streaming/artifact-manifest mode
- `R0-T10-01` 真实数据源与 R0-T04 raw metrics 物化：completed via PR #69
- `R0-T10-02` R0-T05 strict-past score 物化：completed via PR #70
- `R0-T10-03` R0-T06 nested state 物化：completed via PR #71
- `R0-T10-04` R0-T07 confirmation / interval 物化：completed via PR #72
- `R0-T10-05` authorized input manifest 与 27 组 full-grid 执行：completed via PR #73; repaired by R0 C2 readiness and state-specific validity rerun
- `R0-T11` R0 审计报告与 R1 交接：completed via PR #74
- `R0-T12` 替代指标口径敏感性骨架：optional
- `R0-T13` Post-Up-Release Short-PCT 研究接口占位：optional
- `R0-T14` R0 并行确定性与性能优化：optional

## R1：状态存在性、结构关系、稳定性与零模型检验

状态：in_progress / active

本 PR 修复 R0 C2 readiness alias 与 state-specific validity blocker，并将 R1-T01、R1-T02、R1-T03 重新锁定到修复后的 R0-T10-05 full-grid package。R1-T04 可以基于非零 `S_PC` / `S_PCT` / `S_PCVT` raw 与 confirmed 结构继续做分线画像；R1-T07 与 R2 仍保持 blocked。

- `R1-T01` 验证协议、状态线假设与 manifest 锁定：completed via PR #75; relocked to repaired R0 package via this PR
- `R1-T02` R0 产物接收、lineage 与无前视复检：completed via this PR
- `R1-T03` 27 组 W/q/K 全量轻量结构扫描：completed via this PR against the repaired R0-T10-05 package; draft PR #77 is superseded by the repaired nonzero package evidence
- `R1-T04` S_PCT 与 S_PCVT 分线状态画像：completed via PR #80
- `R1-T05` 单指标诊断与层内互补性分析：completed via PR #81
- `R1-T06` 层间条件 Lift 与固定滞后结构关系：in_progress
- `R1-T07` S_PCT/S_PCVT 预注册配置的同步性零模型：planned
- `R1-T08` 年份稳定性与状态集中度检查：planned
- `R1-T09` R1 验收门禁与 R2 交接矩阵：planned
- `R1-T10` 27 组全量零模型 family-level sidecar：optional / triggered
- `R1-T11` CTV-bundle、无锚平移与块长 B 对照零模型：optional / triggered
- `R1-T12` 替代指标口径 sensitivity sidecar：optional / triggered

## R2：参数、事件规则与状态版本冻结

状态：blocked until R1

- `R2-T01` 参数候选收敛
- `R2-T02` 事件规则与状态边界
- `R2-T03` 状态版本冻结

## R3：释放定义、风险集、对照组与未来标签

状态：blocked until R2

- `R3-T01` 释放定义
- `R3-T02` 风险集与对照组
- `R3-T03` 未来标签契约

## R4：释放后的方向、幅度、持续期与路径研究

状态：blocked until R3

- `R4-T01` 方向与幅度研究
- `R4-T02` 持续期与路径研究

## R5：样本外验证、回测、成本与稳健性检验

状态：blocked until R4

- `R5-T01` 样本外验证
- `R5-T02` 回测与成本检验
- `R5-T03` 稳健性检验

## R6：交易可行性、执行约束、运行监控与结论发布

状态：blocked until R5

- `R6-T01` 交易可行性与执行约束
- `R6-T02` 运行监控
- `R6-T03` 结论发布

## 说明

- 本索引只定义阶段和任务队列，不替代 task 正文契约。
- 若某阶段范围发生实质变化，应先更新本索引，再新增 task。
