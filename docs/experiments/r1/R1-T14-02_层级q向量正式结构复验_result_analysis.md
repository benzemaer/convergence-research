# R1-T14-02 层级 q-vector 正式结构复验 result analysis

## 1. Authoritative run 与 lineage

本报告读取并分析 author-revision successor `R1-T14-02-20260711T1100Z`。运行绑定 code commit `96bf8f0acbfb265d0a242c2d700a54e5ef294b1e`、v3 config SHA-256 `8b2797f4516c0103ee4467fd6a874fcbea626c00f69489ca85da84311ed6f9ce`，实际从头执行 `N_perm=10000`，耗时 1165.89 秒。外部复审 comment `4944536998` 将 `R1-T14-02-20260711T0900Z` 判为 needs revision，原因是 V selectivity guard 误用 raw counts；该 run 已由独立 supersession record 标记为 superseded。更早的 `R1-T14-02-20260710T2340Z` 仍保持 superseded，`R1-T14-02-20260711T0800Z` 仍保持 failed-incomplete，均不属于 current evidence。

v3 upstream binding 指向已合并 PR #88：final head `faea7a957b84b0bd0e327d1af945c00c967f6ecb`、merge commit `09fb86510dc021f031c5f646777c5202013f2e86`、final package `aaea43c420289d95a384b49ce045f69045007ba6a5ac669079d6d3f055d72ac2`、canonical handoff `438d2f09ee7a853547a037521ba4ca133bd18bf1fa5dfef91f97db5f670393c3`、manifest `664b6d45...`、registry `02fdaf1b...`、external review `28062c82...` 与 final-gate validation `2e68d0fa...`。Post-merge transition record `c1d3fb28...` 另外绑定 #88 final-head 时的历史 README blob `e753cc3b...` 与当前 T14-02-authorized README `b0880c2e...`；它解释全局任务索引的合法演进，不改写 frozen #88 package。兼容字段仍保留 `stale_dependency=true`，但 scope 已拆清：`current_dependency_stale=false`、`superseded_run_dependency_stale=true`，current dependency 经 merge/final-gate cross-binding 验证通过。

## 2. Frozen family、工程验收与非退化性

Registry 仍严格为 10 vectors：2 个 shared-q baselines、4 个 centers、4 个 immediate neighbors；没有运行后删减或重排。12 项 R0 state-line reconciliation 的 mismatch 总和为 0，24 项 existence profiles 均非全零/全一，12 项 interval conservation mismatch 为 0，raw/confirmed PCVT→PCT violation 均为 0。Anomaly scan 的 15 项 checks 全部 passed，engineering validator 为 passed、0 errors。

运行继续保留 `selection_path_not_independently_confirmed=true`。它是同一样本结构复验，不校正 T14-01 discovery path，也不选择 best/frozen q。

## 3. Scope-specific robust envelope 与 complexity gate

Complexity matrix 逐 W、affected state/step 直接读取 T14-01 committed robust envelope `a97c094d...`，不再使用 T14-02 固定 fallback 代替。四个 centers 均至少在 coverage 或 affected Delta 上超过相应 envelope，仍是 `tradeoff_not_dominated`：

- W120 T=.25：coverage +0.00499085 > 0.00354046，Delta +0.03655636 > 0.01131262；
- W250 T=.25：coverage +0.00497050 > 0.00327239，Delta +0.03488450 > 0.02490461；
- W120 V=.30：coverage +0.00101518 > 0.00055873，Delta +0.05584514 > 0.04172699；
- W250 V=.30：coverage +0.00096317 > 0.00068610，Delta +0.06946805 > 0.04169740。

两个 V=.25 neighbors 的旧分类被纠正。W120 的 coverage +0.00048823、Delta +0.02591690 和 Lift 改变均未超过 scope envelope；W250 的 coverage +0.00044234、Delta +0.03160425 和 Lift 改变也均未超过。因此二者现为 `stability_envelope_equivalent / complexity_not_justified / prefer_shared_q`，candidate status 为 `review_only`。T=.30 neighbors 虽有 material improvement，但 frozen role 仍只是 neighbor，不能据此替换 T=.25 center。

## 4. V selectivity guard 与 security heterogeneity

V guard 已按预注册公式实现：

```text
selectivity_retained = (1 - R_candidate) / (1 - R_baseline)
R = confirmed PCVT / confirmed same-parameter PCT
```

Decision matrix 显式记录 `v_ratio_scope=confirmed_state_days`。W120 baseline ratio 为 2941/12480，V=.30 为 4567/12480、retained=0.82954188，V=.25 为 3723/12480、retained=0.91802076；W250 baseline ratio 为 2143/10854，V=.30 为 3591/10854、retained=0.83377339，V=.25 为 2808/10854、retained=0.92365974。四项均高于 0.50，所有 candidate ratio < 1，V nested formal pass=true，raw/confirmed parent-child violation=0，因此 guard 全部通过。

Validator 不再只验证输出 ratio 的代数关系，而是从 existence profile 的 confirmed rows 独立复算 numerator 和 same-parameter PCT denominator。新增 failure-path test 直接验证旧 `0900Z` raw-ratio package 会以 `v_selectivity_guard_contract` fail closed。Guard 继续进入 candidate status、anomaly 和 validator hard gate；若失败会强制 `do_not_advance`。

V=.30 centers 的 security-level negative Delta share 分别为 13.9241% 和 18.1934%。Pooled 与 security median 没有符号反转，但这仍是 material heterogeneity；decision matrix 已加入 `V_security_negative_delta_share_material`，所以两个 V centers 必须保持 `formal_structure_supported_with_warning`，不能降格为一般备注。

## 5. Denominator reconciliation

新增 10 行 `r1_t14_02_denominator_reconciliation.csv`，逐 vector/affected step 同时列出 T14-01、T14-02 与 R1-T06 baseline 的 `N/n11/n10/n01/n00`、retention、target marginal、Lift 与 Delta。三者语义为：

- T14-01：strict required-layer common-valid；
- T14-02：ordered short-circuit parent + target valid；
- R1-T06：step-specific minimal common-valid。

T14-02 short-circuit 只扩张 shared baseline 的 parent-false rows；四种 W×step 扩张量为 19,970、20,056、38,695、42,719。所有对账中 `n11/n10` mismatch=0、retention change=0，差异仅落在 `n01/n00`，因此来源可解释。八个 nonbaseline vectors 的 T14-01→T14-02 Delta 改变为 +0.000739 至 +0.002161；affected Delta rank flip=0，structural gate flip=0。

审阅举例也被逐字复现：W120 T=.25 Delta 从 0.15746302 变为 0.15820179；W250 V=.30 从 0.16815583 变为 0.17012764。该变化来自 denominator 语义，不是候选重选、未来标签或 null 变化。

## 6. Null、multiplicity、年份与邻域

本 run 从头执行 10,000 permutations；`reuse_prior_null=false`。30 行 null results、50,000 行 family maxima、30 行 multiplicity 与 replicate manifest 的 SHA-256 均与 superseded `0900Z` 完全相同，证明 confirmed-ratio 修复没有改变 frozen family、seed 或 null schedule，也没有复制 prior null artifacts。独立复算确认每一项 adjusted p 均为 `(0+1)/(10000+1)=1/10001`，所有 null SD > 0。

最大 confirmed-year share 为 0.22681144，低于 0.50；全部 affected-step LOYO rows 保持 Delta>0、Lift>1；四个 center neighborhood status 全部 passed。年份、LOYO 和邻域没有因 denominator revision 发生方向或排序翻转。

## 7. Decision matrix 与有限推断

四个 centers 的最终 author-side status 仍为 `formal_structure_supported_with_warning`，四个 immediate neighbors 为 `review_only`。这说明在冻结的 same-sample family 内，centers 的 global/nested structure、年份与邻域证据没有被三项修复推翻；同时 complexity 结论现在正确区分 V=.25 neighbors，V heterogeneity 也被正式保留。

有限推断仅限于：当前 corrected package 可以提交独立外部科学复审。不能据此声称 q-vector 已独立确认、T/V q 优于 shared q、存在因果机制、已冻结最终状态定义、具有预测能力或交易优势。

## 8. Author-draft gate

```text
scientific_review_status=needs_revision
independent_review_status=needs_revision
repository_final_gate_status=pending
R1-T10_allowed_to_start=false
R2_allowed_to_start=false
formal_task_completed=false
selection_path_not_independently_confirmed=true
```

Engineering validator 与 author analysis 均不能替代独立审阅。本 package 只提交 Draft；在新的外部科学复审与 final gate 前，不推进 R1-T10 或 R2。
