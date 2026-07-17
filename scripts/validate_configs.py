"""Validate committed governance configurations."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
D2_HITHINK_MATERIALIZATION_SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "d2_hithink_raw_market_prices_candidate_materialization_contract.schema.json"
)
D2_HITHINK_MATERIALIZATION_CONFIG_PATH = (
    ROOT
    / "configs"
    / "d2"
    / "hithink_raw_market_prices_candidate_materialization_contract.v1.json"
)
D2_HITHINK_ARTIFACT_SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "d2_hithink_raw_market_prices_candidate_artifact_contract.schema.json"
)
D2_HITHINK_ARTIFACT_CONFIG_PATH = (
    ROOT
    / "configs"
    / "d2"
    / "hithink_raw_market_prices_candidate_artifact_contract.v1.json"
)
D2_T11_SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "d2_source_status_factor_evidence_acceptance_handoff_contract.schema.json"
)
D2_T11_CONFIG_PATH = (
    ROOT
    / "configs"
    / "d2"
    / "source_status_factor_evidence_acceptance_handoff_contract.v1.json"
)
D2_T12_SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "d2_tnskhdata_tushare_hithink_provider_remediation_contract.schema.json"
)
D2_T12_CONFIG_PATH = (
    ROOT
    / "configs"
    / "d2"
    / "tnskhdata_tushare_hithink_provider_remediation_contract.v1.json"
)
D2_T12_ASOF_SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "d2_tnskhdata_source_level_asof_snapshot_revision_policy.schema.json"
)
D2_T12_ASOF_CONFIG_PATH = (
    ROOT
    / "configs"
    / "d2"
    / "tnskhdata_source_level_asof_snapshot_revision_policy.v1.json"
)
D2_T13_SCHEMA_PATH = (
    ROOT
    / "schemas"
    / "d2_tnskhdata_full_materialization_acceptance_contract.schema.json"
)
D2_T13_CONFIG_PATH = (
    ROOT
    / "configs"
    / "d2"
    / "tnskhdata_full_materialization_acceptance_contract.v1.json"
)
SECURITY_MAPPING_REFERENCE_CONTRACT_PATH = (
    ROOT
    / "configs/d1"
    / "csi800_static_2026_06_security_mapping_reference_contract.v1.json"
)
SECURITY_MAPPING_OUTPUT_CONTRACT_PATH = (
    ROOT
    / "configs/d1"
    / "csi800_static_2026_06_security_mapping_output_contract.v1.json"
)
SECURITY_MAPPING_OUTPUT_REPORT_PATH = (
    ROOT / "configs/d1" / "csi800_static_2026_06_security_mapping_output_report.v1.json"
)
MEMBERSHIP_REFERENCE_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_reference.v1.json"
)
MEMBERSHIP_COMPLETION_REPORT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_completion_report.v1.json"
)
CONFIGS = (
    (
        ROOT / "schemas/g0_universe_time_boundaries.schema.json",
        ROOT / "configs/g0/universe_time_boundaries.v1.json",
    ),
    (
        ROOT / "schemas/d0_source_registry.schema.json",
        ROOT / "configs/d0/source_registry.v1.json",
    ),
    (
        ROOT / "schemas/d0_data_product_contracts.schema.json",
        ROOT / "configs/d0/data_product_contracts.v1.json",
    ),
    (
        ROOT / "schemas/d1_security_master_contract.schema.json",
        ROOT / "configs/d1/security_master_contract.v1.json",
    ),
    (
        ROOT / "schemas/d1_trading_calendar_status_contract.schema.json",
        ROOT / "configs/d1/trading_calendar_status_contract.v1.json",
    ),
    (
        ROOT / "schemas/d1_corporate_actions_adjustment_contract.schema.json",
        ROOT / "configs/d1/corporate_actions_adjustment_contract.v1.json",
    ),
    (
        ROOT / "schemas/d1_csi800_static_membership_contract.schema.json",
        ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json",
    ),
    (
        ROOT / "schemas/d1_csi800_static_membership_validation_report.schema.json",
        ROOT / "configs/d1/csi800_static_2026_06_membership_validation_report.v1.json",
    ),
    (
        ROOT / "schemas/d1_csi800_static_membership_field_diagnostics.schema.json",
        ROOT / "configs/d1/csi800_static_2026_06_membership_field_diagnostics.v1.json",
    ),
    (
        ROOT / "schemas/d1_csi800_static_membership_field_aliases.schema.json",
        ROOT / "configs/d1/csi800_static_2026_06_membership_field_aliases.v1.json",
    ),
    (
        ROOT
        / "schemas/d1_csi800_static_security_mapping_reference_contract.schema.json",
        SECURITY_MAPPING_REFERENCE_CONTRACT_PATH,
    ),
    (
        ROOT / "schemas/d1_csi800_static_security_mapping_output_contract.schema.json",
        SECURITY_MAPPING_OUTPUT_CONTRACT_PATH,
    ),
    (
        ROOT / "schemas/d1_csi800_static_security_mapping_output_report.schema.json",
        SECURITY_MAPPING_OUTPUT_REPORT_PATH,
    ),
    (
        ROOT / "schemas/d1_csi800_static_membership_reference.schema.json",
        MEMBERSHIP_REFERENCE_PATH,
    ),
    (
        ROOT / "schemas/d1_csi800_static_membership_completion_report.schema.json",
        MEMBERSHIP_COMPLETION_REPORT_PATH,
    ),
    (
        ROOT / "schemas/d3_daily_market_observations_contract.schema.json",
        ROOT / "configs/d3/daily_market_observations_contract.v1.json",
    ),
    (
        ROOT / "schemas/d3_daily_market_observation_values_contract.schema.json",
        ROOT / "configs/d3/daily_market_observation_values_contract.v1.json",
    ),
    (
        ROOT / "schemas/d3_component_lineage_no_bypass_contract.schema.json",
        ROOT / "configs/d3/component_lineage_no_bypass_contract.v1.json",
    ),
    (
        ROOT / "schemas/d3_quality_readiness_contract.schema.json",
        ROOT / "configs/d3/quality_readiness_contract.v1.json",
    ),
    (
        ROOT / "schemas/d3_synthetic_daily_observation_build_contract.schema.json",
        ROOT / "configs/d3/synthetic_daily_observation_build_contract.v1.json",
    ),
    (
        ROOT / "schemas/d3_data_version_quality_manifest_gate_contract.schema.json",
        ROOT / "configs/d3/data_version_quality_manifest_gate_contract.v1.json",
    ),
    (
        ROOT / "schemas/d3_t07_candidate_daily_observation_contract.schema.json",
        ROOT / "configs/d3/d3_t07_candidate_daily_observation_contract.v1.json",
    ),
    (
        ROOT / "schemas/d3_t08_research_dataset_registry_contract.schema.json",
        ROOT / "configs/d3/d3_t08_research_dataset_registry_contract.v1.json",
    ),
    (
        ROOT / "schemas/d3_t10_field_availability_probe_gap_fill_contract.schema.json",
        ROOT / "configs/d3/d3_t10_field_availability_probe_gap_fill_contract.v1.json",
    ),
    (
        ROOT
        / "schemas/d3_t11_volume_amount_share_turnover_candidate_contract.schema.json",
        ROOT
        / "configs/d3/d3_t11_volume_amount_share_turnover_candidate_contract.v1.json",
    ),
    (
        ROOT / "schemas/d3_t12_open_candidate_gate_contract.schema.json",
        ROOT / "configs/d3/d3_t12_open_candidate_gate_contract.v1.json",
    ),
    (
        ROOT / "schemas/r0/r0_t01_pcvt_candidate_spec.schema.json",
        ROOT / "configs/r0/r0_t01_pcvt_candidate_spec.v1.json",
    ),
    (
        ROOT / "schemas/r0/r0_t02_input_readiness_gate_contract.schema.json",
        ROOT / "configs/r0/r0_t02_input_readiness_gate_contract.v1.json",
    ),
    (
        ROOT / "schemas/r0/r0_t03_v_layer_turnover_readiness_contract.schema.json",
        ROOT / "configs/r0/r0_t03_v_layer_turnover_readiness_contract.v1.json",
    ),
    (
        ROOT / "schemas/r0/r0_t04_raw_metric_engine_contract.schema.json",
        ROOT / "configs/r0/r0_t04_raw_metric_engine_contract.v1.json",
    ),
    (
        ROOT / "schemas/r0/r0_t05_strict_past_percentile_score_contract.schema.json",
        ROOT / "configs/r0/r0_t05_strict_past_percentile_score_contract.v1.json",
    ),
    (
        ROOT / "schemas/r0/r0_t06_weak_dimension_nested_state_contract.schema.json",
        ROOT / "configs/r0/r0_t06_weak_dimension_nested_state_contract.v1.json",
    ),
    (
        ROOT / "schemas/r0/r0_t07_confirmation_streak_interval_contract.schema.json",
        ROOT / "configs/r0/r0_t07_confirmation_streak_interval_contract.v1.json",
    ),
    (
        ROOT / "schemas/r0/r0_t08_main_grid_candidate_artifact_contract.schema.json",
        ROOT / "configs/r0/r0_t08_main_grid_candidate_artifact_contract.v1.json",
    ),
    (
        ROOT / "schemas/r0/r0_t09_main_grid_materialization_contract.schema.json",
        ROOT / "configs/r0/r0_t09_main_grid_materialization_contract.v1.json",
    ),
    (
        ROOT / "schemas/r0/r0_t15_layer_q_vector_materialization.schema.json",
        ROOT / "configs/r0/r0_t15_layer_q_vector_materialization.v1.json",
    ),
    (
        ROOT / "schemas/r0/r0_t15_author_revision.schema.json",
        ROOT / "configs/r0/r0_t15_author_revision.v1.json",
    ),
    (
        ROOT / "schemas/r1/r1_t01_validation_protocol_manifest_lock.schema.json",
        ROOT / "configs/r1/r1_t01_validation_protocol_manifest_lock.v1.json",
    ),
    (
        ROOT / "schemas/r1/r1_t02_r0_lineage_pit_audit.schema.json",
        ROOT / "configs/r1/r1_t02_r0_lineage_pit_audit.v1.json",
    ),
    (
        ROOT / "schemas/r1/r1_t03_27_grid_light_profile.schema.json",
        ROOT / "configs/r1/r1_t03_27_grid_light_profile.v1.json",
    ),
    (
        ROOT / "schemas/r1/r1_t04_state_line_profiles.schema.json",
        ROOT / "configs/r1/r1_t04_state_line_profiles.v1.json",
    ),
    (
        ROOT / "schemas/r1/r1_t05_indicator_intralayer_diagnostics.schema.json",
        ROOT / "configs/r1/r1_t05_indicator_intralayer_diagnostics.v1.json",
    ),
    (
        ROOT / "schemas/r1/r1_t06_contemporaneous_retention_lift.schema.json",
        ROOT / "configs/r1/r1_t06_contemporaneous_retention_lift.v1.json",
    ),
    (
        ROOT / "schemas/r1/r1_t07_p_onset_fixed_lag_relations.schema.json",
        ROOT / "configs/r1/r1_t07_p_onset_fixed_lag_relations.v1.json",
    ),
    (
        ROOT / "schemas/r1/r1_t08_global_nested_null_models.schema.json",
        ROOT / "configs/r1/r1_t08_global_nested_null_models.v1.json",
    ),
    (
        ROOT / "schemas/r1/r1_t09_year_stability_concentration.schema.json",
        ROOT / "configs/r1/r1_t09_year_stability_concentration.v1.json",
    ),
    (
        ROOT / "schemas/r1/r1_t14_01_layer_q_response_diagnostic.schema.json",
        ROOT / "configs/r1/r1_t14_01_layer_q_response_diagnostic.v1.json",
    ),
    (
        ROOT / "schemas/r1/r1_t14_02_formal_structural_revalidation.schema.json",
        ROOT / "configs/r1/r1_t14_02_formal_structural_revalidation.v1.json",
    ),
    (
        ROOT / "schemas/r1/r1_t14_02_formal_structural_revalidation.schema.json",
        ROOT / "configs/r1/r1_t14_02_formal_structural_revalidation.v2.json",
    ),
    (
        ROOT / "schemas/r1/r1_t14_02_formal_structural_revalidation.schema.json",
        ROOT / "configs/r1/r1_t14_02_formal_structural_revalidation.v3.json",
    ),
    (
        ROOT / "schemas/r2/r2_t02_protocol_freeze_config.schema.json",
        ROOT / "configs/r2/r2_t02_confirmed_event_zone_state_machine_contract.v8.json",
    ),
    (
        ROOT / "schemas/r2/r2_t03_four_route_event_zone_scan_config.schema.json",
        ROOT / "configs/r2/r2_t03_four_route_event_zone_scan.v1.json",
    ),
    (
        ROOT / "schemas/r2/r2_t04_hard_gate_pareto_freeze_plan.schema.json",
        ROOT / "configs/r2/r2_t04_hard_gate_pareto_freeze_plan.v1.json",
    ),
    (
        ROOT / "schemas/r2/r2_t08_r2_gate_r3_handoff.schema.json",
        ROOT / "configs/r2/r2_t08_r2_gate_r3_handoff.v1.json",
    ),
    (
        ROOT / "schemas/governance/r_formal_experiment_governance.schema.json",
        ROOT / "configs/governance/r_formal_experiment_governance.v1.json",
    ),
    (
        ROOT / "schemas/d2_formal_source_registry_contract.schema.json",
        ROOT / "configs/d2/formal_source_registry_contract.v1.json",
    ),
    (
        ROOT / "schemas/d2_hithink_raw_ohlcv_probe_contract.schema.json",
        ROOT / "configs/d2/hithink_raw_ohlcv_probe_contract.v1.json",
    ),
    (
        D2_HITHINK_MATERIALIZATION_SCHEMA_PATH,
        D2_HITHINK_MATERIALIZATION_CONFIG_PATH,
    ),
    (
        D2_HITHINK_ARTIFACT_SCHEMA_PATH,
        D2_HITHINK_ARTIFACT_CONFIG_PATH,
    ),
    (
        ROOT / "schemas/d2_adjusted_price_quality_gap_candidate_contract.schema.json",
        ROOT / "configs/d2/adjusted_price_quality_gap_candidate_contract.v1.json",
    ),
    (D2_T11_SCHEMA_PATH, D2_T11_CONFIG_PATH),
    (D2_T12_SCHEMA_PATH, D2_T12_CONFIG_PATH),
    (D2_T12_ASOF_SCHEMA_PATH, D2_T12_ASOF_CONFIG_PATH),
    (D2_T13_SCHEMA_PATH, D2_T13_CONFIG_PATH),
)


def sidecar_config_pairs() -> tuple[tuple[Path, Path], ...]:
    """Discover sidecar schema/config pairs without changing mainline semantics."""

    pairs: list[tuple[Path, Path]] = []
    schema_root = ROOT / "schemas" / "sidecar"
    config_root = ROOT / "configs" / "sidecar"
    for schema_path in sorted(schema_root.glob("*.schema.json")):
        if schema_path.name in {
            "exp_a01_authorized_input_manifest.schema.json",
            "exp_a01_accepted_result_handoff.schema.json",
            "exp_a02_authorized_input_manifest.schema.json",
            "exp_a02_accepted_result_handoff.schema.json",
            "exp_a03_authorized_input_manifest.schema.json",
        }:
            continue
        schema_stem = schema_path.name.removesuffix(".schema.json")
        candidates = [config_root / f"{schema_stem}.v1.json"]
        candidates.extend(sorted(config_root.glob(f"{schema_stem}_*.v1.json")))
        candidates = [path for path in candidates if path.is_file()]
        if len(candidates) != 1:
            raise FileNotFoundError(
                f"sidecar schema must have exactly one matching config: "
                f"{schema_path} -> {candidates}"
            )
        pairs.append((schema_path, candidates[0]))
    return tuple(pairs)


def standalone_sidecar_schemas() -> tuple[Path, ...]:
    """Return sidecar schemas that validate external manifests, not configs."""

    return (
        ROOT / "schemas" / "sidecar" / "exp_a01_authorized_input_manifest.schema.json",
        ROOT / "schemas" / "sidecar" / "exp_a01_accepted_result_handoff.schema.json",
        ROOT / "schemas" / "sidecar" / "exp_a02_authorized_input_manifest.schema.json",
        ROOT / "schemas" / "sidecar" / "exp_a02_accepted_result_handoff.schema.json",
        ROOT / "schemas" / "sidecar" / "exp_a03_authorized_input_manifest.schema.json",
    )


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    for schema_path in standalone_sidecar_schemas():
        Draft202012Validator.check_schema(load_json(schema_path))
        print(f"validated schema {schema_path.relative_to(ROOT)}")
    for schema_path, config_path in (*CONFIGS, *sidecar_config_pairs()):
        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            load_json(config_path)
        )
        print(f"validated {config_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
