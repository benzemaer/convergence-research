# R2-T01 参数候选收敛与 shortlist registry 结果分析

## 1. 研究目标与预注册问题
observed_fact: 本任务绑定 R1-T10 合法交接的 12 行候选，只回答四类处置：primary、strict_core_reference、sensitivity、excluded。research_judgment: 本任务不选择 d/g，不冻结状态版本，不评价未来收益或交易优势；它只把 R1 已交接候选登记为 R2-T03 之前的确定性 shortlist registry。

## 2. 输入 package、lineage、时间与样本范围
observed_fact: run_id 为 `R2-T01-20260711T2345Z`，R1 decision matrix SHA-256 为 `r2_t01_candidate_convergence_shortlist.v1` 配置绑定的 `c3dddd698a0876743e822a55864be06074f94c14a4cd142b44de062a35d83134`，source row count 为 12。observed_fact: source reconciliation failed count 为 0，warning reconciliation failed count 为 0，selection path propagation failed count 为 0。inference: 该结果只继承 R1-T10 的结构证据和行级 warning，不扩展样本或读取行情原始数据。

## 3. 参数网格与 reference baseline
observed_fact: T01 没有运行参数网格；固定输入是 W120/W250、K=3、R1-T10 的 shared-q 与 q-vector 候选。observed_fact: shared-q rows 被登记为 strict_core_reference 且 fallback_eligible=true；q-vector center rows 被登记为 primary；qT=.30 rows 被登记为 sensitivity；qV=.25 rows 被登记为 excluded。research_judgment: shared-q 在本任务中是 reference baseline 和 fallback capability，不是独立产品版本。

## 4. 核心结果
observed_fact: canonical registry 行数为 12，role counts 为 {'primary': 4, 'strict_core_reference': 4, 'sensitivity': 2, 'excluded': 2}。observed_fact: primary shortlist 四条 route 为 `r2_s_pct_w120_qt25_primary, r2_s_pct_w250_qt25_primary, r2_s_pcvt_w120_qv30_primary, r2_s_pcvt_w250_qv30_primary`。derived_statistic: W120 角色分布为 {'primary': 2, 'strict_core_reference': 2, 'sensitivity': 1, 'excluded': 1}，W250 角色分布为 {'primary': 2, 'strict_core_reference': 2, 'sensitivity': 1, 'excluded': 1}。observed_fact: shared-primary pairing 为 {'r2_s_pct_w120_q20_shared': 'r2_s_pct_w120_qt25_primary', 'r2_s_pct_w250_q20_shared': 'r2_s_pct_w250_qt25_primary', 'r2_s_pcvt_w120_q20_shared': 'r2_s_pcvt_w120_qv30_primary', 'r2_s_pcvt_w250_q20_shared': 'r2_s_pcvt_w250_qv30_primary'}。

## 5. 预期结果与实际结果对照
observed_fact: 预期 4/4/2/2 角色计数，实际为 {'primary': 4, 'strict_core_reference': 4, 'sensitivity': 2, 'excluded': 2}；预期 primary 行数 4，实际为 4。observed_fact: audit assignment failed count 为 0。inference: 实际结果与预注册 deterministic mapping 一致，没有产生 automatic winner、preferred window 或排名字段。

## 6. coverage / NULL / unknown / blocked / denominator 检查
observed_fact: evidence snapshot 行数为 12，与 registry 行数一致，并包含 eligible_days、denominator_scope、metric_source_task、metric_source_run 与 coverage_comparable_group。derived_statistic: denominator groups 为 {'same_scope_t14_02_pct_W120': {'rows': 2, 'denominator_scope': 'r1_t14_02_same_sample_ordered_short_circuit_scope', 'eligible_days': ['1602732', '1602732']}, 'same_scope_t14_02_pct_W250': {'rows': 2, 'denominator_scope': 'r1_t14_02_same_sample_ordered_short_circuit_scope', 'eligible_days': ['1503671', '1503671']}, 'same_scope_t14_02_pcvt_W120': {'rows': 2, 'denominator_scope': 'r1_t14_02_same_sample_ordered_short_circuit_scope', 'eligible_days': ['1601692', '1601692']}, 'same_scope_t14_02_pcvt_W250': {'rows': 2, 'denominator_scope': 'r1_t14_02_same_sample_ordered_short_circuit_scope', 'eligible_days': ['1503366', '1503366']}, 'mixed_scope_shared_q_W120_S_PCT': {'rows': 1, 'denominator_scope': 'r1_t01_to_t09_strict_common_valid_mixed_scope', 'eligible_days': ['1730769']}, 'mixed_scope_shared_q_W250_S_PCT': {'rows': 1, 'denominator_scope': 'r1_t01_to_t09_strict_common_valid_mixed_scope', 'eligible_days': ['1730769']}, 'mixed_scope_shared_q_W120_S_PCVT': {'rows': 1, 'denominator_scope': 'r1_t01_to_t09_strict_common_valid_mixed_scope', 'eligible_days': ['1730769']}, 'mixed_scope_shared_q_W250_S_PCVT': {'rows': 1, 'denominator_scope': 'r1_t01_to_t09_strict_common_valid_mixed_scope', 'eligible_days': ['1730769']}}。research_judgment: R1-T10 matrix 是 mixed-scope lineage snapshot；shared-q 的 strict-common-valid denominator 与 R1-T14-02 q-vector ordered short-circuit denominator 不同，不能直接用 confirmed_coverage 的跨角色差值说明 q-vector 覆盖扩大。inference: 只有相同 coverage_comparable_group 内的 q-vector neighbor rows 可做数值响应比较；shared-q 只能作为 fallback/reference identity，不作为同口径 coverage baseline。

## 7. baseline 与至少两个 challenger 对照
observed_fact: baseline 是四个 shared-q strict-core/fallback reference；challenger 一是四个 q-vector center primary；challenger 二是两个 qT=.30 immediate-neighbor sensitivity rows；另有两个 qV=.25 excluded rows 保留 R1 do_not_freeze 结论。inference: 这些对照只用于确认角色处置和限制传播，不构成 winner 排名；涉及 q-vector 数值变化时，仅在 R1-T14-02 same-scope group 内解释方向，不把 shared-q mixed-scope coverage 当成同口径 challenger。

## 8. 参数响应与敏感性
observed_fact: T01 不扫描 d/g，不重扫 K，也不生成新 q-vector。derived_statistic: qT=.30 sensitivity 行数为 2，qV=.25 excluded 行数为 2。research_judgment: 参数响应在 T01 表现为 mutation-sensitive role mapping；若 qT=.30 被改为 primary 或 qV=.25 被改为 sensitivity/excluded 以外角色，validator 必须失败。

## 9. 层级、漏斗、守恒关系与不变量
observed_fact: source rows、candidate disposition registry、canonical shortlist registry 三者均为 12 行；primary shortlist 为 4 行。observed_fact: shared-q 未复制成额外 fallback row，因此 registry 没有扩张为 16 行。inference: shared-q 与同 state_line x W 的 primary route 唯一配对，保持 R1 12 行交接矩阵一一对应。

## 10. 异常结果及根因调查
observed_fact: anomaly blocking errors 为 []。observed_fact: source reconciliation failed count 为 0，warning reconciliation failed count 为 0。research_judgment: 当前 author analysis 未发现 unresolved blocker；若后续 reviewer 发现 warning 丢失、source hash 变化或行级 selection_path limitation 丢失，应标记 blocked_return_to_R1 或 needs_revision。

## 11. 替代解释与反证检查
inference: q-vector rows 的 same-scope 参数响应可能来自阈值放宽和状态身份变化，而非更强的经济结构。research_judgment: T01 只接受 R1 已完成的结构资格和 R2 预注册角色安排，不证明 q-vector 优于 shared-q，也不证明未来预测价值。observed_fact: result package 保持 scientific_review_status=pending，等待独立 reviewer 直接读取 matrix、registry、audit、warning reconciliation 和本报告。

## 12. 研究限制
research_judgment: 本任务没有事件区间、d/g、释放标签、未来路径、交易成本或样本外证据；selection_path_not_independently_confirmed 仍为 package 顶层限制。inference: 任何把四条 primary 解释为最终冻结版本或交易信号的说法均超出本任务证据。

## 13. 可以支持的结论
observed_fact: R1-T10 的 12 行候选被确定性登记为 4 primary、4 strict_core_reference、2 sensitivity、2 excluded。derived_statistic: 每个 W 均为 2 primary、2 strict_core_reference、1 sensitivity、1 excluded。inference: 这些 registry artifacts 可以作为 R2-T02/T03 设计审阅的 author-draft 输入，但不能作为下游正式 completed gate。

## 14. 不可以支持的结论
research_judgment: 本任务不支持哪个 W 最优、哪个状态线最优、哪个候选有交易优势、最终冻结哪个版本、最终选择哪个 d/g、以及任何未来收益、方向、波动或路径结论。

## 15. 下游 gate 建议
research_judgment: author_result_analysis_status 可标记 passed；scientific_review_status、independent_review_status 和 repository_final_gate_status 必须保持 pending。research_judgment: R2-T02_allowed_to_start=false，R3_allowed_to_start=false；只有独立科学审阅和 final gate 通过后，才能考虑推进 R2-T02。
