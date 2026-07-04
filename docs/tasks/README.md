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
current_stage: D2
current_task: D2-T03
next_planned_task: D2-T04
```

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
- `D2-T06` 候选行情快照探针：small-sample redacted execution report via PR #32; formal ingestion still blocked
- `D2-T07` 价格质量、交易约束、机械缺口与 PCVT 底层依赖契约：contract-only via PR #33
- `D2-T08` D2 阶段验收与 D3 交接契约：contract-only via PR #34; D3 generation still blocked

完成标准：

- D2-T01 至 D2-T08 均完成对应 PR 级验收；
- `d1.raw_market_prices`、`d2.adjusted_market_prices`、`d2.market_price_quality_flags` 和
  `d2.membership_alignment` 的来源、as-of、snapshot、manifest 和 revision 边界均通过审核；
- 原始交易事实层、连续研究价格层、交易约束引用和公司行为/机械缺口归因之间的使用边界可测试、可追溯；
- D3 可以仅通过引用已验收的 D1/D2 事实构建 `daily_market_observations`。

## D3：跨研究复用的标准日频观测表与基础质量指标

状态：planned

- `D3-T01` `daily_market_observations` contract：planned
- `D3-T02` 数据质量报告与 `data_version` 发布

## R0：PCVT 候选观测量与候选状态定义

状态：blocked until D3

- `R0-T01` PCVT 候选指标定义
- `R0-T02` `q = 10 / 20 / 30` 结构检验

## R1：状态存在性、结构关系、稳定性与零模型检验

状态：blocked until R0

- `R1-T01` 状态存在性与频率轮廓
- `R1-T02` 结构关系与协同约束检验
- `R1-T03` 稳定性与零模型检验

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
