# R2A-T01 result analysis

- analysis_status = `passed`
- validator_status = `passed`
- release_recommendation = `publish_candidate`
- score_release_id = `pcavt-score-w120-v1-c7e04f11a2cd09aa`
- synthetic_only = `false`

## Actual DuckDB artifact inspection

Security/date coverage: securities=800, date_min=2016-01-04, date_max=2026-06-30.

### Seven-table row counts

| table | rows |
| --- | ---: |
| securities | 800 |
| trading_sessions | 2546 |
| security_observation_spine | 1751066 |
| dimension_definitions | 5 |
| dimension_components | 10 |
| daily_component_scores | 17510660 |
| daily_dimension_scores | 8755330 |

### Observation-status distribution

| expected_observation_status | rows |
| --- | ---: |
| listing_pause | 1014 |
| missing | 19283 |
| present | 1730769 |

### Component Score distributions

| dimension | component | total_rows | eligible_rows | null_score_rows | valid_rows | unknown_rows | diagnostic_required_rows | blocked_rows | min | max | mean |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | A1_LogBodyCenterToMACloudCenter_5_60 | 1751066 | 1536246 | 214820 | 1632073 | 42899 | 0 | 76094 | 0 | 1 | 0.497953968093 |
| A | A2_BodyCenterOutsideMACloudRate20_5_60 | 1751066 | 1507205 | 243861 | 1602937 | 55631 | 0 | 92498 | 0 | 1 | 0.493366217049 |
| C | C1_LogMASpread_5_60 | 1751066 | 1587742 | 163324 | 1587742 | 143027 | 0 | 20297 | 0 | 1 | 0.512851641933 |
| C | C2_AdjVWAPSpread_5_60 | 1751066 | 1563558 | 187508 | 1563558 | 134706 | 0 | 52802 | 0 | 1 | 0.50584020548 |
| P | P1_NATR14 | 1751066 | 1623605 | 127461 | 1623605 | 107164 | 0 | 20297 | 0 | 1 | 0.527647000553 |
| P | P2_LogRange20 | 1751066 | 1619612 | 131454 | 1619612 | 111157 | 0 | 20297 | 0 | 1 | 0.511845769234 |
| T | T1_ER20 | 1751066 | 1618814 | 132252 | 1618814 | 111955 | 0 | 20297 | 0 | 1 | 0.499615119464 |
| T | T2_AbsTrendT20 | 1751066 | 1619612 | 131454 | 1619612 | 111157 | 0 | 20297 | 0 | 1 | 0.498636098234 |
| V | V1_TurnoverShrink20_60 | 1751066 | 1567078 | 183988 | 1567078 | 162449 | 0 | 21539 | 0 | 1 | 0.488062586334 |
| V | V2_AmountLevel20Pct | 1751066 | 1619612 | 131454 | 1619612 | 111157 | 0 | 20297 | 0 | 1 | 0.507616855148 |

### Dimension Score distributions

| dimension | total_rows | eligible_rows | null_score_rows | valid_rows | unknown_rows | diagnostic_required_rows | blocked_rows | min | max | mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 1751066 | 1507205 | 243861 | 1602937 | 55631 | 0 | 92498 | 0 | 1 | 0.495384081517 |
| C | 1751066 | 1563558 | 187508 | 1563558 | 134706 | 0 | 52802 | 0 | 1 | 0.51001299067 |
| P | 1751066 | 1619612 | 131454 | 1619612 | 111157 | 0 | 20297 | 0 | 1 | 0.519469856052 |
| T | 1751066 | 1618814 | 132252 | 1618814 | 111955 | 0 | 20297 | 0 | 1 | 0.499117043918 |
| V | 1751066 | 1567078 | 183988 | 1567078 | 162449 | 0 | 21539 | 0 | 1 | 0.496092520602 |

### Yearly coverage

| year | component rows | eligible rows | securities |
| ---: | ---: | ---: | ---: |
| 2016 | 1299750 | 354829 | 552 |
| 2017 | 1397390 | 1207788 | 591 |
| 2018 | 1463980 | 1352503 | 614 |
| 2019 | 1539720 | 1470062 | 649 |
| 2020 | 1631890 | 1545268 | 696 |
| 2021 | 1736260 | 1654853 | 731 |
| 2022 | 1809930 | 1746037 | 764 |
| 2023 | 1872170 | 1827808 | 781 |
| 2024 | 1902120 | 1878154 | 791 |
| 2025 | 1929630 | 1908654 | 799 |
| 2026 | 927820 | 917128 | 800 |

## Independent reconciliation evidence

- source reconciliation: PCVT source valid rows=12819633; output valid rows=12819633
- PCVT independent recomputation: samples=100824; mismatches=0
- A independent recomputation: samples=25460; mismatches=0
- component-to-dimension mean/min mismatch count: 0
- availability mismatch count: 0
- expected-empty observations=20297; blocked component rows=202970; blocked dimension rows=101485

## Anomaly register

| anomaly | status | explanation |
| --- | --- | --- |
| none | explained | No blocking anomaly was found in the inspected package. |

## Interpretation boundary

Completion of the runner and validator does not complete R2A-T01. Any unexplained anomaly blocks publication, README gate advancement, formal acceptance, and R2A-T02. This analysis does not authorize a formal run.
