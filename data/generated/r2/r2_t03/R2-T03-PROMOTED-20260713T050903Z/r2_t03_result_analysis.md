# R2-T03 promoted execution 结果分析与异常审计

本报告覆盖全部 8 routes、72 cells，不筛选 cell，不选择 winner，不冻结 d/g，也不使用未来收益、方向或回测字段。执行模式为 `promoted_preserved_fact_run_plus_current_postscan`。

## 全局执行与样本

日期范围为 2016-01-04 至 2026-06-30；每条 route 均为 800–800 只证券。8 条 route 合计 eligible days=12,422,922、confirmed days=75,364、qualified components=179,073、event zones=173,202、accepted bridge segments=5,871、reentry attempts=1,843。

## d 参数响应

- d=1：qualified components=94,002，events=90,156；retained confirmed-day ratio 范围 1.000000–1.000000，as-of coverage 范围 0.001425–0.012774。
- d=2：qualified components=53,787，events=52,360；retained confirmed-day ratio 范围 0.758761–0.856501，as-of coverage 范围 0.000744–0.007988。
- d=3：qualified components=31,284，events=30,686；retained confirmed-day ratio 范围 0.530812–0.683403，as-of coverage 范围 0.000390–0.005035。

12 项冻结 parameter invariants 在 288 个 scope rows 上均为零 violation；d 增大时 retrospective/as-of coverage 非增，qualification delay 非减。

## g 参数响应

- g=0：events=59,691，bridges=0，raw-false bridged days=0，preconfirmation days=0；duration q95 范围 5.00–9.00。
- g=1：events=57,428，bridges=2,263，raw-false bridged days=2,263，preconfirmation days=4,526；duration q95 范围 6.00–11.00。
- g=2：events=56,083，bridges=3,608，raw-false bridged days=4,953，preconfirmation days=7,499；duration q95 范围 6.00–11.00。

g 增大时 bridge、bridged days 与 zone coverage 非减，confirmed/qualified days 保持冻结不变量；g=0 identity 全部闭合。

## Primary、strict-core 与 window

36 个 strict pairs 全部满足 subset；strict confirmed-day share 范围 0.592219–0.643953，strict event share 范围 0.541635–0.720880。shell-only event/day 与 strict component 指标完整保留在 descriptive JSON 和 compact CSV。

36 个 W120/W250 pairs 的 confirmed-day Jaccard 范围 0.197784–0.338116；matched events 合计 42,948，component overlaps 合计 44,517。own/common denominator reconciliation 均通过。

## Event-zone 几何

72 cells 的 event count 范围 272–7,671，duration mean 范围 2.06–5.10，duration q95 范围 5.00–11.00，max zone span 范围 12–28。merge ratio、open-event ratio、density、mega-zone concentration、events/security、events/year 与 max-year share 均逐 cell 保存在正式 descriptive JSON。

## Censor 与质量中断

natural finalized=172,981，quality-break finalized=221，right-censored=0，prequalification right-censored=0，quality-interrupted short components=48。这些 population 分开统计，未混用 denominator。

## 异常扫描与科学边界

Runtime status=`passed`；anomaly status=`passed`；blocking engineering anomalies=0，scientific investigation items=0，冻结 scientific gate failures=0。

本结果支持描述性状态机有效性、参数响应和区间几何审计，不支持 winner 选择、最佳 d/g 冻结、未来收益或策略有效性主张。R2-T04 与 R3 继续关闭，等待独立 scientific review 与 repository final gate。
