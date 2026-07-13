# ruff: noqa: E501

"""Independent T06 deterministic state-machine implementation.

This module is deliberately separate from T02/T03 executable helpers.  Its
inputs are the committed dense facts and the frozen transition contract.
"""

from __future__ import annotations

import hashlib
from typing import Any

CONTRACT_VERSION = "r2_t02_confirmed_event_zone_state_machine_contract.v8"


class T06FSMError(RuntimeError):
    """Raised when the independent FSM cannot construct a valid state."""


def atomic_intervals(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in timeline:
        if row["confirmed_state"]:
            if current is None:
                current = {
                    "start_index": row["row_index"],
                    "end_index": row["row_index"],
                    "start_date": row["trade_date"],
                    "end_date": row["trade_date"],
                    "confirmed_day_count": 1,
                }
            else:
                current["end_index"] = row["row_index"]
                current["end_date"] = row["trade_date"]
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


def group_event_zones(
    timeline: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
    d: int,
    g: int,
    *,
    candidate_cell_id: str = "candidate_cell_for_synthetic",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    components: list[dict[str, Any]] = []
    for ordinal, interval in enumerate(intervals, start=1):
        qualified = interval["confirmed_day_count"] >= d
        component = {
            **interval,
            "component_id": f"component_{ordinal:03d}",
            "qualified": qualified,
            "event_qualification_time": timeline[interval["start_index"] + d - 1][
                "available_time"
            ]
            if qualified
            else "",
        }
        components.append(component)

    zones: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    zone: dict[str, Any] | None = None
    previous_component: dict[str, Any] | None = None
    for component in components:
        if not component["qualified"]:
            if zone is not None:
                gap_rows = _rows_between(
                    timeline, previous_component["end_index"], component["start_index"]
                )
                ledger.extend(
                    {**row, "scan_event_id": zone["scan_event_id"]}
                    for row in _gap_entry_ledger(gap_rows)
                )
                gap = _gap_segment(gap_rows, g)
                early_gap_decision = _earliest_gap_decision(gap_rows, gap)
                if early_gap_decision is not None:
                    zone["status"] = early_gap_decision["status"]
                    zone["zone_finalization_time"] = early_gap_decision[
                        "available_time"
                    ]
                    zones.append(zone)
                    ledger.append(
                        {
                            "from_state": "GAP_PENDING",
                            "to_state": early_gap_decision["status"],
                            "reason_code": early_gap_decision["reason_code"],
                            "scan_event_id": zone["scan_event_id"],
                        }
                    )
                    zone = None
                else:
                    ledger.append(
                        {
                            "from_state": "GAP_PENDING",
                            "to_state": "REENTRY_PENDING_QUALIFICATION",
                            "reason_code": "unqualified_reentry_observed",
                            "scan_event_id": zone["scan_event_id"],
                        }
                    )
                    right_censored_reentry = (
                        component["termination_reason"] == "sample_end_censoring"
                    )
                    quality_break_reentry = (
                        component["termination_reason"] == "quality_interruption"
                    )
                    unqualified_available_time = (
                        _component_exit_observation_time(timeline, component)
                        if not right_censored_reentry
                        else timeline[component["end_index"]]["available_time"]
                    )
                    zone["membership_rows"].extend(
                        _component_membership(
                            timeline,
                            component,
                            unqualified_available_time,
                            d,
                            event_zone_member=False,
                            unqualified_reentry_member=True,
                            prequalification_status="REENTRY_PENDING_QUALIFICATION",
                        )
                    )
                    if right_censored_reentry:
                        zone["status"] = "RIGHT_CENSORED"
                        zone["zone_finalization_time"] = ""
                        to_state = "RIGHT_CENSORED"
                        reason_code = "sample_end_before_requalification"
                    elif quality_break_reentry:
                        zone["status"] = "FINALIZED_WITH_QUALITY_BREAK"
                        zone["zone_finalization_time"] = (
                            _component_exit_observation_time(timeline, component)
                        )
                        to_state = "FINALIZED_WITH_QUALITY_BREAK"
                        reason_code = "quality_break"
                    else:
                        zone["status"] = "FINALIZED"
                        zone["zone_finalization_time"] = (
                            _component_exit_observation_time(timeline, component)
                        )
                        to_state = "FINALIZED"
                        reason_code = "unqualified_reentry_blocks_merge"
                    zones.append(zone)
                    ledger.append(
                        {
                            "from_state": "REENTRY_PENDING_QUALIFICATION",
                            "to_state": to_state,
                            "reason_code": reason_code,
                            "scan_event_id": zone["scan_event_id"],
                        }
                    )
                    zone = None
            right_censored = component["termination_reason"] == "sample_end_censoring"
            ledger.append(
                {
                    "from_state": "COMPONENT_FORMING",
                    "to_state": "RIGHT_CENSORED"
                    if right_censored
                    else "UNQUALIFIED_CLOSED",
                    "reason_code": "normal_short_interval_drop"
                    if not right_censored
                    else "prequalification_right_censored",
                }
            )
            previous_component = component
            continue
        if zone is None:
            event_id = scan_event_id(
                candidate_cell_id, timeline[0]["security_id"], component["component_id"]
            )
            zone = {
                "scan_event_id": event_id,
                "first_component_id": component["component_id"],
                "component_count": 1,
                "bridge_count": 0,
                "bridged_day_count": 0,
                "raw_false_bridge_segment_count": 0,
                "raw_false_bridged_day_count": 0,
                "preconfirmation_gap_day_count": 0,
                "total_nonconfirmed_gap_day_count": 0,
                "max_raw_false_gap_days": 0,
                "max_total_gap_span_days": 0,
                "start_date": component["start_date"],
                "end_date": component["end_date"],
                "status": "QUALIFIED_ACTIVE",
                "zone_revision": 0,
                "zone_finalization_time": "",
                "membership_available_time": component["event_qualification_time"],
                "membership_rows": _component_membership(
                    timeline,
                    component,
                    component["event_qualification_time"],
                    d,
                    zone_revision_as_of=0,
                    prequalification_status="COMPONENT_FORMING",
                ),
            }
            ledger.append(
                {
                    "from_state": "COMPONENT_FORMING",
                    "to_state": "QUALIFIED_ACTIVE",
                    "reason_code": "d_qualification",
                    "scan_event_id": zone["scan_event_id"],
                }
            )
            previous_component = component
            continue
        assert previous_component is not None
        gap_rows = _rows_between(
            timeline, previous_component["end_index"], component["start_index"]
        )
        gap = _gap_segment(gap_rows, g)
        decisive_gap_event = _earliest_gap_decision(gap_rows, gap)
        intervening_unqualified = (
            previous_component is not None
            and previous_component.get("qualified") is False
        )
        ledger.extend(
            {**row, "scan_event_id": zone["scan_event_id"]}
            for row in _gap_entry_ledger(gap_rows)
        )
        if decisive_gap_event is not None:
            zone["status"] = decisive_gap_event["status"]
            zone["zone_finalization_time"] = decisive_gap_event["available_time"]
            zones.append(zone)
            ledger.append(
                {
                    "from_state": "GAP_PENDING",
                    "to_state": decisive_gap_event["status"],
                    "reason_code": decisive_gap_event["reason_code"],
                    "scan_event_id": zone["scan_event_id"],
                }
            )
            event_id = scan_event_id(
                candidate_cell_id, timeline[0]["security_id"], component["component_id"]
            )
            zone = {
                "scan_event_id": event_id,
                "first_component_id": component["component_id"],
                "component_count": 1,
                "bridge_count": 0,
                "bridged_day_count": 0,
                "raw_false_bridge_segment_count": 0,
                "raw_false_bridged_day_count": 0,
                "preconfirmation_gap_day_count": 0,
                "total_nonconfirmed_gap_day_count": 0,
                "max_raw_false_gap_days": 0,
                "max_total_gap_span_days": 0,
                "start_date": component["start_date"],
                "end_date": component["end_date"],
                "status": "QUALIFIED_ACTIVE",
                "zone_revision": 0,
                "zone_finalization_time": "",
                "membership_available_time": component["event_qualification_time"],
                "membership_rows": _component_membership(
                    timeline,
                    component,
                    component["event_qualification_time"],
                    d,
                    zone_revision_as_of=0,
                    prequalification_status="COMPONENT_FORMING",
                ),
            }
            ledger.append(
                {
                    "from_state": "COMPONENT_FORMING",
                    "to_state": "QUALIFIED_ACTIVE",
                    "reason_code": "d_qualification",
                    "scan_event_id": event_id,
                }
            )
        elif (
            not gap["exceeds_g"]
            and not intervening_unqualified
            and gap["raw_false_gap_count"] > 0
        ):
            ledger.append(
                {
                    "from_state": "GAP_PENDING",
                    "to_state": "REENTRY_PENDING_QUALIFICATION",
                    "reason_code": "reentry_pending",
                    "scan_event_id": zone["scan_event_id"],
                }
            )
            zone["component_count"] += 1
            zone["bridge_count"] += 1
            zone["raw_false_bridge_segment_count"] += 1
            zone["bridged_day_count"] += gap["raw_false_gap_count"]
            zone["raw_false_bridged_day_count"] += gap["raw_false_gap_count"]
            zone["preconfirmation_gap_day_count"] += gap[
                "preconfirmation_raw_true_count"
            ]
            zone["total_nonconfirmed_gap_day_count"] += gap[
                "total_nonconfirmed_gap_count"
            ]
            zone["max_raw_false_gap_days"] = max(
                zone["max_raw_false_gap_days"], gap["raw_false_gap_count"]
            )
            zone["max_total_gap_span_days"] = max(
                zone["max_total_gap_span_days"], gap["total_nonconfirmed_gap_count"]
            )
            zone["end_date"] = component["end_date"]
            prior_zone_revision = zone["zone_revision"]
            zone["zone_revision"] += 1
            bridge_available = component["event_qualification_time"]
            zone["membership_available_time"] = bridge_available
            zone["membership_rows"].extend(
                _bridge_membership(
                    gap["raw_false_rows"],
                    bridge_available,
                    zone_revision_as_of=prior_zone_revision,
                    zone_status_as_of="GAP_PENDING",
                )
            )
            zone["membership_rows"].extend(
                _preconfirmation_membership(
                    gap["preconfirmation_rows"],
                    bridge_available,
                    raw_false_gap_count_as_of=gap["raw_false_gap_count"],
                    zone_revision_as_of=prior_zone_revision,
                )
            )
            zone["membership_rows"].extend(
                _component_membership(
                    timeline,
                    component,
                    bridge_available,
                    d,
                    zone_revision_as_of=prior_zone_revision,
                    qualified_zone_revision_as_of=zone["zone_revision"],
                    prequalification_status="REENTRY_PENDING_QUALIFICATION",
                )
            )
            ledger.append(
                {
                    "from_state": "REENTRY_PENDING_QUALIFICATION",
                    "to_state": "QUALIFIED_ACTIVE",
                    "reason_code": "reentry_reaches_d_merge",
                    "scan_event_id": zone["scan_event_id"],
                }
            )
        else:
            zone["status"] = "FINALIZED"
            if gap["exceeds_g"]:
                zone["zone_finalization_time"] = gap["g_plus_one_raw_false_time"]
            else:
                zone["zone_finalization_time"] = component["event_qualification_time"]
            zones.append(zone)
            ledger.append(
                {
                    "from_state": "GAP_PENDING",
                    "to_state": "FINALIZED",
                    "reason_code": "raw_false_gap_exceeds_g"
                    if gap["exceeds_g"]
                    else "unqualified_reentry_blocks_merge",
                    "scan_event_id": zone["scan_event_id"],
                }
            )
            event_id = scan_event_id(
                candidate_cell_id, timeline[0]["security_id"], component["component_id"]
            )
            zone = {
                "scan_event_id": event_id,
                "first_component_id": component["component_id"],
                "component_count": 1,
                "bridge_count": 0,
                "bridged_day_count": 0,
                "raw_false_bridge_segment_count": 0,
                "raw_false_bridged_day_count": 0,
                "preconfirmation_gap_day_count": 0,
                "total_nonconfirmed_gap_day_count": 0,
                "max_raw_false_gap_days": 0,
                "max_total_gap_span_days": 0,
                "start_date": component["start_date"],
                "end_date": component["end_date"],
                "status": "QUALIFIED_ACTIVE",
                "zone_revision": 0,
                "zone_finalization_time": "",
                "membership_available_time": component["event_qualification_time"],
                "membership_rows": _component_membership(
                    timeline,
                    component,
                    component["event_qualification_time"],
                    d,
                    zone_revision_as_of=0,
                    prequalification_status="COMPONENT_FORMING",
                ),
            }
            ledger.append(
                {
                    "from_state": "COMPONENT_FORMING",
                    "to_state": "QUALIFIED_ACTIVE",
                    "reason_code": "d_qualification",
                    "scan_event_id": event_id,
                }
            )
        previous_component = component
    if zone is not None:
        trailing = [
            row
            for row in timeline
            if row["row_index"] > zone["membership_rows"][-1]["row_index"]
        ]
        gap = _gap_segment(trailing, g)
        decisive_gap_event = _earliest_gap_decision(trailing, gap)
        if decisive_gap_event is not None:
            zone["status"] = decisive_gap_event["status"]
            zone["zone_finalization_time"] = decisive_gap_event["available_time"]
            reason_code = decisive_gap_event["reason_code"]
            to_state = decisive_gap_event["status"]
        else:
            zone["status"] = "RIGHT_CENSORED"
            reason_code = "sample_end_open_zone"
            to_state = "RIGHT_CENSORED"
        zones.append(zone)
        ledger.append(
            {
                "from_state": "GAP_PENDING",
                "to_state": to_state,
                "reason_code": reason_code,
                "scan_event_id": zone["scan_event_id"],
            }
        )
    return components, zones, ledger


def _component_membership(
    timeline: list[dict[str, Any]],
    component: dict[str, Any],
    available_time: str,
    d: int,
    *,
    event_zone_member: bool = True,
    zone_revision_as_of: int = 0,
    qualified_zone_revision_as_of: int | None = None,
    prequalification_status: str = "COMPONENT_FORMING",
    unqualified_reentry_member: bool = False,
) -> list[dict[str, Any]]:
    rows = []
    qualification_index = component["start_index"] + d - 1
    qualified_revision = (
        zone_revision_as_of
        if qualified_zone_revision_as_of is None
        else qualified_zone_revision_as_of
    )
    for row in timeline:
        if component["start_index"] <= row["row_index"] <= component["end_index"]:
            component_qualified_as_of = row["row_index"] >= qualification_index
            row_status_as_of = (
                "QUALIFIED_ACTIVE"
                if component_qualified_as_of and event_zone_member
                else prequalification_status
            )
            row_zone_revision = (
                qualified_revision
                if component_qualified_as_of and event_zone_member
                else zone_revision_as_of
            )
            prequalification_member = not component_qualified_as_of
            rows.append(
                {
                    "row_index": row["row_index"],
                    "trade_date": row["trade_date"],
                    "event_zone_member": event_zone_member,
                    "retrospective_component_member": event_zone_member,
                    "component_qualified_as_of": component_qualified_as_of,
                    "is_raw_false_bridge": False,
                    "is_preconfirmation_gap": False,
                    "is_bridged_gap": False,
                    "raw_false_gap_ordinal_as_of": 0,
                    "raw_false_gap_count_as_of": 0,
                    "membership_available_time": max(
                        row["available_time"], available_time
                    ),
                    "zone_revision_as_of": row_zone_revision,
                    "zone_status_as_of": row_status_as_of,
                    "prequalification_member": prequalification_member,
                    "unqualified_reentry_member": unqualified_reentry_member,
                    "state_risk_set_eligible": bool(
                        row["eligible"]
                        and row["quality_state"] == "valid"
                        and row["confirmed_state"]
                    ),
                    "qualified_event_risk_set_eligible": bool(
                        event_zone_member
                        and row["eligible"]
                        and row["quality_state"] == "valid"
                        and row["confirmed_state"]
                        and component_qualified_as_of
                        and not unqualified_reentry_member
                    ),
                }
            )
    return rows


def _rows_between(
    timeline: list[dict[str, Any]], left_index: int, right_index: int
) -> list[dict[str, Any]]:
    return [row for row in timeline if left_index < row["row_index"] < right_index]


def _gap_entry_ledger(gap_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not gap_rows:
        return []
    return [
        {
            "from_state": "QUALIFIED_ACTIVE",
            "to_state": "GAP_PENDING",
            "reason_code": "gap_pending",
        }
    ]


def _gap_segment(gap_rows: list[dict[str, Any]], g: int) -> dict[str, Any]:
    raw_false_rows = []
    preconfirmation_rows = []
    raw_false_count_as_of = 0
    for row in gap_rows:
        if (
            row["eligible"]
            and row["quality_state"] == "valid"
            and row["raw_state"] is False
        ):
            raw_false_count_as_of += 1
            raw_false_rows.append(
                {**row, "raw_false_gap_count_as_of": raw_false_count_as_of}
            )
        elif (
            row["eligible"]
            and row["quality_state"] == "valid"
            and row["raw_state"] is True
            and row["confirmed_state"] is False
        ):
            preconfirmation_rows.append(
                {**row, "raw_false_gap_count_as_of": raw_false_count_as_of}
            )
    return {
        "raw_false_rows": raw_false_rows,
        "preconfirmation_rows": preconfirmation_rows,
        "g": g,
        "raw_false_gap_count": len(raw_false_rows),
        "preconfirmation_raw_true_count": len(preconfirmation_rows),
        "total_nonconfirmed_gap_count": len(raw_false_rows) + len(preconfirmation_rows),
        "exceeds_g": len(raw_false_rows) > g,
        "first_raw_false_time": raw_false_rows[0]["available_time"]
        if raw_false_rows
        else "",
        "g_plus_one_raw_false_time": raw_false_rows[g]["available_time"]
        if len(raw_false_rows) > g
        else "",
    }


def _earliest_gap_decision(
    gap_rows: list[dict[str, Any]], gap: dict[str, Any]
) -> dict[str, str] | None:
    raw_false_count = 0
    for row in gap_rows:
        if row["hard_break"]:
            return {
                "status": "FINALIZED_WITH_QUALITY_BREAK",
                "reason_code": "quality_break",
                "available_time": row["available_time"],
            }
        if (
            row["eligible"]
            and row["quality_state"] == "valid"
            and row["raw_state"] is False
        ):
            raw_false_count += 1
            if raw_false_count <= gap["g"]:
                continue
            return {
                "status": "FINALIZED",
                "reason_code": "raw_false_gap_exceeds_g",
                "available_time": row["available_time"],
            }
    return None


def _bridge_membership(
    bridge_rows: list[dict[str, Any]],
    available_time: str,
    *,
    zone_revision_as_of: int,
    zone_status_as_of: str,
) -> list[dict[str, Any]]:
    return [
        {
            "row_index": row["row_index"],
            "trade_date": row["trade_date"],
            "event_zone_member": True,
            "retrospective_component_member": False,
            "component_qualified_as_of": False,
            "is_raw_false_bridge": True,
            "is_preconfirmation_gap": False,
            "is_bridged_gap": True,
            "raw_false_gap_ordinal_as_of": index + 1,
            "raw_false_gap_count_as_of": row.get(
                "raw_false_gap_count_as_of", index + 1
            ),
            "membership_available_time": available_time,
            "zone_revision_as_of": zone_revision_as_of,
            "zone_status_as_of": zone_status_as_of,
            "prequalification_member": False,
            "unqualified_reentry_member": False,
            "state_risk_set_eligible": False,
            "qualified_event_risk_set_eligible": False,
        }
        for index, row in enumerate(bridge_rows)
    ]


def _preconfirmation_membership(
    rows: list[dict[str, Any]],
    available_time: str,
    *,
    raw_false_gap_count_as_of: int,
    zone_revision_as_of: int,
) -> list[dict[str, Any]]:
    return [
        {
            "row_index": row["row_index"],
            "trade_date": row["trade_date"],
            "event_zone_member": True,
            "retrospective_component_member": False,
            "component_qualified_as_of": False,
            "is_raw_false_bridge": False,
            "is_preconfirmation_gap": True,
            "is_bridged_gap": False,
            "raw_false_gap_ordinal_as_of": 0,
            "raw_false_gap_count_as_of": row.get(
                "raw_false_gap_count_as_of", raw_false_gap_count_as_of
            ),
            "membership_available_time": available_time,
            "zone_revision_as_of": zone_revision_as_of,
            "zone_status_as_of": "GAP_PENDING",
            "prequalification_member": True,
            "unqualified_reentry_member": False,
            "state_risk_set_eligible": False,
            "qualified_event_risk_set_eligible": False,
        }
        for row in rows
    ]


def _component_start_time(
    timeline: list[dict[str, Any]], component: dict[str, Any]
) -> str:
    return timeline[component["start_index"]]["available_time"]


def _component_exit_observation_time(
    timeline: list[dict[str, Any]], component: dict[str, Any]
) -> str:
    exit_index = component["end_index"] + 1
    if exit_index < len(timeline):
        return timeline[exit_index]["available_time"]
    return timeline[component["end_index"]]["available_time"]


def _first_hard_break_time(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row["hard_break"]:
            return row["available_time"]
    return ""


def scan_event_id(
    candidate_cell_id: str, security_id: str, component_identity: str
) -> str:
    if not candidate_cell_id:
        raise T06FSMError("missing_candidate_cell_id")
    payload = (
        f"{CONTRACT_VERSION}|{candidate_cell_id}|{security_id}|{component_identity}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
