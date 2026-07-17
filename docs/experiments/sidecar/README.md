# Sidecar experiments

本目录只记录独立支线探索，不替代 `docs/tasks/README.md`，也不改变 R0–R6 的任何 gate、状态定义、freeze manifest 或主线任务指针。

当前 sidecar program 状态：

```text
current_sidecar_program: EXP-A
current_sidecar_task: EXP-A02 formal execution activation
workflow_mode: long_lived_same_pr
phase: formal_execution_activation_implementation_review
approved_A02_aggregate_implementation_sha: f6f0dc961357ffe2f4cc43c07be11e804a7af992
formal_execution_activation_sha:
formal_execution_activation_review_status: pending
implementation_review_status: pending
reviewed_implementation_sha:
formal_run_allowed: false
formal_run_status: not_started
formal_run_executed: false
formal_artifacts_generated: false
formal_run_id:
execution_sha:
result_review_status: not_started
formal_result_review_status: not_started
EXP-A01_status: completed_accepted
EXP-A01_accepted_run_id: EXP-A01-20260717T040145984Z
EXP-A01_accepted_result_commit: b7be2577233c045e507efe05d20601a20d373c9b
EXP-A01_execution_sha: c9a52dc29f7d41c85ab416e99bb9ef8cc6411b9d
EXP-A02_started: true
EXP-A02_implementation_review_status: pending
EXP-A02_reviewed_implementation_sha:
EXP-A02_formal_run_allowed: false
EXP-A02_formal_run_status: not_started
EXP-A02_formal_run_executed: false
EXP-A02_formal_artifacts_generated: false
EXP-A02_result_review_status: not_started
EXP-A02_real_authorized_input_manifest_created: false
EXP-A02_real_raw_opened: false
EXP-A03_started: false
program_phase: A02_formal_execution_activation_implementation
mainline_task_unchanged: true
mainline_current_task: R3-T02
```

EXP-A 是长期 sidecar program。EXP-A01 已完成并接受，保留 A1、A2、A2b 三个价格—均线贴合 raw metric 候选及其 compact result package；A 层尚未成立，没有正式指标选择，没有 PCATV。当前任务仅激活 EXP-A02 的 formal execution path，使用已接受 EXP-A01 的五项 artifact 作为唯一上游契约：accepted-result handoff、raw metrics、A01 manifest、A01 validator result 和 A01 anomaly scan。A02 的九张 compact CSV、validator 的聚合定义、denominator、quantile、domain、grid、availability、reason-code 和 anomaly 口径均未改变；本次只接入正式 manifest、精确 SHA 门禁、只读输入、before/after hash 和原子 compact-package 发布路径。不生成或复制 raw DuckDB，不消费 D3 证据，不执行全量 Python raw-row 遍历，不输出 percentile、score、state、winner、replacement、future outcome 或交易结果。真实 authorized manifest 尚未创建，真实 A01 raw 尚未打开，formal run 保持关闭，formal activation review 仍 pending；A03 未开始。

EXP-A01 只复用 `D3_T07_CANDIDATE_DAILY_OBSERVATION_CONTRACT_V1` 的 `d3_t07_candidate_daily_observation.duckdb` / `d3_candidate_daily_observation` research candidate，角色为 `exploration_research_candidate`，`formal_data_version=false`。当前实现不再混用 D3 value-layer，也不强行映射 D3-T07 未声明的 `continuous_ohlc_integrity_status`、`adjustment_method`、`factor_as_of_time` 或 `corporate_action_flag`。`listed_open_resolved_daily` 是 D2/D3 已解析的上市开放交易日状态，在 A01 中作为可用的 present observation；它不改变 suspended、listing_pause、missing 或 unresolved 的非有效语义。在 owner-approved 的四项输入契约中，formal manifest 绑定 D3-T07 handoff/quality 以及独立授权的 dense `expected_price_observation_index`，不要求 D3-T08 evidence；其相关检查已由 D3-T07 gate、主表检查、dense reconciliation、全量 persisted invariant/profile validation 和确定性分层独立 oracle 覆盖。expected index 与 D3-T07 主表必须双向逐 key reconcile，非 present slot 不得被压缩。EXP-A01 的真实 formal result 已被接受；该接受只作为 A02 的固定上游 lineage，不延伸为 A02 formal-run 授权。它不修改正式 PCVT、PCATV、candidate registry、freeze manifest、state version 或主线状态机，不使用未来观测，不输出 percentile、score、state、winner、replacement、future outcome 或交易结果。

EXP-C01 历史记录：

```text
task_id: EXP-C01
phase: completed
implementation_review_status: approved
formal_run_allowed: true
formal_run_status: completed
formal_run_executed: true
formal_run_id: EXP-C01-20260715T181429267Z
result_review_status: accepted
EXP-C01_status: completed_accepted
accepted_run_id: EXP-C01-20260715T181429267Z
accepted_result_commit: 54ed238609d116c784b121a5b6df72e4c0179fc8
completion_governance_commit: e93311d253cf572692fc2533a57b5a4f5dc90a2c
execution_sha: 58020f299b2c1def96c10eb49778afd6d1eb09d5
authorized_input_manifest_sha256: 2d10de31897955595a33d642cfdfe57773b3304a8bd0b763aea56253a5e9e0fa
replacement_decision: not_approved
selected_indicator: none
retain_current_C1_C2_pair: true
mainline_task_unchanged: true
```

EXP-C01 的正式结果已由用户接受：C1-only 与 C2-only 均未达到预注册 strong-substitutability reference，保留当前 C1+C2 pair，不选择或删除指标，不创建 C v2。EXP-A 不继承 EXP-C01 的 formal-run 授权；本 program 当前处于 EXP-A02 implementation review，A02 formal run 仍未授权，下一阶段必须由用户明确授权。
