# R2-T05 实际结果分析

本报告只描述两个 T04 selected W120 primary 版本的 author-stage canonical 物化；不代表 T05 final freeze，也不打开 T06/R3。所有数量来自本次 DuckDB 实际表，并由独立 validator 重新复算。

## Daily surface 与风险集

| state_version_id | daily rows | eligible | valid | raw true | confirmed | state risk | qualified event risk | strict-core |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8 | 1751066 | 1602732 | 1602732 | 52420 | 20474 | 20474 | 13081 | 12476 |
| r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8 | 1751066 | 1601692 | 1601692 | 16073 | 4564 | 4564 | 2431 | 2939 |

## Event 与 membership

| state_version_id | events | securities | components | bridges | raw-false bridge days | confirmed days | trading span |
|---|---:|---:|---:|---:|---:|---:|---:|
| r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8 | 4561 | 771 | 4733 | 172 | 172 | 17536 | 18052 |
| r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8 | 1086 | 579 | 1108 | 22 | 22 | 3495 | 3561 |

membership rows include source qualified, retrospective prequalification, accepted raw-false bridge, unqualified reentry and synthesized terminal decision rows. `event_zone_member=true` is not used as a risk-set shortcut; bridge, prequalification and reentry rows remain excluded from qualified event risk.

## 对账与限制

T03 source event counts, authoritative security-date surface, primary confirmed truth, strict-core exact-key subset, canonical event one-to-one mapping and as-of time ordering are checked in the compact reconciliation artifacts. T03 的大型 row-level DuckDB 不进入 Git，但其 package path、byte SHA-256、表 row count 与 fingerprints 已绑定。T05 仍是 author-stage evidence；independent scientific review、T06 replay、T07 registry/freeze 和 R3 均保持关闭。
