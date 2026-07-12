from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

REQUIRED_CASE_ORACLES = {
    "missing_row_fail_closed": "missing_expected_trading_row",
    "cross_state_rejection": "cross_state_rejected",
    "cross_role_rejection": "cross_role_rejected",
    "confirmed_only_risk_set": "sample_end_open_zone",
    "strict_core_subset": "sample_end_open_zone",
    "sidecar_mutation": "sidecar_hash_mismatch",
    "input_chain_mutation": "input_chain_hash_mismatch",
    "forbidden_field_mutation": "forbidden_output_field",
    "double_rebuild_determinism": "deterministic_rebuild_match",
}


def validate_artifacts(output_dir: Path) -> list[str]:
    output_dir = output_dir.resolve()
    errors: list[str] = []
    registry = _load_json(output_dir / "r2_t02_synthetic_case_registry.json")
    results = _read_csv(output_dir / "r2_t02_synthetic_case_results.csv")
    result_by_case = {row["case_id"]: row for row in results}
    registry_by_case = {row["case_id"]: row for row in registry.get("cases", [])}

    for case_id, expected_reason in REQUIRED_CASE_ORACLES.items():
        registry_row = registry_by_case.get(case_id)
        result_row = result_by_case.get(case_id)
        if registry_row is None:
            errors.append(f"independent_missing_case_registry:{case_id}")
            continue
        if result_row is None:
            errors.append(f"independent_missing_case_result:{case_id}")
            continue
        if registry_row.get("oracle_id") != f"r2_t02_oracle_{case_id}":
            errors.append(f"independent_oracle_id_mismatch:{case_id}")
        if result_row.get("expected_reason_code") != expected_reason:
            errors.append(f"independent_expected_reason_mismatch:{case_id}")
        if result_row.get("status") != "passed":
            errors.append(f"independent_case_not_passed:{case_id}")
        if not result_row.get("assertion_ledger_sha256", "").strip():
            errors.append(f"independent_missing_assertion_ledger_hash:{case_id}")

    missing_case = result_by_case.get("missing_row_fail_closed")
    if (
        missing_case
        and missing_case.get("error_code") != "missing_expected_trading_row"
    ):
        errors.append("independent_missing_row_not_fail_closed")

    mutation_cases = [
        "sidecar_mutation",
        "input_chain_mutation",
        "forbidden_field_mutation",
    ]
    for case_id in mutation_cases:
        row = result_by_case.get(case_id)
        if row and int(row.get("assertion_count", "0")) < 3:
            errors.append(f"independent_mutation_case_too_thin:{case_id}")

    transitions = _read_csv(output_dir / "r2_t02_transition_registry.csv")
    transition_pairs = {
        (row["machine"], row["from_state"], row["to_state"], row["reason_code"])
        for row in transitions
    }
    required_transitions = {
        (
            "event_zone",
            "COMPONENT_FORMING",
            "RIGHT_CENSORED",
            "prequalification_right_censored",
        ),
        ("event_zone", "REENTRY_PENDING_QUALIFICATION", "FINALIZED", "gap_exceeds_g"),
        (
            "event_zone",
            "REENTRY_PENDING_QUALIFICATION",
            "FINALIZED_WITH_QUALITY_BREAK",
            "quality_break",
        ),
        (
            "event_zone",
            "REENTRY_PENDING_QUALIFICATION",
            "RIGHT_CENSORED",
            "sample_end_open_zone",
        ),
    }
    for item in required_transitions - transition_pairs:
        errors.append(f"independent_missing_transition:{'|'.join(item)}")

    risk_set = _load_json(output_dir / "r2_t02_r3_risk_set_contract.json")
    required_fields = set(risk_set.get("required_fields", []))
    for field in {"state_risk_set_eligible", "qualified_event_risk_set_eligible"}:
        if field not in required_fields:
            errors.append(f"independent_missing_risk_set_field:{field}")

    t03_output = _load_json(output_dir / "r2_t02_t03_output_contract.json")
    table_contracts = t03_output.get("table_contracts", {})
    for table in {
        "atomic_confirmed_daily",
        "qualified_component",
        "event_zone",
        "event_zone_membership_daily",
        "transition_profile",
        "strict_core_window_comparison",
    }:
        if table not in table_contracts:
            errors.append(f"independent_missing_t03_table_contract:{table}")
    return errors


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
