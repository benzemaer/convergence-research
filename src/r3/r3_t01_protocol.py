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
from typing import Any

from src.common.canonical_io import write_csv, write_json, write_markdown

ROOT = Path(__file__).resolve().parents[2]


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
    exit_attempt_time: str,
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
            "exit_attempt_time": exit_attempt_time,
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


def _event_zone_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("state_version_id", "")),
        str(row.get("event_id", "")),
        str(row.get("security_id", "")),
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
    membership_rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reconstruct R3 confirmed-run identities from public membership rows."""

    surface = sort_expected_surface(rows)
    membership_by_row: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(
        list
    )
    for membership in membership_rows:
        membership_by_row[
            (
                str(membership.get("state_version_id", "")),
                str(membership.get("security_id", "")),
                str(membership.get("trade_date", "")),
            )
        ].append(membership)
    components: list[dict[str, Any]] = []
    for group_rows in _groups(surface).values():
        previous_was_member = False
        current: dict[str, Any] | None = None
        for row in group_rows:
            membership_candidates = membership_by_row.get(
                (
                    str(row.get("state_version_id", "")),
                    str(row.get("security_id", "")),
                    str(row.get("trade_date", "")),
                ),
                [],
            )
            if len(membership_candidates) > 1:
                raise ProtocolContractError(
                    "AMBIGUOUS_MEMBERSHIP_ROW", str(_row_key(row))
                )
            membership = membership_candidates[0] if membership_candidates else None
            is_member = bool(
                row.get("expected_row_present") is True
                and row.get("confirmed_state") is True
                and membership is not None
                and membership.get("component_member") is True
            )
            if not is_member:
                previous_was_member = False
                current = None
                continue
            event_id = str(membership.get("event_id", ""))
            if not event_id:
                raise ProtocolContractError(
                    "COMPONENT_EVENT_ID_MISSING", str(_row_key(row))
                )
            if not previous_was_member or current is None:
                current = {
                    "state_version_id": str(row["state_version_id"]),
                    "event_id": event_id,
                    "security_id": str(row["security_id"]),
                    "source_component_start_date": str(row["trade_date"]),
                    "source_component_end_date": str(row["trade_date"]),
                    "component_qualified_as_of": bool(
                        membership.get("component_qualified_as_of") is True
                    ),
                    "qualification_available_time": membership.get(
                        "component_qualification_available_time"
                    ),
                    "row_keys": [_row_key(row)],
                }
                components.append(current)
            else:
                if event_id != current["event_id"]:
                    previous_was_member = False
                    current = None
                    continue
                current["source_component_end_date"] = str(row["trade_date"])
                current["component_qualified_as_of"] = bool(
                    current["component_qualified_as_of"]
                    or membership.get("component_qualified_as_of") is True
                )
                available = membership.get("component_qualification_available_time")
                if available and not current.get("qualification_available_time"):
                    current["qualification_available_time"] = available
                current["row_keys"].append(_row_key(row))
            previous_was_member = True

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

    by_event: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for component in components:
        by_event[
            (
                component["state_version_id"],
                component["event_id"],
                component["security_id"],
            )
        ].append(component)
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
    components = reconstruct_source_components(surface, membership_rows, config)
    attempts: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []

    for group_rows in _groups(surface).values():
        for index in range(1, len(group_rows)):
            prior = group_rows[index - 1]
            current = group_rows[index]
            if current.get("expected_row_present") is not True:
                _reject(rejections, "CURRENT_EXPECTED_ROW_MISSING", current)
                continue
            if prior.get("expected_row_present") is not True:
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

            membership_key = (
                str(current["state_version_id"]),
                event_id,
                str(current["security_id"]),
                str(current["trade_date"]),
            )
            membership = memberships.get(membership_key)
            if membership is None or not membership.get("membership_available_time"):
                _reject(rejections, "T0_MEMBERSHIP_UNAVAILABLE", current)
                continue
            t0_time = str(membership["membership_available_time"])
            zone_key = (
                str(current["state_version_id"]),
                event_id,
                str(current["security_id"]),
            )
            zone = zones.get(zone_key)
            if zone is None:
                _reject(rejections, "EVENT_NOT_FOUND", current)
                continue
            if not _time_leq(str(zone["first_qualification_time"]), t0_time):
                _reject(rejections, "EVENT_NOT_QUALIFIED", current)
                continue
            if not _transition_matches(prior, current, transition):
                _reject(rejections, "TRANSITION_NOT_NATURAL_STATE_EXIT", current)
                continue

            component = _component_for_prior(components, prior)
            if component is None or component["event_id"] != event_id:
                _reject(rejections, "SOURCE_COMPONENT_NOT_FOUND", current)
                continue
            source_id = component["source_component_id"]
            attempt_id = exit_attempt_id(
                contract_version=str(config["contract_version"]),
                state_version_id=str(current["state_version_id"]),
                event_id=event_id,
                security_id=str(current["security_id"]),
                source_component_id_value=source_id,
                exit_attempt_date=str(current["trade_date"]),
                exit_attempt_time=t0_time,
                namespace=config["analysis_unit_contract"]["exit_attempt_id_spec"][
                    "namespace"
                ],
            )
            qualified_count = sum(
                1
                for item in components
                if item["state_version_id"] == component["state_version_id"]
                and item["event_id"] == event_id
                and item["security_id"] == component["security_id"]
                and item["component_qualified_as_of"]
                and item.get("qualification_available_time")
                and _time_leq(str(item["qualification_available_time"]), t0_time)
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
                    "source_component_ordinal": component["source_component_ordinal"],
                    "component_count_as_of_exit": qualified_count,
                    "zone_revision_as_of_exit": membership.get("zone_revision"),
                    "exit_attempt_date": str(current["trade_date"]),
                    "exit_attempt_time": t0_time,
                    "prior_confirmed_state": True,
                    "exit_raw_state": False,
                    "exit_reason": transition["reason_code"],
                    "g_used_as_of_exit": membership.get("g_used_as_of_exit"),
                    "event_status_as_of_exit": current.get("event_status_as_of"),
                    "unqualified_reentry": not component["component_qualified_as_of"],
                    "attempt_weight": 1.0,
                }
            )

        if sample_end_censoring and group_rows:
            last = group_rows[-1]
            if (
                last.get("expected_row_present") is True
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
            attempt["exit_attempt_time"],
        )
        if t0_key in seen_t0:
            raise ProtocolContractError("DUPLICATE_SOURCE_COMPONENT_T0")
        seen_t0.add(t0_key)
    attempts.sort(
        key=lambda item: (
            item["state_version_id"],
            item["event_id"],
            item["exit_attempt_time"],
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
        row.get("expected_row_present") is True
        and row.get("eligible_state") is True
        and row.get("quality_state") == "valid"
    )


def build_landmarks(
    rows: list[dict[str, Any]],
    t0_date: str,
    *,
    horizon_days: tuple[int, ...] = (5, 10, 20, 30),
) -> dict[str, Any]:
    """Build T0/T1/T2 and valid-row horizon positions without path features."""

    future = [
        row
        for row in sort_expected_surface(rows)
        if str(row.get("trade_date", "")) > t0_date
    ]
    valid_rows = [row for row in future if _valid_landmark_row(row)]
    result: dict[str, Any] = {
        "T0": {
            "landmark_id": "T0",
            "available": True,
            "trade_date": t0_date,
            "ordinal": 0,
            "intervening_unobservable_row_count": 0,
            "intervening_unobservable_reason_set": [],
            "landmark_unavailable_reason": None,
        }
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
                case.get("rows", []), attempt["exit_attempt_date"]
            )
        results.append(
            {
                "case_id": case["case_id"],
                "actual_attempts": attempts,
                "rejections": rejections,
                "landmarks": landmarks,
            }
        )
    return results


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


def execute_formal_run(
    config_path: Path,
    reviewed_implementation_sha: str,
    *,
    root: Path = ROOT,
    run_id: str | None = None,
) -> Path:
    """Future formal-run entrypoint; requires explicit reviewed implementation SHA."""

    if len(reviewed_implementation_sha) != 40:
        raise ProtocolContractError("REVIEWED_IMPLEMENTATION_SHA_REQUIRED")
    current = _git(root, "rev-parse", "HEAD")
    if current != reviewed_implementation_sha:
        raise ProtocolContractError("IMPLEMENTATION_SHA_MISMATCH")
    if _git(root, "status", "--porcelain"):
        raise ProtocolContractError("WORKTREE_NOT_CLEAN")
    config = load_json(config_path)
    startup = verify_local_startup_binding(config, root)
    startup["remote"] = verify_remote_startup_binding(config, root)
    fixture_path = root / config["synthetic_fixture_path"]
    fixture = load_json(fixture_path)
    bundle = build_contract_bundle(config)
    synthetic_results = build_synthetic_results(config, fixture)
    run_id = run_id or datetime.now(UTC).strftime("R3-T01-%Y%m%dT%H%M%SZ")
    run_dir = root / "data" / "generated" / "r3" / "r3_t01" / run_id
    if run_dir.exists():
        raise ProtocolContractError("FORMAL_RUN_DIR_ALREADY_EXISTS", str(run_dir))
    run_dir.mkdir(parents=True)
    for name, value in bundle.items():
        path = run_dir / name
        if name.endswith(".csv"):
            write_csv(
                path,
                value,
                list(config["field_semantics"][0].keys()),
            )
        else:
            write_json(path, value)
    write_json(run_dir / "r3_t01_upstream_binding.json", startup)
    write_csv(
        run_dir / "r3_t01_synthetic_case_results.csv",
        synthetic_results,
        ["case_id", "actual_attempts", "rejections", "landmarks"],
    )
    write_csv(
        run_dir / "r3_t01_mutation_results.csv",
        [],
        ["mutation_id", "expected_error_code", "actual_error_code", "status"],
    )
    write_json(
        run_dir / "r3_t01_anomaly_scan.json",
        {"status": "pending_validator", "findings": []},
    )
    artifact_names = sorted(
        artifact["filename"]
        for artifact in config["output_contract"]["formal_artifacts"]
    )
    written_names = sorted(
        set(bundle)
        | {
            "r3_t01_upstream_binding.json",
            "r3_t01_synthetic_case_results.csv",
            "r3_t01_mutation_results.csv",
            "r3_t01_anomaly_scan.json",
            "r3_t01_manifest.json",
            "r3_t01_validator_result.json",
            "r3_t01_result_analysis.md",
        }
    )
    if written_names != artifact_names:
        raise ProtocolContractError("FORMAL_OUTPUT_CONTRACT_MISMATCH")
    write_json(
        run_dir / "r3_t01_manifest.json",
        {
            "task_id": config["task_id"],
            "contract_version": config["contract_version"],
            "run_id": run_id,
            "implementation_sha": reviewed_implementation_sha,
            "formal_run_executed": True,
            "real_database_opened": False,
            "synthetic_case_count": len(fixture["cases"]),
            "artifact_names": artifact_names,
            "validator_status": "pending",
        },
    )
    write_json(
        run_dir / "r3_t01_validator_result.json",
        {
            "status": "pending",
            "validator": "src.r3.r3_t01_validator",
            "formal_run_executed": True,
            "scientific_review_status": "not_started",
        },
    )
    write_markdown(
        run_dir / "r3_t01_result_analysis.md",
        "# R3-T01 formal result analysis\n\nPending independent result review.\n",
    )
    return run_dir
