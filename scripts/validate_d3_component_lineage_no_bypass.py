"""Validate D3 synthetic component lineage and no-bypass payloads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PATH_PARTS = {
    "data/raw",
    "data\\raw",
    "data/external",
    "data\\external",
    "marketdb",
}
FORBIDDEN_SUFFIXES = {".duckdb", ".day"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


def _canonical_ref(row: dict[str, Any], primary_key: list[str]) -> str:
    return "|".join(str(row.get(field, "")) for field in primary_key)


def _walk_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_dicts(child))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_dicts(item))
    return found


def _contains_forbidden_payload_path(payload: dict[str, Any]) -> bool:
    for value in _walk_dicts(payload):
        for item in value.values():
            if not isinstance(item, str):
                continue
            lowered = item.lower()
            if any(part in lowered for part in FORBIDDEN_PATH_PARTS):
                return True
            if any(lowered.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
                return True
    return False


def validate_component_lineage_payload(
    payload: dict[str, Any], contract: dict[str, Any]
) -> list[str]:
    """Return validation errors for a synthetic D3 lineage payload."""
    errors: list[str] = []
    primary_key = list(contract["primary_key"])
    component_refs = set(contract["component_refs"])
    prohibited_fields = set(contract["prohibited_fields"])
    lineage_fields = set(contract["lineage_inheritance_fields"])
    allowed_sources = set(contract["no_bypass_policy"]["allowed_r0_sources"])
    direct_sources = set(contract["no_bypass_policy"]["prohibited_r0_sources"])

    if not contract["validator_behavior"]["accept_synthetic_payload_only"]:
        errors.append("contract does not require synthetic-only validation")

    canonical = payload.get("canonical_observation")
    value = payload.get("value_observation")
    if not isinstance(canonical, dict):
        errors.append("canonical_observation must be an object")
        canonical = {}
    if not isinstance(value, dict):
        errors.append("value_observation must be an object")
        value = {}

    rows = [("canonical_observation", canonical), ("value_observation", value)]
    for row_name, row in rows:
        present_prohibited = prohibited_fields.intersection(row)
        if present_prohibited:
            errors.append(
                f"{row_name} contains prohibited fields: {sorted(present_prohibited)}"
            )

    missing_component_refs = sorted(
        ref for ref in component_refs if not canonical.get(ref)
    )
    if missing_component_refs:
        errors.append(
            f"canonical_observation missing component refs: {missing_component_refs}"
        )

    if not value.get("canonical_observation_ref"):
        errors.append("value_observation missing canonical_observation_ref")
    elif value.get("canonical_observation_ref") != _canonical_ref(
        canonical, primary_key
    ):
        errors.append(
            "value_observation canonical_observation_ref does not match "
            "canonical primary key"
        )

    for field in primary_key:
        if canonical.get(field) != value.get(field):
            errors.append(f"primary key mismatch for {field}")

    inherited_fields = lineage_fields - {"canonical_observation_ref"}
    for field in sorted(inherited_fields):
        if canonical.get(field) != value.get(field):
            errors.append(f"lineage inheritance mismatch for {field}")

    for field in [
        "observed_at",
        "observed_at_rule",
        "revision_policy",
        "history_revision_class",
        "research_use_tier",
    ]:
        if not canonical.get(field):
            errors.append(f"canonical_observation missing {field}")

    if canonical.get("research_use_tier") in {None, "", "unknown"}:
        errors.append("research_use_tier missing or unknown")
    if canonical.get("observed_at") in {None, "", "unknown"}:
        errors.append("observed_at missing or unknown")

    if (
        canonical.get("history_revision_class") == "final_revised_history"
        and canonical.get("observed_at_rule") == "point_in_time"
    ):
        errors.append("final_revised_history cannot claim point_in_time support")

    r0_allowed = set(payload.get("r0_allowed_sources", []))
    if not r0_allowed <= allowed_sources:
        errors.append(
            "R0 allowed sources include non-D3 sources: "
            f"{sorted(r0_allowed - allowed_sources)}"
        )
    if r0_allowed.intersection(direct_sources):
        errors.append("R0 allowed sources include prohibited D1/D2 direct sources")

    if _contains_forbidden_payload_path(payload):
        errors.append("payload references forbidden real data path or storage file")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--payload", required=True, type=Path)
    args = parser.parse_args()

    contract = load_json(args.contract)
    payload = load_json(args.payload)
    errors = validate_component_lineage_payload(payload, contract)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("validated synthetic D3 component lineage payload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
