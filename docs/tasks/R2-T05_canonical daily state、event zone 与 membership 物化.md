# R2-T05 canonical daily state、event zone 与 membership 物化

状态：startup contract corrected，formal run pending。当前尚未执行本次修订后的 formal run，也未生成新的 author package；T06 回放、T07 最终状态登记、T08/R3 交接不属于本 task。

## 目标与边界

T05 消费 T04 post-merge immutable handoff、freeze decision/freeze plan，以及 promoted T03 row-level DuckDB。主职责是把两个 selected source candidate cell 映射为稳定 `state_version_id`，生成 canonical event ID，物化完整 authoritative security-date daily surface、event zone 和可供 T06 回放的 membership ledger，并保留 source-to-canonical reconciliation。T05 不重新运行 Pareto、72-cell scan 或状态机，不新增 W250、shared-q independent version、PCT parent 或其他候选。

启动复核只从 handoff/validation sidecar 验证门禁状态；随后按 handoff `committed_inputs` 从指定 committed Git blobs 读取 `r2_t04_freeze_decision.json`、`r2_t04_freeze_plan_manifest.json` 和 `r2_t04_phase_b_independent_validation.json`，复核 blob SHA、committed byte SHA-256、冻结计数、planned cardinality、版本字段和排除项。T04 顶层不重复要求 selected/strict-core 计数，T04 artifact 本身不修改或重新发布。

selected primary 为 `r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8` 与 `r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8`；对应 shared-q 只产生 `strict_core_member`，不产生 canonical event 或独立 membership。`W=120,K=3,d=2,g=1` 由 T04 freeze plan 逐项消费。

## 实现与 formal run

核心实现位于 `src/r2/r2_t05_canonical_materialization.py`，独立 validator 位于 `src/r2/r2_t05_independent_validator.py`，CLI 只负责参数和退出码。canonical event ID 使用 UTF-8、sorted-key、compact JSON 和完整 SHA-256，输入包含 contract version、state version、security 和首个 qualified component identity，不依赖 scan event、zone revision 或后续 component。

formal execution 必须先提交 execution code/config/schema，再由 committed Git blobs 建立 input binding。正式运行命令为：

```text
python scripts/r2/run_r2_t05_canonical_materialization.py --config configs/r2/r2_t05_canonical_state_event_zone_materialization.v1.json
python scripts/r2/validate_r2_t05_materialization.py --run-dir data/generated/r2/r2_t05/R2-T05-<UTC timestamp>
python scripts/r2/validate_r2_t05_committed_artifacts.py --run-dir data/generated/r2/r2_t05/R2-T05-<UTC timestamp>
```

T03 row-level 数据库按 T03 result package 读取路径和 SHA-256，不能用 compact counts 或 rehearsal fallback 代替。最终 manifest 记录数据库路径、字节大小、SHA-256、DuckDB 表 schema、row count 和 stable multiset fingerprint；数据库遵循仓库大文件策略留在本地，不将它伪装成已提交 artifact。

## Author-stage gate

当前 blocked marker 为：

```text
current_stage: R2
current_task: R2-T05 canonical daily state、event zone 与 membership 物化
next_planned_task: R2-T06 canonical 双层状态机无前视回放与一致性验收
R2-T05_status: startup_contract_corrected_formal_run_pending
R2-T05_startup_status: passed
R2-T05_formal_run_executed: false
R2-T05_formal_task_completed: false
R2-T06_allowed_to_start: false
R2-T07_allowed_to_start: false
R2-T08_allowed_to_start: false
R3_allowed_to_start: false
```

`r2_t05_author_stage_scientific_review.json` 必须保持 pending；Codex 不自行设置 scientific pass 或 downstream gate。若实际结果出现全零/全 NULL、daily surface 不一致、strict-core 非子集、event ID 不稳定、as-of 回填、revision 倒退、quality break 被解释为 natural exit，必须停止后续推进并回退到对应上游定义阶段。
