# R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型

## 任务定位

R1-T08 是 R1 阶段的正式 null-model experiment。它检验 S_PCT 与 S_PCVT 的同期联合确认覆盖是否高于保留单层边际分布、块内持续结构和自相关但破坏跨层同期对齐的 circular-shift null，并检验 C、T、V 在同参数 parent 风险集中的嵌套 retention 是否高于相应新增层错位 null。本任务不冻结参数、不选择最佳配置、不生成交易或未来预测结论，也不授权 R2。

## 前置门禁与输入

正式运行只消费 R1-T01 锁定且由 R0-T10-05 authorized input manifest 绑定的 dimension state、nested daily state、daily confirmation 和 confirmed interval。R1-T04、R1-T06、R1-T07 的 final-gate 产物仅用于 observed reconciliation 和治理门禁核验。不得读取 raw、MarketDB、通达信 `.day` 或其他未授权源。

开始 formal run 前必须满足：PR #83 已合并；R1-T07 为 completed/scientific passed/anomaly passed/downstream allowed；README 当前任务为 R1-T08，且 R1-T09 与 R2 均未放行。

## 冻结候选与检验组

正式候选仅包括 S_PCT 和 S_PCVT 在 W=250/q=0.20/K=3 与 W=120/q=0.20/K=3 的四个对象。每个 W 执行 global PCT、global PCVT、C given P、T given PC、V given PCT 五组检验，共十组。K2、W500 和 K5 sidecar 不执行。

global PCT 固定 P 并独立移动 C/T；global PCVT 固定 P 并独立移动 C/T/V。C、T、V nested null 分别只移动新增层。禁止直接移动最终 PCT/PCVT 或 confirmed state。

## Segment 与 shift 契约

上游未物化 continuous segment id，因此在 formal run 前冻结 `authorized_master_calendar_gap_v1`：master calendar 是 authorized nested daily state 中 distinct trading_date 的有序集合；序列按 security_id 和 year 分区；security/year 改变或相邻观测的 master-calendar ordinal gap 不为 1 时开启新 segment。分段前不得按 state、validity、unknown 或 blocked 过滤。

每个 layer 的 raw state、validity status 与 reason payload 使用同一 source-index mapping。长度大于 1 的 block offset 必须在 `[1, length-1]`；singleton 保留 offset 0 并显式计数。子 seed 由 root seed、candidate、null model、replicate 和 layer 经 SHA-256 派生，再由 counter-based SplitMix64 生成 block offsets。结果不得依赖线程、批次或检验组顺序。

## Observed 对账

任何 permutation 前，R1-T08 从 dimension payload 独立重建 ordered three-valued AND、K=3 daily confirmation、confirmation date 和 interval geometry，并按完整 key 与 nested daily、R0 daily confirmation、R0 interval 对账。同时核对 R1-T04 的 confirmed days/coverage/interval/duration/fragment 与 R1-T06 的 C/T/V retention。任一 missing、extra、raw、confirmed、interval 或上游聚合 mismatch 非零即 `blocked_input_contract`，禁止执行 null simulation。

## Monte Carlo 与统计量

正式 `N_perm=2000`，经验 p 为 `(n_extreme+1)/(N_perm+1)`，null interval 为线性 percentile 2.5%/97.5%，failed simulation 必须为 0。coverage、nested retention 和 duration 使用 upper tail；fragment rate 使用 lower tail。z-score 仅为描述统计；null SD 为 0 时写 NULL。实现支持 10000 次，但本版本未注册触发条件，因此 formal run 禁止切换至 10000。

global primary statistic 是 confirmed coverage；nested primary statistic 是 target-valid parent-active 风险集中的 retention。JointLift 是 observed/null mean，JointExcess 是 observed-null mean。null mean 为 0 时 JointLift 必须为 NULL。

## 工程与科学门禁

runner 必须提交 20,000 行 replicate artifact，并记录每行 offset-plan hash。engineering validator 必须从 replicate 行独立重算 mean、median、percentile interval、tail、n_extreme、empirical p、JointLift、JointExcess、失败数和 replicate 完整性，并从 root seed 重建全部 offset hashes。

author-draft 阶段固定为 scientific review pending、downstream false、README 不推进、R1-T09 false、R2 false。只有独立 scientific review 与 final-gate validator 均通过后，才可由后续提交推进 README。
