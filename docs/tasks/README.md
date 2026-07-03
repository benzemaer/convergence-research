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

## 当前阶段

```text
current_stage: D0
current_task: D0-T01
next_planned_task: D0-T02
```

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

## D0：数据仓库与数据源资格

状态：active

目标：

- 建立 DuckDB 架构边界；
- 明确数据源资格审查入口；
- 定义 D1/D2/D3 数据产品契约。

非目标：

- 不采集行情；
- 不运行 D0 装载；
- 不创建正式 DuckDB 文件；
- 不计算 PCVT、事件、标签或回测。

任务列表：

- `D0-T01` DuckDB 数据架构设计：PR #6
- `D0-T02` 数据源资格审查与 source registry：planned
- `D0-T03` D1 / D2 / D3 数据产品契约：planned

完成标准：

- `D0-T01`、`D0-T02`、`D0-T03` 合并；
- D0 的设计、来源资格和数据产品契约均固定；
- 仍未进入研究运行。

## D1：证券主数据与静态样本

状态：planned

- `D1-T01` `security_master` 与代码映射
- `D1-T02` `CSI800_STATIC_2026_06` universe membership materialization

## D2：原始行情与可交易状态

状态：planned

- `D2-T01` OHLCV 与成交额采集
- `D2-T02` 停复牌与交易状态
- `D2-T03` 涨跌停状态
- `D2-T04` 公司行为与复权因子
- `D2-T05` 换手率或参与度代理

## D3：研究日频观察表

状态：planned

- `D3-T01` `daily_market_observations`
- `D3-T02` 数据质量报告与 `data_version` 发布

## R0：候选状态定义

状态：blocked until D3

- `R0-T01` PCVT 候选指标定义
- `R0-T02` `q = 10 / 20 / 30` 结构检验

## 说明

- 本索引只定义阶段和任务队列，不替代 task 正文契约。
- 若某阶段范围发生实质变化，应先更新本索引，再新增 task。
