# R1-T01 验证协议、状态线假设与 manifest 锁定

## 目标

本 task 冻结 R1 v0.2 的协议层，包括 R1 研究取舍、reference baseline、27-grid light profile、`S_PCT` / `S_PCVT` 分线验证、raw/confirmed 双主线、年份稳定性、正式零模型、固定滞后、禁止事项和 R2 交接状态。`W=250,q=0.20,K=3` 在本 task 中是 reference baseline，不是默认最优参数，也不是 optimized / best / selected parameter；27 组 `W/q/K` 只承担轻量结构扫描、预注册配置正式验证和触发式全量零模型三类作用。

本 task 的完成标准是仓库具备可机器校验的 R1-T01 协议层。下游 R1-T02 必须能够明确 R1 只能消费哪个 R0 evidence-bound package，`S_PCT` 与 `S_PCVT` 如何分线研究，raw 与 confirmed 分别承担什么角色，baseline 与 challenger 如何评价，正式零模型是什么，年份稳定性如何定义，后续输出 schema 和 artifacts 如何推进，以及每个 `state_line × candidate_config_id` 未来如何进入 R2 decision matrix。

## 非目标

本 task 不读取真实原始源，不做 R1 正式统计，不跑零模型，不生成 light profile，不做参数选择，不生成 future / return / backtest / portfolio / trade signal，不启动 R2。R1-T01 不读取 raw / external / MarketDB / `.day`，不绕过 R0 授权交接产物，不重新计算 strict-past percentile，不生成 future label、future return、release direction、breakout direction、backtest、portfolio 或 trade signal。

R1-T01 不把 `W=250,q=0.20,K=3` 写成最优参数，不把 27 组网格当作按未来表现选择参数的搜索池，也不对 27 组配置打 R2 最终结论。R1 不冻结最终状态版本；R2 才能冻结最终 `W/q/K`、状态线版本、确认规则、区间规则和后续事件接口。

## 输入

R1-T01 只登记 R1 后续可消费的输入范围，不直接读取行级数据。允许输入为 R0 候选状态日表、确认区间表、manifest、config hash、schema、quality flags、`confirmation_time`，以及 R0-T11 handoff 中允许 R1 消费的 evidence-bound package。

R0-T11 已记录当前 R0 formal package 的 confirmed interval 为 0。R1-T01 将其作为 input fact 和后续分析限制登记，不在本 task 内修改 K、回填 confirmed state、做 gap merge、降低阈值或重跑 R0 来制造 confirmed intervals。

## 输出

本 task 输出 R1 stage doc、R1 config manifest、schema、validator、thin wrapper、tests、evidence、README 更新和合订本更新。核心实现位于 `src/r1/`，`scripts/r1/validate_r1_t01_manifest_lock.py` 只能作为 thin wrapper 导入 CLI main 并执行，不包含 DuckDB 查询、hash gate、evidence 解析、参数网格或业务常量。

R1-T01 evidence 只记录路径、hash、counts、validator result 和 gate，不嵌入 row payload，不复制 DuckDB、Parquet、CSV 或 JSONL 内容。README gate 只有在 R1-T01 evidence 存在且 `validator_status=passed` 后，才允许 current task 推进到 R1-T02。

## 协议锁定

R1 必须分线研究 `S_PCT = P ∧ C ∧ T` 与 `S_PCVT = P ∧ C ∧ T ∧ V`。`S_PCT` 表示不要求参与度枯竭的结构收敛状态，`S_PCVT` 表示在 `S_PCT` 基础上叠加 V 的枯竭型结构收敛状态。R1 不强迫 `S_PCT` 与 `S_PCVT` 共用同一组 `W/q/K`，但 state-line-specific candidate 只能在后续正式证据产生后进入 R2 decision matrix。

raw/confirmed 双主线固定为：raw 用于诊断定义本体、单指标边界、层内互补性与 raw fragment；confirmed 用于判断是否具备 R2 `freeze_candidate` 或 `review_candidate` 资格。R2 decision matrix 的主状态必须以 confirmed state 与 `confirmation_time` 为准，raw 结果不能单独使某配置进入 `freeze_candidate`。

正式零模型预注册为 `P_fixed_independent_CTV_circular_shift`：P 保持不变，C/T/V 在 `security_id × year × continuous trading segment` 内分别 circular shift，保留每层边际分布、块内自相关和持续结构，破坏 P/C/T/V 的 contemporaneous alignment。`N_perm = 2000`，经验 p 值为 `(n_extreme + 1) / (N_perm + 1)`，主证据是 JointLift 与 empirical p，z-score 只能作为描述统计。固定滞后集合为 `[1,3,5,10,20]`。

基础稳定性只按年份检查，年份由 `year = YEAR(trading_date)` 派生。市场状态、流动性层、股票年龄、行业、交易约束和质量归因不进入 R1 v0.2 基础门槛，除非后续数据层提供版本化、时点一致、可审计字段。

## 失败状态

若读取 forbidden inputs、生成 forbidden outputs、绕过 R0 evidence chain、把 baseline 写成最优参数、把 raw 单独作为 R2 freeze basis、把 confirmed interval 0 行解释成 R0 失败、或 validator 硬编码 passed，则本 PR 失败。若 R1 task、stage、config 或 evidence 出现 strategy validated、trading signal ready、backtest passed、future return analyzed、parameter optimized、R1 completed、R2 started 等肯定性结论，也视为失败。

若后续 R1-T02 发现 R0 manifest、schema、hash、`confirmation_time`、严格过去分位、unknown/blocked 语义或候选状态表/确认区间表对齐等输入前提不成立，应标记 `blocked_return_to_R0`，不得在 R1 内临时修补后继续使用。

## 回退方式

回退本 PR 新增和更新的 R1 文档、config、schema、src、scripts、tests、evidence、README 和合订本即可。由于本 PR 不生成大型数据产物，不提交 generated DuckDB、Parquet、CSV 或 JSONL，因此不需要数据回滚。

## 验收命令

提交前必须通过以下命令：

```bash
python scripts/build_compendium.py --check
python scripts/validate_configs.py
python scripts/validate_manifests.py
python -m src.r1.r1_t01_manifest_lock_validator_cli
python scripts/r1/validate_r1_t01_manifest_lock.py
ruff format --check scripts tests src
ruff check scripts tests src
python -m unittest discover -s tests -v
git diff --check
```

如果合订本 check 失败，先运行 `python scripts/build_compendium.py`，然后重新运行全部验收命令。
