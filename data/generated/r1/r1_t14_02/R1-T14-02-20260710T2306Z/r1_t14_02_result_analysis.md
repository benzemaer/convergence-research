# R1-T14-02 层级 q-vector 正式结构复验 result analysis

## 1. Formal registry 与 R0 lineage

权威 author-draft run 为 `R1-T14-02-20260710T2306Z`，代码提交为 `a17bbf676169305fa921ae5e612b3a71ca3acfe4`。formal registry 严格等于 R0-T15 交接的 10 个向量：W120/W250 各 1 个 shared-q baseline reference、1 个 T=.25 center、1 个 T=.30 immediate neighbor、1 个 V=.30 center 和 1 个 V=.25 immediate neighbor，没有运行后增删。12 个 `vector × relevant state line` 的 raw days、confirmed days、证券数、区间数与区间 duration sum 均与 R0-T15 或原 shared-q R0 artifact 一致，mismatch 全为 0。

## 2. Same-sample limitation

本任务是 same-sample formal structural revalidation，不是独立 confirmatory test。T14-01 在同一历史样本上完成提名，T14-02 的 10,000 次置换和 family correction 只控制冻结的 T14-02 family，不能校正 T14-01 更大的 OFAT discovery path。因此所有 package、matrix 和 handoff 永久保留 `selection_path_not_independently_confirmed=true`；以下“supported”仅指预注册结构门槛在同一样本内得到支持。

## 3. Baseline、center 与 neighbor 的存在性

shared-q confirmed state days 为 W120 PCT/PCVT=12,480/2,941，W250=10,854/2,143。T=.25 centers 将 PCT confirmed days 提高至 W120 20,479、W250 18,328；T=.30 neighbors 进一步提高至 29,515、27,083。V=.30 centers 将 PCVT confirmed days提高至 W120 4,567、W250 3,591；V=.25 neighbors 为 3,723、2,808。所有 relevant profiles 均非零、非全一、非全 NULL，证券覆盖 520–788 只；confirmed max-year share 为 .157–.227，低于 .50 门槛。

## 4. Layer intralayer structure

40 行层内结果覆盖每个向量的 P/C/T/V。author-side 对 8 个 `W × layer` continuous Spearman 与 R1-T05 reviewed artifact 对账，average-rank tie semantics 下全部在 `1e-12` 容差内一致；冻结 family 与 T05 相交的 12 个 q=.20/.30 threshold profiles 在 common eligible、both-hit、a-only、b-only、neither counts 上完全一致。受影响层的 Spearman 为 T W120/W250=.65546/.66646、V=.61950/.52894；T/V center/neighbor 的 Jaccard 范围 .284–.425，未显示近乎完全冗余。q 放宽使 both-hit 单调增加，参数响应方向正常。

## 5. Retention、Lift 与 Delta

PCT T=.25 centers 的 T_given_PC retention 为 W120 .3614、W250 .3466，Delta 为 .1582/.1483；shared-q baseline 的 Delta 为 .1216/.1134。T=.30 neighbors 的 Delta 进一步为 .1915/.1807，但 Lift 从 baseline 1.796/1.770 降至 1.752/1.719，显示覆盖与相对 lift 的取舍。PCVT V=.30 centers 的 V_given_PCT retention 为 .4147/.3750，Delta 为 .1694/.1701；baseline Delta 为 .1135/.1007。W120 V=.30 的 Lift 与 baseline 几乎相同（变化 -.00062 in lift-excess），W250 V=.30 改善 .04666。所有 pooled JointExcess 为正。

## 6. Global null

global PCT 和 global PCVT 使用 P 固定、其余目标层在 `security × year × continuous segment` 内按共同 schedule 平移，再按 K=3 重建 confirmation；没有直接平移最终联合状态。F1 PCT 的 observed/null lift 为 3.49–3.95，F2 PCVT 为 4.73–6.00。两个 global families 的 12 个成员 family-adjusted p 均为 `1/10001=.00009999000099990002`。

## 7. Nested null

C_given_P、T_given_PC、V_given_PCT 分别形成 F3/F4/F5。F3 observed/null lift 为 1.74–1.79，F4 为 1.67–1.78，F5 为 1.44–1.57；全部 JointExcess>0。18 个 nested family members 的 adjusted p 同样均为 p-floor。PCVT decision 明确同时绑定同参数 PCT parent 的 F1/F3/F4 通过，不以 global PCVT 替代 V nested gate。

## 8. Max-statistic correction

正式运行固定 `N_perm=10000`。每个 family 的 replicate identity 同时覆盖 W120、W250、baseline、center 和 neighbor；共写出 50,000 行 family maxima、30 行 candidate null results 和 30 行 multiplicity results。所有 `null_sd>0`；studentized observed Z 的 family 范围为 F1 83.77–130.29、F2 46.87–80.05、F3 91.92–96.48、F4 67.70–85.14、F5 18.56–33.17。author-side 逐行复算 `(n_family_extreme+1)/10001` 与 artifact 完全一致。显著性很强，但不能消除选择路径的非独立性。

## 9. Year stability

132 行 year profile 保留 2016–2026 的所有年份行及 2026 partial-year 标记，没有删除零状态年份。四个 centers 的 max-year share 为 W120 V30=.1570、T25=.1816，W250 V30=.2050、T25=.2268。affected step 的 11 个 year Delta 对所有非 baseline 向量均保持正方向；330 行 LOYO 中 Delta 与 Lift-excess 无方向翻转。

## 10. Identity overlap

所有变更都是从 q=.20 向 .25/.30 放宽，因此 baseline confirmed days 全部被保留，lost days=0，baseline retention=1。与此同时 identity 并非等价：T=.25 centers 对 baseline 的 Jaccard 为 .609/.592，新增 7,999/7,474 days；T=.30 neighbors Jaccard 降至 .423/.401。V=.30 centers Jaccard 为 .644/.597，新增 1,626/1,448 days；V=.25 neighbors为 .790/.763。identity 漂移被视为复杂度与解释性代价，不能只报告 coverage gain。

## 11. Interval geometry

12 个 relevant profiles 的 confirmed interval count 为 1,024–9,499，duration median 均为 2；interval duration sum 与 confirmed-day count 全部守恒，open interval 为 0，cross-year interval 为 18–226。PCT fragment rate 从 baseline W120/W250=.455/.461 降至 T25=.383/.378、T30=.327/.309。PCVT fragment rate维持在 .475–.497，V 放宽增加事件量，但没有形成明显更长的中位持续期。

## 12. Neighborhood stability

四个 center 均有预注册 immediate neighbor。center/neighbor 的 global 与 affected nested JointExcess 方向一致，neighbor 非退化且通过 adjusted null；四个 center 均无 isolated-peak warning。neighbor 本身在 decision matrix 中保持 `review_only`，因为其职责是验证局部连续性，不作为另一个正向 handoff center。

## 13. Complexity return

四个 centers 相对 shared-q 的 coverage 与 affected Delta 改善均超过 stability envelope，且 baseline 不在所有重要维度上支配它们。代价是 T centers 的 lift-excess 分别下降 .0178/.0221，W120 V center 下降 .00062；W250 V center 则上升 .0467。所有非 baseline 行属于 `tradeoff_not_dominated`，不是自动 winner，也不表示复杂度已经由外部 reviewer 认可。

## 14. Baseline dominance

shared-q 没有严格支配任何 center 或 neighbor；反之，复杂向量也没有在 coverage、identity、Lift、fragment、年份与简洁性上全面支配 baseline。当前证据应理解为 Pareto tradeoff：放宽 T/V 增加状态日和 pooled Delta，同时扩大 identity novelty；T 放宽还降低 Lift，V 放宽的 security heterogeneity 更明显。

## 15. V construct guard

两个 V=.30 centers 与 V=.25 neighbors 均通过 `selectivity_retained>=.50`、V nested formal gate 和 PCVT 严格窄于同参数 PCT 的保护。raw/confirmed PCVT→PCT 逐日 violation 均为 0。需要保留的 material warning 是 security heterogeneity：V=.30 centers 的 security-level Delta 为负占比分别为 13.92% 和 18.19%，V=.25 neighbors 为 18.61% 和 21.37%；虽然 pooled 与 security median 均为正，不能写成所有证券同向。

## 16. Anomalies 与 root causes

权威 anomaly scan 的 11 项检查全部 passed，blocking/unresolved findings 为空。两次先行正式计算 `2221Z` 与 `2245Z` 不作为当前 evidence：`2221Z` 暴露 decision assembler 未显式计算 PCVT parent PCT gates、security median sign 和逐日 parent-child count；`2245Z` 修复门禁后又在 author-side T05 对账中发现 Spearman ties 使用带空档 rank 而非 average rank。两次修复均未改变 frozen family、seed、null、existence、interlayer、year 或 interval；三次 run 的 null results、family maxima 和 multiplicity SHA 完全一致。只提交 `2306Z` 为当前 author-draft evidence。

## 17. Supported conclusions

同一样本、冻结 family 和正式 max-stat correction 下，四个 centers 均通过对应 global/nested、年份、LOYO、parent-child、邻域、复杂度和 V guard 门槛，状态为 `formal_structure_supported_with_warning`。四个 immediate neighbors 为 `review_only`，并提供中心响应非孤立的证据。R0 lineage、K3 confirmation、interval conservation 与 R1-T05 层内语义得到复验。

## 18. Unsupported conclusions

本结果不支持“独立确认”“最终 winner”“最佳 q”“冻结参数”“预测能力”“因果机制”“稳定交易优势”或 R2 authorization。p-floor 不代表效应大小没有不确定性，也不能校正 T14-01 的选择过程。security-level 负 Delta、identity novelty、T Lift 下降和 PCVT 高 fragment 均限制了强结论。

## 19. R1-T10 handoff recommendation

author-side 建议把四个 centers 及 shared-q baseline 的完整 evidence matrix 交给外部 review；在 review 通过前只设置 goal 内部 completion gate，不设置 repository downstream gate。外部 reviewer 应重点审查：T coverage/Delta 与 Lift 退化的取舍、V security heterogeneity、identity novelty、same-sample selection limitation，以及复杂度是否足以优于 shared-q。当前保持 `scientific_review_status=pending`、`independent_review_status=not_started`、`repository_final_gate_status=pending`、`R1-T10_allowed_to_start=false`、`R2_allowed_to_start=false`、`formal_task_completed=false`。
