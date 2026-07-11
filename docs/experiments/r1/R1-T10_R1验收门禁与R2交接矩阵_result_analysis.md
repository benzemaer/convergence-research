# R1-T10 R1 验收门禁与 R2 交接矩阵：结果分析

## 研究问题与证据边界

本次验收回答的是：已合法关闭的 R1 结构实验能否形成一个确定、可审计的 R2 决策输入。它不是新实验，不用未来结果选参数，也不把 `freeze_candidate` 解释为已经冻结。

上游 registry 绑定 12 个 task。T01-T03 通过显式 legacy adapter 绑定其协议、审计和 profile 产物；T04-T09 绑定 current result package、独立审阅和 final-gate validation；T14 路线分别绑定 discovery history、R0-T15 权威物化以及 T14-02 final package。superseded T14-02 runs 未进入证据。REV3 使用 schema-aware adapters 读取 `validator_status`、`author_package_validator_status`、repository merge transition、external review 与 T14-02 final package；12 个 upstream reconciliation 均为 `passed`。实际文件 SHA 在 registry 中复算，source hash mismatch 与 superseded source 均为零。正式任务 lineage 不再使用 `repository_main_history` 占位：T01 与 T04-T09、T14-01、R0-T15、T14-02 均绑定真实 repository merge commit，T02-T03 通过 legacy adapter 绑定可追溯历史 commit。`r1_t10_readme_transition_artifact.json` 由 T10 显式绑定 T14-02 final README hash、PR #89 merge commit、当前 README hash、允许字段与实际变更字段；不再要求 T14-02 历史 final-gate validator 接受下游 README 变化。

## 12 行矩阵与逐行判定

矩阵恰好包含 4 行 shared-q、4 行 center 和 4 行 neighbor。判定结果为 `freeze_candidate=4`、`review_candidate=6`、`do_not_freeze=2`、`blocked_return_to_R0=0`。q-vector 的 `target_marginal` 字段映射已修复，所有行均通过 `retention = Lift x target_marginal` 与 `Delta = retention - target_marginal` 的逐行代数检查；mandatory scientific field 缺失不再静默填零。REV3 validator 不再导入 builder decision function，而是通过独立只读 precedence engine 按角色、q-vector、parent window、warnings 和 gate status 复算，逐行 `expected_status / actual_status / mismatch_reason` 见 `r1_t10_decision_recomputation.csv`，mismatch 为零。precedence 状态机已按 R1 定义拆分：input、lineage、schema、PIT、validity、confirmation、interval 或 R0 lineage 类失败才返回 `blocked_return_to_R0`；存在性、构念、层间增量、global/nested null、年份稳定性、复杂度和多重性等科学 hard gate 失败返回 `do_not_freeze`。当前 4/6/2/0 分布未因此改变。

Shared-q 的 W120 与 W250 均通过存在性、层内、同期层间、global/nested null 和年份方向门禁。W120 的 coverage 与短历史可用性、W250 的长窗口身份与样本可用性是结构取舍，不能据此宣称某窗口更优。T07 仅是 secondary evidence：P→T 长 lag 弱化或转负，C/V 短 lag 可由 target pre-existence 与 persistence 部分解释，P→PCVT 存在证券异质性；这些不作为 hard veto。

T=.25 centers 的 coverage 与 Delta 相对 baseline 增加，但 Lift 下降且增加 q-vector 复杂度，因此进入 R2 review。PCT q-vector 的 nested null 现在确定性绑定 `F4_T_GIVEN_PC`，不依赖 CSV 行序；例如 W120 T=.25 的 nested lift 为 `1.7589168403073427`，W250 T=.25 为 `1.6940180296944136`。V=.30 centers 增加 coverage 和 V Delta，confirmed-state-day 口径仍保留约 83% baseline selectivity，但存在证券级 negative-Delta heterogeneity，同样进入 review；PCVT q-vector 的 nested null 确定性绑定 `F5_V_GIVEN_PCT`。所有 T14 行保留同样本 selection path 未独立确认的独立布尔标记。

T=.30 neighbors 具有正式结构和 null 支持，但其角色是更远离 shared baseline 的 upper neighbor，不能直接 freeze。V=.25 neighbors 与 robust envelope 等价，复杂度收益不足，故为 `do_not_freeze` 并仅保留 sensitivity 角色。p-value 均接近模拟分辨率下限，未用于排序。

## 验收、异常与可支持结论

八项 stage checklist 全部为 `passed` 或 `passed_with_warning`。checklist 状态由 upstream reconciliation、warning 和 gate grouping 动态生成；若任一 supporting task reconciliation 失败，对应 checklist 会转为 `failed`，相关矩阵行的 `input_gate_status` 也会 fail closed。shared-q 行级 lineage 现在逐行绑定 R1-T01 至 R1-T09 的 source artifact/hash，而不是只绑定 T04/T06/T08/T09；q-vector 行继续绑定 T14-01、R0-T15 与 T14-02。R1-T11/T12/T13 均未触发：当前没有 hard baseline/challenger 冲突、主 null 不是结论敏感 blocker，也没有授权的替代指标或构念失效 warning。异常扫描未发现缺行、重复、跨窗口 parent、warning 丢失、全同状态、错误 selection flag 或 decision mismatch；`upstream_reconciliation_failed_count=0`。

REV3 的 failure-path tests 改为复制完整最小合法 fixture，并在 mutation 前先断言 validator passed；mutation 后检查特定 error code，而不是依赖缺失文件天然失败。覆盖路径包括缺行、跨窗口 parent、V=.25 非法升级、upstream fail、superseded/duplicate source、review/final-gate fail、source hash mismatch、缺失 marginal、错误 F4/F5 nested family、warning loss、scientific hard-gate precedence mismatch、optional-trigger conflict 和非法 README transition。

可以支持的有限结论是：R1 的结构证据与拒绝/保留规则已形成可供 R2 裁决的完整矩阵。不能支持最佳 q、最佳 W、最终 state、预测有效性或交易优势。R2 必须决定窗口与状态版本语义、qT 解耦的简约性、qV selectivity/heterogeneity 取舍，并保留同样本选择尚未独立确认这一限制。

README 只应记录 author-draft 完成并等待外部科学审阅；本 PR 不开放 R2。
