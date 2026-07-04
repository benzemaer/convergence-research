"""Build synthetic D3 daily observation payloads for contract integration tests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_d3_component_lineage_no_bypass import (  # noqa: E402
    is_forbidden_payload_path,
    validate_component_lineage_payload,
)

FORBIDDEN_CONTENT_PATTERNS = (
    "data/raw",
    "data\\raw",
    "data/external",
    "data\\external",
    "marketdb",
    ".duckdb",
    ".day",
)


class SyntheticBuildError(ValueError):
    """Raised when a synthetic build payload violates the D3-T05 boundary."""


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise SyntheticBuildError(f"{path} must contain a JSON object")
    return loaded


def _walk_values(value: Any) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for child in value.values():
            found.extend(_walk_values(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_values(child))
    else:
        found.append(value)
    return found


def _contains_forbidden_content_path(payload: dict[str, Any]) -> bool:
    for value in _walk_values(payload):
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        if any(pattern in lowered for pattern in FORBIDDEN_CONTENT_PATTERNS):
            return True
    return False


def _canonical_ref(row: dict[str, Any]) -> str:
    fields = [
        "data_version",
        "universe_id",
        "security_id",
        "trading_date",
        "observation_revision",
    ]
    return "|".join(str(row.get(field, "")) for field in fields)


def _group_fields(build_contract: dict[str, Any], group_name: str) -> list[str]:
    groups = build_contract["synthetic_input_field_groups"]
    return list(groups[group_name])


def _require_fields(
    source: dict[str, Any], fields: list[str], section: str
) -> list[str]:
    return [field for field in fields if source.get(field) in {None, "", "unknown"}]


def _select_fields(source: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {field: source[field] for field in fields if field in source}


def _raise_if_errors(errors: list[str]) -> None:
    if errors:
        raise SyntheticBuildError("; ".join(errors))


def build_synthetic_daily_observation(
    payload: dict[str, Any], contracts: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Build a synthetic D3 observation and validate lineage/no-bypass alignment."""
    build_contract = contracts["build_contract"]
    lineage_contract = contracts["lineage_contract"]
    quality_contract = contracts["quality_contract"]
    errors: list[str] = []

    if _contains_forbidden_content_path(payload):
        raise SyntheticBuildError("payload references forbidden real data path")

    prohibited = set(build_contract["prohibited_fields"])
    present_prohibited = sorted(prohibited.intersection(payload))
    if present_prohibited:
        raise SyntheticBuildError(
            f"payload contains prohibited fields: {present_prohibited}"
        )

    identity_fields = _group_fields(build_contract, "identity_fields")
    component_ref_fields = _group_fields(build_contract, "component_ref_fields")
    lineage_fields = _group_fields(build_contract, "lineage_fields")
    raw_fields = _group_fields(build_contract, "raw_trading_value_fields")
    continuous_fields = _group_fields(
        build_contract, "continuous_research_price_fields"
    )
    participation_fields = _group_fields(build_contract, "participation_value_fields")
    trading_fields = _group_fields(build_contract, "trading_constraint_fields")
    quality_fields = _group_fields(build_contract, "quality_status_fields")
    readiness_fields = _group_fields(build_contract, "pcvt_input_readiness_fields")

    missing_identity = _require_fields(payload, identity_fields, "identity")
    missing_component_refs = _require_fields(
        payload, component_ref_fields, "component refs"
    )
    missing_lineage = _require_fields(payload, lineage_fields, "lineage")
    if missing_identity:
        errors.append(f"missing identity fields: {missing_identity}")
    if missing_component_refs:
        errors.append(f"missing component refs: {missing_component_refs}")
    if missing_lineage:
        errors.append(f"missing lineage fields: {missing_lineage}")
    if payload.get("observed_at") in {None, "", "unknown"}:
        errors.append("observed_at missing or unknown")
    if payload.get("research_use_tier") in {None, "", "unknown"}:
        errors.append("research_use_tier missing or unknown")
    _raise_if_errors(errors)

    canonical_fields = identity_fields + component_ref_fields + lineage_fields
    canonical_observation = _select_fields(payload, canonical_fields)

    value_fields = (
        identity_fields
        + lineage_fields
        + ["source_snapshot_ref", "run_ref"]
        + raw_fields
        + continuous_fields
        + participation_fields
        + trading_fields
    )
    value_observation = _select_fields(payload, value_fields)
    value_observation["canonical_observation_ref"] = _canonical_ref(
        canonical_observation
    )

    quality_readiness_summary = _select_fields(
        payload, quality_fields + readiness_fields
    )
    _validate_quality_vocabulary(quality_readiness_summary, quality_contract)

    lineage_payload = {
        "canonical_observation": canonical_observation,
        "value_observation": value_observation,
        "r0_allowed_sources": [
            "d3.daily_market_observations",
            "d3.daily_market_observation_values",
        ],
    }
    lineage_errors = validate_component_lineage_payload(
        lineage_payload, lineage_contract
    )

    return {
        "canonical_observation": canonical_observation,
        "value_observation": value_observation,
        "quality_readiness_summary": quality_readiness_summary,
        "lineage_validation_errors": lineage_errors,
        "build_diagnostics": {
            "synthetic_only": True,
            "builder_contract_id": build_contract["contract_id"],
            "quality_contract_id": quality_contract["contract_id"],
            "manifest_created": False,
            "duckdb_written": False,
            "data_version_released": False,
        },
    }


def _validate_quality_vocabulary(
    summary: dict[str, Any], quality_contract: dict[str, Any]
) -> None:
    status_values = set(quality_contract["status_vocabulary"])
    severity_values = set(quality_contract["severity_vocabulary"])
    readiness_values = set(
        quality_contract["pcvt_readiness_policy"]["readiness_status_vocabulary"]
    )
    errors: list[str] = []
    for field, value in summary.items():
        if field == "quality_severity_max" and value not in severity_values:
            errors.append(f"{field} is outside D3-T04 severity vocabulary")
        elif field.endswith("_input_ready") or field == "pcvt_input_readiness_status":
            if value not in readiness_values:
                errors.append(f"{field} is outside D3-T04 readiness vocabulary")
        elif field.endswith("_status") and value not in status_values:
            errors.append(f"{field} is outside D3-T04 status vocabulary")
    present_prohibited = set(quality_contract["prohibited_fields"]).intersection(
        summary
    )
    if present_prohibited:
        errors.append(
            "quality_readiness_summary contains prohibited fields: "
            f"{sorted(present_prohibited)}"
        )
    _raise_if_errors(errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-contract", required=True, type=Path)
    parser.add_argument("--lineage-contract", required=True, type=Path)
    parser.add_argument("--quality-contract", required=True, type=Path)
    parser.add_argument("--payload", required=True, type=Path)
    args = parser.parse_args()

    build_contract = load_json(args.build_contract)
    lineage_contract = load_json(args.lineage_contract)
    quality_contract = load_json(args.quality_contract)

    if is_forbidden_payload_path(args.payload):
        print(f"refusing forbidden payload path: {args.payload}")
        return 1

    try:
        payload = load_json(args.payload)
        output = build_synthetic_daily_observation(
            payload,
            {
                "build_contract": build_contract,
                "lineage_contract": lineage_contract,
                "quality_contract": quality_contract,
            },
        )
    except SyntheticBuildError as exc:
        print(str(exc))
        return 1

    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
