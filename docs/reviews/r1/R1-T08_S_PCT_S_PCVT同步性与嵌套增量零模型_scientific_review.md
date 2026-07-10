# R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型科学审阅

`reviewer_identity`: benzemaer
`reviewer_role`: independent_scientific_reviewer
`implementation_actor`: codex
`independence_attestation`: true
`reviewed_code_commit`: 59218fa714f3275f7bdc4995265f381aa1140fa5
`reviewed_pr_head_commit`: b5d12918f434a7aea7f701468b199234d273eef2
`reviewed_summary_sha256`: 0d10c21bd05778bd770384624b3297a0156375d6046014235c026361805f400f
`reviewed_analysis_sha256`: 66a23faefb5ed98ea4ca3da063bc7a774ca75377e15d83aceaac2aafd2b3a0b8
`scientific_review_status`: passed
`downstream_gate_recommendation`: true
`review_source`: https://github.com/benzemaer/convergence-research/pull/84#issuecomment-4937738056

## 独立复算

已从 committed count、replicate 与 aggregate artifacts 独立复算四个 global coverage。W120 S_PCT 为 `12480/1730769=0.007210667628089017`，JointLift 为 `0.007210667628089017/0.0018381912895366163=3.9226970931`；W120 S_PCVT 为 `2941/1730769=0.0016992446710104006`。W250 S_PCT 与 S_PCVT 分别为 `10854/1730769=0.006271200836160112` 和 `2143/1730769=0.00123817794286817`。四组均有 `n_extreme=0`，经验 p 正确为 `(0+1)/(2000+1)=0.0004997501249375312`，不是 p=0。

Nested observed retention 与 R1-T06 count 一致：W120 C 为 `145033/(145033+175677)=0.4522247513`，T 为 `39800/(39800+105233)=0.2744203043`；W250 V 为 `7860/(7860+26450)=0.2290877295`。六个 nested groups 均有 `n_extreme=0`，null mean 数量级合理。

## 审阅结论

实际执行严格限于四个 candidate、十个 test groups 和每组 2,000 permutations。Observed raw/confirmed/confirmation-time/interval、R1-T04 profile 与 R1-T06 nested retention mismatch 均为 0。20,000 replicate 与 22 aggregate 行完整，failed simulation=0。每个 W 有 8,677 blocks、8 个 singleton；shiftable offset=0、越界、跨块和 payload preservation violation 均为 0。Validator 从 root seed 重建全部 offset-plan hash 与 chain hash。

未发现 blocking finding。结果支持 observed S_PCT/S_PCVT 同期结构和 C/T/V nested retention 超过当前预注册 circular-shift null；W120/W250 方向一致。PCVT duration/fragment 分离弱于 coverage，不否定主 coverage 结果，但不得写成几何指标全面通过。

## 非阻断警告与边界

主 null 固定 P，具有 anchor asymmetry。尤其需要明确：被移动的是 raw、validity 与 reason 的完整 payload，因此 primary global null 同时打破 active-state alignment 和 validity/availability alignment；JointLift 不能解释为纯 active=true 同步倍数。独立 security-year shift 也破坏共同市场 regime 对齐，不能排除共同环境、共享输入、定义重叠或非平稳性。

结果为 pooled panel，尚未完成 R1-T09 年份稳定性与状态集中度检查。`n_extreme=0` 仅达到 1/2001 的分辨率下限，不能用于 W120/W250 winner 排名。本结果不支持因果、预测、交易、最优参数、冻结候选或直接进入 R2。

## Gate 建议

科学审阅结论为 passed，blocking findings 为空，建议 downstream gate 放行至 R1-T09。README 只推进至 `R1-T09 年份稳定性与状态集中度检查`；R1-T10 与 R2 继续保持未授权，最终授权以 final-gate package validator passed 为准。
