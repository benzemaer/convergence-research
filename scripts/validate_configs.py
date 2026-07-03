"""Validate committed governance configurations."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SECURITY_MAPPING_REFERENCE_CONTRACT_PATH = (
    ROOT
    / "configs/d1"
    / "csi800_static_2026_06_security_mapping_reference_contract.v1.json"
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
