# R2-T06 successor formal replay evidence

## Authoritative successor

本次 successor formal run 为 `R2-T06-20260713T183455Z`。execution commit 为 `b2b1b193ded0040c9695bca1ad98d22c10263044`，artifact commit 为 `0bfa2c5`。runner 在关闭 DuckDB connection、写出 `r2_t06_materialization_complete.json` 后完成 compact finalization；marker 与 committed DuckDB 的 SHA-256 均为 `671b1a1027c1e56af0a551142fc35e31a399d699d732fc145d36c189973ccea1`。

本 evidence 只记录 author-stage 的可复核事实，不构成 scientific PASS，不打开 R2-T07、R2-T08 或 R3 gate。

## 实际结果

两个 state version 的 daily surface 均为 `1,751,066` 行。S_PCT 的 confirmed/state-risk/qualified-event-risk/event/membership 数量为 `20,474 / 20,474 / 12,803 / 4,561 / 22,719`；S_PCVT 为 `4,564 / 4,564 / 2,387 / 1,086 / 4,669`。总表行数为 daily `3,502,132`、event `5,647`、membership `27,388`、component `9,848`、atomic interval `9,848`、transition ledger `16,815`；daily、event、membership 主键 duplicate excess 均为 0。

independent validator 的 exact reconciliation、独立 interval/component/event identity、transition registry、current-source event overlay、qualification/risk、FK 和 no-lookahead checks 全部为 0，`r2_t06_anomaly_scan.json` 的 anomaly count 为 0。

11 个 compact audit 均由实际 DuckDB 查询生成，且均为 `status=passed`、`mismatch_count=0`：atomic interval、component qualification、event transition、event zone、membership、no-lookahead、exit/censor、event ID/revision、strict-core/risk-set、unselected exclusion、count/geometry。

## Committed-byte validation

`r2_t06_committed_artifact_validation.json` 使用 `git show <artifact_commit>:<path>` 和 `git rev-parse <artifact_commit>:<path>` 读取并验证 manifest 中的 23 个 artifact；`validated_commit=0bfa2c5`、`validation_mode=git_show_committed_blob_bytes`、`failure_count=0`。验证同时复核每个 artifact 的 Git blob SHA、committed byte SHA-256 和 manifest SHA/size。

## Superseded runs

`R2-T06-20260713T174639Z` 为历史 incomplete/superseded run：其 materialization 后曾因 Windows DuckDB 文件锁以非零退出，随后只在同一目录人工收尾，不能作为 authoritative evidence。该 run 不得用于 scientific review、formal input 或下游 gate。

`R2-T06-20260713T171456Z` 保留为失败诊断 run，不删除、不覆盖、不包装为 successor evidence。

author-stage 状态保持：

```text
scientific_review_status=pending_independent_scientific_review
formal_task_completed=false
R2-T07_allowed_to_start=false
R2-T08_allowed_to_start=false
R3_allowed_to_start=false
```
