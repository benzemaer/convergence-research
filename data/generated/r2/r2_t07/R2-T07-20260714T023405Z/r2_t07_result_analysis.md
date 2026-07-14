# R2-T07 successor independent result analysis

- Run: `R2-T07-20260714T023405Z`
- Execution commit: `a76e8c990e6279d5c840115a34014f1590e9869e`
- Scope: registry/freeze only; no replay performed.
- Independent validation: `passed` with `0` failures.

## Frozen state versions

| state_version_id | line | W | K | qP | qC | qT | qV | d | g | strict core | source cell | strict-core cell | formula binding | R1 row | warnings |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|
| r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8 | S_PCT | 120 | 3 | 0.2 | 0.2 | 0.25 | 0.2 | 2 | 1 | True | r2_s_pct_w120_qt25_primary__d2__g1 | r2_s_pct_w120_q20_shared__d2__g1 | `58a51105740a6dd6bb4cada54718026a67a476290a1ed828943d76f6cbc38b78` | `q_W120_K3_P20_C20_T25_V20_S_PCT` / `7c376fcc17f3b9fa0ac72ccb92cfbdad35e70c3960baa85a7457694159c0844b` | `["affected_lift_deterioration_vs_baseline","layer_q_complexity_added","same_sample_formal_revalidation_only","selection_path_not_independently_confirmed"]` |
| r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8 | S_PCVT | 120 | 3 | 0.2 | 0.2 | 0.2 | 0.3 | 2 | 1 | True | r2_s_pcvt_w120_qv30_primary__d2__g1 | r2_s_pcvt_w120_q20_shared__d2__g1 | `58a51105740a6dd6bb4cada54718026a67a476290a1ed828943d76f6cbc38b78` | `q_W120_K3_P20_C20_T20_V30_S_PCVT` / `e155fe06fbc492427beb4d3a4fec8389f1ff2ae0855bb060e44837c47c34c04b` | `["V_security_negative_delta_share_material","V_selectivity_reduced_but_guard_passed","layer_q_complexity_added","same_sample_formal_revalidation_only","selection_path_not_independently_confirmed"]` |

## Upstream and canonical bindings

- T04: `R2-T04-20260713T120000Z`; decision `f1344346662225f1f0837bc160be1bf6f88f12174cbacc8f27f8a126ad9bf3bf`; freeze decision `ceb99c3480aa49a13a545dd06d43a85c2faf378256c49623b17d1b0255e0048d`; freeze plan `1ea368d67b9445a6916ee31ff33e6f0a5f94ed43b0fd5a2b716f8d60c39a80dc`.
- T05: `R2-T05-20260713T154957Z`; database `4488f0cca26f703890dfea8701ed761e7de124467a6d373f2e0264dbd0215129`; daily `64c396322b0e358a5c5440eebe90483d65f18a2cc6461a9a28f2cb72711da4ec` (3502132 rows); event `4c0fcec9012fa46a7b68d3dd436e9e14881c44719f90def22490b8b6bc118acb` (5647 rows); membership `5664a11fc7f4c61f3b6e8d4b0a465ed0d5c89447a38fc29cd12e966ab6340d0a` (27388 rows).
- T06: `R2-T06-20260713T183455Z`; merge `12cd31d125e31762e62f8b1db5a808d189c7c732`; reviewed `4604117678b53b2c756d866babd9a4ad8d85a2ef`; review `4690087611`; artifact `07f4771ea78038d230e1dba62c2494614b4553aa`; replay database `671b1a1027c1e56af0a551142fc35e31a399d699d732fc145d36c189973ccea1`.
- Core artifact refs: state registry `{'path': 'data/generated/r2/r2_t07/R2-T07-20260714T023405Z/r2_state_version_registry.csv', 'sha256': 'b08f6254bc6c76481d449cd03a8b3622797970446055e47a5ca6725c6ae17e3e', 'size_bytes': 4684}`; interval registry `{'path': 'data/generated/r2/r2_t07/R2-T07-20260714T023405Z/r2_interval_rule_registry.json', 'sha256': 'd3da2885752b0a43ebd59672ae09e6b5579f34439be0f0635bd7ae70b51f4551', 'size_bytes': 3434}`; event registry `{'path': 'data/generated/r2/r2_t07/R2-T07-20260714T023405Z/r2_event_state_machine_registry.json', 'sha256': '68b974df058ddd6821f78d4e2acec9db60dd8b6819438151314e2587639ca09a', 'size_bytes': 9656}`; decision log `{'path': 'data/generated/r2/r2_t07/R2-T07-20260714T023405Z/r2_freeze_decision_log.json', 'sha256': 'bdbbf49550a75080ff02734de910c6cd8d291c59b6062f122dda1760191a15ba', 'size_bytes': 1646}`.

## Rule and consumer contracts

- Interval registry `r2_t07_interval_rule_registry.v2`: K=3, confirmation backfill=False, d=2 `confirmed_trading_day`, g=1 `eligible_valid_raw_false_trading_day`; hard breaks `['blocked', 'diagnostic_required', 'ineligible', 'intervening_unqualified_confirmed_interval', 'missing_expected_trading_row', 'missing_observation', 'unknown']`.
- Event registry `r2_t07_event_state_machine_registry.v2`: states=8, transitions=19, transition registry SHA `e2656afa07244b5fb2219327dda48dc9a6968e61a87c40662fb882208ca5440e`.
- Canonical risk policies: `{'daily_audit_formula': 'qualified_event_risk_set_eligible => state_risk_set_eligible AND component_qualified_as_of AND event_zone_member AND NOT is_raw_false_bridge AND NOT is_preconfirmation_gap', 'excluded_source_only_fields': ['raw_false_gap_ordinal_as_of', 'raw_false_gap_count_as_of'], 'membership_audit_formula': 'event_zone_member AND NOT state_risk_set_eligible is permitted for bridge/preconfirmation rows and is not an audit failure', 'qualified_event_risk_set_eligible': 'direct canonical daily/membership field; event_zone_member alone is insufficient', 'required_canonical_fields': ['state_risk_set_eligible', 'qualified_event_risk_set_eligible'], 'state_risk_set_eligible': 'direct canonical daily field; not derived from event_zone_member'}`.
- Authoritative times: `['confirmation_time', 'first_qualification_time', 'last_exit_observation_time', 'zone_finalization_time', 'membership_available_time']`; non-authoritative: `['r2_t06_replayed_transition_ledger.trigger_trade_date']`.
- Allowed uses: `['T08_R2_final_acceptance_input', 'T08_R3_handoff_source', 'canonical_daily_state_consumption', 'canonical_event_zone_consumption', 'canonical_event_membership_consumption', 'state_risk_set_consumption', 'qualified_event_risk_set_consumption', 'R3_contract_design_only']`.
- Forbidden reinterpretations: `['no_trading_advantage_claim', 'no_global_optimum_claim', 'no_future_outcome_selection', 'confirmed_exit_is_not_release', 'quality_interruption_is_not_natural_release', 'event_zone_member_is_not_risk_set', 'no_zone_finalization_time_backfill', 'no_state_and_qualified_event_risk_set_mixing', 'strict_core_is_not_independent_product', 'no_PCT_parent_product', 'transition_trigger_trade_date_not_causal_time', 'no_cross_state_version_event_merge']`.

## Reconciliation and gates

- Registry reconciliation is computed from the actual registry, decision log and final manifest; no missing-audit passed placeholder is accepted.
- Forbidden-use scan recursively inspected generated JSON keys/values and required negative guards.
- Final downstream gates: `{'R2-T08_allowed_to_start': False, 'R3_allowed_to_start': False}`.
- Result: `passed`; formal task remains author-stage incomplete and scientific review remains pending.
