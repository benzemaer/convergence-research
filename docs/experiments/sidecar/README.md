# Sidecar experiments

本目录只记录独立支线探索，不替代 `docs/tasks/README.md`，也不改变 R0–R6 的任何 gate、状态定义、freeze manifest 或主线任务指针。

当前 sidecar program 状态：

```text
current_sidecar_program: EXP-A
current_sidecar_task: EXP-A01 价格—均线贴合候选 raw metric
workflow_mode: long_lived_same_pr
phase: implementation_review
implementation_review_status: needs_revision
reviewed_implementation_sha:
formal_run_allowed: false
formal_run_status: not_started
formal_run_executed: false
formal_artifacts_generated: false
result_review_status: not_started
EXP-A02_started: false
program_phase: A01_formal_execution_package_implementation
mainline_task_unchanged: true
mainline_current_task: R3-T02
```

EXP-A 是长期 sidecar program，当前只实现 EXP-A01：A1、A2、A2b 三个价格—均线贴合 raw metric 候选及其 formal execution package。A 层尚未成立，没有正式指标选择，没有 PCATV，也没有真实 formal run。当前 package 已包含四项输入授权、set-based raw materialization、四张 compact CSV、全量 persisted invariant/profile validation、确定性分层独立 oracle、validator、anomaly scan、result analysis 和 atomic publish/cleanup；只在临时 synthetic 输入上验证。大输入不执行全量 Python raw-row 复算，小输入仍执行完整 oracle。当前 owner governance override 只改变执行资源：单一 Python 进程、单一 DuckDB 连接、单一 writer、DuckDB 12 threads、12GB memory limit；科学公式、SQL、dense-window、输入契约和输出契约不变。该 override 在 exact-head Quality 成功后自动承接执行授权，`formal_run_executed=false`、`formal_artifacts_generated=false`；A02–A06 尚未开始，每个后续阶段都必须经过独立 implementation commit、用户 exact-SHA 审阅、明确的 formal-run 授权和 Formal-result 审阅后才能推进。

EXP-A01 只复用 `D3_T07_CANDIDATE_DAILY_OBSERVATION_CONTRACT_V1` 的 `d3_t07_candidate_daily_observation.duckdb` / `d3_candidate_daily_observation` research candidate，角色为 `exploration_research_candidate`，`formal_data_version=false`。当前实现不再混用 D3 value-layer，也不强行映射 D3-T07 未声明的 `continuous_ohlc_integrity_status`、`adjustment_method`、`factor_as_of_time` 或 `corporate_action_flag`。`listed_open_resolved_daily` 是 D2/D3 已解析的上市开放交易日状态，在 A01 中作为可用的 present observation；它不改变 suspended、listing_pause、missing 或 unresolved 的非有效语义。在 owner-approved 的四项输入契约中，formal manifest 绑定 D3-T07 handoff/quality 以及独立授权的 dense `expected_price_observation_index`，不要求 D3-T08 evidence；其相关检查已由 D3-T07 gate、主表检查、dense reconciliation、全量 persisted invariant/profile validation 和确定性分层独立 oracle 覆盖。expected index 与 D3-T07 主表必须双向逐 key reconcile，非 present slot 不得被压缩。没有授权真实 index 时，formal run 保持 blocked。它不修改正式 PCVT、PCATV、candidate registry、freeze manifest、state version 或主线状态机，不使用未来观测，不输出 percentile、score、state、winner、replacement、future outcome 或交易结果。

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

EXP-C01 的正式结果已由用户接受：C1-only 与 C2-only 均未达到预注册 strong-substitutability reference，保留当前 C1+C2 pair，不选择或删除指标，不创建 C v2。EXP-A 不继承 EXP-C01 的 formal-run 授权；本 program 当前仍处于 EXP-A01 implementation review，下一阶段必须由用户明确授权。
