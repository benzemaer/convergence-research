# R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型 Result Analysis

## 1. 研究目标与预注册问题

本报告分析 formal run `R1-T08-20260710T1629Z`。预注册问题是：S_PCT 与 S_PCVT 的同期 confirmed coverage 是否超过保留单层块内边际与持续结构、但破坏跨层同期对齐的 circular-shift null；C、T、V 在同参数 parent-active 风险集中的 retention 是否超过仅移动新增层的 nested null。`observed_fact`：正式范围为四个 candidate、十个 test groups，每组 `N_perm=2000`，未执行 sidecar 或 10000 次扩展。

## 2. 输入 package、lineage、时间与样本范围

输入由 R0-T10-05 authorized manifest 绑定，包含 dimension state、nested daily state、daily confirmation 与 confirmed interval，日期为 2016-01-04 至 2026-06-30，800 只证券。每个 W/q candidate 有 1,730,769 个 key。代码 commit 为 `59218fa714f3275f7bdc4995265f381aa1140fa5`，环境为 Python 3.12.10、NumPy 2.5.0、DuckDB 1.5.4，DuckDB threads=4、memory limit=12GB。`observed_fact`：四个输入 SHA-256 均与 authorized manifest 一致，未读取 raw、MarketDB 或未来字段。

## 3. 参数网格与 reference baseline

reference 为 W250/q0.20/K3，challenger 为 W120/q0.20/K3，两条 state line 分别分析 S_PCT 与 S_PCVT。global PCT 固定 P 并独立移动 C/T；global PCVT 固定 P 并独立移动 C/T/V。nested C/T/V 分别只移动新增层，parent 使用同 W/q 的 P、PC、PCT。root seed 为 2026071008，子 seed 绑定 candidate、null model、replicate 与 layer；没有按结果修改参数、tail 或 permutation 次数。

## 4. 核心结果

`observed_fact`：四个 global confirmed coverage 均高于 97.5% null quantile，且 2,000 个 replicate 中 `n_extreme=0`，经验 p 均为可分辨下限 `1/2001=0.00049975`。

| test | observed | null mean | 95% null interval | JointLift | JointExcess | empirical p |
|---|---:|---:|---:|---:|---:|---:|
| W250 S_PCT coverage | 0.0062712 | 0.0017758 | [0.0016727, 0.0018789] | 3.5315 | 0.0044954 | 0.0004998 |
| W120 S_PCT coverage | 0.0072107 | 0.0018382 | [0.0017270, 0.0019477] | 3.9227 | 0.0053725 | 0.0004998 |
| W250 S_PCVT coverage | 0.0012382 | 0.0002623 | [0.0002230, 0.0003039] | 4.7211 | 0.0009759 | 0.0004998 |
| W120 S_PCVT coverage | 0.0016992 | 0.0002902 | [0.0002467, 0.0003357] | 5.8557 | 0.0014091 | 0.0004998 |

`independent_recomputation`：直接从 replicate CSV 重算 W250 PCT 得 mean=0.0017757930、`n_extreme=0`、p=1/2001、JointLift=0.0062712008/0.0017757930=3.5314931；W250 PCVT 对应 mean=0.0002622664、JointLift=4.7210702。上述数值与 aggregate CSV 一致。

## 5. 预期结果与实际结果对照

预注册预期是：若跨层同期对齐包含超出各层自身持续性的结构，observed coverage 和 nested retention 应位于 upper tail；若只是边际 hit rate 与自相关叠加，则 observed 应接近 null。实际四个 coverage 与六个 nested retention 全部位于 2,000-replicate upper tail 之外。`inference`：在本 null 所保留和破坏的结构范围内，单层块内分布与持续性不足以复现 observed 同期联合覆盖。

几何指标并非全部强分离。PCT mean duration 的 W120/W250 p 均为 0.0004998，fragment lower-tail p 分别为 0.0014993/0.0019990；但 duration median 因离散取值大量并列，p 为 0.7271/0.5617。PCVT mean duration 的 W120 p=0.0590、W250 p=0.00750，fragment p=0.1799/0.0625，median p=0.1964/0.1744。`material_warning`：coverage separation 不能改写为所有 duration/fragment 指标均同等分离。

## 6. coverage / NULL / unknown / blocked / denominator 检查

W120 S_PCT/S_PCVT confirmed days 分别为 12,480/2,941，coverage 为 0.0072107/0.0016992；W250 分别为 10,854/2,143，coverage 为 0.0062712/0.0012382。global denominator 均为完整 1,730,769 key。W120 S_PCT 有 126,422 unknown、1,615 blocked；W250 有 226,030 unknown、1,068 blocked，未把非 valid 状态压成 false。

nested denominator 在每个 replicate 中按 shift 后 target-valid 且 fixed parent-active 定义，unknown/blocked 不进入 retention 分母。`observed_fact`：20,000 行 required primary statistic 无 NULL，failed simulation=0；observed true/false/null 合计逐行等于 key count。

## 7. baseline 与至少两个 challenger 对照

相对 W250 reference，W120 S_PCT challenger 的 observed coverage、null mean、JointLift 与 JointExcess均更高；W120 S_PCVT challenger也呈相同方向。两个 challenger 对象都没有方向冲突：PCT lift 3.9227 对 3.5315，PCVT lift 5.8557 对 4.7211。

这不是候选优选。W120 availability 更高、unknown 更少，本身改变 observed 与 null 的水平；R1-T08 未预注册用于冻结参数的 p cutoff 或 winner rule。`research_judgment`：reference/challenger 对照支持“两个窗口均有同方向 null separation”，参数交接必须留给 R1-T10。

## 8. 参数响应与敏感性

W 从 250 缩短到 120 后，PCT confirmed days 从 10,854 增至 12,480，PCVT 从 2,143 增至 2,941；global observed、null mean 与 lift 均发生响应，不是参数退化输出。nested lift 也一致略高于 W250：C 为 1.7918 对 1.7373，T 为 1.7786 对 1.7188，V 为 1.5656 对 1.4414。

本 task 只比较两个预注册 W；q 固定 0.20、K 固定 3。没有执行 K2、W500、K5 sidecar，也没有根据最小 p 切换至 10,000 permutations。`material_warning`：当前结果不能代表 27 组 family-level null 或其他 block/shift 构造的稳健性。

## 9. 层级、漏斗、守恒关系与不变量

`observed_fact`：W120 raw PCT/PCVT true days 为 39,800/10,768；W250 为 34,615/7,860，均满足 PCVT subset PCT。confirmed days与 interval 也保持 child 不超过 parent。dimension→ordered AND→nested daily→K3 daily confirmation→confirmed interval 的 missing、extra、raw、confirmed、confirmation-time、interval mismatch 全为 0；R1-T04 profile 与 R1-T06 nested retention mismatch 也均为 0。

每个 W 形成 8,677 个 blocks，其中 8,669 个可 shift、8 个 singleton。所有 rows 均被分配；跨证券、跨年份、block 内 calendar gap、shiftable offset=0、offset 越界与 payload preservation violation 均为 0。validator 从 root seed 重建了所有 replicate offset-plan hash 与十个 chain hash。

## 10. 异常结果及根因调查

实际 anomaly scan 未发现全零、全一、全 NULL、全部 replicate 相同、参数无响应、层级反转、denominator 错位、failed simulation 或 p formula mismatch。`observed_fact`：engineering validator status=passed，errors=[]，candidate exact=true，10 groups、20,000 replicates、22 result rows均完整。

PCVT 几何指标的 separation 弱于 coverage，不是工程异常。其 null interval count 较低、duration/fragment 为离散比率，且 observed median=2 落在 null interval 上界附近；因此保留为统计事实而非强行解释。没有 `blocking_finding`，但该差异属于科学审阅应重点核查的 material warning。

## 11. 替代解释与反证检查

该 null 保留每层在 security/year/continuous-segment 内的边际 true/false/null、validity、reason payload 与 circular persistence，同时破坏跨层 contemporaneous alignment。它反证了“仅由这些块内单层结构即可得到 observed coverage”的简单解释，但没有排除共同市场环境、共同输入指标、横截面混合、年份组成、非平稳性或状态定义共享信息造成的同步。

P 被固定而 C/T/V 被移动，null 具有 anchor asymmetry；它没有检验 P 自身移动、bundle shift、跨层 lead-lag 或其他 segment 定义。`inference`：结果是相对于特定 null 的结构关联，不是层间因果贡献。

## 12. 研究限制

经验 p 的最小可分辨值是 1/2001，`n_extreme=0` 只表示在 2,000 个已执行 replicate 中未达到 observed，不能解释成真实 p=0。结果为 pooled panel 指标，未在本 task 完成年份稳定性、证券异质性或 family-level multiplicity 评估。continuous segment 由 authorized master-calendar gap 规则派生，虽然已冻结并零违规，但仍是本研究对“连续交易段”的操作化定义。

R1-T08 不使用未来结果，因此不能回答预测价值、方向、交易可行性或样本外稳定性。当前 author analysis 也不能替代独立 scientific review。

## 13. 可以支持的结论

`research_judgment`：可以支持以下有限结论。第一，两个预注册 W 下，S_PCT 与 S_PCVT observed confirmed coverage 都显著高于本 circular-shift null 的经验分布。第二，C、T、V 在各自同参数 parent-active 风险集中的 observed retention 都高于仅移动新增层的 null，且 W120/W250 方向一致。第三，PCT 的 mean duration 和 lower fragment rate 也有 separation；PCVT 几何证据较弱且指标间不一致，应单独陈述。

## 14. 不可以支持的结论

不可以据此宣称因果机制、未来预测力、交易优势、突破方向、最优 W、冻结候选或多数证券/年份均同向。不能把经验 p 下限排序为 winner，也不能把 global coverage 结果外推为 duration 与 fragment 全面通过。不能启动 R2，不能跳过 R1-T09 年份稳定性与后续交接门禁。

## 15. 下游 gate 建议

`research_judgment`：engineering 与 author anomaly gate 可记为 passed，result package 应进入独立 scientific review；`scientific_review_status=pending`、`downstream_gate_allowed=false`、`R1-T09_allowed_to_start=false`、`R2_allowed_to_start=false`，README 保持当前 R1-T08，不在本提交推进。只有独立审阅通过并完成 final-gate package 后，才可决定是否授权 R1-T09。
