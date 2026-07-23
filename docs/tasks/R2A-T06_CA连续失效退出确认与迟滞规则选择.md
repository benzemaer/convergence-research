# R2A-T06 CA 连续失效退出确认与迟滞规则选择

## 当前状态与停止点

```text
task_id: R2A-T06
status: formal_execution_candidate_pending_owner_review
branch: codex/r2a-t06-ca-consecutive-failure-exit-confirmation
base_merge_commit: fec2a640d478e18e10c0a56164caedee7666ed16
R2A-T05_status: completed_accepted
R2A-T05_DONE: present
R2A-T06_allowed_to_start: true
q20_role: research_anchor_only
q_selection_status: not_selected
canonical_dynamic_request_selected: false
winner_selected: false
selected_exit_confirmation_m: null
previous_unapproved_implementation_sha: 2bd24badf22ede38392ef7a4b3467602cc929106
owner_implementation_review_status: passed
approved_implementation_sha: 2710d282fadcb998b80b9a482a5d55a4facc775a
formal_execution_candidate_status: pending_owner_review
formal_execution_candidate_sha: exact PR head（由 Git/PR 外部绑定，避免提交自引用）
formal_run_allowed: false
formal_run_executed: false
real_score_data_read: false
formal_artifacts_generated: false
R2A-T06_DONE: absent
R2A-T07_allowed_to_start: false
R3_allowed_to_start: false
owner_implementation_review_required: false
owner_formal_execution_review_required: true
PR_state: Draft
```

Owner 已批准 implementation SHA `2710d282fadcb998b80b9a482a5d55a4facc775a`。当前只交付 formal-execution candidate：未来 runner、manifest 协议、授权门禁、17 文件结果包、落盘后异常扫描与结果分析代码及合成验证。完成 runner、validator 或 Quality 不等于任务完成；没有 owner 对 exact formal-execution candidate SHA 的明确批准和后续独立 authorization commit，不得生成权威 manifest、读取真实 Score、执行 formal run、生成正式结果或选择 M。

## 唯一研究问题

对 accepted `selected_dimensions=[C,A]`、`K=5` 动态状态，第一个 valid joint `raw_state=false` 仅作为 provisional exit trigger。比较连续 `M∈{1,2,3}` 个 valid false 后确认退出，是否能在严格实时、无前视、跨 q 一致且完整可审计的条件下减少边界抖动、快速重入和区间碎片。

候选固定为：

```text
M=1: accepted v1 baseline，第一个 valid false 当日确认退出
M=2: primary challenger，第二个连续 valid false 当日确认退出
M=3: secondary challenger，第三个连续 valid false 当日确认退出
```

实现与文档不得预选 winner。未来独立结果审阅遵循最小充分复杂度：先检验 M=2 是否实质消除单日抖动；只有 M=2 不足才检验 M=3 的增量价值；若 M=3 只增加一天延迟而没有稳定降低 recognition 后重入，不得选择 M=3；M=2 没有实质改善时允许保留 M=1。选择不得读取收益、未来路径、模型准确率或回测结果。

## 权威输入绑定

R2A-T05 accepted handoff、canonical `DONE` 和 PR #115 merge commit 是启动依据：

```text
accepted_handoff: data/generated/r2a/r2a_t05/R2A-T05-20260722T012719685Z/r2a_t05_accepted_result_handoff.json
accepted_handoff_sha256: 6d69a6526d14f4844fdc1f5b888bb87768c7eedb58b65ea76445eede3d1a6881
accepted_handoff_git_blob_sha: 94c06849ff4c6945bbea0e3ae76f4ffefef13c4c
DONE: data/generated/r2a/r2a_t05/R2A-T05-20260722T012719685Z/DONE
DONE_git_blob_sha: fa02b2b53596ef237f959ffa6fe019beb6fa9160
PR_115_merge_commit: fec2a640d478e18e10c0a56164caedee7666ed16
```

四档 request identity、request hash、Score release identity、coverage 和 accepted count 只能从 accepted handoff/config 读取并独立对账，不得根据 `CA_qXX_k5` 简称重建。T05 accepted RunRoot、handoff、DONE、正式结果和历史证据均为只读，本任务不得修改。

## 冻结参数与事实层

```text
selected_dimensions = [C, A]
confirmation_k = 5
q10 = {C:1000, A:1000}
q15 = {C:1500, A:1500}
q20 = {C:2000, A:2000}
q25 = {C:2500, A:2500}
exit_confirmation_m = 1 | 2 | 3
```

accepted v1 的 `raw_state`、`confirmed_state`、dimension active、eligibility、validity 和 reason codes 是不可修改事实。T06 输出使用名称 `confirmed_state_v1` 明确其来源；不得为维持 episode 改写 false 为 true，不得把 pending observation 伪造成 `confirmed_state_v1=true`。

## 独立退出生命周期

生命周期至少包含 `ACTIVE`、`EXIT_PENDING`、`EXIT_RECOGNIZED`、`QUALITY_TERMINATED` 和 `PENDING_RIGHT_CENSORED`。未进入 confirmed active 的 observation 可标记为 `INACTIVE`，输入在 active 且无 pending 时结束可作为 `ACTIVE_RIGHT_CENSORED` episode termination class；它们不改变五个强制生命周期状态的语义。

状态转移固定为：ACTIVE 遇 valid true 保持 ACTIVE；遇第一个 valid false 进入 EXIT_PENDING、记录 trigger 和 `fail_streak=1`；pending 中继续 false 递增 streak，并只在 streak 达到 M 的当前 observation 进入 EXIT_RECOGNIZED。pending 中先遇 valid true 则取消 provisional exit、保留 cancellation evidence 并返回 ACTIVE。ACTIVE 或 EXIT_PENDING 一旦遇 missing expected observation、listing pause、blocked、diagnostic_required、unknown、not eligible 或 score non-finite，必须当日 QUALITY_TERMINATED，M 不得延迟质量终止。输入结束时仍 pending 则 PENDING_RIGHT_CENSORED。

连续性只按同证券相邻 `observation_sequence` 定义。sequence 缺口必须 fail closed；calendar 日期间隔不影响连续性；missing/listing/non-ready row 必须显式存在并终止，不得跳过。

输出至少保留：

```text
exit_trigger_time / exit_trigger_observation_sequence
exit_recognition_time / exit_recognition_observation_sequence
recognition_lag / exit_confirmation_m
provisional_exit_cancelled / cancellation_time
termination_class / quality_reason / right_censored
episode_id / episode_identity / stable ordinal
raw_state / confirmed_state_v1
```

recognition available time 不得回填到 trigger：M=1/2/3 的 recognition lag 必须分别为 0/1/2 个 observation。

## Candidate lifecycle 跨 q invariant

对相同 M 和 observation key，`active_or_pending = lifecycle_state in {ACTIVE, EXIT_PENDING}`，并冻结：

```text
active_or_pending(q10) subset active_or_pending(q15)
active_or_pending(q15) subset active_or_pending(q20)
active_or_pending(q20) subset active_or_pending(q25)
```

每个 stricter-q episode 的全部 active-or-pending observation 必须唯一包含于同证券的一个 looser-q episode。找不到 parent、横跨多个 parent、多对多 mapping 或 stricter active-or-pending observation 在 looser q 不 active/pending，均须 fail closed。Raw/confirmed input nesting 与 candidate lifecycle nesting 分开复算和报告。

## 实现、validator 与测试

实现包括版本化 config/schema、纯生命周期 builder、逐 observation online reducer、独立 validator、result-analysis 骨架、synthetic-only implementation runner 和默认拒绝的 future-formal 入口。独立 validator 不导入 production 私有科学函数，不接受 builder 自报 counts，必须独立复算输入 domain、quality precedence、exit type、identity、observation、trigger、episode、recognition、cancellation、quality termination、right censoring、summary、trigger-anchored false run/hazard、排序和跨 q mapping。Online receipt 只有在 one-row、fixed/random chunk、false/recovery/quality 边界和交错证券 replay 与 batch 全表一致后才可为 true。

集合关系使用稳定的 accepted baseline episode identity，而不是 recognition date：

```text
recognized_episode_set(M3) subset recognized_episode_set(M2) subset recognized_episode_set(M1)
cancelled_episode_set(M2) subset cancelled_episode_set(M3)
```

测试覆盖四种 false-run 长度、false 后恢复、false 后 quality/input end、confirmed 前 false、证券隔离、calendar gap、sequence gap、missing、listing pause、blocked/unknown/diagnostic、not eligible、non-finite、三种 exit type、四档 q 嵌套、多 episode ordinal、重复运行、worker 标签一致和二进制路径枚举属性。M=1 必须逐项复现 accepted v1 valid raw-false exit；原 daily facts 必须逐行不变。

## Formal-execution candidate（本阶段不运行）

未来 formal runner 已冻结为 q10、q15、q20、q25 严格串行且每档只调用一次 accepted T03 evaluator；每档立即校验 request/Score identity、daily/true/interval/security counts，任一不一致即在 T06 lifecycle 前停止。四档已验证 daily facts 各自复用于 M=1/2/3，canonical worker=1，并以 worker=4 做全表一致性检查；两次独立 build 比较 observation、trigger、episode、compact tables、排序、null 语义和 fingerprint。

候选 manifest builder 只读取 accepted metadata 与版本化契约，不读取 Score 内容。未来权威 manifest 只能在 exact reviewed SHA 的 GitHub Quality success 后生成，并从该 SHA 的 Git blob 绑定 config/schema canonical bytes；authorization、HEAD/parent、attempt、manifest hash/size、clean worktree、RunRoot、repository-local path、accepted identity/count 和禁止字段门禁全部必须在 Score discovery 前通过。当前配置保持 `formal_run_allowed=false`，未创建 authorization 或权威 manifest。

## 未来 formal 结果包（本阶段不生成）

未来正式包必须包含用户授权列出的 17 个 compact/detail 文件且每个恰好一次，包括 `false_run_length_profile.csv`、`recovery_hazard_profile.csv`、`candidate_exit_summary.csv`、recognition/reentry/fragmentation/margin/cross-q/year/security profiles、deterministic samples 与 git-ignored `t06_detail.duckdb`。Formal pending 不得提前选择 M；completed accepted 必须绑定 accepted run、reviewed implementation/execution SHA、owner accepted、completed-passed result analysis、零 blocking anomaly、具体 `selected_exit_confirmation_m` 和最小充分复杂度选择证据。逐 observation、trigger、episode 和 candidate mapping 只能进入 repository-local git-ignored detail storage。

未来每个 `q × M` 必须报告 provisional、recognized、cancelled、quality-terminated-pending、pending-right-censored、cancel rate、recognition lag、security breadth、episode count/span、active-day density、bridged false count 和 recognition 后 raw/confirmed re-entry。False-run `L` 只从已 confirmed active 后的合法 provisional trigger 开始，在紧邻的首次 raw true、quality interruption 或 input end 前计数；不得纳入 confirmed active 前或已退出 inactive 状态的任意 false。h1/h2/h3 的 risk set 不得跳过中间 quality/missing，并按 q、year、security、trigger exit type 和 threshold-margin bucket 分层。

## Owner implementation review 与 formal 停止点

前一 candidate `2bd24badf22ede38392ef7a4b3467602cc929106` 未获批准；successor `2710d282fadcb998b80b9a482a5d55a4facc775a` 已通过 owner implementation review，且是本 formal-execution candidate 的唯一实现基线。当前停止于 formal-execution candidate pending owner review；不得将实现批准解释为 formal authorization。

## 禁止范围与阻塞条件

本任务不读取未来价格、收益、MFE、MAE 或未来路径；不定义 UP/DOWN/RECONVERGENCE、release onset/direction/intensity；不研究交易、信号、回测或最佳 q；不修改 Score、组件、threshold、weak delta、K=5 或 accepted v1 daily facts；不引入 dimension-specific M、gap tolerance、自动合并或事后回填；不启动 R3、不注册 canonical dynamic request。

M=1 不能复现 baseline、daily facts 被修改、全零/全一/全 NULL、M 无响应、lag 非 0/1/2、集合非单调、quality 被吞、missing 被跳过、cross-q 异常、identity 不守恒、单年/少数证券/单 exit type 异常主导、数量级相对 T05 突变、availability/evaluability 不一致、online/batch 或 parallel 不一致、validator 复算不一致，任一出现都必须停止，不能创建 DONE、推进 README gate、允许 T07/R3 或解释为正式结果。

## Formal-execution review 交付

本 PR 停止于 formal runner、manifest/authorization schema、结果包与 artifact-readback analysis、synthetic tests 和全 Quality 通过；随后只提交并推送 formal-execution candidate SHA、保持 Draft PR 和 clean worktree。`formal_run_executed=false`、`real_score_data_read=false`、`formal_artifacts_generated=false`、`selected_exit_confirmation_m=null`、`winner_selected=false`、`R2A-T06_DONE=absent`、`R2A-T07_allowed_to_start=false`、`R3_allowed_to_start=false`，且 `owner_formal_execution_review_required=true`。
