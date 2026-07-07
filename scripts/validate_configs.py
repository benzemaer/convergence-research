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


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    for schema_path, config_path in CONFIGS:
        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            load_json(config_path)
        )
        print(f"validated {config_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
