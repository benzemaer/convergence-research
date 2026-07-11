# R2-T02 K/d/g、事件指标、hard gate 与 R3 risk-set 契约

## 任务边界

本任务是 `protocol_freeze`，只冻结从 confirmed state 到 retrospective event geometry 的规则、指标、hard gate 和 R3 risk-set guard。它不读取正式日表，不运行四条路线的 `d x g` 几何扫描，不选择参数，不定义 release 或未来标签，也不形成状态版本。输入候选边界由 R2-T01 final gate 固定为 4 条 primary、4 条 shared-q sidecar、2 条 sensitivity-only 和 2 条 excluded；后两类在 T03 的 cell 数均为零。

## 事件规则

`K=3`：同一路线、证券内连续三个 eligible、valid、raw-true 交易行后，仅第三行起 confirmed，不回填前两行。unknown、blocked、ineligible 和缺失交易行均重置计数。confirmed interval 是 maximal consecutive confirmed-true trading rows。

`d in {1,2,3}` 且比较符为 `>=`。第 d 个 confirmed 日收盘后取得资格。资格成立后可在 retrospective geometry 中包含该 interval 的较早 confirmed 日，但其 membership availability 不早于 qualification time。

`g in {0,1,2}`，单位是 eligible trading days。只有两个 qualified intervals 之间全部为 eligible confirmed-false rows 且 gap 不超过 g 时才可合并。unknown、blocked、ineligible、缺行及 intervening unqualified confirmed interval 都是 hard break。bridge membership 直到后一个 interval 取得资格才可见。open zone 没有伪造 finalization time，并排除在 closed-duration quantiles 之外。

事件 ID 对 `contract_version, route_id, security_id, d, g, first_qualified_interval_confirmed_start_date` 做 SHA-256；后续 merge 不改写 identity。

## 指标与 denominator

机器可读指标字典位于正式 run 的 `r2_t02_metric_dictionary.csv`。每项记录 numerator、denominator、deduplication key、included/excluded rows、open policy、denominator scope、参数响应、hard-gate 用途和零分母策略。

`own_eligible` 是路线自身合法计算状态的 exact key set，用于 viability。`common_W120_W250` 仅在相同 state line 且相同 primary/shared role 内取 W120/W250 exact intersection，用于公平窗口比较和 overlap。禁止跨状态线、跨角色或以较小 own sample 冒充 intersection。

## Hard Gates

全局 lineage、schema、source hash/supersession、重复键、非法 bridge、守恒、overlap、post-merge short zone、risk-set、strict-core subset 和 forbidden fields 均为零容忍。S_PCT 与 S_PCVT 的 event/security floor、retention、drop、bridge、merge、open、年份集中度和 duration inflation 阈值均在 versioned config 中冻结；阈值不按 W 定制，不构成评分或 winner。

固定 d 改 g 时，qualified intervals、qualified confirmed days、confirmed coverage 和 drop rate 不变；event count 单调不增，span/bridge 单调不减。固定 g 改 d 时，qualified intervals/days/coverage 单调不增，drop 单调不减，并与 upstream duration histogram 精确守恒。无理论响应样本时必须报告 `not_applicable_with_reason`。

shared-q strict core 必须在 common eligible keys 上是 paired primary 的 confirmed subset；standalone fallback 仍须通过同状态线完整 geometry gates，并需要明确用户决策，不能静默补选。

## R3 Risk Set

`risk_set_eligible=true` 当且仅当 `confirmed_state` 显式为 true 且该行在 evaluation time 已可见。unknown、blocked、null 和 bridged false days 均不得进入风险集。`event_zone_member` 不能扩张风险集；尚未取得 d 资格的 confirmed day 仍可进入风险集。T02 不定义 release、outcome、control、cooldown 或交易信号。

## Gate 状态

作者阶段只允许 `scientific_review_status=pending`、`formal_task_completed=false` 和 `R2-T03_allowed_to_start=false`。独立审阅必须绑定 reviewed HEAD 和全部 contract/config/schema/artifact hashes；repository final gate 才能仅授权 R2-T03，R2-T04 与 R3 继续关闭。任一实质性 contract hash 变化必须创建新版本，并使绑定旧版本的 T03 run superseded。
