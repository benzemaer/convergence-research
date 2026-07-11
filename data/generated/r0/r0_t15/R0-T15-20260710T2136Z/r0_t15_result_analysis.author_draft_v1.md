# R0-T15 层级 q-vector 正式物化与 R1-T14-02 交接 result analysis

## 1. 结论与门禁边界

formal materialization run `R0-T15-20260710T2136Z` 绑定代码 commit `b7cd0c2a3d4d3dbe3867246712c68107ea604c96`，逐字消费 PR-A #87 的 frozen request。两个 shared baseline references 只做 lineage reconciliation，8 个 nonbaseline center/neighbor vectors 全部完成 dimension、nested daily、K=3 confirmation 和 confirmed interval 物化。engineering validator、schema/PK、anomaly scan 与 baseline reconciliation 均通过，author-side internal continuation 可以放行 stacked R1-T14-02 implementation。

该结论只表示 R0-T15 author-draft 物化与交接候选完整，不表示独立审阅、repository final gate 或正式 request fulfilled。`independent_review_status=not_started`、`repository_final_gate_status=pending`、`R1-T14-02_allowed_to_start=false`、`formal_task_completed=false` 保持不变。

## 2. 不可变 upstream binding

运行绑定 PR-A #87 head `2e2cc2931a4c3ff1ab427966bc78f79a0f69c151`。PR-A result package、author analysis 和 final author-draft request 的 SHA-256 分别为 `ceb869819569ff4949db4b07febc364cf74eb2bb7419da5f460f7b91e4b06306`、`edc804be74d4a2780b3ebce061e56c38bead7e9d3739c39db474bd5554e530da`、`7ee17192ae32c71d6ee839af93993b4b7f841738dbc0a17e9078ac1d1408fb33`。运行前确认 PR-A internal continuation passed，同时 repository R0 materialization gate 仍为 false。

唯一状态计算输入是 R0-T05 strict-past dimension score；没有重算 raw metrics、percentile score、candidate selection 或 archetype ranking，也没有读取未来收益、波动、方向、路径、回测或交易结果。

## 3. Frozen registry 消费

candidate registry 恰好包含 request 的 10 个 vector ids：W120/W250 各一个 baseline reference、一个 T=.25 center、一个 T=.30 neighbor、一个 V=.30 center 和一个 V=.25 neighbor。formal vector id 由 W/K/qP/qC/qT/qV/state-line role/request id 确定性哈希生成；10 个 id 无碰撞。8 个 nonbaseline vectors 全部物化，未新增、删除或重排 candidate family；两个 baseline 沿用既有正式 lineage，不复制大表。

V=.25/.30 的 same-parameter PCT parent 均绑定相同 W 的 shared-q PCT baseline；T=.25/.30 同时物化其同参数 PCT/PCVT nested lines。R1-T14-02 因而可以严格使用 same-parameter parent，不需要跨 vector 借用 PCT。

## 4. 正式输出与 manifest

四个本地 DuckDB 均完成 checkpoint 并由 artifact manifest 绑定最终字节：

- dimension state：55,384,608 rows、8 vectors、800 securities，SHA-256 `f979cf5c13fab855842e834a2c5af67f4d488022c137140ee4098c4241c8e95a`；
- nested daily state：13,846,152 rows、8 vectors、800 securities，SHA-256 `39ec9c7c798280a67218cc32ce41b8ae854e68f4c1cf7826520c3eb91eab14d1`；
- daily confirmation：55,384,608 rows、8 vectors、800 securities，SHA-256 `310393bf78d58eaf76fa5a02aeb18cfa069c3e917ba1526c014167f9dca00d46`；
- confirmed interval：340,625 rows、8 vectors、794 securities，SHA-256 `40c3ec70e68999d0db413a57e79705d85aabd5d0f8c26c498769d4560992a171`。

前三表日期域为 20160104–20260630；区间 confirmation/end domain 为 20160801–20260625。大 DuckDB 按仓库政策保留为本地、可由 manifest hash 验证的正式运行产物，不强制提交到 Git；registry、manifest、reconciliation、anomaly、analysis 和 package 提交到仓库。artifact manifest SHA-256 为 `4434adfa9fe0941d340ff0f16b194993894cd39c7151acb94e7565e4ea7999a9`。

## 5. Baseline reconciliation

W120/W250 shared baseline 的 S_PCT/S_PCVT 在 raw days、confirmed days、valid/unknown/blocked rows、interval count、confirmed duration 与 open interval 上形成 32 项 reconciliation，`mismatch_count=0`。这证明 q-vector materializer 在 baseline 上复现既有 R0-T07 语义，且 baseline reference 可以安全采用 lineage reuse 而无需复制。

## 6. Center 与 neighbor 实际结果

正式物化与 T14-01 diagnostic 的 raw/confirmed/interval 三层结果对全部 8 个 nonbaseline vectors、S_PCT/S_PCVT 共 16 个组合逐项相等。关键 center/neighbor 如下：

- W120 T=.25 center：S_PCT raw 52,420、confirmed 20,479、7,673 intervals、783 confirmed securities；T=.30 neighbor 为 64,711、29,515、9,499、788。
- W250 T=.25 center：S_PCT raw 46,019、confirmed 18,328、6,958 intervals、782 securities；T=.30 neighbor 为 57,364、27,083、8,562、784。
- W120 V=.30 center：S_PCVT raw 16,073、confirmed 4,567、2,179 intervals、704 securities；V=.25 neighbor 为 13,299、3,723、1,769、669。
- W250 V=.30 center：S_PCVT raw 12,866、confirmed 3,591、1,674 intervals、640 securities；V=.25 neighbor 为 10,172、2,808、1,319、587。

所有 center 与 neighbor 均非全零、非全一、非全 NULL；q=.30 对应 state count 不小于 .25，参数响应存在。这里不重新评价候选优劣，结果只能用于确认物化忠实性与为 T14-02 提供完整 family。

## 7. Confirmation、interval 与 parent-child 守恒

每个 vector/state 的 confirmed true count 与其 confirmed interval duration 总和完全相等。S_PCVT raw/confirmed 均未超出同 vector S_PCT，child violation count 为 0。四张表的主键重复数均为 0：dimension `(vector,security,date,dimension)`、nested `(vector,security,date)`、daily `(vector,security,date,state)` 与 interval id 均唯一。

unknown/blocked 没有静默写成 valid NULL；`null_marked_valid=0`。blocked/unknown rows 按既有 state-specific short-circuit 语义保留，不能按 false state 解读。

## 8. 独立复算

author-side 独立读取四个正式 DuckDB，而不是复用 runner summary，复算了两个 centers、两个 neighbors 和 baseline。W120 T=.25/T=.30 与 W250 V=.30/V=.25 的 total/raw/confirmed/unique-security counts 与正式表一致；两个 baseline 的 32 项指标与 R0-T07 一致。此外，对全部 8 vectors 的 PCT/PCVT raw、confirmed、interval count 和 interval-duration conservation 进行了逐项交叉核对，全部等于 T14-01 diagnostic artifact。

## 9. 异常扫描

11 项强制 anomaly checks 全部通过：registry exact count、baseline mismatch zero、非全 NULL/零/一、unknown validity、parent-child、confirmation/interval conservation、q monotonic response、schema 与 primary key。`blocking_findings=[]`、`unresolved_questions=[]`。工程 validator 重新读取四个 DuckDB 并复核文件 SHA-256、row counts 与 vector counts，结果 passed。

## 10. 有限推断与不可支持结论

直接事实是 R0-T15 已忠实物化 frozen registry，输出 schema、lineage、hash 和数值守恒完整。有限推断是这些本地 formal artifacts 足以作为 stacked Draft PR-C 的精确输入。不能据此声称 T/V q-vector 通过正式结构 null、优于 shared q、构成冻结状态、具有独立 confirmation 或交易价值。

若 PR-A 或 PR-B 的 code/config/registry/request/result package/analysis 任一发生变化，PR-C 必须标记 `stale_dependency=true`，重新绑定新 commit/hash，并重跑所有受影响计算；不得只 rebase 后沿用本结果。

## 11. Goal 内部 continuation 建议

registry 与 request 完全一致，baseline mismatch=0，schema/hash/PK、parent-child、confirmation/interval conservation、anomaly scan 和 independent recomputation 均通过，没有 blocking finding 或 unresolved question。因此 author-side `goal_internal_continuation_gate_status=passed`、`goal_internal_t14_02_authorized=true`。这一内部状态只允许创建 stacked Draft PR-C；`repository_t14_02_gate_passed=false`、`R1-T14-02_allowed_to_start=false` 仍保留，等待外部独立审阅与 final gate。
