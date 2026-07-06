# R0-T01 PCVT 候选指标规格与状态族定义

> 状态：in_progress / design-only  
> 所属阶段：R0  
> PR 标题：`[codex] R0-T01 PCVT 候选指标规格与状态族定义`  
> 分支：`codex/r0-t01-pcvt-candidate-indicator-spec-state-family`

## 目标

本 task 建立 R0 阶段纲领稳定入口，冻结 R0-T01 的设计边界和 R0 task 路线图。稳定入口为 `docs/stages/R0_PCVT候选观测量与候选状态定义.md`，文件名不携带版本号，正文保留版本字段。

## 非目标

本 task 不实现指标计算，不读取真实数据，不写 DuckDB，不生成 PCVT values、scores、states、intervals，不生成 labels、returns、backtest 或 portfolio，不发布 formal `data_version`。本 task 也不新增 R0 JSON Schema 或 config，不修改 D2/D3 数据契约语义，不创建 `docs/stages/archive/`，不把当前 task 状态写入 `docs/00_研究章程.md`，不把 R0 v0.3 全文复制进 `docs/01_研究方案与预分析计划.md`。

## 输入

- 用户提供的 `R0_PCVT候选观测量与候选状态定义_v0.3.md` 草案；
- `README.md`、`AGENTS.md`；
- `docs/00_研究章程.md` 至 `docs/05_证据与产物治理政策.md`；
- `docs/tasks/README.md`；
- D3-T09 后的 R 阶段工程分层与 Task-as-Step 治理规则。

## 输出

- 新增 `docs/stages/README.md`；
- 新增 `docs/stages/R0_PCVT候选观测量与候选状态定义.md`；
- 更新 `README.md`、`docs/00_研究章程.md`、`docs/01_研究方案与预分析计划.md`、`docs/03_可复现研究工程标准.md`、`docs/04_阶段与门禁框架.md` 和 `docs/tasks/README.md`；
- 新增本 R0-T01 task 文档；
- 重新生成根目录合订本。

## 验收标准

- 阶段纲领稳定入口不带版本号，正文保留 `版本：0.3`；
- R0 v0.3 设计要点完整，包括八项候选指标、`S_PCT` / `S_PCVT` 双主线、严格过去历史分位、`score_i = 1 - percentile_i`、维度连续分、`score_*_min`、strict baseline、weak sensitivity、`W/q/K` 主网格、C2/V1 readiness gate、`unknown` 语义和 Post-Up-Release Short-PCT 后移到 R3/R4；
- `docs/tasks/README.md` 当前阶段指向 R0-T01，R0 task 路线图包含 R0-T01 至 R0-T08 必须路线和 R0-T09 至 R0-T11 可选路线；
- 未引入数据运行、PCVT 计算、真实数据读取、future labels、returns、backtest、portfolio 或 formal `data_version`。

## 失败状态

若本 PR 计算指标、生成状态、引入数据读取、发布 `data_version`、生成 future labels、returns、backtest 或 portfolio，则本 PR 失败并回退。

## 回退方式

回退本 PR 新增和更新的文档及根目录合订本。由于本 task 不读取数据、不写 DuckDB、不发布数据版本，因此无需数据回滚。
