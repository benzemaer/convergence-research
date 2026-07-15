"""R3-T01 protocol construction and synthetic replay primitives.

This module contains the implementation-side rules for the R3-T01 contract.  It
does not read the R2 canonical database.  Formal execution only consumes the
committed R2 binding records and the synthetic fixture declared by this task.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from src.common.canonical_io import write_csv, write_json

ROOT = Path(__file__).resolve().parents[2]
FIELD_SEMANTICS_HEADER = [
    "field_name",
    "type",
    "nullable",
    "availability_class",
    "available_time_source",
    "allowed_at_T0",
    "allowed_at_T1",
    "allowed_at_T2",
    "audit_only",
    "forbidden_model_feature",
    "source_artifact",
    "derivation_rule",
]


class ProtocolContractError(ValueError):
    """A fail-closed contract or synthetic replay error."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        detail = f":{message}" if message else ""
        super().__init__(f"{code}{detail}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize values using the R3 identity contract."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ProtocolContractError("CONFIG_NOT_OBJECT", str(path))
    return value


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolContractError("INVALID_TIME", value) from exc
    if parsed.tzinfo is None:
        raise ProtocolContractError("TIMEZONE_REQUIRED", value)
    return parsed


def _time_leq(left: str, right: str) -> bool:
    return _parse_time(left) <= _parse_time(right)


def timestamp_leq(left: str, right: str) -> bool:
    """Compare two timezone-aware ISO-8601 timestamps in absolute time."""

    return _time_leq(left, right)


def validate_timestamp_order(earlier: str, later: str) -> None:
    """Require a timezone-aware timestamp order and fail closed on inversion."""

    if not timestamp_leq(earlier, later):
        raise ProtocolContractError("TIME_ORDER_MISMATCH", f"{earlier}>{later}")


def _date_from_timestamp(value: str) -> str:
    return _parse_time(value).date().isoformat()


def _identity_hash(
    namespace: str,
    contract_version: str,
    fields: dict[str, str],
) -> str:
    payload: dict[str, str] = {
        "namespace": namespace,
        "contract_version": contract_version,
        **fields,
    }
    return canonical_json_sha256(payload)


def source_component_id(
    *,
    contract_version: str,
    state_version_id: str,
    event_id: str,
    security_id: str,
    source_component_start_date: str,
    namespace: str,
) -> str:
    return _identity_hash(
        namespace,
        contract_version,
        {
            "state_version_id": state_version_id,
            "event_id": event_id,
            "security_id": security_id,
            "source_component_start_date": source_component_start_date,
        },
    )


def exit_attempt_id(
    *,
    contract_version: str,
    state_version_id: str,
    event_id: str,
    security_id: str,
    source_component_id_value: str,
    exit_attempt_date: str,
    namespace: str,
) -> str:
    return _identity_hash(
        namespace,
        contract_version,
        {
            "state_version_id": state_version_id,
            "event_id": event_id,
            "security_id": security_id,
            "source_component_id": source_component_id_value,
            "exit_attempt_date": exit_attempt_date,
        },
    )


def _row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("state_version_id", "")),
        str(row.get("security_id", "")),
        str(row.get("trade_date", "")),
    )


def _membership_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("state_version_id", "")),
        str(row.get("event_id", "")),
        str(row.get("security_id", "")),
        str(row.get("trade_date", "")),
    )


def _event_zone_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("state_version_id", "")),
        str(row.get("event_id", "")),
    )


def _index_unique(
    rows: list[dict[str, Any]],
    key_fn: Any,
    duplicate_code: str,
) -> dict[Any, dict[str, Any]]:
    result: dict[Any, dict[str, Any]] = {}
    for row in rows:
        key = key_fn(row)
        if key in result:
            raise ProtocolContractError(duplicate_code, str(key))
        result[key] = row
    return result


def sort_expected_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort the complete expected-row surface without filtering invalid rows."""

    indexed = _index_unique(rows, _row_key, "DUPLICATE_EXPECTED_ROW")
    return sorted(indexed.values(), key=_row_key)


def _groups(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("state_version_id")), str(row.get("security_id")))].append(
            row
        )
    return grouped


def _expected_row_present(row: dict[str, Any]) -> bool:
    """Treat the fixture-only row-presence control as true by default."""

    return row.get("expected_row_present", True) is True


def _transition_matches(
    prior: dict[str, Any],
    current: dict[str, Any],
    transition: dict[str, Any],
) -> bool:
    """Replay the registered transition, including its hard-break semantics."""

    prior_state = (
        transition["from_state"]
        if prior.get("eligible_state") is True
        and prior.get("quality_state") == "valid"
        and prior.get("confirmed_state") is True
        and prior.get("active_event_id_as_of")
        and prior.get("event_status_as_of") in transition["from_event_statuses"]
        else "OTHER"
    )
    current_state = (
        transition["to_state"]
        if current.get("eligible_state") is True
        and current.get("quality_state") == "valid"
        and current.get("raw_state") is False
        and current.get("confirmed_state") is False
        else "OTHER"
    )
    observed = {
        "from_state": prior_state,
        "to_state": current_state,
        "trigger": "raw_false" if current.get("raw_state") is False else "other",
        "hard_break": current.get("quality_state") != "valid",
        "reason_code": transition["reason_code"]
        if prior_state == transition["from_state"]
        and current_state == transition["to_state"]
        and current.get("quality_state") == "valid"
        else "other",
    }
    expected = {
        "from_state": transition["from_state"],
        "to_state": transition["to_state"],
        "trigger": transition["trigger"],
        "hard_break": transition["hard_break"],
        "reason_code": transition["reason_code"],
    }
    return observed == expected


def reconstruct_source_components(
    rows: list[dict[str, Any]],
    event_zones: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reconstruct causal component identities from daily rows and event zones.

    Membership is deliberately not an input to this function.  It is a
    retrospective audit surface and therefore cannot create a run, change its
    identity, or determine its ordinal.
    """
    surface = sort_expected_surface(rows)
    zones = _index_unique(event_zones, _event_zone_key, "DUPLICATE_EVENT_ZONE")
    components: list[dict[str, Any]] = []
    first_component_seen: set[tuple[str, str, str]] = set()
    for group_rows in _groups(surface).values():
        current: dict[str, Any] | None = None
        for row in group_rows:
            event_id_value = row.get("active_event_id_as_of")
            event_id = str(event_id_value) if event_id_value is not None else ""
            zone = zones.get((str(row.get("state_version_id")), event_id))
            causal_row = bool(
                _expected_row_present(row)
                and row.get("eligible_state") is True
                and row.get("quality_state") == "valid"
                and row.get("confirmed_state") is True
                and event_id
                and zone is not None
                and str(zone.get("security_id")) == str(row.get("security_id"))
            )
            if not causal_row:
                current = None
                continue
            if current is None or event_id != current["event_id"]:
                event_key = (
                    str(row["state_version_id"]),
                    event_id,
                    str(row["security_id"]),
                )
                is_first_component = event_key not in first_component_seen
                if is_first_component:
                    first_component_seen.add(event_key)
                    start_date = str(zone.get("first_component_start_date", ""))
                    try:
                        qualification_date = _date_from_timestamp(
                            str(zone["first_qualification_time"])
                        )
                    except (KeyError, ProtocolContractError) as exc:
                        raise ProtocolContractError(
                            "EVENT_ZONE_FIRST_QUALIFICATION_MISSING",
                            str(event_key),
                        ) from exc
                    if not start_date:
                        raise ProtocolContractError(
                            "EVENT_ZONE_FIRST_COMPONENT_START_MISSING",
                            str(event_key),
                        )
                    qualified = True
                else:
                    start_date = str(row["trade_date"])
                    qualification_date = (
                        str(row["trade_date"])
                        if row.get("component_qualified_as_of") is True
                        else None
                    )
                    qualified = qualification_date is not None
                current = {
                    "state_version_id": str(row["state_version_id"]),
                    "event_id": event_id,
                    "security_id": str(row["security_id"]),
                    "source_component_start_date": start_date,
                    "source_component_end_date": str(row["trade_date"]),
                    "source_component_qualification_date": qualification_date,
                    "source_component_qualified": qualified,
                    "row_keys": [_row_key(row)],
                }
                components.append(current)
            else:
                current["source_component_end_date"] = str(row["trade_date"])
                if (
                    current["source_component_qualification_date"] is None
                    and row.get("component_qualified_as_of") is True
                ):
                    current["source_component_qualification_date"] = str(
                        row["trade_date"]
                    )
                current["source_component_qualified"] = bool(
                    current["source_component_qualified"]
                    or row.get("component_qualified_as_of") is True
                )
                current["row_keys"].append(_row_key(row))

    namespace = config["analysis_unit_contract"]["source_component_id_spec"][
        "namespace"
    ]
    contract_version = str(config["contract_version"])
    for component in components:
        component["source_component_id"] = source_component_id(
            contract_version=contract_version,
            state_version_id=component["state_version_id"],
            event_id=component["event_id"],
            security_id=component["security_id"],
            source_component_start_date=component["source_component_start_date"],
            namespace=namespace,
        )

    by_event: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for component in components:
        by_event[(component["state_version_id"], component["event_id"])].append(
            component
        )
    for event_components in by_event.values():
        event_components.sort(
            key=lambda item: (
                item["source_component_start_date"],
                item["source_component_id"],
            )
        )
        for ordinal, component in enumerate(event_components, start=1):
            component["source_component_ordinal"] = ordinal
    return components


def _component_for_prior(
    components: list[dict[str, Any]], prior: dict[str, Any]
) -> dict[str, Any] | None:
    key = _row_key(prior)
    for component in components:
        if key in component["row_keys"]:
            return component
    return None


def _reject(rejections: list[dict[str, Any]], code: str, row: dict[str, Any]) -> None:
    rejections.append({"row_key": list(_row_key(row)), "code": code})


def enumerate_exit_attempts(
    rows: list[dict[str, Any]],
    event_zones: list[dict[str, Any]],
    membership_rows: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    sample_end_censoring: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Enumerate all legal natural exits from the unfiltered expected surface."""

    surface = sort_expected_surface(rows)
    zones = _index_unique(event_zones, _event_zone_key, "DUPLICATE_EVENT_ZONE")
    memberships = _index_unique(
        membership_rows, _membership_key, "DUPLICATE_MEMBERSHIP_ROW"
    )
    transition = config["t0_transition_contract"]["transition_registry"]
    components = reconstruct_source_components(surface, event_zones, config)
    attempts: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []

    for group_rows in _groups(surface).values():
        for index in range(1, len(group_rows)):
            prior = group_rows[index - 1]
            current = group_rows[index]
            if not _expected_row_present(current):
                _reject(rejections, "CURRENT_EXPECTED_ROW_MISSING", current)
                continue
            if not _expected_row_present(prior):
                _reject(rejections, "PRIOR_EXPECTED_ROW_MISSING", current)
                continue
            if prior.get("active_event_id_as_of") is None:
                _reject(rejections, "PREQUALIFICATION_EXIT", current)
                continue
            if (
                prior.get("eligible_state") is not True
                or prior.get("quality_state") != "valid"
            ):
                _reject(rejections, "PRIOR_ROW_NOT_ELIGIBLE", current)
                continue
            if prior.get("confirmed_state") is not True:
                _reject(rejections, "PRIOR_NOT_CONFIRMED", current)
                continue
            if current.get("eligible_state") is not True:
                _reject(rejections, "CURRENT_INELIGIBLE", current)
                continue
            if current.get("quality_state") != "valid":
                _reject(rejections, "QUALITY_INTERRUPTION", current)
                continue
            if current.get("raw_state") is None:
                _reject(rejections, "CURRENT_RAW_UNKNOWN", current)
                continue
            if (
                current.get("raw_state") is not False
                or current.get("confirmed_state") is not False
            ):
                _reject(rejections, "NOT_NATURAL_STATE_EXIT", current)
                continue

            event_id = str(prior.get("active_event_id_as_of"))
            current_event_id = current.get("active_event_id_as_of")
            if current_event_id is not None and str(current_event_id) != event_id:
                _reject(rejections, "EVENT_ID_CONFLICT", current)
                continue

            zone_key = (str(current["state_version_id"]), event_id)
            zone = zones.get(zone_key)
            if zone is None or str(zone.get("security_id")) != str(
                current.get("security_id")
            ):
                _reject(rejections, "EVENT_NOT_FOUND", current)
                continue
            try:
                first_qualification_date = _date_from_timestamp(
                    str(zone["first_qualification_time"])
                )
            except ProtocolContractError:
                _reject(rejections, "EVENT_NOT_QUALIFIED", current)
                continue
            if first_qualification_date > str(current["trade_date"]):
                _reject(rejections, "EVENT_NOT_QUALIFIED", current)
                continue
            if not _transition_matches(prior, current, transition):
                _reject(rejections, "TRANSITION_NOT_NATURAL_STATE_EXIT", current)
                continue

            component = _component_for_prior(components, prior)
            if component is None or component["event_id"] != event_id:
                _reject(rejections, "SOURCE_COMPONENT_NOT_FOUND", current)
                continue
            qualification_date = component["source_component_qualification_date"]
            if component["source_component_start_date"] > str(current["trade_date"]):
                _reject(rejections, "SOURCE_COMPONENT_DATE_ORDER", current)
                continue
            if qualification_date is not None and not (
                component["source_component_start_date"]
                <= qualification_date
                <= str(current["trade_date"])
            ):
                _reject(rejections, "SOURCE_COMPONENT_DATE_ORDER", current)
                continue
            source_id = component["source_component_id"]
            attempt_id = exit_attempt_id(
                contract_version=str(config["contract_version"]),
                state_version_id=str(current["state_version_id"]),
                event_id=event_id,
                security_id=str(current["security_id"]),
                source_component_id_value=source_id,
                exit_attempt_date=str(current["trade_date"]),
                namespace=config["analysis_unit_contract"]["exit_attempt_id_spec"][
                    "namespace"
                ],
            )
            membership_key = (
                str(current["state_version_id"]),
                event_id,
                str(current["security_id"]),
                str(current["trade_date"]),
            )
            membership = memberships.get(membership_key)
            prior_membership_rows = [
                item
                for item in membership_rows
                if str(item.get("state_version_id")) == str(current["state_version_id"])
                and str(item.get("event_id")) == event_id
                and str(item.get("security_id")) == str(current["security_id"])
                and str(item.get("trade_date")) < str(current["trade_date"])
            ]
            last_prior_membership = max(
                prior_membership_rows,
                key=lambda item: str(item.get("trade_date")),
                default=None,
            )
            state_version = next(
                (
                    item
                    for item in config["frozen_inputs"]["state_versions"]
                    if item["state_version_id"] == str(current["state_version_id"])
                ),
                None,
            )
            if state_version is None:
                _reject(rejections, "FROZEN_STATE_VERSION_MISMATCH", current)
                continue
            qualified_count = sum(
                1
                for item in components
                if item["state_version_id"] == component["state_version_id"]
                and item["event_id"] == event_id
                and item.get("source_component_qualification_date") is not None
                and item["source_component_qualification_date"]
                <= str(current["trade_date"])
            )
            current_membership_available_time = (
                membership.get("membership_available_time") if membership else None
            )
            attempts.append(
                {
                    "state_version_id": str(current["state_version_id"]),
                    "event_id": event_id,
                    "security_id": str(current["security_id"]),
                    "exit_attempt_id": attempt_id,
                    "source_component_id": source_id,
                    "source_component_start_date": component[
                        "source_component_start_date"
                    ],
                    "source_component_end_date": component["source_component_end_date"],
                    "source_component_qualification_date": component[
                        "source_component_qualification_date"
                    ],
                    "source_component_qualified": component[
                        "source_component_qualified"
                    ],
                    "source_component_ordinal": component["source_component_ordinal"],
                    "component_count_as_of_exit": qualified_count,
                    "frozen_g": state_version["g"],
                    "last_observed_zone_revision_before_exit": (
                        last_prior_membership.get("zone_revision")
                        if last_prior_membership
                        else None
                    ),
                    "current_exit_membership_zone_revision": (
                        membership.get("zone_revision") if membership else None
                    ),
                    "exit_attempt_date": str(current["trade_date"]),
                    "exit_attempt_time": None,
                    "exit_attempt_time_missing_reason": (
                        "UPSTREAM_DAILY_AVAILABLE_TIME_NOT_EXPOSED"
                    ),
                    "prior_confirmed_state": True,
                    "exit_raw_state": False,
                    "exit_reason": transition["reason_code"],
                    "event_status_as_of_exit": current.get("event_status_as_of"),
                    "current_membership_row_present": membership is not None,
                    "current_membership_available_time": (
                        current_membership_available_time
                    ),
                    "current_membership_availability_is_causal_for_t0": False,
                    "membership_resolution_status": (
                        "current_row_not_available"
                        if membership is None
                        else (
                            "current_row_available"
                            if current_membership_available_time
                            else "current_row_available_time_missing"
                        )
                    ),
                    "unqualified_reentry": not component["source_component_qualified"],
                    "attempt_weight": 1.0,
                }
            )

        if sample_end_censoring and group_rows:
            last = group_rows[-1]
            if (
                _expected_row_present(last)
                and last.get("confirmed_state") is True
                and last.get("active_event_id_as_of")
            ):
                _reject(rejections, "RIGHT_CENSORING", last)

    seen_ids: set[str] = set()
    seen_t0: set[tuple[str, str, str, str]] = set()
    for attempt in attempts:
        if attempt["exit_attempt_id"] in seen_ids:
            raise ProtocolContractError("DUPLICATE_EXIT_ATTEMPT_ID")
        seen_ids.add(attempt["exit_attempt_id"])
        t0_key = (
            attempt["state_version_id"],
            attempt["event_id"],
            attempt["security_id"],
            attempt["exit_attempt_date"],
        )
        if t0_key in seen_t0:
            raise ProtocolContractError("DUPLICATE_SOURCE_COMPONENT_T0")
        seen_t0.add(t0_key)
    attempts.sort(
        key=lambda item: (
            item["state_version_id"],
            item["event_id"],
            item["exit_attempt_date"],
            item["exit_attempt_id"],
        )
    )
    for group in _attempt_groups(attempts).values():
        for ordinal, attempt in enumerate(group, start=1):
            attempt["exit_attempt_ordinal"] = ordinal
    return attempts, rejections


def _attempt_groups(
    attempts: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        grouped[(attempt["state_version_id"], attempt["event_id"])].append(attempt)
    return grouped


def _valid_landmark_row(row: dict[str, Any]) -> bool:
    return bool(
        _expected_row_present(row)
        and row.get("eligible_state") is True
        and row.get("quality_state") == "valid"
    )


def build_landmarks(
    rows: list[dict[str, Any]],
    *,
    state_version_id: str,
    security_id: str,
    t0_date: str,
    horizon_days: tuple[int, ...] = (5, 10, 20, 30),
) -> dict[str, Any]:
    """Build landmarks only on the target state/security expected surface."""

    future = [
        row
        for row in sorted(
            [
                item
                for item in rows
                if str(item.get("state_version_id")) == state_version_id
                and str(item.get("security_id")) == security_id
            ],
            key=_row_key,
        )
        if str(row.get("trade_date", "")) > t0_date
    ]
    valid_rows = [row for row in future if _valid_landmark_row(row)]
    result: dict[str, Any] = {
        "state_version_id": state_version_id,
        "security_id": security_id,
        "t0_date": t0_date,
        "T0": {
            "landmark_id": "T0",
            "available": True,
            "trade_date": t0_date,
            "ordinal": 0,
            "intervening_unobservable_row_count": 0,
            "intervening_unobservable_reason_set": [],
            "landmark_unavailable_reason": None,
        },
    }
    consumed = 0
    reasons: set[str] = set()
    for target in (1, 2):
        found: dict[str, Any] | None = None
        while consumed < len(future):
            row = future[consumed]
            consumed += 1
            if _valid_landmark_row(row):
                if (
                    len(
                        [
                            item
                            for item in future[:consumed]
                            if _valid_landmark_row(item)
                        ]
                    )
                    >= target
                ):
                    found = row
                    break
            else:
                reasons.add(_unobservable_reason(row))
        if found is None:
            result[f"T{target}"] = {
                "landmark_id": f"T{target}",
                "available": False,
                "trade_date": None,
                "ordinal": None,
                "intervening_unobservable_row_count": len(
                    [
                        item
                        for item in future[:consumed]
                        if not _valid_landmark_row(item)
                    ]
                ),
                "intervening_unobservable_reason_set": sorted(reasons),
                "landmark_unavailable_reason": "INSUFFICIENT_VALID_EXPECTED_ROWS",
            }
        else:
            result[f"T{target}"] = {
                "landmark_id": f"T{target}",
                "available": True,
                "trade_date": found["trade_date"],
                "ordinal": target,
                "intervening_unobservable_row_count": len(
                    [
                        item
                        for item in future[:consumed]
                        if not _valid_landmark_row(item)
                    ]
                ),
                "intervening_unobservable_reason_set": sorted(reasons),
                "landmark_unavailable_reason": None,
            }
    for horizon in horizon_days:
        item = valid_rows[horizon - 1] if len(valid_rows) >= horizon else None
        result[f"H{horizon}"] = {
            "horizon_id": f"H{horizon}",
            "valid_expected_row_count": horizon if item else len(valid_rows),
            "available": item is not None,
            "trade_date": item["trade_date"] if item else None,
            "unavailable_reason": None if item else "INSUFFICIENT_VALID_EXPECTED_ROWS",
        }
    return result


def _unobservable_reason(row: dict[str, Any]) -> str:
    if row.get("expected_row_present") is not True:
        return "MISSING_EXPECTED_TRADING_ROW"
    if row.get("eligible_state") is not True:
        return "INELIGIBLE_STATE"
    if row.get("quality_state") != "valid":
        return "QUALITY_NOT_VALID"
    return "UNOBSERVABLE"


def validate_event_split_assignments(
    attempts: list[dict[str, Any]], assignments: dict[str, str | list[str]]
) -> None:
    by_event: dict[str, set[str]] = defaultdict(set)
    for attempt in attempts:
        event_id = str(attempt["event_id"])
        assigned = assignments.get(event_id)
        if assigned is None:
            raise ProtocolContractError("EVENT_SPLIT_ASSIGNMENT_MISSING", event_id)
        roles = [assigned] if isinstance(assigned, str) else list(assigned)
        by_event[event_id].update(roles)
    if any(len(roles) != 1 for roles in by_event.values()):
        raise ProtocolContractError("EVENT_SPLIT_LEAKAGE")


def event_balanced_weights(attempts: list[dict[str, Any]]) -> dict[str, float]:
    counts: dict[str, int] = defaultdict(int)
    for attempt in attempts:
        counts[str(attempt["event_id"])] += 1
    return {event_id: 1.0 / count for event_id, count in counts.items()}


def build_contract_bundle(config: dict[str, Any]) -> dict[str, Any]:
    """Return the artifacts that a future formal run will materialize."""

    return {
        "r3_t01_protocol_registry.json": copy.deepcopy(config),
        "r3_t01_anchor_decision.json": copy.deepcopy(config["anchor_decision"]),
        "r3_t01_t0_transition_contract.json": {
            "contract_version": config["contract_version"],
            "anchor_decision": copy.deepcopy(config["anchor_decision"]),
            "t0_transition_contract": copy.deepcopy(config["t0_transition_contract"]),
            "analysis_unit_contract": copy.deepcopy(config["analysis_unit_contract"]),
            "field_semantics": copy.deepcopy(config["field_semantics"]),
        },
        "r3_t01_analysis_unit_contract.json": copy.deepcopy(
            config["analysis_unit_contract"]
        ),
        "r3_t01_field_semantics_registry.csv": copy.deepcopy(config["field_semantics"]),
        "r3_t01_landmark_horizon_contract.json": copy.deepcopy(
            config["landmark_horizon_contract"]
        ),
        "r3_t01_sample_split_contract.json": copy.deepcopy(
            config["sample_split_contract"]
        ),
        "r3_t01_schema_registry.json": copy.deepcopy(config["schema_registry"]),
    }


def build_synthetic_results(
    config: dict[str, Any], fixture: dict[str, Any]
) -> list[dict[str, Any]]:
    """Run only declared synthetic cases; no real R2 table is opened."""

    results: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        attempts, rejections = enumerate_exit_attempts(
            case.get("rows", []),
            case.get("event_zones", []),
            case.get("membership_rows", []),
            config,
            sample_end_censoring=bool(case.get("sample_end_censoring", False)),
        )
        landmarks: dict[str, Any] = {}
        for attempt in attempts:
            landmarks[attempt["exit_attempt_id"]] = build_landmarks(
                case.get("rows", []),
                state_version_id=attempt["state_version_id"],
                security_id=attempt["security_id"],
                t0_date=attempt["exit_attempt_date"],
            )
        results.append(
            {
                "case_id": case["case_id"],
                "state_version_security_groups": sorted(
                    {
                        (
                            str(row.get("state_version_id")),
                            str(row.get("security_id")),
                        )
                        for row in case.get("rows", [])
                    }
                ),
                "actual_attempts": attempts,
                "rejections": rejections,
                "landmarks": landmarks,
            }
        )
    return results


def build_deterministic_runner_payload(
    config: dict[str, Any], fixture: dict[str, Any]
) -> dict[str, Any]:
    """Build only deterministic runner-owned artifacts from supplied inputs."""

    payload = build_contract_bundle(config)
    payload["r3_t01_production_synthetic_results.json"] = {
        "case_count": len(fixture["cases"]),
        "cases": build_synthetic_results(config, fixture),
    }
    return payload


def _write_runner_payload(
    directory: Path, payload: dict[str, Any], config: dict[str, Any]
) -> dict[str, str]:
    """Write deterministic runner payload bytes and return their SHA-256 values."""

    fieldnames = FIELD_SEMANTICS_HEADER
    hashes: dict[str, str] = {}
    for name, value in payload.items():
        path = directory / name
        if name.endswith(".csv"):
            if not isinstance(value, list):
                raise ProtocolContractError("FORMAL_CSV_PAYLOAD_INVALID", name)
            write_csv(path, value, fieldnames)
        else:
            write_json(path, value)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def build_production_rebuild_comparison(
    config_path: Path, fixture_path: Path
) -> dict[str, Any]:
    """Rebuild deterministic production artifacts twice in isolated directories."""

    rebuild_hashes: list[dict[str, str]] = []
    with TemporaryDirectory(prefix="r3_t01_rebuild_1_") as first_dir:
        with TemporaryDirectory(prefix="r3_t01_rebuild_2_") as second_dir:
            for directory in (Path(first_dir), Path(second_dir)):
                config = load_json(config_path)
                fixture = load_json(fixture_path)
                payload = build_deterministic_runner_payload(config, fixture)
                hashes = _write_runner_payload(directory, payload, config)
                rebuild_hashes.append(hashes)
    first, second = rebuild_hashes
    mismatches = [
        {
            "filename": name,
            "rebuild_1_sha256": first.get(name),
            "rebuild_2_sha256": second.get(name),
        }
        for name in sorted(set(first) | set(second))
        if first.get(name) != second.get(name)
    ]
    return {
        "rebuild_1_hashes": first,
        "rebuild_2_hashes": second,
        "compared_artifact_count": len(set(first) | set(second)),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "status": "passed" if not mismatches else "failed",
    }


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise ProtocolContractError("GIT_COMMAND_FAILED", " ".join(args))
    return result.stdout.strip()


def verify_local_startup_binding(
    config: dict[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    """Verify R2-T08 ancestry and committed-byte bindings without opening DuckDB."""

    binding = config["upstream_binding"]
    merge_commit = binding["r2_t08_merge_commit"]
    gov_commit = binding["gov_t02_merge_commit"]
    head = _git(root, "rev-parse", "HEAD")
    for required in (merge_commit, gov_commit):
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", required, head],
            cwd=root,
            check=False,
        )
        if result.returncode != 0:
            raise ProtocolContractError("UPSTREAM_ANCESTRY_MISMATCH", required)
    result = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            binding["r2_t08_reviewed_head"],
            merge_commit,
        ],
        cwd=root,
        check=False,
    )
    if result.returncode != 0:
        raise ProtocolContractError("REVIEWED_HEAD_NOT_ANCESTOR")

    checked: list[dict[str, Any]] = []
    for artifact in binding["required_artifacts"]:
        blob = subprocess.run(
            [
                "git",
                "cat-file",
                "blob",
                f"{artifact['source_commit']}:{artifact['path']}",
            ],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if blob.returncode != 0:
            raise ProtocolContractError("UPSTREAM_BLOB_MISSING", artifact["path"])
        actual = hashlib.sha256(blob.stdout).hexdigest()
        if actual != artifact["committed_byte_sha256"]:
            raise ProtocolContractError(
                "UPSTREAM_ARTIFACT_HASH_MISMATCH", artifact["path"]
            )
        checked.append(
            {
                "path": artifact["path"],
                "source_commit": artifact["source_commit"],
                "committed_byte_sha256": actual,
            }
        )
    authority = config["canonical_interface_authority"]
    authority_source = authority["source_artifact"]
    canonical_blob = subprocess.run(
        [
            "git",
            "cat-file",
            "blob",
            f"{authority_source['source_commit']}:{authority_source['path']}",
        ],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if canonical_blob.returncode != 0:
        raise ProtocolContractError("CANONICAL_INTERFACE_SOURCE_RUN_MISMATCH")
    if (
        hashlib.sha256(canonical_blob.stdout).hexdigest()
        != authority_source["committed_byte_sha256"]
    ):
        raise ProtocolContractError("CANONICAL_INTERFACE_HASH_MISMATCH")
    try:
        canonical_value = json.loads(canonical_blob.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolContractError("CANONICAL_INTERFACE_SOURCE_RUN_MISMATCH") from exc
    if (
        canonical_value.get("task_id") != authority["task_id"]
        or canonical_value.get("run_id") != authority["run_id"]
        or canonical_value.get("status") != "passed"
        or canonical_value.get("database_not_opened") is not True
    ):
        raise ProtocolContractError("CANONICAL_INTERFACE_SOURCE_RUN_MISMATCH")
    expected_by_name = {
        item["logical_table_name"]: item
        for item in config["frozen_inputs"]["canonical_interfaces"]
    }
    for value in canonical_value.get("interfaces", {}).values():
        expected = expected_by_name.get(value.get("logical_table_name"))
        if expected is None:
            raise ProtocolContractError("CANONICAL_INTERFACE_TABLE_SET_MISMATCH")
        for field in (
            "primary_key",
            "row_count",
            "stable_multiset_sha256",
            "source_run_id",
        ):
            if value.get(field) != expected.get(field):
                code = {
                    "primary_key": "CANONICAL_INTERFACE_PRIMARY_KEY_MISMATCH",
                    "row_count": "CANONICAL_INTERFACE_ROW_COUNT_MISMATCH",
                    "stable_multiset_sha256": "CANONICAL_INTERFACE_HASH_MISMATCH",
                    "source_run_id": "CANONICAL_INTERFACE_SOURCE_RUN_MISMATCH",
                }[field]
                raise ProtocolContractError(code, value.get("logical_table_name"))
    validation = binding["committed_artifact_validation"]
    blob = subprocess.run(
        [
            "git",
            "cat-file",
            "blob",
            f"{validation['source_commit']}:{validation['path']}",
        ],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if blob.returncode != 0:
        raise ProtocolContractError("UPSTREAM_VALIDATION_BLOB_MISSING")
    try:
        validation_value = json.loads(blob.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolContractError("UPSTREAM_VALIDATION_JSON_INVALID") from exc
    if (
        validation_value.get("status") != "passed"
        or validation_value.get("failure_count") != 0
    ):
        raise ProtocolContractError("UPSTREAM_COMMITTED_VALIDATION_NOT_PASSED")
    return {
        "startup_status": "passed",
        "head": head,
        "r2_t08_merge_commit": merge_commit,
        "gov_t02_merge_commit": gov_commit,
        "reviewed_head": binding["r2_t08_reviewed_head"],
        "required_artifacts": checked,
        "canonical_interface_binding": {
            "path": authority_source["path"],
            "source_commit": authority_source["source_commit"],
            "git_blob_sha": authority_source["git_blob_sha"],
            "committed_byte_sha256": authority_source["committed_byte_sha256"],
            "task_id": authority["task_id"],
            "run_id": authority["run_id"],
            "status": authority["status"],
        },
        "committed_validation_status": "passed",
        "remote_check_required": True,
    }


def _gh_json(root: Path, *args: str) -> dict[str, Any]:
    result = subprocess.run(
        ["gh", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ProtocolContractError("REMOTE_STARTUP_CHECK_FAILED", " ".join(args))
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProtocolContractError(
            "REMOTE_STARTUP_RESPONSE_INVALID", " ".join(args)
        ) from exc
    if not isinstance(value, dict):
        raise ProtocolContractError("REMOTE_STARTUP_RESPONSE_INVALID", " ".join(args))
    return value


def verify_remote_startup_binding(
    config: dict[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    """Verify the merged R2-T08 PR and its scientific review record."""

    binding = config["upstream_binding"]
    review = binding["scientific_review_record"]
    repository = review["repository"]
    pr_number = str(review["pull_request"])
    pr = _gh_json(
        root,
        "pr",
        "view",
        pr_number,
        "--repo",
        repository,
        "--json",
        "state,mergeCommit,headRefOid",
    )
    merge_commit = (pr.get("mergeCommit") or {}).get("oid")
    if pr.get("state") != "MERGED":
        raise ProtocolContractError("UPSTREAM_PR_NOT_MERGED", pr_number)
    if merge_commit != binding["r2_t08_merge_commit"]:
        raise ProtocolContractError("UPSTREAM_PR_MERGE_MISMATCH", str(merge_commit))
    if pr.get("headRefOid") != review["required_reviewed_head"]:
        raise ProtocolContractError(
            "UPSTREAM_PR_REVIEWED_HEAD_MISMATCH", str(pr.get("headRefOid"))
        )
    review_payload = _gh_json(
        root,
        "api",
        f"repos/{repository}/pulls/{pr_number}/reviews/{review['review_comment_id']}",
    )
    body = str(review_payload.get("body", ""))
    if review["required_status_marker"] not in body:
        raise ProtocolContractError("SCIENTIFIC_REVIEW_MARKER_MISSING")
    if review_payload.get("commit_id") not in {
        None,
        review["required_reviewed_head"],
    }:
        raise ProtocolContractError(
            "SCIENTIFIC_REVIEW_COMMIT_MISMATCH",
            str(review_payload.get("commit_id")),
        )
    return {
        "repository": repository,
        "pull_request": int(pr_number),
        "pull_request_state": pr["state"],
        "merge_commit": merge_commit,
        "reviewed_head": pr["headRefOid"],
        "review_comment_id": review["review_comment_id"],
        "scientific_review_status": "passed",
        "required_status_marker": review["required_status_marker"],
    }


def verify_formal_approval(
    config: dict[str, Any],
    reviewed_implementation_sha: str,
    approval_comment_id: str | int | None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Authorize exactly one implementation SHA from a GitHub issue comment."""

    contract = config.get("formal_authorization_contract", {})
    if approval_comment_id is None or not str(approval_comment_id).strip():
        raise ProtocolContractError("FORMAL_APPROVAL_RECORD_REQUIRED")
    comment_id = str(approval_comment_id).strip()
    if not comment_id.isdigit() or int(comment_id) <= 0:
        raise ProtocolContractError("FORMAL_APPROVAL_RECORD_INVALID")
    repository = str(contract.get("repository", ""))
    try:
        comment = _gh_json(
            root,
            "api",
            f"repos/{repository}/issues/comments/{comment_id}",
        )
    except ProtocolContractError as exc:
        raise ProtocolContractError("FORMAL_APPROVAL_RECORD_INVALID") from exc
    repository_url = str(comment.get("repository_url", ""))
    html_url = str(comment.get("html_url", ""))
    if repository not in repository_url and f"/{repository}/" not in html_url:
        raise ProtocolContractError("FORMAL_APPROVAL_RECORD_INVALID")
    if comment.get("id") is not None and str(comment.get("id")) != comment_id:
        raise ProtocolContractError("FORMAL_APPROVAL_RECORD_INVALID")
    author = (comment.get("user") or {}).get("login")
    if author != contract.get("required_author_login"):
        raise ProtocolContractError("FORMAL_APPROVAL_AUTHOR_MISMATCH", str(author))
    body = comment.get("body")
    if not isinstance(body, str) or not body.strip():
        raise ProtocolContractError("FORMAL_APPROVAL_RECORD_INVALID")
    lines = [line.strip() for line in body.splitlines()]
    if (
        lines.count("task_id=R3-T01") != 1
        or lines.count("implementation_review_status=approved") != 1
    ):
        raise ProtocolContractError("FORMAL_APPROVAL_RECORD_INVALID")
    sha_markers = [
        line for line in lines if line.startswith("reviewed_implementation_sha=")
    ]
    expected_sha_marker = f"reviewed_implementation_sha={reviewed_implementation_sha}"
    if sha_markers != [expected_sha_marker]:
        raise ProtocolContractError("FORMAL_APPROVAL_SHA_MISMATCH")
    if lines.count("formal_run_allowed=true") != 1:
        raise ProtocolContractError("FORMAL_APPROVAL_RECORD_INVALID")
    scopes = [
        line.split("=", 1)[1] for line in lines if line.startswith("approval_scope=")
    ]
    if scopes != ["R3-T01_formal_run_only"]:
        raise ProtocolContractError("FORMAL_APPROVAL_SCOPE_MISMATCH")
    try:
        pr = _gh_json(
            root,
            "pr",
            "view",
            str(contract["pull_request"]),
            "--repo",
            repository,
            "--json",
            "state,headRefOid",
        )
    except (KeyError, ProtocolContractError) as exc:
        raise ProtocolContractError("PR_HEAD_SHA_MISMATCH") from exc
    if pr.get("state") != "OPEN" or pr.get("headRefOid") != reviewed_implementation_sha:
        raise ProtocolContractError("PR_HEAD_SHA_MISMATCH", str(pr.get("headRefOid")))
    body_bytes = body.encode("utf-8")
    return {
        "approval_comment_id": int(comment_id),
        "approval_comment_url": comment.get("html_url"),
        "approval_author_login": author,
        "approval_created_at": comment.get("created_at"),
        "approval_updated_at": comment.get("updated_at"),
        "approval_body_sha256": hashlib.sha256(body_bytes).hexdigest(),
        "reviewed_implementation_sha": reviewed_implementation_sha,
        "formal_execution_sha": reviewed_implementation_sha,
        "pr_head_sha": pr.get("headRefOid"),
        "pr_number": int(contract["pull_request"]),
        "pr_state": pr.get("state"),
        "approval_scope": "R3-T01_formal_run_only",
    }


def authorize_formal_run(
    config: dict[str, Any],
    reviewed_implementation_sha: str,
    approval_comment_id: str | int | None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Run the external approval preflight without mutating tracked config."""

    if config.get("implementation_state", {}).get("formal_run_allowed") is not False:
        raise ProtocolContractError("FORMAL_APPROVAL_RECORD_INVALID")
    return verify_formal_approval(
        config, reviewed_implementation_sha, approval_comment_id, root
    )


def execute_formal_run(
    config_path: Path,
    reviewed_implementation_sha: str,
    *,
    approval_comment_id: str | int | None,
    root: Path = ROOT,
    run_id: str | None = None,
) -> Path:
    """Generate runner-owned artifacts; validation and analysis are separate steps."""

    if len(reviewed_implementation_sha) != 40:
        raise ProtocolContractError("REVIEWED_IMPLEMENTATION_SHA_REQUIRED")
    current = _git(root, "rev-parse", "HEAD")
    if current != reviewed_implementation_sha:
        raise ProtocolContractError("IMPLEMENTATION_SHA_MISMATCH")
    if _git(root, "status", "--porcelain"):
        raise ProtocolContractError("WORKTREE_NOT_CLEAN")
    config = load_json(config_path)
    approval = authorize_formal_run(
        config, reviewed_implementation_sha, approval_comment_id, root
    )
    startup = verify_local_startup_binding(config, root)
    startup["remote"] = verify_remote_startup_binding(config, root)
    startup["approval"] = approval
    startup.update(approval)
    fixture_path = root / config["synthetic_fixture_path"]
    run_id = run_id or datetime.now(UTC).strftime("R3-T01-%Y%m%dT%H%M%SZ")
    run_dir = root / "data" / "generated" / "r3" / "r3_t01" / run_id
    if run_dir.exists():
        raise ProtocolContractError("FORMAL_RUN_DIR_ALREADY_EXISTS", str(run_dir))
    fixture = load_json(fixture_path)
    payload = build_deterministic_runner_payload(config, fixture)
    rebuild_comparison = build_production_rebuild_comparison(config_path, fixture_path)
    if rebuild_comparison["status"] != "passed":
        raise ProtocolContractError("PRODUCTION_DOUBLE_REBUILD_MISMATCH")
    runner_artifacts = {
        artifact["filename"]
        for artifact in config["output_contract"]["formal_artifacts"]
        if artifact["artifact_owner"] == "runner"
    }
    written_names = set(payload) | {
        "r3_t01_upstream_binding.json",
        "r3_t01_production_rebuild_comparison.json",
    }
    if written_names != runner_artifacts:
        raise ProtocolContractError("FORMAL_OUTPUT_CONTRACT_MISMATCH")
    run_dir.mkdir(parents=True)
    startup.update(
        {
            "run_id": run_id,
            "reviewed_implementation_sha": reviewed_implementation_sha,
            "formal_execution_sha": current,
        }
    )
    _write_runner_payload(run_dir, payload, config)
    write_json(run_dir / "r3_t01_upstream_binding.json", startup)
    write_json(
        run_dir / "r3_t01_production_rebuild_comparison.json",
        rebuild_comparison,
    )
    return run_dir
