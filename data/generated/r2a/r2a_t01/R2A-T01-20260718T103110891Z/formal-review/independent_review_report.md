# R2A-T01 independent formal extract review

## 审阅边界

本审阅只读取已提交的 review extract 与 compact review manifests/evidence。未读取完整
`score_data.duckdb`，未调用 formal materializer、validator、analyzer 或任何 R2A
production Score/dimension 函数，也未创建 `DONE`、successor run 或下游发布状态。

## 方法独立性

Review script imports：`argparse`, `ast`, `collections`, `datetime`, `duckdb`, `hashlib`, `json`, `math`, `pathlib`, `re`, `sys`, `zoneinfo`。

明确未 import：`src.r2a.score_engine`, `src.r2a.r2a_t01_validator`, `src.r2a.r2a_t01_score_release`, `src.r2a.r2a_t01_result_analysis`。

## 文件 identity

| item | value |
| --- | --- |
| review extract SHA-256 | `e42ff63c8f5416d1c2372daf2d2033f417ee80d951966d2a89acde9d5da4fb79` |
| review extract bytes | 30420992 |
| bundle manifest SHA-256 | `d123383b11bb5d64f773bf329151fa94b38c4d8a7499ab65f4178837962a73f3` |
| formal database reference | `d1ee60ef854a5fe18042c61175febd837db43d76c5c104462ce61c3f176403a3` / 4255395840 bytes |

## 30-table inventory

| table | rows | columns |
| --- | ---: | ---: |
| analysis_anomalies | 1 | 6 |
| availability_profile | 4 | 6 |
| cardinality_profile | 6 | 5 |
| component_score_profile | 10 | 13 |
| component_validity_profile | 30 | 9 |
| dimension_score_profile | 5 | 14 |
| dimension_validity_profile | 15 | 8 |
| expected_empty_profile | 1 | 4 |
| formal_coverage | 7 | 4 |
| formal_semantic_fingerprints | 7 | 4 |
| formal_table_counts | 7 | 2 |
| observation_status_profile | 3 | 5 |
| reference_window_profile | 10 | 12 |
| registry_fingerprints | 2 | 2 |
| review_metadata | 17 | 2 |
| sample_a_raw | 42450 | 15 |
| sample_component_scores | 212250 | 22 |
| sample_dimension_scores | 106125 | 15 |
| sample_pcvt_source_component_scores | 165296 | 19 |
| sample_pcvt_source_dimension_scores | 82648 | 12 |
| sample_pcvt_validation_raw | 165296 | 15 |
| sample_securities | 12 | 11 |
| sample_spine | 21225 | 8 |
| sequence_domain_profile | 3 | 6 |
| source_bindings | 5 | 15 |
| source_reconciliation_profile | 10 | 2 |
| validator_checks | 53 | 2 |
| validator_metrics | 15 | 2 |
| yearly_component_profile | 110 | 14 |
| yearly_dimension_profile | 55 | 13 |

数据库恰含 30 张表；manifest table set、实际 row counts、schema inventory、无
view/macro/temp relation 以及关闭后只读重开检查均通过。

## 12 样本选择

- `000001.SZ`：first_3_sorted_security_ids
- `000002.SZ`：first_3_sorted_security_ids
- `000009.SZ`：first_3_sorted_security_ids
- `688819.SH`：last_3_sorted_security_ids
- `688981.SH`：last_3_sorted_security_ids
- `689009.SH`：last_3_sorted_security_ids
- `601077.SH`：required_security_601077_SH
- `000155.SZ`：maximum_expected_empty_count
- `601112.SH`：latest_first_expected_date, lowest_positive_a_valid_count
- `001280.SZ`：lowest_positive_pcvt_eligible_rate
- `300502.SZ`：maximum_sequence_session_mismatch_count
- `000021.SZ`：deterministic_sorted_fill_to_12

所有样本均保留完整 observation history。

## PCVT strict-past 独立复算

比较 169800 行；row mismatch=0，
field mismatch=0，最大绝对差=0。

## A strict-past 独立复算

比较 42450 行；row mismatch=0，
field mismatch=0，最大绝对差=0。
A components 恰为 A1/A2，A2b rows=0。

## 五维 mean/min 独立复算

| dimension | compared | eligible | mismatches | max mean diff | max min diff |
| --- | ---: | ---: | ---: | ---: | ---: |
| P | 21225 | 19037 | 0 | 0 | 0 |
| C | 21225 | 18410 | 0 | 0 | 0 |
| A | 21225 | 17727 | 0 | 0 | 0 |
| V | 21225 | 17604 | 0 | 0 | 0 |
| T | 21225 | 19027 | 0 | 0 | 0 |

## PCVT accepted source reconciliation

Component compared=165296，key mismatch=0，
row mismatch=0，field mismatch=0。
Dimension compared=82648，key mismatch=0，
row mismatch=0，field mismatch=0。

## Sequence、expected-empty 与 availability

Sequence checked securities=12，mismatch=0。
Expected-empty observations=563，
blocked components=5630，
blocked dimensions=2815，
mismatch=0。
Availability mismatch：spine=0，
component=0，
dimension=0。

## 全市场 aggregate profiles

七表数量={'daily_component_scores': 17510660, 'daily_dimension_scores': 8755330, 'dimension_components': 10, 'dimension_definitions': 5, 'securities': 800, 'security_observation_spine': 1751066, 'trading_sessions': 2546}。Observation status={'listing_pause': 1014, 'missing': 19283, 'present': 1730769}。
Validator checks=53，failed=0；
blocking anomalies=0；
aggregate arithmetic failures=0。
所有 component/dimension 的 validity 加总、eligible/null 关系、0/1 domain 与非退化检查均已独立复算。

## 年度 coverage 与合理性

| year | securities | component rows | component eligible | rate | dimension rows | dimension eligible | rate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2016 | 552 | 1299750 | 354829 | 0.272998 | 649875 | 157405 | 0.242208 |
| 2017 | 591 | 1397390 | 1207788 | 0.864317 | 698695 | 595306 | 0.852026 |
| 2018 | 614 | 1463980 | 1352503 | 0.923853 | 731990 | 672021 | 0.918074 |
| 2019 | 649 | 1539720 | 1470062 | 0.954759 | 769860 | 730660 | 0.949082 |
| 2020 | 696 | 1631890 | 1545268 | 0.946919 | 815945 | 768562 | 0.941929 |
| 2021 | 731 | 1736260 | 1654853 | 0.953114 | 868130 | 823056 | 0.948079 |
| 2022 | 764 | 1809930 | 1746037 | 0.964699 | 904965 | 869952 | 0.961310 |
| 2023 | 781 | 1872170 | 1827808 | 0.976305 | 936085 | 911637 | 0.973883 |
| 2024 | 791 | 1902120 | 1878154 | 0.987400 | 951060 | 937157 | 0.985382 |
| 2025 | 799 | 1929630 | 1908654 | 0.989130 | 964815 | 952701 | 0.987444 |
| 2026 | 800 | 927820 | 917128 | 0.988476 | 463910 | 457810 | 0.986851 |

2016 eligibility 明显较低，与 W120 启动期及 staggered listings 一致；2017 后显著
上升，未出现中间年份归零。2026 数据截至 2026-06-30，属于部分年度；未把逐年
单调上升设为 gate。

## Mismatch 与 anomaly

总 mismatch=0；年度无法解释 anomaly=0。

## 最终 recommendation

`accept_candidate`。Independent overall status=`passed`。
该 recommendation 只针对 candidate 进入独立 formal-result review，不表示 R2A-T01
completed/accepted，不推进 README gate、A-layer registration 或 R2A-T02。
