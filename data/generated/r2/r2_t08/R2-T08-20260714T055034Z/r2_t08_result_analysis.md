# R2-T08 result analysis

## Scope and status

This author-stage package accepts the committed R2-T07 final freeze interface. It does not replay T01–T07, open the canonical DuckDB, select a release anchor, define a future label, or make a trading claim.

- task: `R2-T08`
- run: `R2-T08-20260714T055034Z`
- execution commit: `5bd00f2b5a9702f2acb02fffb79bd3c6acad95a4`
- T07 merge commit: `90aba54a54474185fa258afd605e24934bd9a864`
- T07 authoritative run: `R2-T07-20260714T034053Z`
- acceptance gates: `R2A01_t07_package_integrity=passed, R2A02_frozen_version_identity=passed, R2A03_canonical_interface_binding=passed, R2A04_registry_and_policy_closure=passed, R2A05_warning_and_limitation_preservation=passed, R2A06_window_and_strict_core_closure=passed, R2A07_release_anchor_obligation=passed, R2A08_unique_r3_entrypoint=passed`
- frozen versions: `r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8, r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8`
- independent checks: `12`, failure count `0`
- anomaly count: `0`
- committed-artifact count: `0`, failure count `0`

## Frozen interface

Both frozen versions are W120/K3/d2/g1. Strict-core sources remain internal stratification fields, not independent products, state versions, event namespaces, or parent products. The T05 canonical interfaces remain bound to their committed database SHA-256, semantic hashes, row counts, logical names and primary keys. R3 must verify the database bytes before calculation and must not substitute T06 replay tables.

The release-anchor obligation remains unselected: R3 owns the choice, `selected_anchor=null`, and exactly three candidates are recorded. No candidate is recommended here.

Warnings and limitations are carried forward per version. Confirmed exit, quality interruption, finalized-with-quality-break and right censor are not release semantics. `r2_t06_replayed_transition_ledger.trigger_trade_date` is not an authoritative causal timestamp. No future outcome, trading efficacy, precision/recall, or backtest result is asserted.

The sole R3 entrypoint is `r2_t08_r3_handoff_manifest.json`; alternative entrypoints are empty. Author-stage gates remain `formal_task_completed=false` and `R3_allowed_to_start=false` pending independent scientific review and merge.
