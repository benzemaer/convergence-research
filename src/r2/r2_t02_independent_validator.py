from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_CASE_ORACLES = {
    "missing_row_fail_closed": "missing_expected_trading_row",
    "cross_state_rejection": "cross_state_rejected",
    "cross_role_rejection": "cross_role_rejected",
    "strict_core_violation": "strict_core_subset_violation",
    "sidecar_mutation": "sidecar_hash_mismatch",
    "contract_config_mutation": "config_hash_mismatch",
    "input_chain_mutation": "input_chain_hash_mismatch",
    "forbidden_field_mutation": "forbidden_output_field",
    "stale_reviewed_head": "reviewed_head_mismatch",
    "cross_pr_evidence": "pull_request_identity_mismatch",
    "missing_heavy_test": "heavy_tests_not_subset_of_full",
    "full_profile_substitution": "full_collection_hash_mismatch",
    "double_rebuild_determinism": "deterministic_rebuild_match",
}

SPECIAL_EVALUATOR_CASES = {
    "cross_state_rejection",
    "cross_role_rejection",
    "strict_core_subset",
    "strict_core_violation",
    "sidecar_mutation",
    "contract_config_mutation",
    "input_chain_mutation",
    "forbidden_field_mutation",
    "stale_reviewed_head",
    "cross_pr_evidence",
    "missing_heavy_test",
    "full_profile_substitution",
    "double_rebuild_determinism",
}

CORE_SCIENTIFIC_ORACLE_CASES = {
    "k3_no_backfill",
    "d1_exact_qualification",
    "d2_exact_qualification",
    "d3_exact_qualification",
    "g0_no_merge_raw_false_exit",
    "g1_raw_false_success_merge",
    "g2_raw_false_success_merge",
    "raw_true_preconfirmation_does_not_reset_g",
    "g_plus_one_raw_false_irreversible_final",
    "quality_break",
    "reentry_fails_d",
    "prequalification_right_censor",
    "bridge_membership_delayed",
    "confirmed_only_risk_set",
    "bridge_not_in_risk_set",
    "event_id_stability",
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
    contract_version = _load_json(output_dir / "r2_t02_t03_output_contract.json")[
        "contract_version"
    ]
    if not _isolated_formal_artifact_rebuild_matches(output_dir):
        errors.append("independent_full_artifact_double_rebuild_mismatch")
    errors.extend(_real_protocol_mutation_probe_errors(output_dir))

    for case_id, fixture_row in sorted(fixture_by_case.items()):
        expected_reason = fixture_row.get("expected_terminal_reason", "")
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
        expected_role = (
            "core_scientific_oracle"
            if case_id in CORE_SCIENTIFIC_ORACLE_CASES
            else "regression_only"
        )
        if registry_row.get("evidence_role") != expected_role:
            errors.append(f"independent_evidence_role_mismatch:{case_id}")
        if result_row.get("expected_reason_code") != expected_reason:
            errors.append(f"independent_expected_reason_mismatch:{case_id}")
        if result_row.get("status") != "passed":
            errors.append(f"independent_case_not_passed:{case_id}")
        if not result_row.get("assertion_ledger_sha256", "").strip():
            errors.append(f"independent_missing_assertion_ledger_hash:{case_id}")
        if case_id in SPECIAL_EVALUATOR_CASES:
            special_reason = _independent_special_case_reason(case_id, fixture_row)
            if special_reason != expected_reason:
                errors.append(f"independent_special_reason_mismatch:{case_id}")
        else:
            replay = _independent_fixture_replay(fixture_row)
            replay_again = _independent_fixture_replay(fixture_row)
            if _stable_json(replay) != _stable_json(replay_again):
                errors.append(f"independent_double_rebuild_mismatch:{case_id}")
            if replay["terminal_reason"] != fixture_row["expected_terminal_reason"]:
                errors.append(f"independent_fixture_terminal_mismatch:{case_id}")
            errors.extend(_independent_membership_errors(case_id, replay))
            if case_id in CORE_SCIENTIFIC_ORACLE_CASES:
                errors.extend(
                    _independent_core_trace_errors(
                        case_id, fixture_row, replay, contract_version
                    )
                )
        if any(
            item.startswith("default_fixture")
            for item in fixture_row.get("expected_assertion_ids", [])
        ):
            errors.append(f"independent_generic_assertion_detected:{case_id}")
        if "hand_authored_oracle" not in fixture_row:
            errors.append(f"independent_missing_hand_authored_oracle:{case_id}")
        elif case_id in CORE_SCIENTIFIC_ORACLE_CASES and not (
            set(fixture_row["hand_authored_oracle"]) - {"d", "g"}
        ):
            errors.append(f"independent_thin_hand_authored_oracle:{case_id}")
        elif (
            case_id not in CORE_SCIENTIFIC_ORACLE_CASES
            and fixture_row["hand_authored_oracle"]
        ):
            errors.append(f"independent_regression_case_claims_oracle:{case_id}")

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
        (
            "event_zone",
            "REENTRY_PENDING_QUALIFICATION",
            "FINALIZED",
            "raw_false_gap_exceeds_g",
        ),
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
            "sample_end_before_requalification",
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
        "event_zone_bridge_segment",
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
    membership_fields = _field_names(table_contracts, "event_zone_membership_daily")
    for field in {
        "membership_available_time",
        "zone_revision_as_of",
        "zone_status_as_of",
        "prequalification_member",
        "unqualified_reentry_member",
        "is_raw_false_bridge",
        "is_preconfirmation_gap",
        "raw_false_gap_count_as_of",
        "raw_false_gap_ordinal_as_of",
        "evaluation_time",
        "eligible",
        "quality_state",
    }:
        if field not in membership_fields:
            errors.append(f"independent_missing_t03_membership_field:{field}")
    profile_required = {
        "dg_event_zone_profile": {
            "qualified_event_count",
            "confirmed_event_coverage",
            "active_zone_count",
            "gap_pending_zone_count",
            "reentry_pending_zone_count",
            "unqualified_reentry_count",
            "confirmed_density",
        },
        "transition_aggregate_profile": {"transition_count", "hard_break_count"},
        "strict_core_shell_profile": {
            "strict_core_confirmed_day_share",
            "strict_core_event_share",
            "shell_only_event_count",
            "shell_only_confirmed_day_share",
        },
    }
    for table, fields in profile_required.items():
        missing_fields = fields - _field_names(table_contracts, table)
        if missing_fields:
            errors.append(
                f"independent_missing_t03_profile_fields:{table}:"
                f"{','.join(sorted(missing_fields))}"
            )
    return errors


def _field_names(table_contracts: dict[str, Any], table: str) -> set[str]:
    fields = table_contracts.get(table, {}).get("fields", [])
    return {field.get("name", "") for field in fields}


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
                "membership_rows": [],
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
    membership_rows = _independent_membership_rows(
        timeline, components, int(fixture["d"])
    )
    zones, gap_membership_rows = _independent_core_zones(
        timeline, components, int(fixture["g"]), int(fixture["d"])
    )
    membership_rows.extend(gap_membership_rows)
    event_zone_count, event_transition_count, terminal_reason = _independent_zones(
        timeline, components, int(fixture["g"])
    )
    return {
        "terminal_reason": terminal_reason,
        "transition_count": transition_count + event_transition_count,
        "atomic_interval_count": len(intervals),
        "qualified_component_count": sum(1 for item in components if item["qualified"]),
        "event_zone_count": event_zone_count,
        "membership_rows": membership_rows,
        "timeline": timeline,
        "components": components,
        "zones": zones,
        "gap_counts": _independent_gap_counts(timeline, components, int(fixture["g"])),
    }


def _independent_core_trace_errors(
    case_id: str,
    fixture: dict[str, Any],
    replay: dict[str, Any],
    contract_version: str,
) -> list[str]:
    errors: list[str] = []

    def mismatch(entity: str, key: str, field: str) -> None:
        errors.append(
            f"independent_core_trace_mismatch:{case_id}:{entity}:{key}:{field}"
        )

    observed_timeline = fixture.get("observed_state_timeline", [])
    independent_timeline = replay["timeline"]
    if len(observed_timeline) != len(independent_timeline):
        mismatch("timeline", "row_count", "row_count")
    for observed, independent in zip(observed_timeline, independent_timeline):
        key = observed["trade_date"]
        for field in ("trade_date", "raw_state", "confirmed_state", "reason_code"):
            if observed.get(field) != independent.get(field):
                mismatch("timeline", key, field)

    observed_components = fixture.get("observed_component_ledger", [])
    independent_components = replay["components"]
    if len(observed_components) != len(independent_components):
        mismatch("component", "row_count", "row_count")
    for ordinal, (observed, independent) in enumerate(
        zip(observed_components, independent_components), start=1
    ):
        for field in ("qualified", "confirmed_day_count", "termination_reason"):
            if observed.get(field) != independent.get(field):
                mismatch("component", str(ordinal), field)
        if independent["qualified"]:
            qualification_index = independent["start_index"] + int(fixture["d"]) - 1
            independent_time = independent_timeline[qualification_index][
                "available_time"
            ]
            if observed.get("event_qualification_time") != independent_time:
                mismatch("component", str(ordinal), "event_qualification_time")

    observed_zones = fixture.get("observed_zone_ledger", [])
    independent_zones = replay["zones"]
    if len(observed_zones) != replay["event_zone_count"]:
        mismatch("zone", "row_count", "event_zone_count")
    final_transitions = [
        row
        for row in fixture.get("observed_transition_ledger", [])
        if "trade_date" not in row
        and row.get("to_state")
        in {"FINALIZED", "FINALIZED_WITH_QUALITY_BREAK", "RIGHT_CENSORED"}
    ]
    for ordinal, (observed, independent) in enumerate(
        zip(observed_zones, independent_zones), start=1
    ):
        for field in (
            "status",
            "zone_finalization_time",
            "raw_false_bridged_day_count",
            "preconfirmation_gap_day_count",
        ):
            if observed.get(field) != independent.get(field):
                mismatch("zone", str(ordinal), field)
        observed_reason = (
            final_transitions[ordinal - 1].get("reason_code")
            if ordinal <= len(final_transitions)
            else ""
        )
        if observed_reason != independent["finalization_reason"]:
            mismatch("zone", str(ordinal), "finalization_reason")

    observed_membership = {
        row["trade_date"]: row for row in fixture.get("observed_membership_rows", [])
    }
    independent_membership = {
        row["trade_date"]: row for row in replay["membership_rows"]
    }
    if observed_membership.keys() != independent_membership.keys():
        mismatch("membership", "row_keys", "trade_date")
    membership_fields = (
        "event_zone_member",
        "is_raw_false_bridge",
        "is_preconfirmation_gap",
        "prequalification_member",
        "unqualified_reentry_member",
        "membership_available_time",
        "zone_status_as_of",
        "state_risk_set_eligible",
        "qualified_event_risk_set_eligible",
    )
    for trade_date in observed_membership.keys() & independent_membership.keys():
        for field in membership_fields:
            if observed_membership[trade_date].get(field) != independent_membership[
                trade_date
            ].get(field):
                mismatch("membership", trade_date, field)

    observed_risk = {
        row["trade_date"]: row for row in fixture.get("observed_risk_set_rows", [])
    }
    if observed_risk.keys() != independent_membership.keys():
        mismatch("risk_set", "row_keys", "trade_date")
    for trade_date in observed_risk.keys() & independent_membership.keys():
        for field in (
            "state_risk_set_eligible",
            "qualified_event_risk_set_eligible",
        ):
            if observed_risk[trade_date].get(field) != independent_membership[
                trade_date
            ].get(field):
                mismatch("risk_set", trade_date, field)

    observed_gaps = fixture.get("observed_raw_false_gap_count_timeline", [])
    if len(observed_gaps) != len(replay["gap_counts"]):
        mismatch("gap", "row_count", "row_count")
    for ordinal, (observed, independent) in enumerate(
        zip(observed_gaps, replay["gap_counts"]), start=1
    ):
        for field in (
            "raw_false_gap_count",
            "preconfirmation_raw_true_count",
            "total_nonconfirmed_gap_count",
            "exceeds_g",
        ):
            if observed.get(field) != independent.get(field):
                mismatch("gap", str(ordinal), field)
    if case_id == "event_id_stability" and fixture.get("observed_zone_ledger"):
        payload = f"{contract_version}|synthetic_{case_id}|S1|component_001"
        independent_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
        if fixture["observed_zone_ledger"][0].get("scan_event_id") != independent_id:
            mismatch("zone", "1", "scan_event_id")
    return errors


def _independent_membership_rows(
    timeline: list[dict[str, Any]], components: list[dict[str, Any]], d: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    qualified_seen = 0
    for component in components:
        if not component["qualified"] and not qualified_seen:
            continue
        qualification_index = component["start_index"] + d - 1
        qualification_time = (
            timeline[qualification_index]["available_time"]
            if component["qualified"]
            else timeline[min(component["end_index"] + 1, len(timeline) - 1)][
                "available_time"
            ]
        )
        for index in range(component["start_index"], component["end_index"] + 1):
            source = timeline[index]
            qualified_as_of = component["qualified"] and index >= qualification_index
            if component["qualified"]:
                status = (
                    "QUALIFIED_ACTIVE"
                    if qualified_as_of
                    else "REENTRY_PENDING_QUALIFICATION"
                    if qualified_seen
                    else "COMPONENT_FORMING"
                )
            else:
                status = (
                    "REENTRY_PENDING_QUALIFICATION"
                    if qualified_seen
                    else "COMPONENT_FORMING"
                )
            state_risk = bool(
                source["eligible"]
                and source["quality_state"] == "valid"
                and source["confirmed_state"]
            )
            rows.append(
                {
                    "trade_date": source["trade_date"],
                    "is_raw_false_bridge": False,
                    "is_preconfirmation_gap": False,
                    "component_qualified_as_of": qualified_as_of,
                    "prequalification_member": not qualified_as_of,
                    "event_zone_member": component["qualified"],
                    "unqualified_reentry_member": bool(
                        qualified_seen and not component["qualified"]
                    ),
                    "zone_status_as_of": status,
                    "membership_available_time": max(
                        source["available_time"], qualification_time
                    ),
                    "row_available_time": source["available_time"],
                    "state_risk_set_eligible": state_risk,
                    "qualified_event_risk_set_eligible": bool(
                        state_risk and component["qualified"] and qualified_as_of
                    ),
                }
            )
        if component["qualified"]:
            qualified_seen += 1
    return rows


def _independent_core_zones(
    timeline: list[dict[str, Any]],
    components: list[dict[str, Any]],
    g: int,
    d: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    zones: list[dict[str, Any]] = []
    gap_membership: list[dict[str, Any]] = []
    open_zone: dict[str, Any] | None = None
    previous_qualified: dict[str, Any] | None = None

    def new_zone(component: dict[str, Any]) -> dict[str, Any]:
        zone = {
            "status": "",
            "zone_finalization_time": "",
            "finalization_reason": "",
            "raw_false_bridged_day_count": 0,
            "preconfirmation_gap_day_count": 0,
        }
        zones.append(zone)
        return zone

    def finalize(
        zone: dict[str, Any], decision: tuple[str, dict[str, Any]] | None
    ) -> None:
        if decision is None:
            zone["status"] = "RIGHT_CENSORED"
            zone["zone_finalization_time"] = ""
            zone["finalization_reason"] = "sample_end_open_zone"
            return
        reason, row = decision
        zone["status"] = (
            "FINALIZED_WITH_QUALITY_BREAK" if reason == "quality_break" else "FINALIZED"
        )
        zone["zone_finalization_time"] = row["available_time"]
        zone["finalization_reason"] = reason

    for component in components:
        if not component["qualified"]:
            if open_zone is not None and previous_qualified is not None:
                if component["termination_reason"] == "sample_end_censoring":
                    finalize(open_zone, None)
                    open_zone["finalization_reason"] = (
                        "sample_end_before_requalification"
                    )
                else:
                    exit_index = min(component["end_index"] + 1, len(timeline) - 1)
                    finalize(
                        open_zone,
                        ("unqualified_reentry_blocks_merge", timeline[exit_index]),
                    )
                open_zone = None
            continue
        if open_zone is None:
            open_zone = new_zone(component)
            previous_qualified = component
            continue
        gap = timeline[previous_qualified["end_index"] + 1 : component["start_index"]]
        decision = _independent_gap_decision_row(gap, g)
        if decision is not None:
            finalize(open_zone, decision)
            open_zone = new_zone(component)
        else:
            qualification_index = component["start_index"] + d - 1
            qualification_time = timeline[qualification_index]["available_time"]
            for source in gap:
                raw_false = bool(
                    source["eligible"]
                    and source["quality_state"] == "valid"
                    and source["raw_state"] is False
                )
                preconfirmation = bool(
                    source["eligible"]
                    and source["quality_state"] == "valid"
                    and source["raw_state"] is True
                    and not source["confirmed_state"]
                )
                open_zone["raw_false_bridged_day_count"] += int(raw_false)
                open_zone["preconfirmation_gap_day_count"] += int(preconfirmation)
                gap_membership.append(
                    {
                        "trade_date": source["trade_date"],
                        "event_zone_member": True,
                        "is_raw_false_bridge": raw_false,
                        "is_preconfirmation_gap": preconfirmation,
                        "prequalification_member": preconfirmation,
                        "unqualified_reentry_member": False,
                        "membership_available_time": qualification_time,
                        "zone_status_as_of": "GAP_PENDING",
                        "state_risk_set_eligible": False,
                        "qualified_event_risk_set_eligible": False,
                    }
                )
        previous_qualified = component

    if open_zone is not None and previous_qualified is not None:
        trailing = timeline[previous_qualified["end_index"] + 1 :]
        finalize(open_zone, _independent_gap_decision_row(trailing, g))
    return zones, gap_membership


def _independent_gap_decision_row(
    rows: list[dict[str, Any]], g: int
) -> tuple[str, dict[str, Any]] | None:
    raw_false_count = 0
    for row in rows:
        if row["hard_break"]:
            return "quality_break", row
        if (
            row["eligible"]
            and row["quality_state"] == "valid"
            and row["raw_state"] is False
        ):
            raw_false_count += 1
            if raw_false_count > g:
                return "raw_false_gap_exceeds_g", row
    return None


def _independent_gap_counts(
    timeline: list[dict[str, Any]], components: list[dict[str, Any]], g: int
) -> list[dict[str, Any]]:
    counts: list[dict[str, Any]] = []
    for left, right in zip(components, components[1:]):
        if not (left["qualified"] and right["qualified"]):
            continue
        gap = timeline[left["end_index"] + 1 : right["start_index"]]
        raw_false = sum(
            row["eligible"]
            and row["quality_state"] == "valid"
            and row["raw_state"] is False
            for row in gap
        )
        preconfirmation = sum(
            row["eligible"]
            and row["quality_state"] == "valid"
            and row["raw_state"] is True
            and not row["confirmed_state"]
            for row in gap
        )
        counts.append(
            {
                "raw_false_gap_count": raw_false,
                "preconfirmation_raw_true_count": preconfirmation,
                "total_nonconfirmed_gap_count": raw_false + preconfirmation,
                "exceeds_g": raw_false > g,
            }
        )
    return counts


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
        if zone_open:
            prior_end = previous["end_index"] if previous else -1
            hard_break_before_component = any(
                row["hard_break"]
                for row in timeline
                if prior_end < row["row_index"] < component["start_index"]
            )
            if hard_break_before_component:
                zones += 1
                zone_open = False
                transitions += 1
                terminal_reason = "quality_break"
        if not component["qualified"]:
            transitions += 1
            if zone_open:
                zones += 1
                zone_open = False
                transitions += 3
                terminal_reason = (
                    "sample_end_before_requalification"
                    if component["termination_reason"] == "sample_end_censoring"
                    else "unqualified_reentry_blocks_merge"
                )
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
        transitions += 1 if gap else 0
        decisive_reason = _independent_gap_decision(gap, g)
        if decisive_reason == "quality_break":
            zones += 1
            transitions += 1
            terminal_reason = "quality_break"
        elif decisive_reason is None and previous.get("qualified") is not False:
            transitions += 2
            terminal_reason = "reentry_reaches_d_merge"
        else:
            zones += 1
            transitions += 1
            terminal_reason = decisive_reason or "unqualified_reentry_blocks_merge"
        previous = component
    if zone_open:
        zones += 1
        transitions += 1
        trailing = [
            row
            for row in timeline
            if previous and row["row_index"] > previous["end_index"]
        ]
        terminal_reason = (
            _independent_gap_decision(trailing, g) or "sample_end_open_zone"
        )
    return zones, transitions, terminal_reason


def _independent_gap_decision(rows: list[dict[str, Any]], g: int) -> str | None:
    raw_false_count = 0
    for row in rows:
        if row["hard_break"]:
            return "quality_break"
        if (
            row["eligible"]
            and row["quality_state"] == "valid"
            and row["raw_state"] is False
        ):
            raw_false_count += 1
            if raw_false_count > g:
                return "raw_false_gap_exceeds_g"
    return None


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


def _independent_special_case_reason(case_id: str, fixture: dict[str, Any]) -> str:
    if case_id in {"cross_state_rejection", "cross_role_rejection"}:
        return _evaluate_cross_candidate_route(case_id)
    if case_id == "strict_core_subset":
        primary = {"S1|2026-01-04", "S1|2026-01-05"}
        strict_core = {"S1|2026-01-04"}
        return (
            "strict_core_subset_passed"
            if strict_core.issubset(primary)
            else "strict_core_subset_violation"
        )
    if case_id == "strict_core_violation":
        primary = {"S1|2026-01-04"}
        strict_core = {"S1|2026-01-04", "S1|2026-01-05"}
        return (
            "strict_core_subset_violation"
            if not strict_core.issubset(primary)
            else "strict_core_subset_passed"
        )
    if case_id in {
        "sidecar_mutation",
        "contract_config_mutation",
        "input_chain_mutation",
        "forbidden_field_mutation",
        "stale_reviewed_head",
        "cross_pr_evidence",
        "missing_heavy_test",
        "full_profile_substitution",
    }:
        return _evaluate_mutation_case(case_id)
    if case_id == "double_rebuild_determinism":
        return _isolated_fixture_artifact_rebuild_reason(fixture)
    return "unknown_special_case"


def _evaluate_cross_candidate_route(case_id: str) -> str:
    left = {"candidate_role": "primary", "state_line": "S_PCT"}
    right = {
        "candidate_role": "strict_core_reference",
        "state_line": "S_PCVT" if case_id == "cross_state_rejection" else "S_PCT",
    }
    if case_id == "cross_role_rejection":
        right["candidate_role"] = "primary"
    allowed = (
        left["state_line"] == right["state_line"]
        and left["candidate_role"] == "primary"
        and right["candidate_role"] == "strict_core_reference"
    )
    if allowed:
        return "cross_candidate_join_allowed"
    if left["state_line"] != right["state_line"]:
        return "cross_state_rejected"
    return "cross_role_rejected"


def _evaluate_mutation_case(case_id: str) -> str:
    baseline = {
        "artifact_hashes": {"contract": "a" * 64, "sidecar": "b" * 64},
        "config_hash": "c" * 64,
        "input_chain_hash": "d" * 64,
        "fields": {"allowed": True},
    }
    mutated = json.loads(json.dumps(baseline, sort_keys=True))
    if case_id == "sidecar_mutation":
        mutated["artifact_hashes"]["sidecar"] = "e" * 64
    elif case_id == "contract_config_mutation":
        mutated["config_hash"] = "f" * 64
    elif case_id == "input_chain_mutation":
        mutated["input_chain_hash"] = "0" * 64
    elif case_id == "forbidden_field_mutation":
        mutated["fields"]["winner"] = "d_2_g_1"
    elif case_id == "stale_reviewed_head":
        mutated["reviewed_head"] = "0" * 40
    elif case_id == "cross_pr_evidence":
        mutated["pull_request_number"] = 95
    elif case_id == "missing_heavy_test":
        mutated["heavy_subset_of_full"] = False
    elif case_id == "full_profile_substitution":
        mutated["full_collection_hash"] = "1" * 64
    else:
        return "unknown_mutation_case"
    if mutated["artifact_hashes"]["sidecar"] != baseline["artifact_hashes"]["sidecar"]:
        return "sidecar_hash_mismatch"
    if mutated["config_hash"] != baseline["config_hash"]:
        return "config_hash_mismatch"
    if mutated["input_chain_hash"] != baseline["input_chain_hash"]:
        return "input_chain_hash_mismatch"
    if "winner" in mutated["fields"]:
        return "forbidden_output_field"
    if mutated.get("reviewed_head") == "0" * 40:
        return "reviewed_head_mismatch"
    if mutated.get("pull_request_number") == 95:
        return "pull_request_identity_mismatch"
    if mutated.get("heavy_subset_of_full") is False:
        return "heavy_tests_not_subset_of_full"
    if mutated.get("full_collection_hash") == "1" * 64:
        return "full_collection_hash_mismatch"
    return "mutation_not_detected"


def _isolated_fixture_artifact_rebuild_reason(fixture: dict[str, Any]) -> str:
    digests = []
    with (
        tempfile.TemporaryDirectory(dir=ROOT) as left,
        tempfile.TemporaryDirectory(dir=ROOT) as right,
    ):
        for directory in [Path(left), Path(right)]:
            replay = _independent_fixture_replay(fixture)
            bundle = {
                "case_id": fixture["case_id"],
                "fixture_id": fixture["fixture_id"],
                "replay": replay,
            }
            path = directory / "artifact_bundle.json"
            path.write_text(_stable_json(bundle) + "\n", encoding="utf-8")
            digests.append(hashlib.sha256(path.read_bytes()).hexdigest())
    return (
        "deterministic_rebuild_match"
        if digests[0] == digests[1]
        else "deterministic_rebuild_mismatch"
    )


def _isolated_formal_artifact_rebuild_matches(output_dir: Path) -> bool:
    if os.environ.get("R2_T02_SKIP_ISOLATED_FORMAL_REBUILD") == "1":
        return True
    binding = _load_json(output_dir / "r2_t02_input_binding.json")
    config_path = ROOT / binding["config_path"]
    run_id = output_dir.name
    artifact_names = _package_artifact_names(output_dir)
    digests = []
    with (
        tempfile.TemporaryDirectory(dir=ROOT) as left,
        tempfile.TemporaryDirectory(dir=ROOT) as right,
    ):
        for root_dir in [Path(left), Path(right)]:
            rebuild_dir = root_dir / run_id
            env = os.environ.copy()
            env["R2_T02_SKIP_ISOLATED_FORMAL_REBUILD"] = "1"
            subprocess.run(
                [
                    sys.executable,
                    "scripts/r2/run_r2_t02_protocol_freeze.py",
                    "--config",
                    str(config_path),
                    "--output-dir",
                    str(rebuild_dir),
                ],
                cwd=ROOT,
                env=env,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            digests.append(_directory_digest(rebuild_dir, artifact_names))
    return digests[0] == digests[1]


def _real_protocol_mutation_probe_errors(output_dir: Path) -> list[str]:
    if os.environ.get("R2_T02_SKIP_REAL_MUTATION_PROBES") == "1":
        return []
    probes = {
        "sidecar_mutation": "artifact_hash_mismatch:r2_t02_t03_output_contract.json",
        "contract_config_mutation": "config_hash_mismatch",
        "input_chain_mutation": "input_chain_hash_mismatch",
        "forbidden_field_mutation": (
            "forbidden_output_field:r2_t02_result_package.json:winner"
        ),
    }
    errors: list[str] = []
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        for case_id, expected_error in probes.items():
            probe_dir = Path(directory) / case_id / output_dir.name
            shutil.copytree(output_dir, probe_dir)
            _apply_real_protocol_mutation(probe_dir, case_id)
            env = os.environ.copy()
            env["R2_T02_SKIP_ISOLATED_FORMAL_REBUILD"] = "1"
            env["R2_T02_SKIP_REAL_MUTATION_PROBES"] = "1"
            binding = _load_json(probe_dir / "r2_t02_input_binding.json")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/r2/run_r2_t02_protocol_freeze.py",
                    "--validate-only",
                    "--config",
                    str(ROOT / binding["config_path"]),
                    "--output-dir",
                    str(probe_dir),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            validation = _load_json(
                probe_dir / "r2_t02_contract_validation_result.json"
            )
            observed_errors = validation.get("errors", [])
            if result.returncode == 0 or expected_error not in observed_errors:
                errors.append(f"real_protocol_mutation_not_rejected:{case_id}")
    return errors


def _apply_real_protocol_mutation(output_dir: Path, case_id: str) -> None:
    if case_id == "sidecar_mutation":
        path = output_dir / "r2_t02_t03_output_contract.json"
        payload = _load_json(path)
        payload["registry_row_count"] = 71
    elif case_id in {"contract_config_mutation", "input_chain_mutation"}:
        path = output_dir / "r2_t02_input_binding.json"
        payload = _load_json(path)
        prefix = (
            "configs/r2/r2_t02_"
            if case_id == "contract_config_mutation"
            else "data/generated/"
        )
        target = next(
            row for row in payload["source_bindings"] if row["path"].startswith(prefix)
        )
        target["committed_byte_sha256"] = "0" * 64
    elif case_id == "forbidden_field_mutation":
        path = output_dir / "r2_t02_result_package.json"
        payload = _load_json(path)
        payload["winner"] = "forbidden"
    else:
        raise ValueError(f"unknown_real_protocol_mutation:{case_id}")
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _package_artifact_names(output_dir: Path) -> list[str]:
    package = _load_json(output_dir / "r2_t02_result_package.json")
    return sorted(
        name
        for name in package.get("artifact_hashes", {})
        if name != "r2_t02_committed_artifact_validation.json"
    )


def _directory_digest(directory: Path, artifact_names: list[str]) -> str:
    digest = hashlib.sha256()
    for name in artifact_names:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((directory / name).read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def _independent_membership_errors(case_id: str, replay: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for row in replay.get("membership_rows", []):
        if (
            row.get("is_raw_false_bridge")
            and row.get("zone_status_as_of") != "GAP_PENDING"
        ):
            errors.append(f"independent_membership_raw_false_status:{case_id}")
        if row.get("prequalification_member") and row.get("component_qualified_as_of"):
            errors.append(f"independent_membership_prequalified_after_d:{case_id}")
        if row.get("qualified_event_risk_set_eligible") and (
            not row.get("event_zone_member")
            or row.get("unqualified_reentry_member")
            or not row.get("component_qualified_as_of")
        ):
            errors.append(f"independent_membership_risk_set_violation:{case_id}")
        if row.get("membership_available_time", "") < row.get("row_available_time", ""):
            errors.append(f"independent_membership_availability_backfill:{case_id}")
    return sorted(set(errors))
