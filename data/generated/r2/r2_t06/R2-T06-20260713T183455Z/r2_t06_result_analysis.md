# R2-T06 实际结果分析

正式回放基于 committed T03 dense facts 独立重建确认、component、event zone、membership 与 daily as-of。

## 验收

- `daily_exact_t05`: `0`
- `event_exact_t05`: `0`
- `membership_exact_t05`: `0`
- `daily_qualified_key_mismatch`: `0`
- `qualified_risk_formula_violation`: `0`
- `strict_core_subset_violation`: `0`
- `active_event_fk_violation`: `0`
- `membership_lookahead_violation`: `0`
- `qualified_component_lineage_mismatch`: `0`
- `qualified_component_prequalification_violation`: `0`
- `unqualified_reentry_risk_violation`: `0`
- `transition_ledger_empty`: `0`
- `independent_interval_lineage_mismatch`: `0`
- `independent_component_lineage_mismatch`: `0`
- `independent_event_identity_mismatch`: `0`
- `independent_transition_registry_mismatch`: `0`
- `independent_current_event_overlay_mismatch`: `0`

结论：passed。author-stage 不推进科学审阅或下游 gate。
