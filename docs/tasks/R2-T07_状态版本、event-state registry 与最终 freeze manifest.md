# R2-T07 状态版本、event-state registry 与最终 freeze manifest

## 任务边界

R2-T07 是 R2-T06 合并后的独立 registry/freeze task。它只把已经通过 T02、T04、T05、T06 门禁的契约、选择记录、canonical fingerprint 和 replay lineage 登记为可审核的状态版本与最终 freeze manifest。它不重跑 T03、T04、T05 或 T06，不生成新的状态机数据库，也不修改任何上游 frozen artifact。

本 task 的 PR、branch 和 task 文档标识如下：

```text
PR title: [codex] R2-T07 状态版本、event-state registry 与最终 freeze manifest
branch: codex/r2-t07-state-version-event-state-registry-final-freeze-manifest
upstream: PR #98 merge commit 12cd31d125e31762e62f8b1db5a808d189c7c732
startup_authorization_mode: merged_pr_direct_binding
```

## 固定上游绑定

T06 直接绑定 PR #98 的 merged PR lineage，不创建 T06 post-merge handoff。绑定值为：

```text
reviewed_head: 4604117678b53b2c756d866babd9a4ad8d85a2ef
scientific_review_id: 4690087611
compatibility_review_id: 4690138251
authoritative_run: R2-T06-20260713T183455Z
formal_execution_commit: b2b1b193ded0040c9695bca1ad98d22c10263044
validator_commit: 8920a3cd3abfcc15ecd337ef6116d7fe286d5c01
artifact_commit: 07f4771ea78038d230e1dba62c2494614b4553aa
replay_duckdb_sha256: 671b1a1027c1e56af0a551142fc35e31a399d699d732fc145d36c189973ccea1
```

启动和 formal generation 均从 `git show <commit>:<path>` 读取绑定输入，并记录 Git blob SHA、committed byte SHA-256、文件大小和 source commit。工作树文件不能替代 committed blob。T06 合并时复用的 R2-T02 专用 consumer 例外仅登记为不适用于 T06 的治理事实，不豁免 T06 的科学审阅、validator、artifact bytes、governance 或跨平台 canonical-text 门禁。

T04 固定 decision hash 为 `f1344346662225f1f0837bc160be1bf6f88f12174cbacc8f27f8a126ad9bf3bf`，freeze decision hash 为 `ceb99c3480aa49a13a545dd06d43a85c2faf378256c49623b17d1b0255e0048d`，freeze plan hash 为 `1ea368d67b9445a6916ee31ff33e6f0a5f94ed43b0fd5a2b716f8d60c39a80dc`。T05 只消费 committed table fingerprint，不重导出完整 daily/event/membership 表；其 canonical database、daily/event/membership semantic hashes 和行数在配置中逐项绑定。

## 冻结版本

最终 registry 只能包含以下两个 state version：

```text
r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8
r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8
```

两个版本都使用 `K=3,d=2,g=1`。K=3 的第三个连续 eligible、valid、raw-true trading row 是首个 confirmed row，不回填；unknown、blocked、diagnostic、ineligible、missing 和 missing expected row 是 hard break。d=2 表示第二个 confirmed trading day 才达到 component qualification；g=1 是 qualified component 后的累计 eligible、valid、raw-false gap-day 计数，g+1 raw-false day 可导致不可逆 finalization。preconfirmation raw-true 不增加也不重置 g，unqualified reentry 不得被吞成 ordinary false gap，open event 只能 right-censor。

T04 的四个 decision unit 必须保留在 decision log：S_PCT×W120 和 S_PCVT×W120 为 selected，S_PCT×W250 和 S_PCVT×W250 为 reject_pair。W250 独立版本、shared-q 独立版本、额外 PCT parent 产品和其他额外 state version 的数量必须为 0。automatic recommendation 不是最终决策 authority，warnings 只登记为已接受的选择风险，不建立下游研究结论。

## registry 内容和时间语义

`r2_interval_rule_registry.json` 登记 confirmed interval、component qualification、gap、reentry、hard-break、right-censor 和 no-backfill 规则；`r2_event_state_machine_registry.json` 登记八个 event states、T02 transition registry、event identity、risk-set policy 与时间字段；`r2_freeze_decision_log.json` 保留完整四个 decision unit；`r2_final_freeze_manifest.json` 汇总 T02/T04/T05/T06 lineage、两个冻结版本、artifact paths 和下游关闭状态。

权威时点字段为 `confirmation_time`、`first_qualification_time`、`last_exit_observation_time`、`zone_finalization_time` 和 `membership_available_time`。`r2_t06_replayed_transition_ledger.trigger_trade_date` 只可作为缺少权威 finalization/membership time 时的 event-start-date fallback，不能解释为权威因果 transition timestamp。event-zone membership 不等于 state risk set 或 qualified-event risk set，也不构成 release、方向、幅度或交易结果结论。

## 产物和门禁

初始 author-draft run `R2-T07-20260714T015043Z`、execution `50d97a8921be08b40bafcaa5e28cfda6b60e2704`、artifact commit `782f4d0b78d2569485793f0b6b828edc8751663c` 已保留为 `HISTORICAL / SUPERSEDED / DO NOT USE`，原因是 `incomplete_final_freeze_interface`，不得作为 T08 输入。其 successor `R2-T07-20260714T023405Z` 及失败诊断 run `R2-T07-20260714T033826Z` 均保留为 `superseded_author_draft`，不得作为当前 evidence。当前 authoritative successor 为：

```text
run_id: R2-T07-20260714T034053Z
execution_commit: 8596be41d7349e9cfcc1c4782282d4a46ea3750d
artifact_commit: 45f0aa9605ca007d11e6aa1360c24340bfa1d04d
committed_validation_commit: dd3118dc9670b585df36db9adfcd930265a08b8c
independent_validation: passed; failure_count=0; integer checks all 0
registry_reconciliation: passed; failure_count=0
forbidden_use_audit: passed; JSON=10, CSV=2, CSV headers=2
anomaly_scan: passed; anomaly_count=0
```

其中 `artifact_commit` 的完整 SHA 以 Git history 和 committed-artifact validation sidecar 为准。四个 core registry 文件的 actual byte SHA、size、路径和 output-manifest binding 均逐项通过；在独立科学审阅前，T07 仍是 author-stage package，`formal_task_completed=false`，T08/R3 保持关闭。

核心产物为 state version registry、interval rule registry、event-state machine registry、freeze decision log 和 final freeze manifest；supporting artifacts 包括 source readiness、input binding、canonical artifact binding、registry reconciliation、forbidden-use audit、independent validation、anomaly scan、result analysis、experiment summary、output manifest、result package、committed-artifact validation 和 supersession record。所有 compact audit 必须来自实际计算；缺失输入、缺失审计或无法读取的 committed blob 只能 fail closed。

所有 compact audit 必须来自实际检查；缺失或无法读取的输入只能 fail closed，不能生成 passed placeholder。independent validator 不得导入 T07 generator。mutation tests 覆盖冻结版本 cardinality、W250/shared-q/PCT parent exclusion、version ID、q/K/d/g、strict-core pair、decision warnings、selection authority、transition registry、event ID/revision policy、semantic hash、T04 binding、rejected unit、time authority、release reinterpretation、risk-set reinterpretation、R3 gate、manifest hash 和 committed bytes mismatch，并包括合法的 zero-version synthetic case：`completed_no_frozen_version` 且 T08/R3 均关闭。

本 task 完成 formal package 和 repository checks 后，仍须等待独立科学审阅。author-stage package 不得自行写入 scientific PASS，不得打开 R2-T08 或 R3。
