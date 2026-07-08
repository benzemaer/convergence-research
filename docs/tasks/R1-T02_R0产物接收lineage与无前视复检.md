# R1-T02 R0 产物接收、lineage 与无前视复检

## 目标

本任务接收 R1-T01 锁定的 R0 输入包，对 R0-T10-05 authorized input manifest、27 组 full-grid manifest、R0-T11 handoff evidence 和 R1-T01 evidence 做可追溯复核。通过后，只允许进入 R1-T03 的 27 组 W/q/K 全量轻量结构扫描。

本任务的核心结论不是状态存在性、稳定性或零模型结果，而是“R1 后续结构扫描是否可以使用这批 R0 candidate artifacts 作为输入”。

## 非目标

本任务不扫描日频状态行，不计算状态频率、共现、Lift、年份稳定性或任何零模型；不读取未来收益、未来波动扩张、突破方向、回测、组合、交易信号或参数优化结果；不冻结 R2 状态定义，也不授权 R1-T07 或 R2 启动。

## 输入

输入边界来自 R1-T01 的 `r0_input_package_lock`，包括 R0-T10-05 authorized input manifest、R0-T10-05 full-grid manifest、R0-T10-05 evidence、R0-T11 evidence 和 R1-T01 evidence。R1-T02 只使用 manifest、evidence、artifact path/hash 与行数摘要，不把行级 payload 写入文档或验证结果。

## 输出

输出包括 `configs/r1/r1_t02_r0_lineage_pit_audit.v1.json`、对应 schema、审计 runner、验证器、合成契约测试和 `docs/evidence/r1/R1-T02_r0_lineage_pit_audit_evidence.md`。正式运行摘要写入 `data/generated/r1/r1_t02/`，该目录是可重建运行产物，不提交到 Git。

## 验收标准

R1-T02 只有在以下条件全部满足时完成：R1-T01 evidence 通过并明确授权 R1-T02；R0-T10-05 / R0-T11 evidence 链路完整；authorized input manifest 与 full-grid manifest 的路径、SHA-256、27 组配置覆盖、baseline、W/q/K 网格和状态线与 R1-T01 锁定一致；per-config artifact 路径存在且 hash 匹配；manifest 层未出现未来字段、回测字段、组合字段或交易信号字段；confirmed interval 为 0 时，必须同时满足 daily confirmed true 为 0、27 组均为 zero interval，并记录原因 `no_confirmed_segments_in_r0_t07_input`。

通过后 `R1-T03_allowed_to_start = true`，但 `R1-T07_allowed_to_start = false` 且 `R2_allowed_to_start = false`。若任一 lineage、hash、禁用字段或门禁不满足，本任务状态为 blocked，不得用补充说明追认为 completed。

## 回退方式

如审计失败，回退到产生不一致的上游证据或 manifest 所属任务；不得在 R1-T02 中手工修改 R0 manifest 或 generated artifact。若需要改变 R0 输入包，必须创建新的 R0 版本并重新通过 R1-T01 manifest lock。
