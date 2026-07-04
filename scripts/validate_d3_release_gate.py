"""Validate synthetic D3 data_version, quality report, and manifest gates."""

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
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


def _walk_values(value: Any) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_values(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_values(child))
    else:
        found.append(value)
    return found


def _contains_forbidden_content(
    payload: dict[str, Any], contract: dict[str, Any]
) -> bool:
    patterns = [
        str(item).lower()
        for item in contract["forbidden_path_policy"]["forbidden_patterns"]
    ]
    for value in _walk_values(payload):
        if isinstance(value, dict) and set(value).intersection(
            contract["prohibited_fields"]
        ):
            return True
        if isinstance(value, str):
            lowered = value.lower()
            if any(pattern.lower() in lowered for pattern in patterns):
                return True
    return False


def _missing_fields(section: dict[str, Any], fields: list[str]) -> list[str]:
    return [
        field
        for field in fields
        if field not in section
        or section.get(field) is None
        or section.get(field) == ""
    ]


def _gate_map(payload: dict[str, Any]) -> dict[str, str]:
    results = payload.get("release_gate_results", {})
    if not isinstance(results, dict):
        return {}
    return {str(gate): str(status) for gate, status in results.items()}


def validate_d3_release_gate_payload(
    payload: dict[str, Any], contract: dict[str, Any]
) -> list[str]:
    """Return validation errors for a synthetic D3 release candidate payload."""
    errors: list[str] = []
    required_sections = [
        "data_version_candidate",
        "manifest_candidate",
        "quality_report_candidate",
        "release_gate_results",
    ]
    for section in required_sections:
        if not isinstance(payload.get(section), dict):
            errors.append(f"{section} must be present")

    if errors:
        return errors

    data_version = payload["data_version_candidate"]
    manifest = payload["manifest_candidate"]
    quality_report = payload["quality_report_candidate"]
    release_gate_results = _gate_map(payload)
    release_decision = payload.get("release_decision")

    for section_name, section, fields in [
        ("data_version_candidate", data_version, contract["data_version_fields"]),
        ("manifest_candidate", manifest, contract["manifest_fields"]),
        ("quality_report_candidate", quality_report, contract["quality_report_fields"]),
    ]:
        missing = _missing_fields(section, fields)
        if missing:
            errors.append(f"{section_name} missing fields: {missing}")

    for field in [
        "row_count",
        "security_count",
        "trading_date_min",
        "trading_date_max",
    ]:
        values = {
            data_version.get(field),
            manifest.get(field),
            quality_report.get(field),
        }
        if len(values) != 1:
            errors.append(f"{field} mismatch across release candidate sections")

    for section_name, section in [
        ("data_version_candidate", data_version),
        ("manifest_candidate", manifest),
    ]:
        if not section.get("sha256"):
            errors.append(f"{section_name} missing sha256")

    required_gates = {
        gate["gate_id"]
        for gate in contract["release_gates"]
        if gate["required_for_formal_release"]
    }
    missing_gates = sorted(required_gates - set(release_gate_results))
    if missing_gates:
        errors.append(f"release_gate_results missing gates: {missing_gates}")

    blocking_statuses = {"failed", "blocked", "not_evaluated"}
    has_blocking_gate = any(
        release_gate_results.get(gate) in blocking_statuses for gate in required_gates
    )
    if has_blocking_gate and release_decision == "release_allowed":
        errors.append("release_allowed is invalid when required formal gates block")
    if release_decision == "release_allowed":
        errors.append("D3-T06 cannot allow formal release")
    if release_decision != contract["current_formal_release_decision"]:
        errors.append("release_decision must be formal_release_blocked for D3-T06")

    for gate in [
        "d2_formal_materialization_gate",
        "source_authorization_gate",
        "factor_as_of_time_coverage_gate",
        "revision_timestamp_coverage_gate",
        "r0_release_gate",
    ]:
        if release_gate_results.get(gate) == "passed":
            errors.append(f"{gate} must not be passed in D3-T06")

    if _contains_forbidden_content(payload, contract):
        errors.append("payload contains prohibited fields or forbidden path content")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--payload", required=True, type=Path)
    args = parser.parse_args()

    contract = load_json(args.contract)
    if is_forbidden_payload_path(args.payload):
        print(f"refusing forbidden payload path: {args.payload}")
        return 1

    payload = load_json(args.payload)
    errors = validate_d3_release_gate_payload(payload, contract)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("validated synthetic D3 release gate payload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
