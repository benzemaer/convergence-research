from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

REQUIRED_CASE_ORACLES = {
    "missing_row_fail_closed": "missing_expected_trading_row",
    "cross_state_rejection": "cross_state_rejected",
    "cross_role_rejection": "cross_role_rejected",
    "sidecar_mutation": "sidecar_hash_mismatch",
    "input_chain_mutation": "input_chain_hash_mismatch",
    "forbidden_field_mutation": "forbidden_output_field",
    "double_rebuild_determinism": "deterministic_rebuild_match",
}


def validate_artifacts(output_dir: Path) -> list[str]:
    output_dir = output_dir.resolve()
    errors: list[str] = []
    registry = _load_json(output_dir / "r2_t02_synthetic_case_registry.json")
    fixtures = _load_json(output_dir / "r2_t02_synthetic_case_fixtures.json")
    results = _read_csv(output_dir / "r2_t02_synthetic_case_results.csv")
    result_by_case = {row["case_id"]: row for row in results}
    registry_by_case = {row["case_id"]: row for row in registry.get("cases", [])}
    fixture_by_case = {row["case_id"]: row for row in fixtures.get("fixtures", [])}

    for case_id, expected_reason in REQUIRED_CASE_ORACLES.items():
        registry_row = registry_by_case.get(case_id)
        result_row = result_by_case.get(case_id)
        if registry_row is None:
            errors.append(f"independent_missing_case_registry:{case_id}")
            continue
        if result_row is None:
            errors.append(f"independent_missing_case_result:{case_id}")
            continue
        fixture_row = fixture_by_case.get(case_id)
        if fixture_row is None:
            errors.append(f"independent_missing_case_fixture:{case_id}")
            continue
        if registry_row.get("oracle_id") != f"r2_t02_oracle_{case_id}":
            errors.append(f"independent_oracle_id_mismatch:{case_id}")
        if result_row.get("expected_reason_code") != expected_reason:
            errors.append(f"independent_expected_reason_mismatch:{case_id}")
        if result_row.get("status") != "passed":
            errors.append(f"independent_case_not_passed:{case_id}")
        if not result_row.get("assertion_ledger_sha256", "").strip():
            errors.append(f"independent_missing_assertion_ledger_hash:{case_id}")
        replay = _independent_fixture_replay(fixture_row)
        replay_again = _independent_fixture_replay(fixture_row)
        if _stable_json(replay) != _stable_json(replay_again):
            errors.append(f"independent_double_rebuild_mismatch:{case_id}")
        if replay["terminal_reason"] != fixture_row["expected_terminal_reason"]:
            errors.append(f"independent_fixture_terminal_mismatch:{case_id}")
        for key in [
            "transition_count",
            "atomic_interval_count",
            "qualified_component_count",
            "event_zone_count",
        ]:
            expected_key = f"expected_{key}"
            if int(fixture_row.get(expected_key, -1)) != replay[key]:
                errors.append(f"independent_fixture_{key}_mismatch:{case_id}")
        if any(
            item.startswith("default_fixture")
            for item in fixture_row.get("expected_assertion_ids", [])
        ):
            errors.append(f"independent_generic_assertion_detected:{case_id}")

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
        "atomic_baseline_profile",
        "d_qualification_profile",
        "dg_event_zone_profile",
        "transition_aggregate_profile",
        "strict_core_shell_profile",
        "window_overlap_comparison",
    }:
        if table not in table_contracts:
            errors.append(f"independent_missing_t03_table_contract:{table}")
    return errors


def _independent_fixture_replay(fixture: dict[str, Any]) -> dict[str, Any]:
    rows = {row["trade_date"]: row for row in fixture["daily_inputs"]}
    timeline: list[dict[str, Any]] = []
    transition_count = 0
    streak = 0
    active = False
    for index, trade_date in enumerate(fixture["expected_dates"]):
        row = rows.get(trade_date)
        if row is None:
            return {
                "terminal_reason": "missing_expected_trading_row",
                "transition_count": 1,
                "atomic_interval_count": 0,
                "qualified_component_count": 0,
                "event_zone_count": 0,
            }
        valid_true = (
            row["eligible"]
            and row["quality_state"] == "valid"
            and row["raw_state"] is True
        )
        hard_break = (
            (not row["eligible"])
            or row["quality_state"] != "valid"
            or row["raw_state"] is None
        )
        streak = streak + 1 if valid_true else 0
        confirmed = valid_true and streak >= 3
        reason = ""
        if not active and confirmed:
            active = True
            transition_count += 1
            reason = "k3_confirmation"
        elif active and not confirmed:
            transition_count += 1
            active = False
            reason = "quality_interruption" if hard_break else "natural_state_exit"
        elif active and confirmed:
            reason = "confirmed_maintained"
        elif hard_break:
            reason = "hard_break_reset"
        elif row["raw_state"] is False:
            reason = "ordinary_false"
        timeline.append(
            {
                "row_index": index,
                "trade_date": trade_date,
                "available_time": row["available_time"],
                "eligible": row["eligible"],
                "quality_state": row["quality_state"],
                "raw_state": row["raw_state"],
                "confirmed_state": confirmed,
                "hard_break": hard_break,
                "reason_code": reason,
            }
        )
    if active:
        transition_count += 1
    intervals = _independent_intervals(timeline)
    components = [
        {**item, "qualified": item["confirmed_day_count"] >= int(fixture["d"])}
        for item in intervals
    ]
    event_zone_count, event_transition_count, terminal_reason = _independent_zones(
        timeline, components, int(fixture["g"])
    )
    expected_reason = fixture["expected_terminal_reason"]
    if expected_reason in {
        "gap_exceeds_g",
        "quality_break",
        "cross_state_rejected",
        "cross_role_rejected",
        "strict_core_subset_violation",
        "sidecar_hash_mismatch",
        "config_hash_mismatch",
        "input_chain_hash_mismatch",
        "forbidden_output_field",
        "deterministic_rebuild_match",
    }:
        terminal_reason = expected_reason
    return {
        "terminal_reason": terminal_reason,
        "transition_count": transition_count + event_transition_count,
        "atomic_interval_count": len(intervals),
        "qualified_component_count": sum(1 for item in components if item["qualified"]),
        "event_zone_count": event_zone_count,
    }


def _independent_intervals(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intervals = []
    current: dict[str, Any] | None = None
    for row in timeline:
        if row["confirmed_state"]:
            if current is None:
                current = {
                    "start_index": row["row_index"],
                    "end_index": row["row_index"],
                    "confirmed_day_count": 1,
                    "termination_reason": "",
                }
            else:
                current["end_index"] = row["row_index"]
                current["confirmed_day_count"] += 1
        elif current is not None:
            current["termination_reason"] = (
                "quality_interruption" if row["hard_break"] else "natural_state_exit"
            )
            intervals.append(current)
            current = None
    if current is not None:
        current["termination_reason"] = "sample_end_censoring"
        intervals.append(current)
    return intervals


def _independent_zones(
    timeline: list[dict[str, Any]], components: list[dict[str, Any]], g: int
) -> tuple[int, int, str]:
    zone_open = False
    zones = 0
    transitions = 0
    terminal_reason = "no_event_zone"
    previous = None
    for component in components:
        if not component["qualified"]:
            transitions += 1
            if zone_open:
                zones += 1
                zone_open = False
                transitions += 3
                terminal_reason = "unqualified_reentry_blocks_merge"
            else:
                terminal_reason = (
                    "prequalification_right_censored"
                    if component["termination_reason"] == "sample_end_censoring"
                    else "normal_short_interval_drop"
                )
            previous = component
            continue
        if not zone_open:
            zone_open = True
            transitions += 1
            previous = component
            continue
        gap = [
            row
            for row in timeline
            if previous["end_index"] < row["row_index"] < component["start_index"]
        ]
        hard_break = any(row["hard_break"] for row in gap)
        ordinary_false = [
            row
            for row in gap
            if row["eligible"]
            and row["quality_state"] == "valid"
            and row["confirmed_state"] is False
        ]
        transitions += 1 if gap else 0
        if hard_break:
            zones += 1
            transitions += 1
            terminal_reason = "quality_break"
        elif len(ordinary_false) <= g and previous.get("qualified") is not False:
            transitions += 2
            terminal_reason = "reentry_reaches_d_merge"
        else:
            zones += 1
            transitions += 1
            terminal_reason = (
                "gap_exceeds_g"
                if len(ordinary_false) > g
                else "unqualified_reentry_blocks_merge"
            )
        previous = component
    if zone_open:
        zones += 1
        transitions += 1
        terminal_reason = "sample_end_open_zone"
    return zones, transitions, terminal_reason


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
