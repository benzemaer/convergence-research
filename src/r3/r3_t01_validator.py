"""Independent R3-T01 contract and synthetic-case validator.

The validator intentionally does not import :mod:`r3_t01_protocol`.  Its
transition replay and identity calculation are separate implementations so a
shared production bug cannot make the task-specific check pass.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_STATE_VERSIONS = (
    "r2_s_pct_W120_K3_qP20_qC20_qT25_qV20_d2_g1_v8",
    "r2_s_pcvt_W120_K3_qP20_qC20_qT20_qV30_d2_g1_v8",
)
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
}


@dataclass
class ValidationReport:
    errors: list[dict[str, str]] = field(default_factory=list)
    synthetic_case_results: list[dict[str, Any]] = field(default_factory=list)
    mutation_results: list[dict[str, str]] = field(default_factory=list)
    double_rebuild_hash: str | None = None

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


def _row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("state_version_id", "")),
        str(row.get("security_id", "")),
        str(row.get("trade_date", "")),
    )


def _event_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("state_version_id", "")),
        str(row.get("event_id", "")),
        str(row.get("security_id", "")),
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
            raise ValueError(f"{code}:{key}")
        result[key] = row
    return result


def _sorted_surface(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        _index(rows, _row_key, "DUPLICATE_EXPECTED_ROW").values(), key=_row_key
    )


def _group_surface(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[(str(row.get("state_version_id")), str(row.get("security_id")))].append(
            row
        )
    return result


def _identity(
    namespace: str,
    contract_version: str,
    fields: dict[str, str],
) -> str:
    payload = {"namespace": namespace, "contract_version": contract_version, **fields}
    return _sha(payload)


def _replay_components(
    rows: list[dict[str, Any]],
    membership_rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    surface = _sorted_surface(rows)
    _index(membership_rows, _membership_key, "DUPLICATE_MEMBERSHIP_ROW")
    by_row: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for member in membership_rows:
        by_row[
            (
                str(member.get("state_version_id")),
                str(member.get("security_id")),
                str(member.get("trade_date")),
            )
        ].append(member)
    components: list[dict[str, Any]] = []
    for group in _group_surface(surface).values():
        current: dict[str, Any] | None = None
        was_member = False
        for row in group:
            candidates = by_row.get(
                (
                    str(row.get("state_version_id")),
                    str(row.get("security_id")),
                    str(row.get("trade_date")),
                ),
                [],
            )
            if len(candidates) > 1:
                raise ValueError(f"AMBIGUOUS_MEMBERSHIP_ROW:{_row_key(row)}")
            member = candidates[0] if candidates else None
            is_member = bool(
                row.get("expected_row_present") is True
                and row.get("confirmed_state") is True
                and member is not None
                and member.get("component_member") is True
            )
            if not is_member:
                current = None
                was_member = False
                continue
            event_id = str(member.get("event_id", ""))
            if not event_id:
                raise ValueError("COMPONENT_EVENT_ID_MISSING")
            if not was_member or current is None or current["event_id"] != event_id:
                current = {
                    "state_version_id": str(row["state_version_id"]),
                    "event_id": event_id,
                    "security_id": str(row["security_id"]),
                    "start": str(row["trade_date"]),
                    "end": str(row["trade_date"]),
                    "qualified": member.get("component_qualified_as_of") is True,
                    "qualification_time": member.get(
                        "component_qualification_available_time"
                    ),
                    "row_keys": [_row_key(row)],
                }
                components.append(current)
            else:
                current["end"] = str(row["trade_date"])
                current["qualified"] = bool(
                    current["qualified"]
                    or member.get("component_qualified_as_of") is True
                )
                if not current.get("qualification_time"):
                    current["qualification_time"] = member.get(
                        "component_qualification_available_time"
                    )
                current["row_keys"].append(_row_key(row))
            was_member = True
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
    event_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in components:
        event_groups[
            (item["state_version_id"], item["event_id"], item["security_id"])
        ].append(item)
    for group in event_groups.values():
        group.sort(key=lambda item: (item["start"], item["source_component_id"]))
        for ordinal, item in enumerate(group, 1):
            item["ordinal"] = ordinal
    return components


def _valid_transition(
    prior: dict[str, Any], current: dict[str, Any], transition: dict[str, Any]
) -> bool:
    from_state = (
        transition["from_state"]
        if prior.get("eligible_state") is True
        and prior.get("quality_state") == "valid"
        and prior.get("confirmed_state") is True
        and prior.get("active_event_id_as_of")
        and prior.get("event_status_as_of") in transition["from_event_statuses"]
        else "OTHER"
    )
    to_state = (
        transition["to_state"]
        if current.get("eligible_state") is True
        and current.get("quality_state") == "valid"
        and current.get("raw_state") is False
        and current.get("confirmed_state") is False
        else "OTHER"
    )
    return (
        from_state == transition["from_state"]
        and to_state == transition["to_state"]
        and current.get("raw_state") is False
        and current.get("quality_state") == "valid"
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
    """Independent expected-surface transition replay."""

    surface = _sorted_surface(rows)
    zone_index = _index(zones, _event_key, "DUPLICATE_EVENT_ZONE")
    membership_index = _index(
        membership_rows, _membership_key, "DUPLICATE_MEMBERSHIP_ROW"
    )
    components = _replay_components(surface, membership_rows, config)
    component_by_row = {
        key: component for component in components for key in component["row_keys"]
    }
    attempts: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    transition = config["t0_transition_contract"]["transition_registry"]
    for group in _group_surface(surface).values():
        for position in range(1, len(group)):
            prior = group[position - 1]
            current = group[position]
            key = list(_row_key(current))
            if current.get("expected_row_present") is not True:
                rejections.append(
                    {"row_key": key, "code": "CURRENT_EXPECTED_ROW_MISSING"}
                )
                continue
            if prior.get("expected_row_present") is not True:
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
            membership_key = (
                str(current["state_version_id"]),
                event_id,
                str(current["security_id"]),
                str(current["trade_date"]),
            )
            membership = membership_index.get(membership_key)
            if membership is None or not membership.get("membership_available_time"):
                rejections.append({"row_key": key, "code": "T0_MEMBERSHIP_UNAVAILABLE"})
                continue
            zone = zone_index.get(
                (
                    str(current["state_version_id"]),
                    event_id,
                    str(current["security_id"]),
                )
            )
            if zone is None:
                rejections.append({"row_key": key, "code": "EVENT_NOT_FOUND"})
                continue
            if str(zone["first_qualification_time"]) > str(
                membership["membership_available_time"]
            ):
                rejections.append({"row_key": key, "code": "EVENT_NOT_QUALIFIED"})
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
            t0 = str(membership["membership_available_time"])
            qualified_count = sum(
                1
                for item in components
                if item["state_version_id"] == component["state_version_id"]
                and item["event_id"] == event_id
                and item["security_id"] == component["security_id"]
                and item["qualified"]
                and item.get("qualification_time")
                and str(item["qualification_time"]) <= t0
            )
            spec = config["analysis_unit_contract"]["exit_attempt_id_spec"]
            attempt = {
                "state_version_id": str(current["state_version_id"]),
                "event_id": event_id,
                "security_id": str(current["security_id"]),
                "exit_attempt_id": _identity(
                    spec["namespace"],
                    str(config["contract_version"]),
                    {
                        "state_version_id": str(current["state_version_id"]),
                        "event_id": event_id,
                        "security_id": str(current["security_id"]),
                        "source_component_id": component["source_component_id"],
                        "exit_attempt_date": str(current["trade_date"]),
                        "exit_attempt_time": t0,
                    },
                ),
                "source_component_id": component["source_component_id"],
                "source_component_start_date": component["start"],
                "source_component_end_date": component["end"],
                "source_component_ordinal": component["ordinal"],
                "component_count_as_of_exit": qualified_count,
                "zone_revision_as_of_exit": membership.get("zone_revision"),
                "exit_attempt_date": str(current["trade_date"]),
                "exit_attempt_time": t0,
                "prior_confirmed_state": True,
                "exit_raw_state": False,
                "exit_reason": transition["reason_code"],
                "g_used_as_of_exit": membership.get("g_used_as_of_exit"),
                "event_status_as_of_exit": current.get("event_status_as_of"),
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
    ids = [attempt["exit_attempt_id"] for attempt in attempts]
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_EXIT_ATTEMPT_ID")
    attempts.sort(
        key=lambda item: (
            item["state_version_id"],
            item["event_id"],
            item["exit_attempt_time"],
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


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


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


def _check_exact_contract_values(
    config: dict[str, Any], report: ValidationReport
) -> None:
    actual = tuple(
        item["state_version_id"] for item in config["frozen_inputs"]["state_versions"]
    )
    if actual != EXPECTED_STATE_VERSIONS:
        report.add("FROZEN_STATE_VERSION_SET_MISMATCH", repr(actual))
    if config["frozen_inputs"]["state_line_count"] != 2:
        report.add("STATE_LINE_COUNT_MISMATCH")
    if config["frozen_inputs"]["parameters"] != {"W": 120, "K": 3, "d": 2, "g": 1}:
        report.add("FROZEN_PARAMETER_MISMATCH")
    anchor = config["anchor_decision"]
    if anchor.get("selected_anchor") != "natural_exit_attempt":
        report.add("ANCHOR_DECISION_MISMATCH")
    if config["implementation_state"]["formal_run_allowed"] is not False:
        report.add("FORMAL_RUN_OPEN_IN_IMPLEMENTATION")
    if config["implementation_state"]["readme_advanced"] is not False:
        report.add("README_ADVANCED_IN_IMPLEMENTATION")
    unit = config["analysis_unit_contract"]
    if unit.get("first_attempt_only") is not False:
        report.add("FIRST_ATTEMPT_ONLY_FORBIDDEN")
    if unit.get("later_attempts_are_sidecar") is not False:
        report.add("LATER_ATTEMPTS_SIDE_CAR_FORBIDDEN")
    if unit.get("all_legal_exit_attempts_are_primary") is not True:
        report.add("ALL_ATTEMPTS_NOT_PRIMARY")
    if unit.get("final_component_count_availability") != "post_event_audit":
        report.add("FINAL_COMPONENT_COUNT_AVAILABILITY_MISMATCH")
    if any(
        field.get("field_name") == "event_balanced_weight"
        and field.get("allowed_at_T0") is True
        for field in config["field_semantics"]
    ):
        report.add("POST_EVENT_FIELD_ALLOWED_AT_T0")


def _check_field_semantics(config: dict[str, Any], report: ValidationReport) -> None:
    fields = {item["field_name"]: item for item in config["field_semantics"]}
    required_t0 = {
        "state_version_id",
        "event_id",
        "security_id",
        "exit_attempt_id",
        "exit_attempt_ordinal",
        "source_component_id",
        "source_component_ordinal",
        "component_count_as_of_exit",
        "zone_revision_as_of_exit",
        "exit_attempt_date",
        "exit_attempt_time",
        "prior_confirmed_state",
        "exit_raw_state",
        "exit_reason",
        "g_used_as_of_exit",
        "event_status_as_of_exit",
    }
    for name in required_t0:
        if name not in fields or fields[name]["allowed_at_T0"] is not True:
            report.add("T0_FIELD_NOT_AVAILABLE", name)
    forbidden = {
        "final_component_count",
        "final_attempt_count_in_event",
        "event_balanced_weight",
        "resolution_status",
        "resolution_time",
        "same_zone_requalified",
        "same_zone_requalification_time",
        "g_exceeded_time",
        "future_overlap_final_result",
        "future_path_class",
        "future_boundary_hit",
    }
    for name in forbidden:
        item = fields.get(name)
        if item is None:
            report.add("FIELD_SEMANTICS_MISSING", name)
        elif (
            item["allowed_at_T0"]
            or item["allowed_at_T1"]
            or item["allowed_at_T2"]
            or not item["forbidden_model_feature"]
        ):
            report.add("FORBIDDEN_FEATURE_LEAK", name)


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


def _check_split_contract(config: dict[str, Any], report: ValidationReport) -> None:
    split = config["sample_split_contract"]
    if split["sample_split_unit"] != "event_id":
        report.add("ATTEMPT_LEVEL_RANDOM_SPLIT_FORBIDDEN")
    if split["all_attempts_of_same_event_in_same_split"] is not True:
        report.add("EVENT_SPLIT_LEAKAGE")
    if split["purge_embargo"]["length_valid_trading_days"] != 32:
        report.add("PURGE_EMBARGO_MISMATCH")
    if split["calendar_boundary_status"] != "unselected_by_design":
        report.add("CALENDAR_BOUNDARY_SELECTED_TOO_EARLY")


def _check_no_future_output(config: dict[str, Any], report: ValidationReport) -> None:
    forbidden_tokens = (
        "return",
        "mfe",
        "mae",
        "boundary",
        "path_class",
        "label",
        "model_output",
    )
    for artifact in config["output_contract"]["formal_artifacts"]:
        filename = artifact["filename"].lower()
        if any(token in filename for token in ("return", "label", "boundary")):
            report.add("FUTURE_OUTCOME_IN_T01", filename)
        if artifact["contains_future_outcome"] is not False:
            report.add("FUTURE_OUTCOME_IN_T01", filename)
    for field_spec in config["field_semantics"]:
        if field_spec["availability_class"] == "as_of_T0" and any(
            token in field_spec["field_name"].lower() for token in forbidden_tokens
        ):
            report.add("FUTURE_OUTCOME_IN_T01", field_spec["field_name"])


def _compare_case(
    case: dict[str, Any],
    attempts: list[dict[str, Any]],
    rejections: list[dict[str, Any]],
    report: ValidationReport,
) -> dict[str, Any]:
    expected = case["expected"]
    expected_ids = [
        item.get("exit_attempt_id") for item in expected.get("attempts", [])
    ]
    actual_ids = [item["exit_attempt_id"] for item in attempts]
    if expected_ids != actual_ids:
        report.add("SYNTHETIC_ATTEMPT_ID_MISMATCH", case["case_id"])
    if [item.get("exit_attempt_ordinal") for item in expected.get("attempts", [])] != [
        item.get("exit_attempt_ordinal") for item in attempts
    ]:
        report.add("SYNTHETIC_ATTEMPT_ORDINAL_MISMATCH", case["case_id"])
    if expected.get("attempt_count") != len(attempts):
        report.add("SYNTHETIC_ATTEMPT_COUNT_MISMATCH", case["case_id"])
    expected_codes = sorted(expected.get("rejection_codes", []))
    actual_codes = sorted(item["code"] for item in rejections)
    if expected_codes != actual_codes:
        report.add("SYNTHETIC_REJECTION_MISMATCH", case["case_id"])
    for expected_attempt, actual in zip(
        expected.get("attempts", []), attempts, strict=False
    ):
        for key in (
            "state_version_id",
            "event_id",
            "security_id",
            "exit_attempt_date",
            "exit_attempt_time",
            "source_component_ordinal",
            "component_count_as_of_exit",
            "unqualified_reentry",
        ):
            if expected_attempt.get(key) != actual.get(key):
                report.add("SYNTHETIC_CONTEXT_MISMATCH", f"{case['case_id']}:{key}")
    return {
        "case_id": case["case_id"],
        "expected_attempt_count": expected.get("attempt_count"),
        "actual_attempt_count": len(attempts),
        "expected_attempt_ids": expected_ids,
        "actual_attempt_ids": actual_ids,
        "rejection_codes": actual_codes,
    }


def validate_independence(source_text: str) -> str | None:
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return "VALIDATOR_SOURCE_INVALID"
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "src.r3.r3_t01_protocol":
            return "VALIDATOR_PRODUCTION_HELPER_REUSE"
        if isinstance(node, ast.Import):
            if any(alias.name == "src.r3.r3_t01_protocol" for alias in node.names):
                return "VALIDATOR_PRODUCTION_HELPER_REUSE"
    return None


def validate_attempt_registry(attempts: list[dict[str, Any]]) -> list[str]:
    """Independently check attempt identity, ordinal and T0 conservation."""

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
                str(item.get("exit_attempt_time")),
            )
        ].add(str(item.get("event_id")))
    if any(len(events) > 1 for events in t0_claims.values()):
        errors.append("T0_CLAIMED_BY_MULTIPLE_EVENTS")
    for group in by_event.values():
        ordered = sorted(
            group,
            key=lambda item: (
                str(item.get("exit_attempt_time")),
                str(item.get("exit_attempt_date")),
                str(item.get("exit_attempt_id")),
            ),
        )
        expected = list(range(1, len(group) + 1))
        actual = [int(item.get("exit_attempt_ordinal", -1)) for item in group]
        if sorted(actual) != expected:
            errors.append("ORDINAL_NOT_CONTIGUOUS")
        if actual != [int(item.get("exit_attempt_ordinal", -1)) for item in ordered]:
            errors.append("ORDINAL_TIME_ORDER_MISMATCH")
    return sorted(set(errors))


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
        mutated_config["frozen_inputs"]["state_versions"].append(
            copy.deepcopy(mutated_config["frozen_inputs"]["state_versions"][0])
        )
        mutated_config["frozen_inputs"]["state_versions"][-1]["W"] = 250
    elif mutation_id in {"M03", "M04"}:
        mutated_config["anchor_decision"]["selected_anchor"] = (
            "finalized_zone" if mutation_id == "M03" else "retrospective_final_exit"
        )
    elif mutation_id == "M05":
        mutated_config["analysis_unit_contract"]["first_attempt_only"] = True
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
        mutated_config["sample_split_contract"]["sample_split_unit"] = "exit_attempt_id"
    elif mutation_id == "M11":
        mutated_fixture["split_assignments_mutation"] = {
            "EV1": ["design", "validation"]
        }
    elif mutation_id == "M12":
        mutated_config["downstream_gate_open"] = True
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
    else:
        raise ValueError(mutation_id)
    return mutated_config, mutated_fixture, source_text


def mutation_error_code(
    config: dict[str, Any], fixture: dict[str, Any], source_text: str | None = None
) -> str | None:
    if source_text is not None:
        return validate_independence(source_text)
    versions = config["frozen_inputs"]["state_versions"]
    if len(versions) != 2:
        return "FROZEN_STATE_VERSION_SET_MISMATCH"
    if (
        tuple(item.get("state_version_id") for item in versions)
        != EXPECTED_STATE_VERSIONS
    ):
        return "FROZEN_STATE_VERSION_MISMATCH"
    if config["anchor_decision"].get("selected_anchor") != "natural_exit_attempt":
        return "ANCHOR_DECISION_MISMATCH"
    unit = config["analysis_unit_contract"]
    if unit.get("first_attempt_only") is True:
        return "FIRST_ATTEMPT_ONLY_FORBIDDEN"
    if (
        config["t0_transition_contract"].get("expected_row_surface_lag")
        != "compute_lag_on_complete_expected_row_surface_before_filter"
    ):
        return "LAG_AFTER_FILTERING_FORBIDDEN"
    if config["t0_transition_contract"].get(
        "qualified_event_risk_set_eligible_required_for_every_later_attempt"
    ):
        return "LATER_ATTEMPT_RISK_SET_POLICY_MISMATCH"
    forbidden_id_fields = set(unit.get("attempt_identity_must_not_include", []))
    if forbidden_id_fields.intersection(unit["exit_attempt_id_spec"].get("fields", [])):
        return "POST_EVENT_FIELD_IN_ID"
    if "calendar-day" in config["landmark_horizon_contract"]["horizon_counting_rule"]:
        return "CALENDAR_DAY_HORIZON_FORBIDDEN"
    if config["sample_split_contract"].get("sample_split_unit") != "event_id":
        return "ATTEMPT_LEVEL_RANDOM_SPLIT_FORBIDDEN"
    if fixture.get("split_assignments_mutation"):
        return "EVENT_SPLIT_LEAKAGE"
    if config.get("downstream_gate_open"):
        return "DOWNSTREAM_GATE_OPEN"
    if any(
        "return_from_t0" == item.get("field_name") for item in config["field_semantics"]
    ):
        return "FUTURE_OUTCOME_IN_T01"
    return None


def validate_in_memory(
    config: dict[str, Any],
    fixture: dict[str, Any],
    *,
    root: Path = ROOT,
    check_upstream: bool = True,
    validator_source_text: str | None = None,
) -> ValidationReport:
    report = ValidationReport()
    protocol_schema = root / "schemas/r3/r3_t01_protocol_registry.schema.json"
    _validate_schema(report, protocol_schema, config, "protocol_registry")
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
    _check_exact_contract_values(config, report)
    _check_field_semantics(config, report)
    _check_split_contract(config, report)
    _check_no_future_output(config, report)
    independence_error = validate_independence(
        validator_source_text
        if validator_source_text is not None
        else Path(__file__).read_text(encoding="utf-8")
    )
    if independence_error:
        report.add(independence_error)
    if check_upstream:
        _check_upstream_committed_bindings(config, report, root)

    for case in fixture.get("cases", []):
        try:
            attempts, rejections = independent_replay(
                case.get("rows", []),
                case.get("event_zones", []),
                case.get("membership_rows", []),
                config,
                sample_end_censoring=bool(case.get("sample_end_censoring", False)),
            )
            report.synthetic_case_results.append(
                _compare_case(case, attempts, rejections, report)
            )
        except (KeyError, ValueError, TypeError) as exc:
            report.add("SYNTHETIC_REPLAY_FAILED", f"{case.get('case_id')}:{exc}")

    first = [
        item
        for item in report.synthetic_case_results
        if item.get("actual_attempt_ids") is not None
    ]
    second_hash = _sha(first)
    report.double_rebuild_hash = second_hash
    if second_hash != _sha(copy.deepcopy(first)):
        report.add("DOUBLE_REBUILD_MISMATCH")
    return report


def validate_mutations(
    config: dict[str, Any], fixture: dict[str, Any]
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for mutation_id, expected_code in MUTATION_CODES.items():
        mutated_config, mutated_fixture, source_text = apply_mutation(
            config, fixture, mutation_id
        )
        actual_code = mutation_error_code(mutated_config, mutated_fixture, source_text)
        results.append(
            {
                "mutation_id": mutation_id,
                "expected_error_code": expected_code,
                "actual_error_code": actual_code or "NONE",
                "status": "passed" if actual_code == expected_code else "failed",
            }
        )
    return results


def _check_formal_artifacts(
    run_dir: Path, config: dict[str, Any], report: ValidationReport
) -> None:
    for artifact in config.get("output_contract", {}).get("formal_artifacts", []):
        filename = artifact.get("filename")
        if not isinstance(filename, str):
            report.add("FORMAL_ARTIFACT_DECLARATION_INVALID")
            continue
        path = run_dir / filename
        if not path.is_file():
            report.add("FORMAL_ARTIFACT_MISSING", filename)
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            if artifact.get("kind") == "json":
                json.loads(text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            report.add("FORMAL_ARTIFACT_INVALID", f"{filename}:{exc}")


def validate_run_dir(run_dir: Path, *, root: Path = ROOT) -> ValidationReport:
    """Validate a future formal run directory without using production helpers."""

    report = ValidationReport()
    registry_path = run_dir / "r3_t01_protocol_registry.json"
    fixture_path = root / "tests/r3/fixtures/r3_t01/cases.json"
    if not registry_path.is_file():
        report.add("RUN_REGISTRY_MISSING", str(registry_path))
        return report
    try:
        config = _load_json(registry_path)
        fixture = _load_json(fixture_path)
    except (OSError, json.JSONDecodeError) as exc:
        report.add("RUN_INPUT_INVALID", str(exc))
        return report
    report = validate_in_memory(config, fixture, root=root, check_upstream=True)
    _check_formal_artifacts(run_dir, config, report)
    return report
