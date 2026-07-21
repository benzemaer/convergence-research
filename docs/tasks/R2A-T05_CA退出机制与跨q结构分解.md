# R2A-T05 CA q20 退出机制与跨 q 结构分解

## 当前状态与停止点

```text
task_id: R2A-T05
status: authorized_pending_execution
scope_id: r2a_t05_ca_exit_mechanism_decomposition.v1
implementation_version: r2a_t05_ca_exit_decomposition.v1
research_anchor_q: 2000
research_anchor_role: exit_mechanism_decomposition
q_selection_status: not_selected
canonical_dynamic_request_selected: false
formal_execution_review_status: owner_approved
approved_formal_execution_sha: b72e53fc571e2b3eb55dfd0c0499982b276371c6
superseded_formal_execution_sha: 6c7b64adc4fe2afa97a3fe41291bd4e8ee8ce28a
failed_authorization_commit: b798fd044f37fbe6b8174c65b9746362097c20c4
authorization_revision: 1
authorization_parent: b72e53fc571e2b3eb55dfd0c0499982b276371c6
authorization_status: authorized_pending_execution
formal_run_allowed: true
formal_run_started: false
formal_run_attempts_consumed: 0
real_score_data_read: false
real_score_metadata_read_for_manifest: true
formal_artifacts_generated: false
R2A-T05_DONE: absent
R2A-T06_started: false
R2A-T06_allowed_to_start: false
PR_state: Draft
```

上一轮对精确 candidate `6c7b64adc4fe2afa97a3fe41291bd4e8ee8ce28a` 的 authorization commit `b798fd044f37fbe6b8174c65b9746362097c20c4` 已因 Git 非 ASCII 路径 quoting 在 preflight 前失败并停止。修复提交 `b72e53fc571e2b3eb55dfd0c0499982b276371c6` 已通过对应 Quality；owner 已批准该精确 formal-execution candidate，本轮已生成其唯一新 manifest 并进入 metadata-only authorization，尚未执行 preflight 或 formal。

## 研究问题

T05 只回答：已确认的 CA 区间为何终止，终止时 C/A 距离各自门槛多远，终止是否在同一 q 的后续状态中快速重入，以及 q20 在 q10/q15/q25 严格嵌套结构中的核心、外壳、边界和碎片结构。T05 不回答 release onset、recognition、方向、强度、未来路径、收益、回测、信号、组合或交易价值，也不比较哪一个 q 更优。

## 锚点与请求身份

T05 的研究锚点是 accepted T04 request `CA_q20_k5`，但它只是退出机制分解的研究锚点，不是 best、optimal、selected canonical、winner 或正式参数选择：

```text
request_id: pcavt-dynreq-v1-21bd144aaed98d9e
request_hash: 21bd144aaed98d9e7d404aaa8d2fa0685f7ec29a3deb714d0d1df99c05d5e971
selected_dimensions: [C, A]
q_by_dimension: {C: 2000, A: 2000}
confirmation_k: 5
selection_status: evaluated_not_selected
```

q10、q15、q25 只作为跨 q 结构比较。其完整 request ID、request hash、selected dimensions、q 和 K 必须从 accepted T04 handoff/config 读取，并由 validator 对账；实现不得根据简称手工重造身份。

## 输入边界

未来 formal T05 只允许绑定 accepted T01 canonical Score release、accepted T03 evaluator/protocol identity、accepted T04 handoff/config 及 repository-local `data/**`。实现只读上述状态和 Score 表；不读取价格、收益、未来路径或交易结果字段。当前 candidate 只能使用 synthetic fixture。T06 的 no-lookahead/PIT 要求保留为未来 release 标签协议的强制验收条件，但 T05 不实现 T06、不创建 T06 config/schema/runner、不读取价格数据。

## 退出终点与一级分类

分析单位是 accepted v1 evaluator 的每个 confirmed interval，区间定义和退出规则保持不变，不引入退出延迟、hysteresis、gap tolerance、自动合并或其他 d/g 变体。每个 interval 保留 confirmation date、last confirmed end、termination observation date、原始 primary reason 和 right-censored。

一级分类固定为：

```text
raw_false
quality_or_availability_termination
input_end_open_right_censored
```

质量/可用性类必须继续保留 accepted protocol 的原始 primary reason：expected observation missing、listing pause、blocked、diagnostic required、unknown、not eligible、score non-finite。只有 `raw_false` 才按 termination observation 的 C/A active 状态划分为且仅为一个 `A_ONLY_FAIL`、`C_ONLY_FAIL` 或 `CA_BOTH_FAIL`；C/A 同时 active 而 joint raw=false 视为 evaluator/lineage mismatch 并阻塞，不产生 `raw_false_unclassified`。

## 阈值距离

对 D∈{C,A}，在 last confirmed end 和 termination observation 两个端点计算：

```text
main_threshold_D = 1 - q_D
weak_threshold_D = 1 - q_D - 0.10
mean_margin_D = score_dimension_D - main_threshold_D
min_margin_D = score_dimension_min_D - weak_threshold_D
active_margin_D = min(mean_margin_D, min_margin_D)
```

margin 保留有符号值，使用 accepted epsilon `1e-12`。gate failure 固定为 `MAIN_ONLY_FAIL`、`WEAK_ONLY_FAIL`、`MAIN_AND_WEAK_FAIL`、`NO_GATE_FAIL` 和 `NOT_EVALUABLE`。结果还必须保留 C/A 的 dimension mean、dimension min、两个 component Score、eligibility、validity 和 reason codes。报告会扫描 margin 的全 NULL、全零、常数列、全一和数量级异常，并报告端点变化、raw_false 子类分布、gate 构成、年度分布和证券分布。

## 快速重入

快速重入只使用同一 q request 的后续 CA 状态。连续性以同一证券的 `observation_sequence` 计算，不使用 calendar-day 差值，也不跳过 missing/listing pause。每个非 right-censored termination record 都保留 `first_raw_true_lag`、`first_confirmed_true_lag`、`first_quality_interruption_lag`、`max_observed_followup_lag` 和 `followup_input_end_censored`；raw 的 1/3/5 与 confirmed 的 5/10 各自独立分类。若 event 在阈值内且早于首个 quality interruption，则为 `reentered`；若首个 quality interruption 在阈值内且此前没有 event，则为 `quality_interrupted`；没有 event/quality 且观测不足阈值才是 `insufficient_followup_censored`，完整观测到阈值而无 event 才是 `not_reentered_within_window`。profile 的主分母固定为 `reentered_count + clean_not_reentered_count`，不把 quality 或 input-end censored 放入主分母；`reentry_rate` 在分母为零时为 NULL。快速重入不会修改、删除、合并或追认原 accepted interval。

## 跨 q 结构

只使用 accepted daily confirmed-state 的严格嵌套关系 `q10 ⊆ q15 ⊆ q20 ⊆ q25`。每个 child 的全部 confirmed observation keys 必须唯一包含于一个 parent interval；child 横跨 parent 或找不到 parent 时 fail closed。日级身份的全局主键至少为 `(security_id, observation_sequence, q25_parent_interval_ordinal)`，每个 q25 parent confirmed 日恰好一行，不能按 q20 sibling 重复展开。身份按全局 confirmed sets 严格派生：先 `Q10_CORE`，否则 `Q15_NOT_Q10_CORE`，否则 `Q20_NOT_Q15_ANCHOR`，否则 `Q25_NOT_Q20_SHELL`；唯一性、全覆盖、行数和差分守恒都必须通过。`cross_q_structure_summary` 以 q25 parent 为一行，至少输出 `q25_parent_confirmed_day_count`、所有 q20 child 的并集 `q20_confirmed_day_count_inside_parent`、`q25_only_shell_day_count`、`q20_child_interval_count` 和 `q20_fragmented_within_q25_parent`，其中 parent shell 必须是 q25 confirmed days 减去所有 q20 sibling 的并集。child 另行输出 `q25_local_leading_shell_days`、`q25_local_trailing_shell_days` 和 `q25_local_adjacent_shell_days`；这些只统计 child 两端与 parent 边界/另一个 q20 confirmed day 之间的连续 q25-only observations，中间 q25-only gap 可分别计入前一 child 的 trailing 和后一 child 的 leading。

## Accepted T04 对账事实

未来 formal run 必须重新计算四个 request，并逐项对账 accepted T04：

| Request | Raw true | Confirmed true | Intervals | Securities with interval |
| --- | ---: | ---: | ---: | ---: |
| CA_q10_k5 | 20,559 | 1,916 | 751 | 473 |
| CA_q15_k5 | 46,651 | 7,125 | 2,426 | 734 |
| CA_q20_k5 | 81,535 | 17,642 | 5,372 | 775 |
| CA_q25_k5 | 124,893 | 35,098 | 9,107 | 788 |

任一 request identity、Score identity、日期/证券覆盖、daily state、interval 或 count reconciliation 不一致，必须停止结果解释和下游推进。

## Candidate package contract

未来 formal package 的 compact review files 为 `request_identity.json`、`input_manifest.json`、`run_summary.json`、`validation_receipt.json`、`result_analysis.md`、`request_reconciliation.csv`、`termination_reason_profile.csv`、`raw_false_exit_decomposition.csv`、`threshold_margin_summary.csv`、`quick_reentry_profile.csv`、`cross_q_structure_summary.csv`、`cross_q_child_structure_summary.csv`、`year_profile.csv`、`security_profile.csv` 和 `deterministic_interval_samples.csv`。完整逐区间 inventory、逐日身份和 mapping 只能保存于 repository-local git-ignored DuckDB/Parquet；本 PR 不生成这些 formal artifacts。

## Validator 与 result analysis

validator 不接受 builder 自报 counts 作为充分证据。它必须独立复算四个 request identity、T04 counts、raw/confirmed subset、termination 分类、margin 公式、observation-sequence lag、follow-up censoring、唯一 parent mapping、daily identity 守恒、表间 reconciliation、输入字段白名单、排序确定性和退化输出。synthetic tests 覆盖正常分类、质量终止、right censoring、raw/confirmed 重入、follow-up 不足、多 child parent、跨 parent、subset violation、margin 符号翻转、calendar/observation lag 混淆、T04 count mismatch 和未授权字段注入。

正式运行后必须立即读取实际结果包并提交独立 `result_analysis.md`。若出现全零、全 NULL、全一、参数无响应、层级关系异常、数量级突变、availability 不一致、T04 count mismatch、raw_false 无法分类、parent 不唯一或 re-entry 语义异常，必须阻塞并调查，不能标记 completed、创建 DONE、推进 README gate 或允许 T06。

## Previous formal authorization failure 与 repair 停止点

```text
superseded_formal_execution_sha: 6c7b64adc4fe2afa97a3fe41291bd4e8ee8ce28a
failed_authorization_commit: b798fd044f37fbe6b8174c65b9746362097c20c4
authorization_parent: 6c7b64adc4fe2afa97a3fe41291bd4e8ee8ce28a
failed_authorization_quality_run_id: 29772023752
failed_authorization_quality_status: completed
failed_authorization_quality_conclusion: success
failed_preflight_reason: authorization_diff_outside_whitelist
failed_preflight_cause: Git path quoting for non-ASCII task-document path
authorization_status: not_authorized
formal_run_allowed: false
formal_run_started: false
formal_run_attempts_consumed: 0
RunRoot: absent
superseded_manifest_1_path: data/generated/r2a/r2a_t05/formal-authorization/r2a_t05_formal_input_manifest.v1.json
superseded_manifest_1_sha256: 6c6a916423f949183941010e0cc2d77df1fa9f91e2a913edaa7d8eb08e197cd4
superseded_manifest_1_byte_size: 10449
superseded_manifest_2_path: data/generated/r2a/r2a_t05/formal-authorization/6c7b64adc4fe2afa97a3fe41291bd4e8ee8ce28a/r2a_t05_formal_input_manifest.v1.json
superseded_manifest_2_sha256: f11f87b7490a0d89133437a62eb657fad7c86b4c5bbf3fc10808706ffe42219a
superseded_manifest_2_byte_size: 10449
R2A-T05_DONE: absent
R2A-T06_allowed_to_start: false
```

本轮 repair 的历史停止点保持不变。当前 owner 授权只允许一个 metadata-only authorization commit；该 commit 完成并通过精确关联的 Quality 后，才执行一次 preflight 和一次 formal run。T06 只有在 T05 formal 结果审阅、异常扫描和相应 gate 完成后才可重新立项，当前 `R2A-T06_allowed_to_start=false`。

## Current formal authorization

```text
approved_formal_execution_sha: b72e53fc571e2b3eb55dfd0c0499982b276371c6
authorization_revision: 1
authorization_parent: b72e53fc571e2b3eb55dfd0c0499982b276371c6
authorization_status: authorized_pending_execution
formal_manifest_relative_path: data/generated/r2a/r2a_t05/formal-authorization/b72e53fc571e2b3eb55dfd0c0499982b276371c6/r2a_t05_formal_input_manifest.v1.json
formal_manifest_sha256: d4f9c83dc198003d55bc3d32d0ae50a4603ccc0b601107b42111f23d313ca13b
formal_manifest_byte_size: 10449
real_score_metadata_read_for_manifest: true
formal_run_started: false
formal_run_attempts_consumed: 0
R2A-T05_DONE: absent
R2A-T06_allowed_to_start: false

## DuckDB bulk-copy repair candidate rerun

failed_authorization_commit: 307dab1f2189aaf8d3c4268b54d42c6f4a3fa96d
failed_formal_run_id: R2A-T05-20260721T013805600Z
historical_formal_attempts_consumed: 1
accepted_copy_diagnosis: copy_path_dominant
accepted_validator_diagnosis: driver_cumulative_timeout
latest_promotion_driver_failure: output_parent_missing
repair_scope: DuckDB-native bulk source staging
q_level_parallelism: false
candidate_authorization_status: not_authorized
formal_retry_authorized: false
R2A-T05_DONE: absent
R2A-T06_allowed_to_start: false

The rerun restores the previously locally tested DuckDB ATTACH READ_ONLY plus
INSERT SELECT source-staging implementation. The connection entrypoint remains
the legacy Python streaming oracle, while the path entrypoint uses bulk staging.
The non-formal promotion driver must pre-create the four-request serial output
root and each request output parent, verify that the parent exists before the
evaluator child starts, and flush an output_parent_verified event. No formal
manifest, authorization, preflight, formal run, DONE marker, or T06 transition
is permitted in this rerun.
```
