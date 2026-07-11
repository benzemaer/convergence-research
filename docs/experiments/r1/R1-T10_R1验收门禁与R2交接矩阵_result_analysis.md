# R1-T10 R1 验收门禁与 R2 交接矩阵：结果分析

## 研究问题与证据边界

本次验收回答的是：已合法关闭的 R1 结构实验能否形成一个确定、可审计的 R2 决策输入。它不是新实验，不用未来结果选参数，也不把 `freeze_candidate` 解释为已经冻结。

上游 registry 绑定 12 个 task。T01–T03 通过显式 legacy adapter 绑定其协议、审计和 profile 产物；T04–T09 绑定 current result package、独立审阅和 final-gate validation；T14 路线分别绑定 discovery history、R0-T15 权威物化以及 T14-02 final package。superseded T14-02 runs 未进入证据。实际文件 SHA 在 registry 中复算，source hash mismatch 与 superseded source 均为零。

## 12 行矩阵与逐行判定

矩阵恰好包含 4 行 shared-q、4 行 center 和 4 行 neighbor。判定结果为 `freeze_candidate=4`、`review_candidate=6`、`do_not_freeze=2`、`blocked_return_to_R0=0`。只读 validator 独立按角色、q-vector、parent window、warnings 和 precedence 复算，逐行 mismatch 为零。

Shared-q 的 W120 与 W250 均通过存在性、层内、同期层间、global/nested null 和年份方向门禁。W120 的 coverage 与短历史可用性、W250 的长窗口身份与样本可用性是结构取舍，不能据此宣称某窗口更优。T07 仅是 secondary evidence：P→T 长 lag 弱化或转负，C/V 短 lag 可由 target pre-existence 与 persistence 部分解释，P→PCVT 存在证券异质性；这些不作为 hard veto。

T=.25 centers 的 coverage 与 Delta 相对 baseline 增加，但 Lift 下降且增加 q-vector 复杂度，因此进入 R2 review。V=.30 centers 增加 coverage 和 V Delta，confirmed-state-day 口径仍保留约 83% baseline selectivity，但存在证券级 negative-Delta heterogeneity，同样进入 review。所有 T14 行保留同样本 selection path 未独立确认的独立布尔标记。

T=.30 neighbors 具有正式结构和 null 支持，但其角色是更远离 shared baseline 的 upper neighbor，不能直接 freeze。V=.25 neighbors 与 robust envelope 等价，复杂度收益不足，故为 `do_not_freeze` 并仅保留 sensitivity 角色。p-value 均接近模拟分辨率下限，未用于排序。

## 验收、异常与可支持结论

八项 stage checklist 全部为 `passed` 或 `passed_with_warning`。R1-T11/T12/T13 均未触发：当前没有 hard baseline/challenger 冲突、主 null 不是结论敏感 blocker，也没有授权的替代指标或构念失效 warning。异常扫描未发现缺行、重复、跨窗口 parent、warning 丢失、全同状态、错误 selection flag 或 decision mismatch。

可以支持的有限结论是：R1 的结构证据与拒绝/保留规则已形成可供 R2 裁决的完整矩阵。不能支持最佳 q、最佳 W、最终 state、预测有效性或交易优势。R2 必须决定窗口与状态版本语义、qT 解耦的简约性、qV selectivity/heterogeneity 取舍，并保留同样本选择尚未独立确认这一限制。

README 只应记录 author-draft 完成并等待外部科学审阅；本 PR 不开放 R2。
