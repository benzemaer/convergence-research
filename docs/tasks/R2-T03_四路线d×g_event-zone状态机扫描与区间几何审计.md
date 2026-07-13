# R2-T03 四路线 d×g event-zone 状态机扫描与区间几何审计

## 1. 当前状态

```text
task_id: R2-T03
initial_startup_status: blocked_missing_authoritative_t02_final_gate_binding
resolution_status: resolved
startup_status: passed
resolved_by: r2_t02_repository_final_gate_handoff.json
historical_formal_run_id: R2-T03-20260712T1205Z
historical_run_status: author_draft_invalidated_pending_successor_run
current_execution_status: code_correction_only
formal_rerun_executed: false
availability_adapter_status: resolved_research_policy
expected_key_adapter_status: resolved_upstream_adapter
interval_reconciliation_adapter_status: resolved_upstream_adapter
scientific_review_scope: implementation_only
implementation_review_status: needs_revision_corrections_submitted
successor_baseline_allowed: false
successor_72_cell_scan_allowed: false
formal_task_completed: false
R2-T04_allowed_to_start: false
R3_allowed_to_start: false
```

本记录中的初始阻断结论保留为历史审计事实。该阻断已由 `R2-T02-20260712T1700Z/r2_t02_repository_final_gate_handoff.json` 及其 validation sidecar 解决；handoff 是正式启动授权，本文档本身仍不替代运行 manifest、正式输入绑定或研究结果。后续实现审计确认 `R2-T03-20260712T1205Z` 的冻结指标、transition ledger、strict-core/window comparison 和所谓独立复算存在具体实现偏差，因此该 run 现标记为 `author_draft_invalidated_pending_successor_run`，保留为历史 author-draft，不再是科学审阅候选。本轮只修正 execution code/schema/tests，没有运行 baseline 或 72-cell scan；R2-T04 与 R3 继续关闭。

### 1.1 本轮 code-correction-only 边界

本轮没有修改 `R2-T03-20260712T1205Z` 自身的 result package、manifest、committed validation sidecar 或任何 compact artifact，也没有创建新的 `R2-T03-*` 目录。科学审阅请求仅针对实现；正式 successor run 必须在实现审阅通过、authoritative expected-key 与 availability 契约补齐、execution code/config/schema 先提交后另行执行。

## 2. 目标与非目标

R2-T03 的授权目标是在 R2-T02 冻结契约和 72 个既定 `candidate_cell_id` 上执行四条 primary route 与四条 shared-q reference 的 `d={1,2,3}`、`g={0,1,2}` 状态机扫描，生成事实层、区间几何、状态转移、strict-core/shell、窗口 overlap、独立复算和异常审计。

本任务不包含 T04 的 hard-gate 候选处置、Pareto 推荐、参数选择或 freeze plan，也不包含 T05 的 selected-only canonical 物化。启动门禁未闭合时，不得以 contract-only、synthetic-only 或局部真实数据运行冒充 T03 正式执行。

## 3. 启动审计事实

审计基于 `main@04530181e7cd80b8805f279dbac5eb5afb70c21d`，得到以下事实：

1. PR #94 的合并记录指向 exact PR head `a98d2a14e8828585e6b4283efee6afdf2db8672d`，merge commit 为 `04530181e7cd80b8805f279dbac5eb5afb70c21d`。GitHub review `4679909839` 在 exact head 上包含 `[R2-T02 scientific PASS]`。
2. GitHub Actions `Quality` run `29189876487` 的 `premerge-full` job 成功，外部 artifact `r2-t02-premerge-full-evidence` 报告 1200 个测试、0 failure、0 error，并在 workflow 内执行 final-gate consumer。
3. R2-T02 v8 committed-artifact validator 可在 artifact commit `a34f3f6c5ad0afece49b1c9a237e21eb032e35a2` 上复验通过，18 个登记 artifact 的 Git blob 与 SHA-256 闭合；protocol validator 也通过。
4. 当前 `main` 未包含上述 premerge-full evidence 或等价 repository final-gate authorization artifact。`git ls-tree -r main` 只能定位 builder、schema 和 author-stage review，不能定位持久化 final-gate 结果。
5. 仓库内 `R2-T02-20260712T1700Z/r2_t02_result_package.json` 仍声明 `scientific_review_status=pending`、`independent_review_status=pending`、`repository_final_gate_status=pending`、`formal_task_completed=false` 和 `R2-T03_allowed_to_start=false`。这是正确的 author-stage fail-closed 状态，不得重写以追认外部 workflow 结果。

外部 workflow 成功和 PR 合并事实不足以替代当前 `main` 中可由 T03 formal input binding 消费的不可变授权。Actions artifact 可能受保留期约束，且未被当前 Git tree 的 committed bytes 绑定，因此不满足本任务规定的持久化下游授权条件。

## 4. 已核对的冻结输入

R2-T02 v8 冻结输入位于 `data/generated/r2/r2_t02/R2-T02-20260712T1700Z/`。本次只读复验确认以下关键 committed artifact 哈希：

| Artifact | SHA-256 |
|---|---|
| `r2_t02_confirmed_state_machine_contract.json` | `6c0d5822416e5e8fef6392a8d97703d0ad9b5c46774029e13a363be6feb2d57c` |
| `r2_t02_event_zone_machine_contract.json` | `e7d877885b3cfe31bf685803f939cdcf56037d02a46d40314a304435dc1ecaed` |
| `r2_t02_transition_registry.csv` | `e2656afa07244b5fb2219327dda48dc9a6968e61a87c40662fb882208ca5440e` |
| `r2_t02_metric_dictionary.csv` | `aa56c49dce9484e7031fde9f345cc918bba70cb8b4cdc222e37ea63582cca00c` |
| `r2_t02_hard_gate_registry.csv` | `533978218585c510693d4236261b23d7a42834786a699412200e9d5f0d2012f5` |
| `r2_t02_r3_risk_set_contract.json` | `cb19687a112ba5ceba23c09fdd6923814d6159a088bff1dc78a322c8e5d1250f` |
| `r2_t02_t03_cell_registry.csv` | `7d8f82c189d0c96ba3091ca142d8612e31aeef36ecf20ff9c832009bd41e6ead` |
| `r2_t02_t03_output_contract.json` | `7587891bd2b705f0f5af90dc3c4faf672c9c8191bd912f92052932c2c7ac4a3c` |

这些哈希证明 contract/artifact bytes 可复验，不证明 T03 已获得启动授权。旧 T02 runs 不得替代 v8；author-stage package 不得被修改为 post-author PASS。

## 5. 阻断解除记录

阻断解除证据已明确绑定 `R2-T02-20260712T1700Z`、PR #94、review ID `4679909839`、head `a98d2a14e8828585e6b4283efee6afdf2db8672d`、workflow run `29189876487`、job `86642565197`、artifact ID `8259206209`、artifact digest 和 merge commit `04530181e7cd80b8805f279dbac5eb5afb70c21d`。handoff validator 重新调用既有 `validate_final_gate()`，校验 GitHub review snapshot、author package、committed-artifact sidecar、exact head、merge ancestry、远端 artifact/job metadata 与所有 committed SHA，并给出 `R2-T03_allowed_to_start=true`。

T02 author package 未被修改，继续保持 immutable author-stage lifecycle；科学 PASS 和 repository final-gate PASS 只记录在非循环 post-merge handoff。T04–R3 继续关闭。

## 6. 历史初始停止边界

初始阻断阶段未读取 loose DuckDB 作为正式输入，未执行单线程 baseline，未执行任何 candidate cell，未创建 R2-T03 formal run 目录，未生成 compact/large result artifacts，未作参数排名、选择或冻结判断。该阶段不构成可 resume 的 scan cell；解除后从完整正式输入绑定开始执行。

## 7. 已失效的历史 author-draft 执行

历史运行 `R2-T03-20260712T1205Z` 曾绑定 execution commit `4dc46e061b72d60f6a34f50f1b35f659a9a28dce`。以下数字只保留为失效 author-draft 的审计历史，不再构成当前 scientific review evidence。该 run 当时的 baseline 与 formal 表指纹一致，但后来确认其 metric、comparison、transition 和 independent validator 实现不符合冻结口径。

实际数据库包含 13,846,152 条 route daily rows、31,346 个 atomic intervals、282,114 个 component rows、173,253 个 event zones、574,299 条 membership rows、135,480 个 bridge segments 和 1,068,562 条 transition rows。72 个 cell 均有非零事件，事件数范围为 272–7,673；`confirmed_event_coverage` 范围为 0.530565–1.0。全部 24 个 route×d 参数响应组在三个 g 值上均产生 3 个不同 event count 和 3 个不同 bridge count；strict-core comparison 共 62,307,684 个共同日期键，subset violation 为 0。availability、risk-set、主键和 confirmed-day 守恒检查均为 0 violation，独立 validator 的 360 项复算比较全部通过。

工程 anomaly scan 未发现全零、全一、全 NULL、参数无响应、subset、availability 或 risk-set 异常。不过冻结 scientific gates 报告 14 个非工程阻断失败，全部是 `duration_q95_ratio > 3.0`：对应 cell 的绝对中位 duration 为 2–3 日、q95 为 7–11 日、最大值为 18–28 日，表现为短中位数下的右尾延长，而不是数量级爆炸或守恒破坏。这些失败保留在 `r2_t03_runtime_gate_results.csv` 和 author-draft 分析中，未用于选择或排除任何 cell；是否可接受只能由后续独立 scientific review 决定。

历史 artifacts 仍位于 `data/generated/r2/r2_t03/R2-T03-20260712T1205Z/`，本轮不修改其任何 bytes。其 package 中原有的 pending author-stage 字段同样不得解释为当前审阅候选；当前权威任务状态是 `author_draft_invalidated_pending_successor_run`，工程 validator 的历史 PASS 已被实现缺陷推翻。

## 8. 本轮冻结口径修正

修正实现逐项绑定 `r2_t02_metric_dictionary.csv`、`r2_t02_hard_gate_registry.csv`、`r2_t02_t03_output_contract.json`、`r2_t02_event_zone_machine_contract.json`、`r2_t02_transition_registry.csv` 和 `r2_t02_r3_risk_set_contract.json`。`confirmed_event_coverage` 改为 qualified component 的 distinct eligible-valid confirmed exact keys 除以 cell 内 eligible-valid daily exact keys，并与 retained、retrospective、as-of 三种 coverage 分开；`duration_q95_ratio` 使用 `ceil(q*n)` nearest-order event span q95 除同 route/state-line upstream atomic duration q95；`merge_ratio` 按 `component_count>1` 的 event 数计；short-drop 只使用 normally ended natural exits；unqualified reentry 按稳定 attempt ID 去重。

strict-core 改为 exact security-date membership/component containment，primary event 只要包含至少一个 strict member 即计一次，跨越多个 primary 边界的 strict event fail closed。W120/W250 daily comparison 同时报告 own/common denominator；event matching 按同证券、confirmed exact-key overlap、primary start、comparison start 与 event ID 的固定顺序执行 greedy one-to-one。transition 增加 component、event-zone、bridge 与 rejected-reentry 的 entity-addressable ledger 及闭合检查，不能再以聚合计数补平。

## 9. 正式上游契约

v2 expected-key adapter 沿当前 R0-T10 authorized manifest 追溯到 R0-T04 实际输入的 D3-T11，再沿 D3-T07 追溯到 D2-T20 `d2_t15_tnskhdata_staging.duckdb`。该库内 `d2_expected_security_dates` 是第一优先级 skeleton；只读审计确认 1,751,066 个唯一 base keys、800 证券、20160104–20260630、0 duplicate，冻结 8-route 展开计数为 14,008,528。完整 keys 不进入 Git。adapter validation 只证明 source identity/schema/aggregate，未执行 successor expected-vs-observed reconciliation。

`r2_t03_eod_availability_policy.v1` 将 `available_time` 冻结为 trade date 当日 15:00:00+08:00 的研究逻辑信息集时点。它不是下载、计算完成或成交时间；不假设 15:00 同瞬间计算和成交。confirmation、d qualification、exit 与 g+1/quality finalization 均取决定行 15:00，membership 继续使用 T02 as-of 规则并不得回填为事件首日。后续交易阶段必须另行冻结 calculation/execution latency。

interval adapter 对 R0-T10 shared-q 和 R0-T15 primary-q 完成 8/8 exact route mapping，总 source interval count 为 31,346。`raw_state_false/end_of_input_open/raw_state_blocked/raw_state_diagnostic_required/raw_state_unknown` 分别映射到 T02 三类 reason。R0-T15 legacy `raw_state_false_or_invalid` 对 closed interval 使用 `last_observed_date` 当日 route-daily decision row 消歧，open 状态直接读取上游 `is_open_interval`，不得由 decision row 是否缺失推断。稀疏 interval reconciliation 的 dense-domain 修订见第 10 节；adapter validation 与只读审计均不能解释为 successor 正式结果通过。

event-zone 主 ledger 现在按 `scan_event_id` 产生连续 ordinal：creation 后显式进入 `QUALIFIED_ACTIVE→GAP_PENDING`，accepted bridge/rejected reentry 保留完整路径，terminal 后不得继续，所有 tuple 必须存在于冻结 transition registry。terminal 通过 event ID 关联，不再按顺序 zip。formal independent validator 从四张允许的 source surfaces 重建并比较 19 个核心指标、transition closure、strict-core 全字段、W120/W250 全字段、expected completeness 与 interval multiset；production derived tables 只作为 comparison target。

## 10. Implementation review 修订

审阅指出完整 D2 expected surface 与稀疏 R0 observation domain 存在每路 20,297 行差异。只读 aggregate audit 确认这些差异全部为 expected-empty：19,283 行 suspended、1,014 行 listing pause，listed-open-missing-daily 与其他状态均为 0；其中 10 个日期落入既有 confirmed interval，影响 2 个 R0 interval，且均属于 `r2_s_pct_w120_qt25_primary`。扩大到会影响 K=3 几何的 `raw_start_date→interval_end` 窗口后，共 30 个差异日期影响 14 个 source intervals；未受影响 exact-reconciliation 据此使用完整 K=3 窗口判定。

successor adapter 因此以完整 expected surface 为权威，将 expected-empty 显式物化为 `eligible=false`、`quality_state=expected_empty`、`raw_state=NULL` 的 hard-break 行，并在 dense timeline 上重新执行 K=3 confirmation。稀疏 R0 intervals 改为来源谱系：未受影响 interval 必须 exact reconciliation，受影响 dense interval 必须唯一包含于一个实际 source interval，不再声称与稀疏 intervals 全表逐行相等。

R0-T15 closed interval 现在只使用 `last_observed_date` 当日 decision row 消歧，open 状态直接读取上游 `is_open_interval`。formal readiness 会重新计算 D2 manifest、D2 DuckDB 与每个 R0 interval source 的实际 SHA-256、size 和 table aggregate，断言 contract route path/source ID/SHA 与 RouteSpec、manifest 和实际 bytes 一致，并把 actual bindings 写入 readiness 和 input binding。formal source binding 同时恢复 `src/common/canonical_io.py`、`src/r2/r2_t02_protocol_freeze.py`、result-package/output-manifest schemas 与 committed-artifact validator。

本节只记录 implementation correction 和 read-only audit。未执行 successor baseline 或 72-cell scan；历史 1205Z 保持 invalidated，R2-T04/R3 关闭。

## 11. E2E-01 至 E2E-09 最终实现修订

最终执行链已收敛为 `route_source_daily → dense expected surface → one-time K=3 replay → canonical route_daily → route_atomic_interval → component/event/metric/validation/analysis`。`route_source_daily` 只承担 sparse source lineage；所有生产消费者读取含完整 available/eligible/quality/raw/confirmed/confirmation/exit/risk/reason/hard-break 字段的 canonical `route_daily`。固定断言为 8 routes、每路 1,751,066 keys、总计 14,008,528 行，其中 162,376 行 expected-empty（154,264 suspended、8,112 listing pause），listed-open-missing-daily 为 0。

实际 adapter-only aggregate audit（未执行任何 candidate cell）得到：geometry affected source intervals 14、termination-only affected 10、all affected 24、split 0、eliminated 12、dense fragments 31,334、unaffected exact intervals 31,322；confirmed interval 内 difference rows 仍为 10。dense `interval_id` 与真实 `upstream_source_interval_id` 分离，production 与 independent validator 分别执行 dense fact exact reconciliation 和 dense-to-sparse lineage reconciliation。`duration_q95_ratio` 的分母为 canonical dense atomic interval nearest-order q95。

event terminal reason 现由携带 `scan_event_id` 的实际 terminal ledger 绑定；component quality interruption 使用冻结的 `COMPONENT_FORMING→UNQUALIFIED_CLOSED` tuple。三层 supplemental diagnostics、strict-core/window diagnostics、runtime structural detectors、全部 parameter invariants、source-level independent dense reconstruction、完整 database/post-validation fingerprint、result analysis/anomaly 分类及 large-DuckDB committed validation 均进入 successor 实现。formal source paths 和 T02/R0/D2 actual input bindings已闭合，非空 run directory fail closed。

这是 final implementation correction for E2E-01..E2E-09，不表示 implementation review、baseline、72 cells 或 scientific review 已通过。本轮未运行 successor baseline，未运行真实 d×g/72-cell scan，未创建新的正式 run 目录，未修改历史 `R2-T03-20260712T1205Z` artifacts；`R2-T04_allowed_to_start=false`、`R3_allowed_to_start=false`。

## 12. Implementation review 六项封闭修订

HEAD `6c075d5a...` 的 implementation review 结论为 needs revision，successor baseline 继续禁止。本轮不改写已静态通过的 dense/source interval lineage、terminal/transition closure与binding/manifest/committed-validation设计，只修正审阅列出的六项。

事实链现明确分为三张表：`route_source_daily` 永远保持13,846,152条R0 sparse rows；`route_dense_input` 由 expected keys、sparse source和独立物化的D2 `expected_empty_status` left join得到14,008,528条raw rows；`route_daily`只保存 dense input完成一次K=3 replay后的canonical facts。adapter-only实际复核得到 `route_source_daily=13,846,152`、`route_dense_input=14,008,528`、dense expected-empty=162,376、sparse source中的expected-empty=0。Independent oracle不读取production `route_dense_input`，而是从sparse source、expected keys和D2 status自行生成dense raw timeline。

Supplemental diagnostics已修正：`atomic_fragment_rate=singleton_count/atomic_interval_count`；qualification delay采用明确的交易观察间隔 `d-1`；component、bridge、duration分别独立排序计算nearest-order q90/q95；`max_single_gap`读取raw-false gap。Strict-core补齐component count/share、shell-only components、density，expansion-shell share绑定shell share；window补齐component overlap以及W120/W250-only component/event counts。

`parameter_invariant_profile`现执行12类冻结不变量，包括g方向的event/bridge/bridged-days/zone-coverage/confirmed/retrospective/as-of、d方向的component/retrospective/as-of/delay及完整g=0 identity。Runtime detector同时扩展为所有zone的raw-false bound、revision时间序列回退、全main output字段扫描及reentry terminal ledger闭合。Independent validator新增三层diagnostics、pending states、strict/window components、12项parameter invariants及独立affected/unaffected/termination-only source-lineage policy复算。

Post-validation保留run ID作为metadata，但baseline/formal equality只比较排除run-specific path与run ID的canonical comparison fingerprint。Anomaly scan消费新增diagnostics并覆盖bridge/gap domination、mega-zone、max span、top-zone share、duration数量级、right-censor/quality-break集中度、confirmed-day conservation、W denominator与as-of backfill；科学调查项不伪装成工程运行失败。

本节仍是implementation-correction-only；未运行successor baseline、真实candidate cell或72-cell scan，未创建formal run目录，未修改历史1205Z artifacts。`implementation_review_status=needs_revision`、`successor_single_worker_baseline_allowed=false`、`successor_formal_scan_allowed=false`、`R2-T04_allowed_to_start=false`、`R3_allowed_to_start=false`。
