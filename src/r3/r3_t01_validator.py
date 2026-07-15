"""Independent R3-T01 validator and formal-artifact closure checks.

This module intentionally does not import the production protocol module.  It
replays transitions, component reconstruction, identity, landmarks, horizon
endpoints, mutation cases, and artifact bindings from its own implementation.
"""

from __future__ import annotations

import ast
import copy
import csv
import hashlib
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from src.common.canonical_io import read_csv, write_csv, write_json

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r3/r3_t01_protocol_t0_analysis_unit.v1.json"
FIXTURE_PATH = ROOT / "tests/r3/fixtures/r3_t01/cases.json"

EXPECTED_STATE_VERSIONS = (
    "r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8",
    "r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8",
)
EXPECTED_ATTEMPT_OUTPUT_FIELDS = {
    "state_version_id",
    "event_id",
    "security_id",
    "exit_attempt_id",
    "source_component_id",
    "source_component_start_date",
    "source_component_end_date",
    "source_component_qualification_date",
    "source_component_qualified",
    "source_component_ordinal",
    "component_count_as_of_exit",
    "frozen_g",
    "last_observed_zone_revision_before_exit",
    "current_exit_membership_zone_revision",
    "exit_attempt_date",
    "exit_attempt_time",
    "exit_attempt_time_missing_reason",
    "prior_confirmed_state",
    "exit_raw_state",
    "exit_reason",
    "event_status_as_of_exit",
    "current_membership_row_present",
    "current_membership_available_time",
    "current_membership_availability_is_causal_for_t0",
    "membership_resolution_status",
    "unqualified_reentry",
    "attempt_weight",
    "exit_attempt_ordinal",
}
EXPECTED_ARTIFACT_HASHES = {
    "r2_t08_r3_handoff_manifest.json": (
        "6cefa5c7bcc97a0d64cc0d1febd27c25f84ab69a89b74ccf238fd36e9cb83ba1"
    ),
    "r2_t08_release_anchor_obligation.json": (
        "c3afe1a6e25c571657677f8325dea403cdf1c808301a47ba18cb88012685d7c1"
    ),
    "r2_t08_final_acceptance.json": (
        "907831632fe449e50491135c49b7b1db0a795869496bb8d09d7506a6772aa516"
    ),
    "r2_t08_canonical_interface_binding.json": (
        "2a20c59b219f74c09cf0389add175522666d2f8777c6fd7668e18a75184ebb1f"
    ),
}
EXPECTED_CANONICAL_INTERFACES = {
    "daily": {
        "logical_table_name": "r2_canonical_daily_state",
        "fields": [
            "state_version_id",
            "state_line",
            "window_track_id",
            "security_id",
            "trade_date",
            "eligible_state",
            "raw_state",
            "confirmed_state",
            "confirmation_time",
            "component_qualified_as_of",
            "event_status_as_of",
            "active_event_id_as_of",
            "state_risk_set_eligible",
            "qualified_event_risk_set_eligible",
            "strict_core_member",
            "quality_state",
            "candidate_config_id",
            "source_run_id",
        ],
        "primary_key": ["state_version_id", "security_id", "trade_date"],
        "row_count": 3502132,
        "stable_multiset_sha256": (
            "64c396322b0e358a5c5440eebe90483d65f18a2cc6461a9a28f2cb72711da4ec"
        ),
        "source_run_id": "R2-T05-20260713T154957Z",
    },
    "event": {
        "logical_table_name": "r2_canonical_event_zone",
        "fields": [
            "state_version_id",
            "event_id",
            "security_id",
            "first_component_start_date",
            "first_qualification_time",
            "last_confirmed_end_date",
            "last_exit_observation_time",
            "zone_finalization_time",
            "zone_status",
            "exit_reason",
            "left_censored",
            "right_censored",
            "component_interval_count",
            "bridge_count",
            "bridged_gap_days",
            "zone_confirmed_day_count",
            "zone_trading_span",
            "confirmed_density",
            "bridged_gap_ratio",
            "zone_revision_count",
        ],
        "primary_key": ["state_version_id", "event_id"],
        "row_count": 5647,
        "stable_multiset_sha256": (
            "4c0fcec9012fa46a7b68d3dd436e9e14881c44719f90def22490b8b6bc118acb"
        ),
        "source_run_id": "R2-T05-20260713T154957Z",
    },
    "membership": {
        "logical_table_name": "r2_canonical_event_membership",
        "fields": [
            "state_version_id",
            "event_id",
            "security_id",
            "trade_date",
            "confirmed_state",
            "component_member",
            "retrospective_component_member",
            "component_qualified_as_of",
            "event_zone_member",
            "is_prequalification_confirmed_day",
            "is_bridged_gap",
            "is_unqualified_reentry_day",
            "event_status_as_of",
            "zone_revision",
            "membership_available_time",
            "state_risk_set_eligible",
            "qualified_event_risk_set_eligible",
        ],
        "primary_key": ["state_version_id", "event_id", "security_id", "trade_date"],
        "row_count": 27388,
        "stable_multiset_sha256": (
            "5664a11fc7f4c61f3b6e8d4b0a465ed0d5c89447a38fc29cd12e966ab6340d0a"
        ),
        "source_run_id": "R2-T05-20260713T154957Z",
    },
}
MUTATION_CODES = {
    "M01": "FROZEN_STATE_VERSION_MISMATCH",
    "M02": "FROZEN_STATE_VERSION_SET_MISMATCH",
    "M03": "ANCHOR_DECISION_MISMATCH",
    "M04": "ANCHOR_DECISION_MISMATCH",
    "M05": "FIRST_ATTEMPT_ONLY_FORBIDDEN",
    "M06": "LAG_AFTER_FILTERING_FORBIDDEN",
    "M07": "LATER_ATTEMPT_RISK_SET_POLICY_MISMATCH",
    "M08": "POST_EVENT_FIELD_IN_ID",
    "M09": "CALENDAR_DAY_HORIZON_FORBIDDEN",
    "M10": "ATTEMPT_LEVEL_RANDOM_SPLIT_FORBIDDEN",
    "M11": "EVENT_SPLIT_LEAKAGE",
    "M12": "DOWNSTREAM_GATE_OPEN",
    "M13": "FUTURE_OUTCOME_IN_T01",
    "M14": "VALIDATOR_PRODUCTION_HELPER_REUSE",
    "M15": "MEMBERSHIP_AVAILABILITY_NOT_T0",
    "M16": "NON_PUBLIC_CANONICAL_FIELD_REFERENCE",
    "M17": "LANDMARK_CROSS_GROUP_CONTAMINATION",
    "M18": "EMPTY_MUTATION_RESULTS",
    "M19": "PENDING_FORMAL_ARTIFACT",
    "M20": "NON_AUTHORITATIVE_TIME_IN_ID",
    "M21": "MEMBERSHIP_LOOKAHEAD_LEAK",
    "M22": "MEMBERSHIP_DERIVED_PRIMARY_ID_FORBIDDEN",
    "M23": "CANONICAL_INTERFACE_PRIMARY_KEY_MISMATCH",
    "M24": "FINAL_VALIDATION_TAMPER_DETECTED",
}
FORBIDDEN_CANONICAL_FIELDS = (
    "component_qualification_" + "available_time",
    "g_used_as_of_exit",
    "daily.available_time",
    "evaluation_time",
    "raw_false_gap_ordinal_as_of",
    "raw_false_gap_count_as_of",
)
MUTATION_HEADER = [
    "mutation_id",
    "baseline_status",
    "mutation_applied",
    "expected_error_code",
    "actual_error_codes",
    "specific_error_detected",
    "unrelated_setup_failure",
    "status",
]
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


class ReplayValidationError(ValueError):
    """An independent replay failure with a stable error code."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        detail = f":{message}" if message else ""
        super().__init__(f"{code}{detail}")


@dataclass
class ValidationReport:
    errors: list[dict[str, str]] = field(default_factory=list)
    synthetic_case_results: list[dict[str, Any]] = field(default_factory=list)
    replay_results: list[dict[str, Any]] = field(default_factory=list)
    mutation_results: list[dict[str, Any]] = field(default_factory=list)
    double_rebuild_hash: str | None = None
    double_rebuild_result: dict[str, Any] | None = None
    artifact_summaries: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def add(self, code: str, message: str = "") -> None:
        self.errors.append({"code": code, "message": message})


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _committed_bytes(
    root: Path, source_commit: str, relative_path: str
) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{source_commit}:{relative_path}"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def _committed_git_blob_sha(
    root: Path, source_commit: str, relative_path: str
) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", f"{source_commit}:{relative_path}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _expected_row_present(row: dict[str, Any]) -> bool:
    return row.get("expected_row_present", True) is True


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ReplayValidationError("INVALID_TIME", str(value)) from exc
    if parsed.tzinfo is None:
        raise ReplayValidationError("TIMEZONE_REQUIRED", str(value))
    return parsed


def compare_timestamps(left: str, right: str) -> bool:
    """Compare absolute instants after independent ISO-8601 parsing."""

    try:
        return _parse_timestamp(left) <= _parse_timestamp(right)
    except ReplayValidationError:
        raise


def validate_timestamp_order(earlier: str, later: str) -> None:
    """Require a timezone-aware timestamp order and fail closed on inversion."""

    if not compare_timestamps(earlier, later):
        raise ReplayValidationError("TIME_ORDER_MISMATCH", f"{earlier}>{later}")


def _date_from_timestamp(value: str) -> str:
    return _parse_timestamp(value).date().isoformat()


def _row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("state_version_id", "")),
        str(row.get("security_id", "")),
        str(row.get("trade_date", "")),
    )


def _event_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("state_version_id", "")),
        str(row.get("event_id", "")),
    )


def _membership_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("state_version_id", "")),
        str(row.get("event_id", "")),
        str(row.get("security_id", "")),
        str(row.get("trade_date", "")),
    )


def _index(
    rows: list[dict[str, Any]], key_fn: Any, code: str
) -> dict[Any, dict[str, Any]]:
    result: dict[Any, dict[str, Any]] = {}
    for row in rows:
        key = key_fn(row)
        if key in result:
            raise ReplayValidationError(code, str(key))
        result[key] = row
    return result


def _sorted_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        _index(rows, _row_key, "DUPLICATE_EXPECTED_ROW").values(), key=_row_key
    )


def _group_surface(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("state_version_id")), str(row.get("security_id")))].append(
            row
        )
    for group in grouped.values():
        group.sort(key=_row_key)
    return grouped


def _identity(namespace: str, contract_version: str, fields: dict[str, str]) -> str:
    return _sha(
        {
            "namespace": namespace,
            "contract_version": contract_version,
            **fields,
        }
    )


def _replay_components(
    rows: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Independently rebuild causal runs without reading membership semantics."""
    surface = _sorted_surface(rows)
    zone_index = _index(zones, _event_key, "DUPLICATE_EVENT_ZONE")
    components: list[dict[str, Any]] = []
    first_component_seen: set[tuple[str, str, str]] = set()
    for group in _group_surface(surface).values():
        current: dict[str, Any] | None = None
        for row in group:
            event_id_value = row.get("active_event_id_as_of")
            event_id = str(event_id_value) if event_id_value is not None else ""
            zone = zone_index.get((str(row.get("state_version_id")), event_id))
            is_member = bool(
                _expected_row_present(row)
                and row.get("eligible_state") is True
                and row.get("quality_state") == "valid"
                and row.get("confirmed_state") is True
                and event_id
                and zone is not None
                and str(zone.get("security_id")) == str(row.get("security_id"))
            )
            if not is_member:
                current = None
                continue
            if current is None or current["event_id"] != event_id:
                event_key = (
                    str(row["state_version_id"]),
                    event_id,
                    str(row["security_id"]),
                )
                first = event_key not in first_component_seen
                if first:
                    first_component_seen.add(event_key)
                    start = str(zone.get("first_component_start_date", ""))
                    if not start:
                        raise ReplayValidationError(
                            "EVENT_ZONE_FIRST_COMPONENT_START_MISSING",
                            str(event_key),
                        )
                    try:
                        qualification_date = _date_from_timestamp(
                            str(zone["first_qualification_time"])
                        )
                    except (KeyError, ReplayValidationError) as exc:
                        raise ReplayValidationError(
                            "EVENT_ZONE_FIRST_QUALIFICATION_MISSING",
                            str(event_key),
                        ) from exc
                    qualified = True
                else:
                    start = str(row["trade_date"])
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
                    "start": start,
                    "end": str(row["trade_date"]),
                    "qualification_date": qualification_date,
                    "qualified": qualified,
                    "row_keys": [_row_key(row)],
                }
                components.append(current)
            else:
                current["end"] = str(row["trade_date"])
                if (
                    current["qualification_date"] is None
                    and row.get("component_qualified_as_of") is True
                ):
                    current["qualification_date"] = str(row["trade_date"])
                current["qualified"] = bool(
                    current["qualified"] or row.get("component_qualified_as_of") is True
                )
                current["row_keys"].append(_row_key(row))
    spec = config["analysis_unit_contract"]["source_component_id_spec"]
    version = str(config["contract_version"])
    for item in components:
        item["source_component_id"] = _identity(
            spec["namespace"],
            version,
            {
                "state_version_id": item["state_version_id"],
                "event_id": item["event_id"],
                "security_id": item["security_id"],
                "source_component_start_date": item["start"],
            },
        )
    event_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in components:
        event_groups[(item["state_version_id"], item["event_id"])].append(item)
    for group in event_groups.values():
        group.sort(key=lambda item: (item["start"], item["source_component_id"]))
        for ordinal, item in enumerate(group, 1):
            item["ordinal"] = ordinal
    return components


def _valid_transition(
    prior: dict[str, Any], current: dict[str, Any], transition: dict[str, Any]
) -> bool:
    prior_ok = bool(
        prior.get("eligible_state") is True
        and prior.get("quality_state") == "valid"
        and prior.get("confirmed_state") is True
        and prior.get("active_event_id_as_of")
        and prior.get("event_status_as_of") in transition["from_event_statuses"]
    )
    current_ok = bool(
        _expected_row_present(current)
        and current.get("eligible_state") is True
        and current.get("quality_state") == "valid"
        and current.get("raw_state") is False
        and current.get("confirmed_state") is False
    )
    return bool(
        prior_ok
        and current_ok
        and transition["from_state"] == "CONFIRMED_ACTIVE"
        and transition["to_state"] == "CONFIRMED_EXITED"
        and transition["trigger"] == "raw_false"
        and transition["hard_break"] is False
        and transition["reason_code"] == "natural_state_exit"
    )


def independent_replay(
    rows: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    membership_rows: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    sample_end_censoring: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rebuild natural exits on the full expected-row surface independently."""

    surface = _sorted_surface(rows)
    zone_index = _index(zones, _event_key, "DUPLICATE_EVENT_ZONE")
    membership_index = _index(
        membership_rows, _membership_key, "DUPLICATE_MEMBERSHIP_ROW"
    )
    components = _replay_components(surface, zones, config)
    component_by_row = {
        key: component for component in components for key in component["row_keys"]
    }
    state_versions = {
        item["state_version_id"]: item
        for item in config["frozen_inputs"]["state_versions"]
    }
    transition = config["t0_transition_contract"]["transition_registry"]
    attempts: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    for group in _group_surface(surface).values():
        for position in range(1, len(group)):
            prior = group[position - 1]
            current = group[position]
            key = list(_row_key(current))
            if not _expected_row_present(current):
                rejections.append(
                    {"row_key": key, "code": "CURRENT_EXPECTED_ROW_MISSING"}
                )
                continue
            if not _expected_row_present(prior):
                rejections.append(
                    {"row_key": key, "code": "PRIOR_EXPECTED_ROW_MISSING"}
                )
                continue
            if prior.get("active_event_id_as_of") is None:
                rejections.append({"row_key": key, "code": "PREQUALIFICATION_EXIT"})
                continue
            if (
                prior.get("eligible_state") is not True
                or prior.get("quality_state") != "valid"
            ):
                rejections.append({"row_key": key, "code": "PRIOR_ROW_NOT_ELIGIBLE"})
                continue
            if prior.get("confirmed_state") is not True:
                rejections.append({"row_key": key, "code": "PRIOR_NOT_CONFIRMED"})
                continue
            if current.get("eligible_state") is not True:
                rejections.append({"row_key": key, "code": "CURRENT_INELIGIBLE"})
                continue
            if current.get("quality_state") != "valid":
                rejections.append({"row_key": key, "code": "QUALITY_INTERRUPTION"})
                continue
            if current.get("raw_state") is None:
                rejections.append({"row_key": key, "code": "CURRENT_RAW_UNKNOWN"})
                continue
            if (
                current.get("raw_state") is not False
                or current.get("confirmed_state") is not False
            ):
                rejections.append({"row_key": key, "code": "NOT_NATURAL_STATE_EXIT"})
                continue
            event_id = str(prior["active_event_id_as_of"])
            if current.get("active_event_id_as_of") not in (None, event_id):
                rejections.append({"row_key": key, "code": "EVENT_ID_CONFLICT"})
                continue
            zone = zone_index.get((str(current["state_version_id"]), event_id))
            if zone is None or str(zone.get("security_id")) != str(
                current.get("security_id")
            ):
                rejections.append({"row_key": key, "code": "EVENT_NOT_FOUND"})
                continue
            try:
                if _date_from_timestamp(str(zone["first_qualification_time"])) > str(
                    current["trade_date"]
                ):
                    rejections.append({"row_key": key, "code": "EVENT_NOT_QUALIFIED"})
                    continue
            except ReplayValidationError as exc:
                rejections.append({"row_key": key, "code": exc.code})
                continue
            if not _valid_transition(prior, current, transition):
                rejections.append(
                    {"row_key": key, "code": "TRANSITION_NOT_NATURAL_STATE_EXIT"}
                )
                continue
            component = component_by_row.get(_row_key(prior))
            if component is None or component["event_id"] != event_id:
                rejections.append(
                    {"row_key": key, "code": "SOURCE_COMPONENT_NOT_FOUND"}
                )
                continue
            if component["start"] > str(current["trade_date"]):
                rejections.append(
                    {"row_key": key, "code": "SOURCE_COMPONENT_DATE_ORDER"}
                )
                continue
            if component["qualification_date"] is not None and not (
                component["start"]
                <= component["qualification_date"]
                <= str(current["trade_date"])
            ):
                rejections.append(
                    {"row_key": key, "code": "SOURCE_COMPONENT_DATE_ORDER"}
                )
                continue
            state_version_id = str(current["state_version_id"])
            if state_version_id not in state_versions:
                rejections.append(
                    {"row_key": key, "code": "FROZEN_STATE_VERSION_MISMATCH"}
                )
                continue
            membership = membership_index.get(
                (
                    state_version_id,
                    event_id,
                    str(current["security_id"]),
                    str(current["trade_date"]),
                )
            )
            prior_memberships = [
                item
                for item in membership_rows
                if str(item.get("state_version_id")) == state_version_id
                and str(item.get("event_id")) == event_id
                and str(item.get("security_id")) == str(current["security_id"])
                and str(item.get("trade_date")) < str(current["trade_date"])
            ]
            last_prior_membership = max(
                prior_memberships,
                key=lambda item: str(item.get("trade_date")),
                default=None,
            )
            qualified_count = sum(
                1
                for item in components
                if item["state_version_id"] == state_version_id
                and item["event_id"] == event_id
                and item["qualification_date"] is not None
                and item["qualification_date"] <= str(current["trade_date"])
            )
            spec = config["analysis_unit_contract"]["exit_attempt_id_spec"]
            attempt = {
                "state_version_id": state_version_id,
                "event_id": event_id,
                "security_id": str(current["security_id"]),
                "exit_attempt_id": _identity(
                    spec["namespace"],
                    str(config["contract_version"]),
                    {
                        "state_version_id": state_version_id,
                        "event_id": event_id,
                        "security_id": str(current["security_id"]),
                        "source_component_id": component["source_component_id"],
                        "exit_attempt_date": str(current["trade_date"]),
                    },
                ),
                "source_component_id": component["source_component_id"],
                "source_component_start_date": component["start"],
                "source_component_end_date": component["end"],
                "source_component_qualification_date": component["qualification_date"],
                "source_component_qualified": component["qualified"],
                "source_component_ordinal": component["ordinal"],
                "component_count_as_of_exit": qualified_count,
                "frozen_g": state_versions[state_version_id]["g"],
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
                    membership.get("membership_available_time") if membership else None
                ),
                "current_membership_availability_is_causal_for_t0": False,
                "membership_resolution_status": (
                    "current_row_not_available"
                    if membership is None
                    else (
                        "current_row_available"
                        if membership.get("membership_available_time")
                        else "current_row_available_time_missing"
                    )
                ),
                "unqualified_reentry": not component["qualified"],
                "attempt_weight": 1.0,
            }
            attempts.append(attempt)
        if sample_end_censoring and group:
            last = group[-1]
            if last.get("confirmed_state") is True and last.get(
                "active_event_id_as_of"
            ):
                rejections.append(
                    {"row_key": list(_row_key(last)), "code": "RIGHT_CENSORING"}
                )
    ids = [item["exit_attempt_id"] for item in attempts]
    if len(ids) != len(set(ids)):
        raise ReplayValidationError("DUPLICATE_EXIT_ATTEMPT_ID")
    attempts.sort(
        key=lambda item: (
            item["state_version_id"],
            item["event_id"],
            item["exit_attempt_date"],
            item["exit_attempt_id"],
        )
    )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        grouped[(attempt["state_version_id"], attempt["event_id"])].append(attempt)
    for group in grouped.values():
        for ordinal, attempt in enumerate(group, 1):
            attempt["exit_attempt_ordinal"] = ordinal
    return attempts, rejections


def _valid_landmark_row(row: dict[str, Any]) -> bool:
    return bool(
        _expected_row_present(row)
        and row.get("eligible_state") is True
        and row.get("quality_state") == "valid"
    )


def build_independent_landmarks(
    rows: list[dict[str, Any]],
    *,
    state_version_id: str,
    security_id: str,
    t0_date: str,
    horizon_days: tuple[int, ...] = (5, 10, 20, 30),
) -> dict[str, Any]:
    """Independently construct T1/T2 and H endpoints for one entity."""

    scoped = sorted(
        [
            row
            for row in rows
            if str(row.get("state_version_id")) == state_version_id
            and str(row.get("security_id")) == security_id
        ],
        key=_row_key,
    )
    future = [row for row in scoped if str(row.get("trade_date", "")) > t0_date]
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
                found = row
                break
            reasons.add(_unobservable_reason(row))
        result[f"T{target}"] = {
            "landmark_id": f"T{target}",
            "available": found is not None,
            "trade_date": found["trade_date"] if found else None,
            "ordinal": target if found else None,
            "intervening_unobservable_row_count": sum(
                not _valid_landmark_row(item) for item in future[:consumed]
            ),
            "intervening_unobservable_reason_set": sorted(reasons),
            "landmark_unavailable_reason": (
                None if found else "INSUFFICIENT_VALID_EXPECTED_ROWS"
            ),
        }
    for horizon in horizon_days:
        found = valid_rows[horizon - 1] if len(valid_rows) >= horizon else None
        result[f"H{horizon}"] = {
            "horizon_id": f"H{horizon}",
            "valid_expected_row_count": horizon if found else len(valid_rows),
            "available": found is not None,
            "trade_date": found["trade_date"] if found else None,
            "unavailable_reason": None if found else "INSUFFICIENT_VALID_EXPECTED_ROWS",
        }
    return result


def _unobservable_reason(row: dict[str, Any]) -> str:
    if not _expected_row_present(row):
        return "MISSING_EXPECTED_TRADING_ROW"
    if row.get("eligible_state") is not True:
        return "INELIGIBLE_STATE"
    if row.get("quality_state") != "valid":
        return "QUALITY_NOT_VALID"
    return "UNOBSERVABLE"


def _schema_has_closed_objects(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        if (
            value.get("type") == "object"
            and value.get("additionalProperties") is not False
        ):
            errors.append(path)
        for key, child in value.items():
            errors.extend(_schema_has_closed_objects(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_schema_has_closed_objects(child, f"{path}[{index}]"))
    return errors


def _validate_schema(
    report: ValidationReport, schema_path: Path, value: Any, label: str
) -> None:
    try:
        schema = _load_json(schema_path)
        closed = _schema_has_closed_objects(schema)
        if closed:
            report.add("SCHEMA_NOT_CLOSED", f"{schema_path}:{closed[0]}")
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                value
            ),
            key=lambda item: str(item.path),
        )
        for error in errors:
            report.add("SCHEMA_VALIDATION_FAILED", f"{label}:{error.message}")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        report.add("SCHEMA_READ_FAILED", f"{label}:{exc}")


def _compare_canonical_interface(
    label: str,
    actual: Any,
    expected: dict[str, Any],
    report: ValidationReport,
    *,
    compare_fields: bool = True,
) -> None:
    if not isinstance(actual, dict):
        report.add("CANONICAL_INTERFACE_TABLE_SET_MISMATCH", label)
        return
    if actual.get("logical_table_name") != expected["logical_table_name"]:
        report.add("CANONICAL_INTERFACE_TABLE_SET_MISMATCH", label)
    if compare_fields and (
        set(actual.get("fields", [])) != set(expected["fields"])
        or len(actual.get("fields", [])) != len(expected["fields"])
    ):
        report.add("CANONICAL_INTERFACE_FIELD_SET_MISMATCH", label)
    if actual.get("primary_key") != expected["primary_key"]:
        report.add("CANONICAL_INTERFACE_PRIMARY_KEY_MISMATCH", label)
    if actual.get("row_count") != expected["row_count"]:
        report.add("CANONICAL_INTERFACE_ROW_COUNT_MISMATCH", label)
    if actual.get("stable_multiset_sha256") != expected["stable_multiset_sha256"]:
        report.add("CANONICAL_INTERFACE_HASH_MISMATCH", label)
    if actual.get("source_run_id") != expected["source_run_id"]:
        report.add("CANONICAL_INTERFACE_SOURCE_RUN_MISMATCH", label)


def _check_public_interface(
    config: dict[str, Any],
    fixture: dict[str, Any],
    root: Path,
    report: ValidationReport,
) -> None:
    expected = EXPECTED_CANONICAL_INTERFACES
    expected_by_name = {item["logical_table_name"]: item for item in expected.values()}
    public = config.get("canonical_public_interface_contract", {})
    public_tables = public.get("tables", [])
    public_names = {
        item.get("logical_table_name")
        for item in public_tables
        if isinstance(item, dict)
    }
    if public_names != set(expected_by_name) or len(public_tables) != len(
        expected_by_name
    ):
        report.add("CANONICAL_INTERFACE_TABLE_SET_MISMATCH", "public")
    for item in public_tables:
        if not isinstance(item, dict):
            report.add("CANONICAL_INTERFACE_TABLE_SET_MISMATCH", "public_entry")
            continue
        expected_item = expected_by_name.get(item.get("logical_table_name"))
        if expected_item is None:
            continue
        _compare_canonical_interface(
            str(item["logical_table_name"]), item, expected_item, report
        )
    harness = set(public.get("synthetic_harness_only_fields", []))
    if harness != {"expected_row_present"}:
        report.add(
            "CANONICAL_INTERFACE_FIELD_SET_MISMATCH", "synthetic_harness_only_fields"
        )
    table_map = public.get("fixture_table_map", {})
    for case in fixture.get("cases", []):
        for fixture_key, table_name in table_map.items():
            expected_item = expected_by_name.get(table_name)
            allowed = set(expected_item["fields"] if expected_item else ()) | harness
            for row in case.get(fixture_key, []):
                for field_name in row:
                    if field_name not in allowed:
                        report.add(
                            "NON_PUBLIC_CANONICAL_FIELD_REFERENCE"
                            if field_name in FORBIDDEN_CANONICAL_FIELDS
                            else "CANONICAL_INTERFACE_FIELD_SET_MISMATCH",
                            f"{case.get('case_id')}:{fixture_key}:{field_name}",
                        )

    frozen = {
        item.get("logical_table_name"): item
        for item in config.get("frozen_inputs", {}).get("canonical_interfaces", [])
        if isinstance(item, dict)
    }
    for expected_item in expected.values():
        _compare_canonical_interface(
            expected_item["logical_table_name"],
            frozen.get(expected_item["logical_table_name"]),
            expected_item,
            report,
            compare_fields=False,
        )
    authority = config.get("canonical_interface_authority", {})
    authority_interfaces = authority.get("interfaces", {})
    for key, expected_item in expected.items():
        _compare_canonical_interface(
            f"authority:{key}",
            authority_interfaces.get(key),
            expected_item,
            report,
        )
    source = authority.get("source_artifact", {})
    committed = _committed_bytes(
        root, str(source.get("source_commit")), str(source.get("path"))
    )
    if committed is None:
        report.add("CANONICAL_INTERFACE_SOURCE_RUN_MISMATCH", "authority_blob")
    else:
        try:
            payload = json.loads(committed.decode("utf-8"))
            upstream_interfaces = payload.get("interfaces", {})
            for key, expected_item in expected.items():
                _compare_canonical_interface(
                    f"upstream:{key}",
                    upstream_interfaces.get(key),
                    expected_item,
                    report,
                    compare_fields=False,
                )
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            report.add("CANONICAL_INTERFACE_SOURCE_RUN_MISMATCH", "authority_json")

    config_text = json.dumps(config, ensure_ascii=False, sort_keys=True)
    source_text = (root / "src/r3/r3_t01_protocol.py").read_text(encoding="utf-8")
    schema_text = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in (
            "schemas/r3/r3_t01_protocol_registry.schema.json",
            "schemas/r3/r3_t01_exit_attempt_contract.schema.json",
            "schemas/r3/r3_t01_landmark_horizon_contract.schema.json",
            "schemas/r3/r3_t01_sample_split_contract.schema.json",
        )
    )
    for forbidden in FORBIDDEN_CANONICAL_FIELDS:
        if (
            forbidden in config_text
            or forbidden in source_text
            or forbidden in schema_text
        ):
            report.add("NON_PUBLIC_CANONICAL_FIELD_REFERENCE", forbidden)


def _check_exact_contract_values(
    config: dict[str, Any], fixture: dict[str, Any], report: ValidationReport
) -> None:
    versions = config.get("frozen_inputs", {}).get("state_versions", [])
    actual_ids = tuple(item.get("state_version_id") for item in versions)
    if actual_ids != EXPECTED_STATE_VERSIONS:
        report.add(
            "FROZEN_STATE_VERSION_SET_MISMATCH"
            if len(versions) != 2
            else "FROZEN_STATE_VERSION_MISMATCH",
            repr(actual_ids),
        )
    parameters = config.get("frozen_inputs", {}).get("parameters", {})
    if parameters != {"W": 120, "K": 3, "d": 2, "g": 1}:
        report.add("FROZEN_STATE_VERSION_SET_MISMATCH", "frozen_parameters")
    if (
        config.get("anchor_decision", {}).get("selected_anchor")
        != "natural_exit_attempt"
    ):
        report.add("ANCHOR_DECISION_MISMATCH")
    unit = config.get("analysis_unit_contract", {})
    id_spec = unit.get("exit_attempt_id_spec", {})
    exact_id_fields = [
        "namespace",
        "contract_version",
        "state_version_id",
        "event_id",
        "security_id",
        "source_component_id",
        "exit_attempt_date",
    ]
    if id_spec.get("namespace") != "r3_exit_attempt_v3":
        report.add("EXIT_ATTEMPT_ID_NAMESPACE_MISMATCH")
    if unit.get("source_component_id_namespace") != "r3_causal_confirmed_run_v2":
        report.add("SOURCE_COMPONENT_ID_NAMESPACE_MISMATCH")
    source_definition = str(unit.get("source_component_definition", ""))
    if (
        "membership_available_time" in source_definition
        or "retrospective" in source_definition
    ):
        report.add("MEMBERSHIP_LOOKAHEAD_LEAK")
    source_id_fields = set(unit.get("source_component_id_spec", {}).get("fields", []))
    if source_id_fields.intersection(
        {
            "retrospective_component_member",
            "membership_row_id",
            "membership_available_time",
        }
    ):
        report.add("MEMBERSHIP_DERIVED_PRIMARY_ID_FORBIDDEN")
    if id_spec.get("fields") != exact_id_fields:
        fields = set(id_spec.get("fields", []))
        if "exit_attempt_time" in fields:
            report.add("NON_AUTHORITATIVE_TIME_IN_ID")
        elif fields.intersection(
            {"zone_finalization_time", "final_component_count", "future_path"}
        ):
            report.add("POST_EVENT_FIELD_IN_ID")
        else:
            report.add("EXIT_ATTEMPT_ID_FIELD_SET_MISMATCH")
    if unit.get("first_attempt_only") is True:
        report.add("FIRST_ATTEMPT_ONLY_FORBIDDEN")
    if unit.get("later_attempts_are_sidecar") is True:
        report.add("LATER_ATTEMPTS_SIDEcar_FORBIDDEN")
    t0 = config.get("t0_transition_contract", {})
    if t0.get("expected_row_surface_lag") != (
        "compute_lag_on_complete_expected_row_surface_before_filter"
    ):
        report.add("LAG_AFTER_FILTERING_FORBIDDEN")
    if (
        t0.get("qualified_event_risk_set_eligible_required_for_every_later_attempt")
        is True
    ):
        report.add("LATER_ATTEMPT_RISK_SET_POLICY_MISMATCH")
    if unit.get("exit_attempt_ordinal_order") != [
        "exit_attempt_date",
        "exit_attempt_id",
    ]:
        report.add("ORDINAL_DATE_ORDER_MISMATCH")
    if "exit_attempt_time" not in set(
        unit.get("attempt_identity_must_not_include", [])
    ):
        report.add("NON_AUTHORITATIVE_TIME_IN_ID")
    time_fields = t0.get("time_fields", {})
    if time_fields.get("exit_attempt_time") != "null_upstream_interface_gap":
        report.add("MEMBERSHIP_AVAILABILITY_NOT_T0")
    if (
        time_fields.get("exit_attempt_date") != "current_trade_date"
        or time_fields.get("exit_attempt_date_authoritative") is not True
    ):
        report.add("T0_DATE_NOT_AUTHORITATIVE")
    if time_fields.get("t0_granularity") != "valid_trading_date":
        report.add("T0_GRANULARITY_MISMATCH")
    if "current_membership_row_is_optional_for_t0" not in t0.get(
        "event_join_requirements", []
    ):
        report.add("MEMBERSHIP_AVAILABILITY_NOT_T0")
    if config.get("landmark_horizon_contract", {}).get(
        "future_landmark_definition", {}
    ).get("group_keys") != ["state_version_id", "security_id"]:
        report.add("LANDMARK_CROSS_GROUP_CONTAMINATION")
    if config.get("sample_split_contract", {}).get("sample_split_unit") != "event_id":
        report.add("ATTEMPT_LEVEL_RANDOM_SPLIT_FORBIDDEN")
    if (
        config.get("sample_split_contract", {}).get(
            "all_attempts_of_same_event_in_same_split"
        )
        is not True
    ):
        report.add("EVENT_SPLIT_LEAKAGE")
    if (
        config.get("sample_split_contract", {})
        .get("purge_embargo", {})
        .get("length_valid_trading_days")
        != 32
    ):
        report.add("PURGE_EMBARGO_MISMATCH")
    if (
        config.get("sample_split_contract", {}).get("calendar_boundary_status")
        != "unselected_by_design"
    ):
        report.add("CALENDAR_BOUNDARY_SELECTED_TOO_EARLY")
    if fixture.get("split_assignments_mutation") or fixture.get("split_unit_mutation"):
        report.add(
            "EVENT_SPLIT_LEAKAGE"
            if fixture.get("split_assignments_mutation")
            else "ATTEMPT_LEVEL_RANDOM_SPLIT_FORBIDDEN"
        )
    if fixture.get("first_attempt_only_mutation"):
        report.add("FIRST_ATTEMPT_ONLY_FORBIDDEN")
    if fixture.get("downstream_gate_mutation"):
        report.add("DOWNSTREAM_GATE_OPEN")
    if "calendar-day" in config.get("landmark_horizon_contract", {}).get(
        "horizon_counting_rule", ""
    ):
        report.add("CALENDAR_DAY_HORIZON_FORBIDDEN")
    if config.get("implementation_state", {}).get("next_task_allowed") is True:
        report.add("DOWNSTREAM_GATE_OPEN")
    if config.get("output_contract", {}).get("formal_artifacts"):
        owners = {
            item.get("artifact_owner")
            for item in config["output_contract"]["formal_artifacts"]
        }
        if owners != {
            "runner",
            "independent_validator",
            "result_analyzer",
            "final_validator",
        }:
            report.add("FORMAL_ARTIFACT_OWNER_MISMATCH")
    for field_spec in config.get("field_semantics", []):
        if field_spec.get("field_name") == "return_from_t0":
            report.add("FUTURE_OUTCOME_IN_T01")


def _check_field_semantics(config: dict[str, Any], report: ValidationReport) -> None:
    field_semantics = config.get("field_semantics", [])
    fields = {
        item.get("field_name"): item
        for item in field_semantics
        if isinstance(item, dict)
    }
    field_name_counts: dict[str, int] = {}
    for item in field_semantics:
        if isinstance(item, dict) and isinstance(item.get("field_name"), str):
            name = item["field_name"]
            field_name_counts[name] = field_name_counts.get(name, 0) + 1
    for name in sorted(name for name, count in field_name_counts.items() if count > 1):
        report.add("DUPLICATE_FIELD_SEMANTICS", name)

    registered_fields = set(field_name_counts)
    for name in sorted(EXPECTED_ATTEMPT_OUTPUT_FIELDS - registered_fields):
        report.add("ATTEMPT_FIELD_SEMANTICS_MISSING", name)

    qualified_field = fields.get("source_component_qualified")
    qualified_available_time = str(
        qualified_field.get("available_time_source", "") if qualified_field else ""
    )
    qualified_source_artifact = (
        qualified_field.get("source_artifact") if qualified_field else None
    )
    if (
        qualified_source_artifact
        != "r2_canonical_daily_state + r2_canonical_event_zone"
        or "membership" in qualified_available_time.lower()
        or "r2_canonical_event_membership" in qualified_available_time.lower()
    ):
        report.add("FIELD_SEMANTICS_LINEAGE_MISMATCH", "source_component_qualified")

    required = {
        "state_version_id",
        "event_id",
        "security_id",
        "exit_attempt_id",
        "exit_attempt_ordinal",
        "source_component_id",
        "source_component_ordinal",
        "source_component_qualification_date",
        "source_component_qualified",
        "component_count_as_of_exit",
        "last_observed_zone_revision_before_exit",
        "current_exit_membership_zone_revision",
        "exit_attempt_date",
        "exit_attempt_time",
        "exit_attempt_time_missing_reason",
        "frozen_g",
        "event_status_as_of_exit",
        "current_membership_row_present",
        "current_membership_available_time",
        "current_membership_availability_is_causal_for_t0",
        "membership_resolution_status",
    }
    for name in required:
        if name not in fields:
            report.add("FIELD_SEMANTICS_MISSING", name)
    time_field = fields.get("exit_attempt_time")
    if (
        time_field is None
        or time_field.get("nullable") is not True
        or time_field.get("availability_class") != "upstream_interface_required"
        or time_field.get("allowed_at_T0") is not False
    ):
        report.add("MEMBERSHIP_AVAILABILITY_NOT_T0", "exit_attempt_time")
    for forbidden in ("g_used_as_of_exit", "zone_revision_as_of_exit"):
        if forbidden in fields:
            report.add("NON_PUBLIC_CANONICAL_FIELD_REFERENCE", forbidden)
    for name in (
        "last_observed_zone_revision_before_exit",
        "current_exit_membership_zone_revision",
        "current_membership_row_present",
        "current_membership_available_time",
        "current_membership_availability_is_causal_for_t0",
        "membership_resolution_status",
    ):
        item = fields.get(name)
        if item and (
            item.get("allowed_at_T0") or not item.get("forbidden_model_feature")
        ):
            report.add("POST_EVENT_AUDIT_FIELD_LEAK", name)
    for item in fields.values():
        if item.get("availability_class") == "as_of_T0" and any(
            token in str(item.get("field_name", "")).lower()
            for token in ("return", "mfe", "mae", "boundary", "path", "label")
        ):
            report.add("FUTURE_OUTCOME_IN_T01", str(item.get("field_name")))


def _check_no_future_output(config: dict[str, Any], report: ValidationReport) -> None:
    for artifact in config.get("output_contract", {}).get("formal_artifacts", []):
        name = str(artifact.get("filename", "")).lower()
        if artifact.get("contains_future_outcome") is not False or any(
            token in name for token in ("return", "label", "boundary", "path_class")
        ):
            report.add("FUTURE_OUTCOME_IN_T01", name)


def _check_upstream_committed_bindings(
    config: dict[str, Any], report: ValidationReport, root: Path
) -> None:
    binding = config["upstream_binding"]
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if head.returncode != 0:
        report.add("GIT_HEAD_UNAVAILABLE")
        return
    for commit in (binding["r2_t08_merge_commit"], binding["gov_t02_merge_commit"]):
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, head.stdout.strip()],
            cwd=root,
            check=False,
        )
        if result.returncode != 0:
            report.add("UPSTREAM_ANCESTRY_MISMATCH", commit)
    result = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            binding["r2_t08_reviewed_head"],
            binding["r2_t08_merge_commit"],
        ],
        cwd=root,
        check=False,
    )
    if result.returncode != 0:
        report.add("REVIEWED_HEAD_NOT_ANCESTOR")
    for artifact in binding["required_artifacts"]:
        result = subprocess.run(
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
        if result.returncode != 0:
            report.add("UPSTREAM_BLOB_MISSING", artifact["path"])
        elif _sha_bytes(result.stdout) != artifact["committed_byte_sha256"]:
            report.add("UPSTREAM_ARTIFACT_HASH_MISMATCH", artifact["path"])
        elif artifact["committed_byte_sha256"] != EXPECTED_ARTIFACT_HASHES.get(
            artifact["name"]
        ):
            report.add("UPSTREAM_EXPECTED_HASH_MISMATCH", artifact["name"])
    validation = binding["committed_artifact_validation"]
    result = subprocess.run(
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
    if result.returncode != 0:
        report.add("UPSTREAM_VALIDATION_BLOB_MISSING")
    else:
        try:
            payload = json.loads(result.stdout.decode("utf-8"))
            if payload.get("status") != validation["required_status"]:
                report.add("UPSTREAM_COMMITTED_VALIDATION_STATUS_MISMATCH")
            if payload.get("failure_count") != validation["required_failure_count"]:
                report.add("UPSTREAM_COMMITTED_VALIDATION_FAILURES")
        except (UnicodeDecodeError, json.JSONDecodeError):
            report.add("UPSTREAM_VALIDATION_JSON_INVALID")


def _compare_landmark_dict(
    expected: dict[str, Any],
    actual: dict[str, Any],
    case_id: str,
    report: ValidationReport,
) -> None:
    for key in ("T1", "T2"):
        if expected.get(key) != actual.get(key):
            report.add("SYNTHETIC_LANDMARK_MISMATCH", f"{case_id}:{key}")
    for key in ("H5", "H10", "H20", "H30"):
        if expected.get(key) != actual.get(key):
            report.add("SYNTHETIC_HORIZON_MISMATCH", f"{case_id}:{key}")


def _compare_case(
    case: dict[str, Any],
    attempts: list[dict[str, Any]],
    rejections: list[dict[str, Any]],
    landmarks: dict[str, Any],
    report: ValidationReport,
) -> dict[str, Any]:
    expected = case.get("expected", {})
    expected_ids = [
        item.get("exit_attempt_id")
        for item in expected.get("attempts", [])
        if item.get("exit_attempt_id") is not None
    ]
    actual_ids = [item["exit_attempt_id"] for item in attempts]
    if expected_ids and expected_ids != actual_ids:
        report.add("SYNTHETIC_ATTEMPT_ID_MISMATCH", case["case_id"])
    if expected.get("attempt_count") != len(attempts):
        report.add("SYNTHETIC_ATTEMPT_COUNT_MISMATCH", case["case_id"])
    if "rejection_codes" in expected:
        expected_codes = sorted(expected.get("rejection_codes", []))
        actual_codes = sorted(item["code"] for item in rejections)
        if expected_codes != actual_codes:
            report.add("SYNTHETIC_REJECTION_MISMATCH", case["case_id"])
    else:
        actual_codes = sorted(item["code"] for item in rejections)
    for expected_attempt, actual in zip(
        expected.get("attempts", []), attempts, strict=False
    ):
        for key in (
            "state_version_id",
            "event_id",
            "security_id",
            "exit_attempt_date",
            "source_component_ordinal",
            "component_count_as_of_exit",
            "source_component_qualification_date",
            "source_component_qualified",
            "unqualified_reentry",
            "exit_attempt_ordinal",
            "source_component_id",
        ):
            if expected_attempt.get(key) is not None and expected_attempt.get(
                key
            ) != actual.get(key):
                report.add("SYNTHETIC_CONTEXT_MISMATCH", f"{case['case_id']}:{key}")
    expected_landmarks = case.get("expected_landmarks", {})
    for attempt_id, expected_landmark in expected_landmarks.items():
        actual_landmark = landmarks.get(attempt_id)
        if actual_landmark is None:
            report.add("SYNTHETIC_LANDMARK_MISMATCH", f"{case['case_id']}:{attempt_id}")
        else:
            _compare_landmark_dict(
                expected_landmark, actual_landmark, case["case_id"], report
            )
    return {
        "case_id": case["case_id"],
        "expected_attempt_count": expected.get("attempt_count"),
        "actual_attempt_count": len(attempts),
        "expected_attempt_ids": expected_ids,
        "actual_attempt_ids": actual_ids,
        "rejection_codes": actual_codes,
        "attempts": attempts,
        "rejections": rejections,
        "landmarks": landmarks,
    }


def validate_independence(source_text: str) -> str | None:
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return "VALIDATOR_SOURCE_INVALID"
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "src.r3.r3_t01_protocol":
            return "VALIDATOR_PRODUCTION_HELPER_REUSE"
        if isinstance(node, ast.Import) and any(
            alias.name == "src.r3.r3_t01_protocol" for alias in node.names
        ):
            return "VALIDATOR_PRODUCTION_HELPER_REUSE"
    return None


def validate_attempt_registry(attempts: list[dict[str, Any]]) -> list[str]:
    """Check duplicate identity, date ordinal conservation, and T0 claims."""

    errors: list[str] = []
    ids = [str(item.get("exit_attempt_id")) for item in attempts]
    if len(ids) != len(set(ids)):
        errors.append("DUPLICATE_EXIT_ATTEMPT_ID")
    by_event: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    t0_claims: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for item in attempts:
        key = (str(item.get("state_version_id")), str(item.get("event_id")))
        by_event[key].append(item)
        t0_claims[
            (
                str(item.get("state_version_id")),
                str(item.get("security_id")),
                str(item.get("exit_attempt_date")),
            )
        ].add(str(item.get("event_id")))
    if any(len(events) > 1 for events in t0_claims.values()):
        errors.append("T0_CLAIMED_BY_MULTIPLE_EVENTS")
    for group in by_event.values():
        ordered = sorted(
            group,
            key=lambda item: (
                str(item.get("exit_attempt_date")),
                str(item.get("exit_attempt_id")),
            ),
        )
        expected = list(range(1, len(group) + 1))
        actual = [int(item.get("exit_attempt_ordinal", -1)) for item in group]
        if sorted(actual) != expected:
            errors.append("ORDINAL_NOT_CONTIGUOUS")
        if actual != [int(item.get("exit_attempt_ordinal", -1)) for item in ordered]:
            errors.append("ORDINAL_DATE_ORDER_MISMATCH")
    return sorted(set(errors))


def _check_contract_mutation_markers(
    config: dict[str, Any], fixture: dict[str, Any], report: ValidationReport
) -> None:
    _check_exact_contract_values(config, fixture, report)


def apply_mutation(
    config: dict[str, Any], fixture: dict[str, Any], mutation_id: str
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    mutated_config = copy.deepcopy(config)
    mutated_fixture = copy.deepcopy(fixture)
    source_text: str | None = None
    if mutation_id == "M01":
        mutated_config["frozen_inputs"]["state_versions"][0]["state_version_id"] = (
            "mutated"
        )
    elif mutation_id == "M02":
        mutated_config["frozen_inputs"]["parameters"]["W"] = 250
    elif mutation_id in {"M03", "M04"}:
        mutated_config["anchor_decision"]["selected_anchor"] = (
            "finalized_zone" if mutation_id == "M03" else "retrospective_final_exit"
        )
    elif mutation_id == "M05":
        mutated_fixture["first_attempt_only_mutation"] = True
    elif mutation_id == "M06":
        mutated_config["t0_transition_contract"]["expected_row_surface_lag"] = (
            "filter_invalid_then_lag"
        )
    elif mutation_id == "M07":
        mutated_config["t0_transition_contract"][
            "qualified_event_risk_set_eligible_required_for_every_later_attempt"
        ] = True
    elif mutation_id == "M08":
        mutated_config["analysis_unit_contract"]["exit_attempt_id_spec"][
            "fields"
        ].append("zone_finalization_time")
    elif mutation_id == "M09":
        mutated_config["landmark_horizon_contract"]["horizon_counting_rule"] = (
            "calendar-day counting"
        )
    elif mutation_id == "M10":
        mutated_fixture["split_unit_mutation"] = "exit_attempt_id"
    elif mutation_id == "M11":
        mutated_fixture["split_assignments_mutation"] = {
            "EV1": ["design", "validation"]
        }
    elif mutation_id == "M12":
        mutated_fixture["downstream_gate_mutation"] = True
    elif mutation_id == "M13":
        mutated_config["field_semantics"].append(
            {
                "field_name": "return_from_t0",
                "type": "number",
                "nullable": True,
                "availability_class": "as_of_T0",
                "available_time_source": "future",
                "allowed_at_T0": True,
                "allowed_at_T1": False,
                "allowed_at_T2": False,
                "audit_only": False,
                "forbidden_model_feature": False,
                "source_artifact": "future",
                "derivation_rule": "future return",
            }
        )
    elif mutation_id == "M14":
        source_text = "from src.r3.r3_t01_protocol import enumerate_exit_attempts"
    elif mutation_id == "M15":
        mutated_config["t0_transition_contract"]["time_fields"]["exit_attempt_time"] = (
            "current_membership.membership_available_time"
        )
    elif mutation_id == "M16":
        forbidden_field = "component_qualification_" + "available_time"
        target = next(
            case for case in mutated_fixture["cases"] if case["case_id"] == "S01"
        )
        target["membership_rows"][0][forbidden_field] = None
    elif mutation_id == "M17":
        mutated_config["landmark_horizon_contract"]["future_landmark_definition"][
            "group_keys"
        ] = ["trade_date"]
    elif mutation_id == "M18":
        mutated_fixture["formal_artifact_mutation"] = "empty_mutation_results"
    elif mutation_id == "M19":
        mutated_fixture["formal_artifact_mutation"] = "pending_formal_artifact"
    elif mutation_id == "M20":
        mutated_config["analysis_unit_contract"]["exit_attempt_id_spec"][
            "fields"
        ].append("exit_attempt_time")
    elif mutation_id == "M21":
        mutated_config["analysis_unit_contract"]["source_component_definition"] = (
            "reconstruct source components from retrospective membership rows and "
            "membership_available_time"
        )
    elif mutation_id == "M22":
        mutated_config["analysis_unit_contract"]["source_component_id_spec"][
            "fields"
        ].append("retrospective_component_member")
    elif mutation_id == "M23":
        event_table = next(
            item
            for item in mutated_config["canonical_public_interface_contract"]["tables"]
            if item["logical_table_name"] == "r2_canonical_event_zone"
        )
        event_table["primary_key"] = ["state_version_id", "event_id", "security_id"]
    elif mutation_id == "M24":
        mutated_fixture["formal_artifact_mutation"] = "post_manifest_tamper"
    else:
        raise ValueError(mutation_id)
    return mutated_config, mutated_fixture, source_text


def _artifact_marker_error(fixture: dict[str, Any]) -> str | None:
    if fixture.get("formal_artifact_mutation") == "empty_mutation_results":
        return "EMPTY_MUTATION_RESULTS"
    if fixture.get("formal_artifact_mutation") == "pending_formal_artifact":
        return "PENDING_FORMAL_ARTIFACT"
    if fixture.get("formal_artifact_mutation") == "post_manifest_tamper":
        return "FINAL_VALIDATION_TAMPER_DETECTED"
    return None


def _mutation_result(
    mutation_id: str,
    baseline_status: str,
    expected_code: str,
    actual_codes: list[str],
) -> dict[str, Any]:
    specific = expected_code in actual_codes
    related_codes = {
        "SCHEMA_VALIDATION_FAILED",
        "SYNTHETIC_ATTEMPT_COUNT_MISMATCH",
        "SYNTHETIC_ATTEMPT_ID_MISMATCH",
        "SYNTHETIC_REJECTION_MISMATCH",
        "SYNTHETIC_CONTEXT_MISMATCH",
        "FINAL_VALIDATION_ARTIFACT_HASH_MISMATCH",
        "FINAL_VALIDATION_ARTIFACT_SIZE_MISMATCH",
        "FINAL_VALIDATION_ARTIFACT_ROW_COUNT_MISMATCH",
    }
    unrelated = any(
        code != expected_code and code not in related_codes for code in actual_codes
    )
    return {
        "mutation_id": mutation_id,
        "baseline_status": baseline_status,
        "mutation_applied": True,
        "expected_error_code": expected_code,
        "actual_error_codes": actual_codes,
        "specific_error_detected": specific,
        "unrelated_setup_failure": unrelated,
        "status": "passed"
        if baseline_status == "passed" and specific and not unrelated
        else "failed",
    }


def validate_mutations(
    config: dict[str, Any], fixture: dict[str, Any]
) -> list[dict[str, Any]]:
    """Run mutations from temporary pristine files through the disk validator path."""

    with TemporaryDirectory(prefix="r3_t01_mutations_") as temp_dir:
        directory = Path(temp_dir)
        config_path = directory / "config.json"
        fixture_path = directory / "fixture.json"
        write_json(config_path, config)
        write_json(fixture_path, fixture)
        return validate_mutations_from_disk(config_path, fixture_path, root=ROOT)


def _artifact_kind_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["filename"]: item for item in config["output_contract"]["formal_artifacts"]
    }


def _csv_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        first = handle.readline().rstrip("\n\r")
    return first.split(",") if first else []


def _artifact_schema_path(name: str, root: Path) -> Path | None:
    mapping = {
        "r3_t01_protocol_registry.json": (
            "schemas/r3/r3_t01_protocol_registry.schema.json"
        ),
        "r3_t01_t0_transition_contract.json": (
            "schemas/r3/r3_t01_exit_attempt_contract.schema.json"
        ),
        "r3_t01_landmark_horizon_contract.json": (
            "schemas/r3/r3_t01_landmark_horizon_contract.schema.json"
        ),
        "r3_t01_sample_split_contract.json": (
            "schemas/r3/r3_t01_sample_split_contract.schema.json"
        ),
    }
    relative = mapping.get(name)
    return root / relative if relative else None


def _status_is_pending(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            (key == "status" and item in {"pending", "pending_validator"})
            or _status_is_pending(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_status_is_pending(item) for item in value)
    return False


def _actual_artifact_schema_errors(
    name: str, value: Any, root: Path
) -> list[dict[str, str]]:
    schema_path = _artifact_schema_path(name, root)
    if schema_path is None:
        return []
    local = ValidationReport()
    _validate_schema(local, schema_path, value, name)
    return local.errors


def _validate_mutation_rows(
    rows: list[dict[str, str]], config: dict[str, Any]
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    expected = config.get("mutation_contract", {}).get("expected_error_codes", {})
    if len(rows) != int(config.get("mutation_contract", {}).get("declared_count", 0)):
        errors.append({"code": "MUTATION_COUNT_MISMATCH", "message": str(len(rows))})
    observed_ids = {row.get("mutation_id") for row in rows}
    if observed_ids != set(expected):
        errors.append({"code": "MUTATION_COUNT_MISMATCH", "message": "mutation_ids"})
    for row in rows:
        mutation_id = row.get("mutation_id", "")
        expected_code = expected.get(mutation_id)
        if row.get("baseline_status") != "passed":
            errors.append(
                {"code": "MUTATION_BASELINE_NOT_PASSED", "message": mutation_id}
            )
        if row.get("mutation_applied") != "True":
            errors.append({"code": "MUTATION_NOT_APPLIED", "message": mutation_id})
        if row.get("status") in {"", "pending", "pending_validator", "failed"}:
            errors.append(
                {
                    "code": "PENDING_FORMAL_ARTIFACT"
                    if row.get("status") in {"", "pending", "pending_validator"}
                    else "MUTATION_VALIDATION_FAILED",
                    "message": mutation_id,
                }
            )
        if expected_code is None or row.get("expected_error_code") != expected_code:
            errors.append(
                {"code": "MUTATION_EXPECTED_CODE_MISMATCH", "message": mutation_id}
            )
        try:
            actual_codes = json.loads(row.get("actual_error_codes", "[]"))
        except json.JSONDecodeError:
            actual_codes = []
            errors.append(
                {
                    "code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED",
                    "message": mutation_id,
                }
            )
        if not isinstance(actual_codes, list) or expected_code not in actual_codes:
            errors.append(
                {"code": "MUTATION_SPECIFIC_ERROR_MISSING", "message": mutation_id}
            )
        if row.get("specific_error_detected") != "True":
            errors.append(
                {"code": "MUTATION_SPECIFIC_ERROR_MISSING", "message": mutation_id}
            )
        if row.get("unrelated_setup_failure") == "True":
            errors.append(
                {"code": "MUTATION_UNRELATED_SETUP_FAILURE", "message": mutation_id}
            )
    return errors


def _manifest_binding_errors(
    run_dir: Path,
    manifest: dict[str, Any],
    *,
    expected_paths: set[str] | None = None,
    root: Path = ROOT,
    declarations: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if manifest.get("manifest_self_hash_excluded") is not True:
        errors.append(
            {
                "code": "MANIFEST_BINDING_INCOMPLETE",
                "message": "manifest_self_hash_excluded",
            }
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return errors + [
            {"code": "MANIFEST_BINDING_INCOMPLETE", "message": "artifacts"}
        ]
    actual_paths = {
        str(item.get("path")) for item in artifacts if isinstance(item, dict)
    }
    if expected_paths is not None and actual_paths != expected_paths:
        errors.append(
            {"code": "MANIFEST_BINDING_INCOMPLETE", "message": "artifact_set"}
        )
    for item in artifacts:
        if not isinstance(item, dict):
            errors.append(
                {"code": "MANIFEST_BINDING_INCOMPLETE", "message": "artifact_entry"}
            )
            continue
        relative = item.get("path")
        required = {"path", "artifact_owner", "artifact_sha256", "size_bytes", "kind"}
        if not required.issubset(item):
            errors.append(
                {"code": "MANIFEST_BINDING_INCOMPLETE", "message": str(relative)}
            )
            continue
        if declarations is not None:
            declaration = declarations.get(str(relative))
            if declaration is None or any(
                item.get(key) != declaration.get(key)
                for key in ("artifact_owner", "kind")
            ):
                errors.append(
                    {
                        "code": "MANIFEST_BINDING_METADATA_MISMATCH",
                        "message": str(relative),
                    }
                )
        path = run_dir / str(relative)
        if not path.is_file():
            errors.append(
                {"code": "MANIFEST_BINDING_INCOMPLETE", "message": str(relative)}
            )
            continue
        payload = path.read_bytes()
        if _sha_bytes(payload) != item.get("artifact_sha256"):
            errors.append(
                {"code": "MANIFEST_BINDING_HASH_MISMATCH", "message": str(relative)}
            )
        if path.stat().st_size != item.get("size_bytes"):
            errors.append(
                {"code": "MANIFEST_BINDING_SIZE_MISMATCH", "message": str(relative)}
            )
        if item.get("kind") == "csv":
            actual_rows = len(read_csv(path))
            if item.get("row_count") != actual_rows:
                errors.append(
                    {
                        "code": "MANIFEST_BINDING_ROW_COUNT_MISMATCH",
                        "message": str(relative),
                    }
                )
        elif item.get("kind") == "json":
            try:
                value = _load_json(path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if (
                "row_count" in item
                and isinstance(value, dict)
                and isinstance(value.get("cases"), list)
            ):
                if item.get("row_count") != len(value["cases"]):
                    errors.append(
                        {
                            "code": "MANIFEST_BINDING_ROW_COUNT_MISMATCH",
                            "message": str(relative),
                        }
                    )
            elif "row_count" in item and isinstance(value, list):
                if item.get("row_count") != len(value):
                    errors.append(
                        {
                            "code": "MANIFEST_BINDING_ROW_COUNT_MISMATCH",
                            "message": str(relative),
                        }
                    )
        schema_path = item.get("schema_path")
        schema_sha = item.get("schema_sha256")
        if (schema_path is None) != (schema_sha is None):
            errors.append(
                {"code": "MANIFEST_BINDING_INCOMPLETE", "message": f"schema:{relative}"}
            )
        elif schema_path is not None:
            schema_file = root / str(schema_path)
            try:
                schema_file.resolve().relative_to(root.resolve())
            except ValueError:
                errors.append(
                    {
                        "code": "MANIFEST_BINDING_INCOMPLETE",
                        "message": f"schema:{relative}",
                    }
                )
            else:
                try:
                    schema_bytes = schema_file.read_bytes()
                except OSError:
                    errors.append(
                        {
                            "code": "MANIFEST_BINDING_INCOMPLETE",
                            "message": f"schema:{relative}",
                        }
                    )
                else:
                    if _sha_bytes(schema_bytes) != schema_sha:
                        errors.append(
                            {
                                "code": "MANIFEST_BINDING_SCHEMA_HASH_MISMATCH",
                                "message": str(relative),
                            }
                        )
    for section in ("config", "fixture"):
        binding = manifest.get(section)
        if not isinstance(binding, dict) or not {
            "path",
            "sha256",
            "size_bytes",
        }.issubset(binding):
            errors.append({"code": "MANIFEST_BINDING_INCOMPLETE", "message": section})
            continue
        path = root / str(binding["path"])
        try:
            path.resolve().relative_to(root.resolve())
            payload = path.read_bytes()
        except (OSError, ValueError):
            errors.append({"code": "MANIFEST_BINDING_INCOMPLETE", "message": section})
            continue
        if _sha_bytes(payload) != binding.get("sha256"):
            errors.append(
                {"code": "MANIFEST_BINDING_HASH_MISMATCH", "message": section}
            )
        if len(payload) != binding.get("size_bytes"):
            errors.append(
                {"code": "MANIFEST_BINDING_SIZE_MISMATCH", "message": section}
            )
        if binding.get("source_commit") is not None:
            source_fields = {
                "git_blob_sha",
                "committed_byte_sha256",
                "normalized_text_sha256",
                "encoding",
                "line_ending",
                "bom",
                "terminal_lf_count",
            }
            if not source_fields.issubset(binding):
                errors.append(
                    {"code": "MANIFEST_BINDING_INCOMPLETE", "message": section}
                )
                continue
            source_commit = str(binding["source_commit"])
            relative = str(binding["path"])
            committed = _committed_bytes(root, source_commit, relative)
            blob_sha = _committed_git_blob_sha(root, source_commit, relative)
            if (
                committed is None
                or blob_sha is None
                or blob_sha != binding.get("git_blob_sha")
                or _sha_bytes(committed) != binding.get("committed_byte_sha256")
            ):
                errors.append(
                    {"code": "MANIFEST_BINDING_SOURCE_MISMATCH", "message": section}
                )
                continue
            try:
                decoded = committed.decode("utf-8")
            except UnicodeDecodeError:
                errors.append(
                    {"code": "MANIFEST_BINDING_SOURCE_MISMATCH", "message": section}
                )
                continue
            normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
            terminal_lf_count = len(committed) - len(committed.rstrip(b"\n"))
            if (
                _sha_bytes(normalized.encode("utf-8"))
                != binding.get("normalized_text_sha256")
                or binding.get("encoding") != "utf-8"
                or binding.get("line_ending") != "lf"
                or binding.get("bom") is not False
                or binding.get("terminal_lf_count") != terminal_lf_count
            ):
                errors.append(
                    {"code": "MANIFEST_BINDING_SOURCE_MISMATCH", "message": section}
                )
    upstream_bindings = manifest.get("upstream_bindings")
    if not isinstance(upstream_bindings, list) or not upstream_bindings:
        errors.append(
            {"code": "MANIFEST_BINDING_INCOMPLETE", "message": "upstream_bindings"}
        )
    else:
        for binding in upstream_bindings:
            if not isinstance(binding, dict) or not {
                "path",
                "sha256",
                "source_commit",
            }.issubset(binding):
                errors.append(
                    {"code": "MANIFEST_BINDING_INCOMPLETE", "message": "upstream_entry"}
                )
                continue
            payload = _committed_bytes(
                root, str(binding["source_commit"]), str(binding["path"])
            )
            if payload is None or _sha_bytes(payload) != binding.get("sha256"):
                errors.append(
                    {
                        "code": "MANIFEST_BINDING_UPSTREAM_MISMATCH",
                        "message": str(binding["path"]),
                    }
                )
    return errors


def _artifact_state_errors(
    run_dir: Path,
    config: dict[str, Any],
    *,
    root: Path = ROOT,
    allow_missing_result_phase: bool = True,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    declarations = _artifact_kind_map(config)
    declared = set(declarations)
    actual = (
        {path.name for path in run_dir.iterdir() if path.is_file()}
        if run_dir.is_dir()
        else set()
    )
    for extra in sorted(actual - declared):
        errors.append({"code": "UNDECLARED_FORMAL_ARTIFACT", "message": extra})
    runner_files = {
        name
        for name, spec in declarations.items()
        if spec["artifact_owner"] == "runner"
    }
    for name in sorted(runner_files):
        path = run_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(
                {"code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", "message": name}
            )
            continue
        try:
            if declarations[name]["kind"] == "json":
                value = _load_json(path)
                if _status_is_pending(value):
                    errors.append({"code": "PENDING_FORMAL_ARTIFACT", "message": name})
                errors.extend(_actual_artifact_schema_errors(name, value, root))
            elif declarations[name]["kind"] == "csv" and not _csv_header(path):
                errors.append(
                    {"code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", "message": name}
                )
            if name == "r3_t01_field_semantics_registry.csv":
                expected_header = FIELD_SEMANTICS_HEADER
                if _csv_header(path) != expected_header:
                    errors.append(
                        {
                            "code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED",
                            "message": name,
                        }
                    )
                elif len(read_csv(path)) != len(config["field_semantics"]):
                    errors.append(
                        {"code": "FORMAL_ARTIFACT_ROW_COUNT_MISMATCH", "message": name}
                    )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            errors.append(
                {"code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", "message": name}
            )
    production_path = run_dir / "r3_t01_production_synthetic_results.json"
    if production_path.is_file():
        try:
            production = _load_json(production_path)
            if production.get("case_count") != len(
                _load_json(root / config["synthetic_fixture_path"]).get("cases", [])
            ) or not isinstance(production.get("cases"), list):
                errors.append(
                    {
                        "code": "PRODUCTION_SCENARIO_COUNT_MISMATCH",
                        "message": production_path.name,
                    }
                )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            errors.append(
                {
                    "code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED",
                    "message": production_path.name,
                }
            )
    comparison_path = run_dir / "r3_t01_production_rebuild_comparison.json"
    if comparison_path.is_file():
        try:
            comparison = _load_json(comparison_path)
            required = {
                "rebuild_1_hashes",
                "rebuild_2_hashes",
                "compared_artifact_count",
                "mismatch_count",
                "mismatches",
                "status",
            }
            if (
                not required.issubset(comparison)
                or comparison.get("status") != "passed"
                or comparison.get("mismatch_count") != 0
            ):
                errors.append(
                    {"code": "DOUBLE_REBUILD_MISMATCH", "message": comparison_path.name}
                )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            errors.append(
                {
                    "code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED",
                    "message": comparison_path.name,
                }
            )
    upstream_path = run_dir / "r3_t01_upstream_binding.json"
    if upstream_path.is_file():
        try:
            upstream = _load_json(upstream_path)
            reviewed_sha = upstream.get("reviewed_implementation_sha")
            formal_sha = upstream.get("formal_execution_sha")
            if (
                not isinstance(reviewed_sha, str)
                or not isinstance(formal_sha, str)
                or reviewed_sha != formal_sha
            ):
                errors.append(
                    {
                        "code": "IMPLEMENTATION_SHA_BINDING_MISMATCH",
                        "message": upstream_path.name,
                    }
                )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            errors.append(
                {
                    "code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED",
                    "message": upstream_path.name,
                }
            )

    mutation_path = run_dir / "r3_t01_mutation_results.csv"
    if mutation_path.is_file():
        if mutation_path.stat().st_size <= len(",".join(MUTATION_HEADER)) + 1:
            errors.append(
                {"code": "EMPTY_MUTATION_RESULTS", "message": mutation_path.name}
            )
        elif _csv_header(mutation_path) != MUTATION_HEADER:
            errors.append(
                {
                    "code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED",
                    "message": mutation_path.name,
                }
            )
        else:
            rows = read_csv(mutation_path)
            errors.extend(_validate_mutation_rows(rows, config))
    elif not allow_missing_result_phase:
        errors.append({"code": "EMPTY_MUTATION_RESULTS", "message": "missing"})
    for name in ("r3_t01_validator_result.json", "r3_t01_anomaly_scan.json"):
        path = run_dir / name
        if not path.is_file():
            if not allow_missing_result_phase:
                errors.append({"code": "PENDING_FORMAL_ARTIFACT", "message": name})
            continue
        try:
            payload = _load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            errors.append(
                {"code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", "message": name}
            )
            continue
        if payload.get("status") in {"pending", "pending_validator"}:
            errors.append({"code": "PENDING_FORMAL_ARTIFACT", "message": name})
        if name.endswith("anomaly_scan.json") and not isinstance(
            payload.get("scan_scope"), list
        ):
            errors.append(
                {"code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", "message": name}
            )
    independent_path = run_dir / "r3_t01_independent_replay_results.json"
    if independent_path.is_file():
        try:
            payload = _load_json(independent_path)
            if not isinstance(payload.get("cases"), list):
                errors.append(
                    {
                        "code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED",
                        "message": independent_path.name,
                    }
                )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            errors.append(
                {
                    "code": "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED",
                    "message": independent_path.name,
                }
            )
    for name in ("r3_t01_result_analysis.md", "r3_t01_manifest.json"):
        path = run_dir / name
        if not path.is_file():
            continue
        if path.stat().st_size == 0:
            errors.append(
                {
                    "code": "MANIFEST_BINDING_INCOMPLETE"
                    if name.endswith("manifest.json")
                    else "RESULT_ANALYSIS_PLACEHOLDER",
                    "message": name,
                }
            )
        elif name.endswith("result_analysis.md"):
            text = path.read_text(encoding="utf-8")
            if (
                "Pending independent result review" in text
                or "placeholder" in text.lower()
            ):
                errors.append({"code": "RESULT_ANALYSIS_PLACEHOLDER", "message": name})
    manifest_path = run_dir / "r3_t01_manifest.json"
    if manifest_path.is_file():
        try:
            errors.extend(
                _manifest_binding_errors(
                    run_dir,
                    _load_json(manifest_path),
                    expected_paths=declared
                    - {"r3_t01_manifest.json", "r3_t01_final_validation.json"},
                    root=root,
                    declarations=declarations,
                )
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            errors.append(
                {"code": "MANIFEST_BINDING_INCOMPLETE", "message": manifest_path.name}
            )
    return errors


def _write_snapshot_for_artifact_mutation(
    directory: Path,
    config: dict[str, Any],
    replay_results: list[dict[str, Any]],
    mutation_rows: list[dict[str, Any]],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "r3_t01_protocol_registry.json", config)
    write_json(
        directory / "r3_t01_production_synthetic_results.json",
        {"case_count": len(replay_results), "cases": replay_results},
    )
    write_json(
        directory / "r3_t01_production_rebuild_comparison.json",
        {
            "rebuild_1_hashes": {"synthetic": "a" * 64},
            "rebuild_2_hashes": {"synthetic": "a" * 64},
            "compared_artifact_count": 1,
            "mismatch_count": 0,
            "mismatches": [],
            "status": "passed",
        },
    )
    write_json(
        directory / "r3_t01_independent_replay_results.json", {"cases": replay_results}
    )
    write_csv(directory / "r3_t01_mutation_results.csv", mutation_rows, MUTATION_HEADER)
    write_json(directory / "r3_t01_validator_result.json", {"status": "passed"})
    write_json(
        directory / "r3_t01_anomaly_scan.json",
        {
            "status": "complete",
            "scan_scope": ["artifact_state"],
            "findings": [],
            "anomaly_count": 0,
        },
    )


def _independent_case_results(
    config: dict[str, Any], fixture: dict[str, Any]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in fixture.get("cases", []):
        attempts, rejections = independent_replay(
            case.get("rows", []),
            case.get("event_zones", []),
            case.get("membership_rows", []),
            config,
            sample_end_censoring=bool(case.get("sample_end_censoring", False)),
        )
        landmarks = {
            attempt["exit_attempt_id"]: build_independent_landmarks(
                case.get("rows", []),
                state_version_id=attempt["state_version_id"],
                security_id=attempt["security_id"],
                t0_date=attempt["exit_attempt_date"],
            )
            for attempt in attempts
        }
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


def _write_mutation_runner_snapshot(
    directory: Path,
    config: dict[str, Any],
    fixture: dict[str, Any],
    *,
    artifact_mutation: str | None = None,
) -> None:
    """Materialize a complete mutation input snapshot without production imports."""

    directory.mkdir(parents=True, exist_ok=True)
    cases = _independent_case_results(config, fixture)
    write_json(
        directory / "r3_t01_upstream_binding.json",
        {
            "startup_status": "passed",
            "synthetic_mutation_snapshot": True,
            "reviewed_implementation_sha": "mutation".ljust(40, "0"),
            "formal_execution_sha": "mutation".ljust(40, "0"),
            "approval_comment_id": 1030000001,
            "approval_comment_url": "https://github.com/benzemaer/convergence-research/pull/103#issuecomment-1030000001",
            "approval_author_login": "benzemaer",
            "approval_created_at": "2026-07-15T00:00:00Z",
            "approval_updated_at": "2026-07-15T00:00:00Z",
            "approval_body_sha256": "0" * 64,
            "pr_head_sha": "mutation".ljust(40, "0"),
            "pr_state": "OPEN",
            "approval_scope": "R3-T01_formal_run_only",
            "required_artifacts": [
                {
                    "path": item["path"],
                    "source_commit": item["source_commit"],
                    "committed_byte_sha256": item["committed_byte_sha256"],
                }
                for item in config["upstream_binding"]["required_artifacts"]
            ],
            "committed_validation_status": "passed",
        },
    )
    write_json(directory / "r3_t01_anchor_decision.json", config["anchor_decision"])
    write_json(directory / "r3_t01_protocol_registry.json", config)
    write_json(
        directory / "r3_t01_t0_transition_contract.json",
        {
            "contract_version": config["contract_version"],
            "anchor_decision": config["anchor_decision"],
            "t0_transition_contract": config["t0_transition_contract"],
            "analysis_unit_contract": config["analysis_unit_contract"],
            "field_semantics": config["field_semantics"],
        },
    )
    write_json(
        directory / "r3_t01_analysis_unit_contract.json",
        config["analysis_unit_contract"],
    )
    write_csv(
        directory / "r3_t01_field_semantics_registry.csv",
        config["field_semantics"],
        FIELD_SEMANTICS_HEADER,
    )
    write_json(
        directory / "r3_t01_landmark_horizon_contract.json",
        config["landmark_horizon_contract"],
    )
    write_json(
        directory / "r3_t01_sample_split_contract.json",
        config["sample_split_contract"],
    )
    write_json(directory / "r3_t01_schema_registry.json", config["schema_registry"])
    write_json(
        directory / "r3_t01_production_synthetic_results.json",
        {"case_count": len(cases), "cases": cases},
    )
    payload_names = [
        name
        for name in (
            "r3_t01_anchor_decision.json",
            "r3_t01_protocol_registry.json",
            "r3_t01_t0_transition_contract.json",
            "r3_t01_analysis_unit_contract.json",
            "r3_t01_field_semantics_registry.csv",
            "r3_t01_landmark_horizon_contract.json",
            "r3_t01_sample_split_contract.json",
            "r3_t01_schema_registry.json",
            "r3_t01_production_synthetic_results.json",
        )
    ]
    hashes = {
        name: _sha_bytes((directory / name).read_bytes()) for name in payload_names
    }
    write_json(
        directory / "r3_t01_production_rebuild_comparison.json",
        {
            "rebuild_1_hashes": hashes,
            "rebuild_2_hashes": hashes.copy(),
            "compared_artifact_count": len(hashes),
            "mismatch_count": 0,
            "mismatches": [],
            "status": "passed",
        },
    )
    if artifact_mutation == "EMPTY_MUTATION_RESULTS":
        write_csv(directory / "r3_t01_mutation_results.csv", [], MUTATION_HEADER)
    elif artifact_mutation == "PENDING_FORMAL_ARTIFACT":
        write_json(directory / "r3_t01_validator_result.json", {"status": "pending"})


def _run_mutations_from_inputs(
    config: dict[str, Any], fixture: dict[str, Any], root: Path
) -> list[dict[str, Any]]:
    baseline = validate_in_memory(config, fixture, root=root, check_upstream=False)
    baseline_status = "passed" if baseline.passed else "failed"
    results: list[dict[str, Any]] = []
    for mutation_id, expected_code in MUTATION_CODES.items():
        mutated_config, mutated_fixture, source_text = apply_mutation(
            config, fixture, mutation_id
        )
        marker = _artifact_marker_error(mutated_fixture)
        if marker:
            actual_codes = [marker]
        else:
            report = validate_in_memory(
                mutated_config,
                mutated_fixture,
                root=root,
                check_upstream=False,
                validator_source_text=source_text,
            )
            actual_codes = sorted({item["code"] for item in report.errors})
        results.append(
            _mutation_result(mutation_id, baseline_status, expected_code, actual_codes)
        )
    for mutation_id, expected_code in (
        ("M18", MUTATION_CODES["M18"]),
        ("M19", MUTATION_CODES["M19"]),
    ):
        with TemporaryDirectory(
            prefix=f"r3_t01_{mutation_id.lower()}_artifact_"
        ) as temp_dir:
            snapshot = Path(temp_dir)
            _write_mutation_runner_snapshot(snapshot, config, fixture)
            if mutation_id == "M18":
                write_csv(snapshot / "r3_t01_mutation_results.csv", [], MUTATION_HEADER)
            else:
                write_json(
                    snapshot / "r3_t01_validator_result.json", {"status": "pending"}
                )
            errors = _artifact_state_errors(snapshot, config)
            codes = sorted({item["code"] for item in errors})
            result = next(
                item for item in results if item["mutation_id"] == mutation_id
            )
            result.update(
                _mutation_result(mutation_id, baseline_status, expected_code, codes)
            )
    return results


def validate_mutations_from_disk(
    config_path: Path, fixture_path: Path, *, root: Path = ROOT
) -> list[dict[str, Any]]:
    """Reload pristine files and send every mutation through the full validator path."""

    baseline_config = _load_json(config_path)
    baseline_fixture = _load_json(fixture_path)
    baseline = validate_in_memory(
        baseline_config, baseline_fixture, root=root, check_upstream=True
    )
    baseline_status = "passed" if baseline.passed else "failed"
    results: list[dict[str, Any]] = []
    for mutation_id, expected_code in MUTATION_CODES.items():
        pristine_config = _load_json(config_path)
        pristine_fixture = _load_json(fixture_path)
        mutated_config, mutated_fixture, source_text = apply_mutation(
            pristine_config, pristine_fixture, mutation_id
        )
        if mutation_id == "M24":
            actual_codes = _run_final_validator_tamper_mutation(
                pristine_config,
                pristine_fixture,
                root=root,
            )
            results.append(
                _mutation_result(
                    mutation_id,
                    baseline_status,
                    expected_code,
                    actual_codes,
                )
            )
            continue
        with TemporaryDirectory(prefix=f"r3_t01_{mutation_id.lower()}_") as temp_dir:
            snapshot = Path(temp_dir)
            _write_mutation_runner_snapshot(
                snapshot,
                mutated_config,
                mutated_fixture,
                artifact_mutation=_artifact_marker_error(mutated_fixture),
            )
            mutation_report = _validate_run_dir_core(
                snapshot,
                root=root,
                execute_mutations=False,
                write_outputs=False,
                fixture_override=mutated_fixture,
                validator_source_text=source_text,
                check_upstream=False,
            )
            actual_codes = sorted({item["code"] for item in mutation_report.errors})
            marker = _artifact_marker_error(mutated_fixture)
            if marker:
                actual_codes = sorted(set(actual_codes) | {marker})
        results.append(
            _mutation_result(
                mutation_id,
                baseline_status,
                expected_code,
                actual_codes,
            )
        )
    return results


def _run_final_validator_tamper_mutation(
    config: dict[str, Any], fixture: dict[str, Any], *, root: Path
) -> list[str]:
    """Exercise M24 through a real analyzer/manifest/terminal-validator package."""

    from src.r3.r3_t01_final_validator import validate_final_run_dir
    from src.r3.r3_t01_result_analysis import analyze_run_dir

    baseline = validate_in_memory(config, fixture, root=root, check_upstream=False)
    mutation_rows = _run_mutations_from_inputs(config, fixture, root)
    with TemporaryDirectory(prefix="r3_t01_m24_final_validator_") as temp_dir:
        snapshot = Path(temp_dir)
        _write_mutation_runner_snapshot(snapshot, config, fixture)
        _write_snapshot_for_artifact_mutation(
            snapshot, config, baseline.replay_results, mutation_rows
        )
        write_json(
            snapshot / "r3_t01_validator_result.json",
            {
                "status": "passed",
                "formal_run_status": "generated_pending_analysis",
                "errors": [],
                "case_count": len(baseline.replay_results),
                "mutation_count": len(mutation_rows),
                "real_database_opened": False,
            },
        )
        fake_sha = "mutation" + "0" * 32
        analyze_run_dir(
            snapshot,
            root / "configs/r3/r3_t01_protocol_t0_analysis_unit.v1.json",
            root / "tests/r3/fixtures/r3_t01/cases.json",
            reviewed_implementation_sha=fake_sha,
            formal_execution_sha=fake_sha,
            root=root,
        )
        clean = validate_final_run_dir(snapshot, root=root)
        if clean.get("status") != "passed":
            return sorted({item["code"] for item in clean.get("errors", [])})
        tampered_path = snapshot / "r3_t01_anchor_decision.json"
        tampered = _load_json(tampered_path)
        tampered["post_manifest_tamper"] = True
        write_json(tampered_path, tampered)
        tampered_result = validate_final_run_dir(snapshot, root=root)
        return sorted({item["code"] for item in tampered_result.get("errors", [])})


def validate_in_memory(
    config: dict[str, Any],
    fixture: dict[str, Any],
    *,
    root: Path = ROOT,
    check_upstream: bool = True,
    validator_source_text: str | None = None,
) -> ValidationReport:
    report = ValidationReport()
    _validate_schema(
        report,
        root / "schemas/r3/r3_t01_protocol_registry.schema.json",
        config,
        "protocol_registry",
    )
    exit_document = {
        "contract_version": config.get("contract_version"),
        "anchor_decision": config.get("anchor_decision"),
        "t0_transition_contract": config.get("t0_transition_contract"),
        "analysis_unit_contract": config.get("analysis_unit_contract"),
        "field_semantics": config.get("field_semantics"),
    }
    _validate_schema(
        report,
        root / "schemas/r3/r3_t01_exit_attempt_contract.schema.json",
        exit_document,
        "exit_attempt_contract",
    )
    _validate_schema(
        report,
        root / "schemas/r3/r3_t01_landmark_horizon_contract.schema.json",
        config.get("landmark_horizon_contract"),
        "landmark_horizon_contract",
    )
    _validate_schema(
        report,
        root / "schemas/r3/r3_t01_sample_split_contract.schema.json",
        config.get("sample_split_contract"),
        "sample_split_contract",
    )
    _check_public_interface(config, fixture, root, report)
    _check_exact_contract_values(config, fixture, report)
    _check_field_semantics(config, report)
    _check_no_future_output(config, report)
    source = validator_source_text or Path(__file__).read_text(encoding="utf-8")
    independence_error = validate_independence(source)
    if independence_error:
        report.add(independence_error)
    if check_upstream:
        _check_upstream_committed_bindings(config, report, root)
    second_replay_results: list[dict[str, Any]] = []
    for case in fixture.get("cases", []):
        try:
            first_attempts, first_rejections = independent_replay(
                case.get("rows", []),
                case.get("event_zones", []),
                case.get("membership_rows", []),
                config,
                sample_end_censoring=bool(case.get("sample_end_censoring", False)),
            )
            first_landmarks = {
                attempt["exit_attempt_id"]: build_independent_landmarks(
                    case.get("rows", []),
                    state_version_id=attempt["state_version_id"],
                    security_id=attempt["security_id"],
                    t0_date=attempt["exit_attempt_date"],
                )
                for attempt in first_attempts
            }
            second_attempts, second_rejections = independent_replay(
                copy.deepcopy(case.get("rows", [])),
                copy.deepcopy(case.get("event_zones", [])),
                copy.deepcopy(case.get("membership_rows", [])),
                copy.deepcopy(config),
                sample_end_censoring=bool(case.get("sample_end_censoring", False)),
            )
            second_landmarks = {
                attempt["exit_attempt_id"]: build_independent_landmarks(
                    copy.deepcopy(case.get("rows", [])),
                    state_version_id=attempt["state_version_id"],
                    security_id=attempt["security_id"],
                    t0_date=attempt["exit_attempt_date"],
                )
                for attempt in second_attempts
            }
            first_rebuild = {
                "attempts": first_attempts,
                "rejections": first_rejections,
                "landmarks": first_landmarks,
            }
            second_rebuild = {
                "attempts": second_attempts,
                "rejections": second_rejections,
                "landmarks": second_landmarks,
            }
            if _canonical(first_rebuild) != _canonical(second_rebuild):
                report.add("DOUBLE_REBUILD_MISMATCH", case["case_id"])
            comparison = _compare_case(
                case,
                first_attempts,
                first_rejections,
                first_landmarks,
                report,
            )
            report.synthetic_case_results.append(comparison)
            report.replay_results.append(
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
                    "actual_attempts": first_attempts,
                    "rejections": first_rejections,
                    "landmarks": first_landmarks,
                }
            )
            second_replay_results.append(
                {
                    "case_id": case["case_id"],
                    "state_version_security_groups": sorted(
                        {
                            (
                                str(row.get("state_version_id")),
                                str(row.get("security_id")),
                            )
                            for row in copy.deepcopy(case.get("rows", []))
                        }
                    ),
                    "actual_attempts": second_attempts,
                    "rejections": second_rejections,
                    "landmarks": second_landmarks,
                }
            )
        except (KeyError, TypeError, ReplayValidationError, ValueError) as exc:
            code = (
                exc.code
                if isinstance(exc, ReplayValidationError)
                else "SYNTHETIC_REPLAY_FAILED"
            )
            report.add(code, f"{case.get('case_id')}:{exc}")
    first_hash = _sha(report.replay_results)
    second_hash = _sha(second_replay_results)
    report.double_rebuild_hash = first_hash
    report.double_rebuild_result = {
        "rebuild_1_hash": first_hash,
        "rebuild_2_hash": second_hash,
        "compared_case_count": min(
            len(report.replay_results), len(second_replay_results)
        ),
        "mismatch_count": int(first_hash != second_hash),
        "status": "passed" if first_hash == second_hash else "failed",
    }
    return report


def _compare_production_and_independent(
    production: dict[str, Any],
    independent: list[dict[str, Any]],
    report: ValidationReport,
) -> None:
    production_cases = production.get("cases")
    if not isinstance(production_cases, list) or len(production_cases) != len(
        independent
    ):
        report.add("PRODUCTION_INDEPENDENT_REPLAY_MISMATCH", "case_count")
        return
    for prod, ind in zip(production_cases, independent, strict=True):
        if _canonical(prod) != _canonical(ind):
            report.add(
                "PRODUCTION_INDEPENDENT_REPLAY_MISMATCH", str(prod.get("case_id"))
            )
            prod_landmarks = prod.get("landmarks", {})
            ind_landmarks = ind.get("landmarks", {})
            if prod_landmarks != ind_landmarks:
                report.add(
                    "LANDMARK_CROSS_GROUP_CONTAMINATION", str(prod.get("case_id"))
                )


def _check_runner_contract_bytes(
    run_dir: Path, config: dict[str, Any], report: ValidationReport
) -> None:
    expected_json = {
        "r3_t01_anchor_decision.json": config.get("anchor_decision"),
        "r3_t01_analysis_unit_contract.json": config.get("analysis_unit_contract"),
        "r3_t01_landmark_horizon_contract.json": config.get(
            "landmark_horizon_contract"
        ),
        "r3_t01_sample_split_contract.json": config.get("sample_split_contract"),
        "r3_t01_schema_registry.json": config.get("schema_registry"),
    }
    for name, expected in expected_json.items():
        path = run_dir / name
        if not path.is_file():
            continue
        try:
            actual = _load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if _canonical(actual) != _canonical(expected):
            report.add("FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", name)
    transition_path = run_dir / "r3_t01_t0_transition_contract.json"
    if transition_path.is_file():
        try:
            transition = _load_json(transition_path)
            expected = {
                "contract_version": config.get("contract_version"),
                "anchor_decision": config.get("anchor_decision"),
                "t0_transition_contract": config.get("t0_transition_contract"),
                "analysis_unit_contract": config.get("analysis_unit_contract"),
                "field_semantics": config.get("field_semantics"),
            }
            if _canonical(transition) != _canonical(expected):
                report.add(
                    "FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", transition_path.name
                )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    field_path = run_dir / "r3_t01_field_semantics_registry.csv"
    if field_path.is_file():
        try:
            rows = read_csv(field_path)
            expected_names = [
                str(item.get("field_name")) for item in config["field_semantics"]
            ]
            actual_names = [row.get("field_name") for row in rows]
            if actual_names != expected_names:
                report.add("FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", field_path.name)
        except (OSError, UnicodeDecodeError, csv.Error):
            pass


def _compare_existing_independent_artifact(
    path: Path, replay_results: list[dict[str, Any]], report: ValidationReport
) -> None:
    if not path.is_file():
        return
    try:
        payload = _load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return
    if _canonical(payload.get("cases")) != _canonical(replay_results):
        report.add("INDEPENDENT_REPLAY_ARTIFACT_MISMATCH", path.name)


def _mutation_signature(row: dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    actual = value.get("actual_error_codes", [])
    if isinstance(actual, str):
        try:
            actual = json.loads(actual)
        except json.JSONDecodeError:
            actual = []
    value["actual_error_codes"] = actual
    return value


def _compare_existing_mutation_artifact(
    path: Path, mutation_results: list[dict[str, Any]], report: ValidationReport
) -> None:
    if not path.is_file():
        return
    try:
        actual = [_mutation_signature(row) for row in read_csv(path)]
    except (OSError, UnicodeDecodeError, csv.Error):
        return
    expected = [_mutation_signature(row) for row in mutation_results]
    if _canonical(actual) != _canonical(expected):
        report.add("MUTATION_ARTIFACT_CONTENT_MISMATCH", path.name)


def _source_opens_duckdb(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == "duckdb" for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "duckdb":
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "connect" and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "duckdb":
                    return True
    return False


def _validate_run_dir_core(
    run_dir: Path,
    *,
    root: Path,
    execute_mutations: bool,
    write_outputs: bool,
    fixture_override: dict[str, Any] | None = None,
    validator_source_text: str | None = None,
    check_upstream: bool = True,
) -> ValidationReport:
    """Shared complete validator path used by formal validation and mutations."""

    report = ValidationReport()
    registry_path = run_dir / "r3_t01_protocol_registry.json"
    if not registry_path.is_file():
        report.add("RUN_REGISTRY_MISSING", str(registry_path))
        return report
    try:
        config = _load_json(registry_path)
        fixture = fixture_override or _load_json(
            root / config["synthetic_fixture_path"]
        )
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        report.add("RUN_INPUT_INVALID", str(exc))
        return report
    for item in _artifact_state_errors(run_dir, config, root=root):
        report.add(item["code"], item["message"])
    _check_runner_contract_bytes(run_dir, config, report)
    for relative in (
        "src/r3/r3_t01_protocol.py",
        "src/r3/r3_t01_validator.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        if _source_opens_duckdb(source):
            report.add("REAL_CANONICAL_DB_ACCESS", relative)
    production_path = run_dir / "r3_t01_production_synthetic_results.json"
    if production_path.is_file():
        try:
            production = _load_json(production_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            report.add("FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", str(exc))
            production = {}
    else:
        production = {}
        report.add("FORMAL_ARTIFACT_CONTENT_NOT_VALIDATED", production_path.name)
    in_memory = validate_in_memory(
        config,
        fixture,
        root=root,
        check_upstream=check_upstream,
        validator_source_text=validator_source_text,
    )
    report.errors.extend(in_memory.errors)
    report.synthetic_case_results = in_memory.synthetic_case_results
    report.replay_results = in_memory.replay_results
    report.double_rebuild_hash = in_memory.double_rebuild_hash
    report.double_rebuild_result = in_memory.double_rebuild_result
    _compare_production_and_independent(production, report.replay_results, report)
    _compare_existing_independent_artifact(
        run_dir / "r3_t01_independent_replay_results.json",
        report.replay_results,
        report,
    )
    if execute_mutations:
        pristine_config_path = (
            root / "configs/r3/r3_t01_protocol_t0_analysis_unit.v1.json"
        )
        pristine_fixture_path = root / "tests/r3/fixtures/r3_t01/cases.json"
        mutation_results = validate_mutations_from_disk(
            pristine_config_path,
            pristine_fixture_path,
            root=root,
        )
        report.mutation_results = mutation_results
        if any(item["status"] != "passed" for item in mutation_results):
            report.add("MUTATION_VALIDATION_FAILED")
        mutation_path = run_dir / "r3_t01_mutation_results.csv"
        if mutation_path.is_file():
            _compare_existing_mutation_artifact(mutation_path, mutation_results, report)
        elif write_outputs:
            write_csv(mutation_path, mutation_results, MUTATION_HEADER)
    else:
        mutation_path = run_dir / "r3_t01_mutation_results.csv"
        if mutation_path.is_file():
            try:
                report.mutation_results = read_csv(mutation_path)
            except (OSError, UnicodeDecodeError, csv.Error):
                pass
    if write_outputs:
        independent_path = run_dir / "r3_t01_independent_replay_results.json"
        if not independent_path.is_file():
            write_json(
                independent_path,
                {
                    "case_count": len(report.replay_results),
                    "cases": report.replay_results,
                    "implementation": "independent_validator",
                },
            )
        anomaly_path = run_dir / "r3_t01_anomaly_scan.json"
        if not anomaly_path.is_file():
            write_json(
                anomaly_path,
                {
                    "status": "complete",
                    "scan_scope": [
                        "production_independent_replay",
                        "landmarks",
                        "horizons",
                        "mutation_results",
                        "artifact_content",
                        "public_interface",
                    ],
                    "findings": report.errors,
                    "anomaly_count": len(report.errors),
                },
            )
        validator_path = run_dir / "r3_t01_validator_result.json"
        validator_payload = {
            "status": "passed" if report.passed else "failed",
            "formal_run_status": "generated_pending_analysis"
            if report.passed
            else "failed_validation",
            "errors": report.errors,
            "case_count": len(report.replay_results),
            "mutation_count": len(report.mutation_results),
            "production_independent_mismatch_count": sum(
                item["code"] == "PRODUCTION_INDEPENDENT_REPLAY_MISMATCH"
                for item in report.errors
            ),
            "real_database_opened": False,
        }
        write_json(validator_path, validator_payload)
        post_errors = _artifact_state_errors(
            run_dir, config, root=root, allow_missing_result_phase=False
        )
        for item in post_errors:
            if item not in report.errors:
                report.add(item["code"], item["message"])
        if post_errors:
            write_json(
                validator_path,
                {
                    **validator_payload,
                    "status": "passed" if report.passed else "failed",
                    "errors": report.errors,
                },
            )
    return report


def validate_run_dir(run_dir: Path, *, root: Path = ROOT) -> ValidationReport:
    """Read actual bytes, replay independently, execute mutations, and write outputs."""

    return _validate_run_dir_core(
        run_dir,
        root=root,
        execute_mutations=True,
        write_outputs=True,
    )
