# R2A-T04 CA four-q formal result acceptance

## 接受范围

Owner 接受 run `R2A-T04-20260720T002158508Z` 在固定 C+A、K=5、相同全市场 observation spine 下对 q=1000/1500/2000/2500 所形成的 formal execution、统计事实、响应梯度和审计证据。Execution HEAD 为 `1d34cf49b9816aac92837213fa668356d5c7b45d`，authorization revision 为 6。

本次接受不是参数选择。`q_selection_status=not_selected`，未选择 canonical dynamic request，未注册 dynamic state，未生成交易信号，也未执行或授权回测。

## Formal 与验证结果

Revision 6 formal run 已完成，四个 request 严格串行执行，DuckDB threads 固定为 4。四个 request validator 与 formal validation 均 passed；request validator、response、security scope、interval reconciliation、Score endpoint reconciliation 和 blocking anomaly 的失败计数均为 0。四个正式输出与 q10/q20 supplemental benchmark 及 q15/q25 benchmark 的五表 row count、schema fingerprint 和 canonical fingerprint mismatch 总数为 0。

| Request | Raw true | Confirmed true | Intervals | Securities with interval |
| --- | ---: | ---: | ---: | ---: |
| CA_q10_k5 | 20,559 | 1,916 | 751 | 473 |
| CA_q15_k5 | 46,651 | 7,125 | 2,426 | 734 |
| CA_q20_k5 | 81,535 | 17,642 | 5,372 | 775 |
| CA_q25_k5 | 124,893 | 35,098 | 9,107 | 788 |

八项 response checks 全部 passed。三个相邻 raw subset 与三个相邻 confirmed subset 均无 violation，joint-ready 在四档间完全相同，整个梯度严格非退化。因此允许的有限结论是：随着 q 放宽，raw-state、confirmed-state、confirmed interval 和出现过区间的证券覆盖均增加。不得据此宣称任一 q 最优或已成为 canonical。

## Independent-review 历史链

首次 independent review 的 failed receipt 保存在 `operator-logs/R2A-T04-20260720T002158508Z.independent.attempt1.failed.receipt.json`，SHA-256 为 `81da003835f045c1938ebc36f9d7dfc9d22a1b020c44a41a55ca00051b2c98b1`。它属于 operator invocation evidence，失败原因是 operator 提供了不存在的 Score 路径，分类为 `score_file_identity`。它没有被复制进或写入 immutable formal RunRoot，也不表示 formal computation、formal validation、Score identity 或结果本身失败。

Owner 随后授权 successor independent review。两次 review 之间没有重新执行 formal request，也没有修改 formal package。最终有效的 passed receipt 位于 `formal-runs/R2A-T04-20260720T002158508Z/independent_review_receipt.json`，SHA-256 为 `8b698c68deb5053634cac9affcb1be7946c6f5b97dc66215a138105efe0eac16`；其 Score identity passed、mismatch count 为 0，mismatch fingerprint 为 `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`。

## Closure

Formal result review、owner result review 和 result review 均为 accepted。Accepted handoff 与唯一 `DONE` 已创建。R2A-T05 只能在 PR #113 合并后启动；本 closure 不定义或启动 T05 implementation。
