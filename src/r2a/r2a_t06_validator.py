"""Independent validator for the R2A-T06 implementation candidate."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.r2a.r2a_t06_consecutive_failure_exit import (
    EXIT_CONFIRMATION_VALUES,
    REQUEST_ORDER,
    load_t06_config,
    verify_accepted_bindings,
)
from src.r2a.r2a_t06_online_replay import replay_exit_lifecycle

_FORBIDDEN_FIELDS = {
    "future_price",
    "future_return",
    "return",
    "mfe",
    "mae",
    "future_path",
    "direction_label",
    "release_label",
    "trade_signal",
    "pnl",
}
_FORMAL_FILES = (
    "request_identity.json",
    "input_manifest.json",
    "run_summary.json",
    "validation_receipt.json",
    "result_analysis.md",
    "false_run_length_profile.csv",
    "recovery_hazard_profile.csv",
    "candidate_exit_summary.csv",
    "recognition_lag_profile.csv",
    "post_recognition_reentry.csv",
    "episode_fragmentation_profile.csv",
    "exit_type_margin_profile.csv",
    "cross_q_nesting_validation.csv",
    "year_profile.csv",
    "security_profile.csv",
    "deterministic_episode_samples.csv",
    "t06_detail.duckdb",
)


class _IndependentInputError(ValueError):
    pass


def _v_forbidden_path(value: Any, prefix: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            name = str(key).lower()
            path = f"{prefix}.{key}" if prefix else str(key)
            if name in _FORBIDDEN_FIELDS or name.startswith("future_"):
                return path
            found = _v_forbidden_path(nested, path)
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _v_forbidden_path(nested, f"{prefix}[{index}]")
            if found:
                return found
    return None


def _v_quality_reason(row: Mapping[str, Any]) -> str | None:
    expected = row.get("expected_observation_status")
    if expected == "missing":
        return "expected_observation_missing"
    if expected == "listing_pause":
        return "expected_observation_listing_pause"
    validity = row.get("joint_validity_status")
    if validity == "blocked":
        return "selected_dimension_blocked"
    if validity == "diagnostic_required":
        return "selected_dimension_diagnostic_required"
    if validity == "unknown":
        return "selected_dimension_unknown"
    codes = [str(value) for value in row.get("joint_reason_codes", [])]
    if any(code.endswith(":dimension_not_eligible") for code in codes):
        return "selected_dimension_not_eligible"
    if any(code.endswith(":score_non_finite") for code in codes):
        return "selected_dimension_score_non_finite"
    if row.get("joint_ready") is not True or row.get("raw_state") is None:
        return "selected_dimension_unknown"
    return None


def _v_exit_type(row: Mapping[str, Any]) -> str:
    active = row.get("dimension_active")
    if not isinstance(active, Mapping) or set(active) != {"C", "A"}:
        raise _IndependentInputError("dimension_active_required_for_valid_row")
    pair = (active["C"], active["A"])
    classes = {
        (False, True): "C_ONLY_FAIL",
        (True, False): "A_ONLY_FAIL",
        (False, False): "CA_BOTH_FAIL",
    }
    if pair not in classes:
        raise _IndependentInputError("raw_false_exit_type_invalid")
    return classes[pair]


def _v_normalize_rows(
    source: Sequence[Mapping[str, Any]], request_name: str
) -> list[dict[str, Any]]:
    rows = [deepcopy(dict(row)) for row in source]
    forbidden = _v_forbidden_path(rows)
    if forbidden:
        raise _IndependentInputError(f"forbidden_field:{forbidden}")
    try:
        rows.sort(
            key=lambda row: (
                str(row["security_id"]),
                int(row["observation_sequence"]),
            )
        )
    except (KeyError, TypeError, ValueError) as error:
        raise _IndependentInputError("observation_identity_invalid") from error
    seen: set[tuple[str, int]] = set()
    previous: dict[str, int] = {}
    for row in rows:
        security = row.get("security_id")
        sequence = row.get("observation_sequence")
        if (
            not isinstance(security, str)
            or not security
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
        ):
            raise _IndependentInputError("observation_identity_invalid")
        key = (security, sequence)
        if key in seen:
            raise _IndependentInputError("duplicate_observation_identity")
        seen.add(key)
        if security in previous and sequence != previous[security] + 1:
            raise _IndependentInputError("observation_sequence_gap")
        previous[security] = sequence
        if row.get("logical_request_name", request_name) != request_name:
            raise _IndependentInputError("observation_request_mismatch")
        row["logical_request_name"] = request_name
        if "confirmed_state_v1" not in row and "confirmed_state" in row:
            row["confirmed_state_v1"] = row["confirmed_state"]
        if row.get("confirmed_state_v1") not in (True, False, None):
            raise _IndependentInputError("confirmed_state_v1_domain_invalid")
        quality = _v_quality_reason(row)
        if quality is None and row.get("raw_state") not in (True, False):
            raise _IndependentInputError("valid_raw_state_domain_invalid")
        if row.get("confirmed_state_v1") is True and row.get("raw_state") is not True:
            raise _IndependentInputError("accepted_confirmed_raw_mismatch")
        row["quality_reason"] = quality
    return rows


def _v_stable_id(*parts: object) -> str:
    canonical = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:24]


class T06ValidationError(ValueError):
    """Fail-closed independent validation error."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(self.issues))


def _independent_lifecycle(
    source: Sequence[Mapping[str, Any]], request_name: str, exit_confirmation_m: int
) -> dict[str, list[dict[str, Any]]]:
    """Recalculate lifecycle without calling the production builder."""

    rows = _v_normalize_rows(source, request_name)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["security_id"])].append(row)
    observations: list[dict[str, Any]] = []
    triggers: list[dict[str, Any]] = []
    episodes: list[dict[str, Any]] = []
    for security_id in sorted(grouped):
        is_active = False
        pending: dict[str, Any] | None = None
        episode: dict[str, Any] | None = None
        ordinal = -1
        for original in grouped[security_id]:
            row = deepcopy(original)
            quality = row.pop("quality_reason")
            sequence = int(row["observation_sequence"])
            state = "INACTIVE"
            fail_streak = 0
            trigger_time = None
            trigger_sequence = None
            recognition_time = None
            recognition_sequence = None
            cancelled = False
            cancellation_time = None
            termination_class = None
            if not is_active and quality is None and row["confirmed_state_v1"] is True:
                ordinal += 1
                baseline = row.get("confirmed_interval_ordinal")
                if baseline is None:
                    raise _IndependentInputError("confirmed_interval_ordinal_missing")
                is_active = True
                episode = {
                    "logical_request_name": request_name,
                    "security_id": security_id,
                    "exit_confirmation_m": exit_confirmation_m,
                    "episode_ordinal": ordinal,
                    "episode_id": _v_stable_id(
                        request_name, security_id, exit_confirmation_m, ordinal
                    ),
                    "episode_identity": _v_stable_id(
                        request_name, security_id, baseline
                    ),
                    "baseline_anchor_interval_ordinal": int(baseline),
                    "start_time": row.get("trading_date"),
                    "start_observation_sequence": sequence,
                    "active_observation_count": 0,
                    "bridged_false_observation_count": 0,
                }
            if is_active:
                assert episode is not None
                if quality is not None:
                    state = "QUALITY_TERMINATED"
                    termination_class = "QUALITY_TERMINATED"
                    if pending:
                        pending.update(
                            {
                                "disposition": "QUALITY_TERMINATED",
                                "quality_reason": quality,
                                "termination_time": row.get("trading_date"),
                                "termination_observation_sequence": sequence,
                            }
                        )
                        triggers.append(pending)
                        pending = None
                    episode.update(
                        {
                            "end_time": row.get("trading_date"),
                            "end_observation_sequence": sequence,
                            "termination_class": termination_class,
                            "quality_reason": quality,
                            "right_censored": False,
                        }
                    )
                    episodes.append(episode)
                    episode = None
                    is_active = False
                elif row["raw_state"] is True:
                    state = "ACTIVE"
                    episode["active_observation_count"] += 1
                    if pending:
                        pending.update(
                            {
                                "disposition": "CANCELLED",
                                "provisional_exit_cancelled": True,
                                "cancellation_time": row.get("trading_date"),
                                "cancellation_observation_sequence": sequence,
                            }
                        )
                        triggers.append(pending)
                        trigger_time = pending["exit_trigger_time"]
                        trigger_sequence = pending["exit_trigger_observation_sequence"]
                        cancelled = True
                        cancellation_time = row.get("trading_date")
                        pending = None
                else:
                    kind = _v_exit_type(row)
                    if pending is None:
                        pending = {
                            "logical_request_name": request_name,
                            "security_id": security_id,
                            "exit_confirmation_m": exit_confirmation_m,
                            "trigger_id": _v_stable_id(
                                request_name,
                                security_id,
                                episode["baseline_anchor_interval_ordinal"],
                                sequence,
                            ),
                            "episode_id": episode["episode_id"],
                            "episode_identity": episode["episode_identity"],
                            "baseline_anchor_interval_ordinal": episode[
                                "baseline_anchor_interval_ordinal"
                            ],
                            "exit_trigger_time": row.get("trading_date"),
                            "exit_trigger_observation_sequence": sequence,
                            "exit_type": kind,
                            "false_run_length_observed": 0,
                            "provisional_exit_cancelled": False,
                            "cancellation_time": None,
                            "cancellation_observation_sequence": None,
                            "exit_recognition_time": None,
                            "exit_recognition_observation_sequence": None,
                            "recognition_lag": None,
                            "quality_reason": None,
                            "termination_time": None,
                            "termination_observation_sequence": None,
                            "disposition": "PENDING",
                        }
                    pending["false_run_length_observed"] += 1
                    episode["bridged_false_observation_count"] += 1
                    fail_streak = int(pending["false_run_length_observed"])
                    trigger_time = pending["exit_trigger_time"]
                    trigger_sequence = pending["exit_trigger_observation_sequence"]
                    if fail_streak == exit_confirmation_m:
                        state = "EXIT_RECOGNIZED"
                        recognition_time = row.get("trading_date")
                        recognition_sequence = sequence
                        pending.update(
                            {
                                "disposition": "EXIT_RECOGNIZED",
                                "exit_recognition_time": recognition_time,
                                "exit_recognition_observation_sequence": sequence,
                                "recognition_lag": sequence - int(trigger_sequence),
                            }
                        )
                        triggers.append(pending)
                        episode.update(
                            {
                                "end_time": recognition_time,
                                "end_observation_sequence": sequence,
                                "termination_class": "EXIT_RECOGNIZED",
                                "quality_reason": None,
                                "right_censored": False,
                            }
                        )
                        episodes.append(episode)
                        episode = None
                        pending = None
                        is_active = False
                        termination_class = "EXIT_RECOGNIZED"
                    else:
                        state = "EXIT_PENDING"
            observations.append(
                {
                    **row,
                    "exit_confirmation_m": exit_confirmation_m,
                    "lifecycle_state": state,
                    "fail_streak": fail_streak,
                    "exit_trigger_time": trigger_time,
                    "exit_trigger_observation_sequence": trigger_sequence,
                    "exit_recognition_time": recognition_time,
                    "exit_recognition_observation_sequence": recognition_sequence,
                    "recognition_lag": (
                        None
                        if recognition_sequence is None
                        else recognition_sequence - int(trigger_sequence)
                    ),
                    "provisional_exit_cancelled": cancelled,
                    "cancellation_time": cancellation_time,
                    "termination_class": termination_class,
                    "quality_reason": quality,
                    "right_censored": False,
                }
            )
        if is_active:
            assert episode is not None
            last = observations[-1]
            if pending:
                last.update(
                    {
                        "lifecycle_state": "PENDING_RIGHT_CENSORED",
                        "termination_class": "PENDING_RIGHT_CENSORED",
                        "right_censored": True,
                    }
                )
                pending["disposition"] = "PENDING_RIGHT_CENSORED"
                triggers.append(pending)
                termination = "PENDING_RIGHT_CENSORED"
            else:
                last["right_censored"] = True
                termination = "ACTIVE_RIGHT_CENSORED"
            episode.update(
                {
                    "end_time": last.get("trading_date"),
                    "end_observation_sequence": last["observation_sequence"],
                    "termination_class": termination,
                    "quality_reason": None,
                    "right_censored": True,
                }
            )
            episodes.append(episode)
    return {
        "observation_rows": observations,
        "trigger_rows": triggers,
        "episode_rows": episodes,
    }


def _summary(expected: Mapping[str, Any], request_name: str, m: int) -> dict[str, Any]:
    triggers = expected["trigger_rows"]
    episodes = expected["episode_rows"]
    counts = Counter(row["disposition"] for row in triggers)
    recognized = [row for row in triggers if row["disposition"] == "EXIT_RECOGNIZED"]
    return {
        "logical_request_name": request_name,
        "exit_confirmation_m": m,
        "provisional_exit_count": len(triggers),
        "recognized_exit_count": len(recognized),
        "cancelled_exit_count": counts["CANCELLED"],
        "quality_terminated_pending_count": counts["QUALITY_TERMINATED"],
        "pending_right_censored_count": counts["PENDING_RIGHT_CENSORED"],
        "cancel_rate": counts["CANCELLED"] / len(triggers) if triggers else None,
        "recognition_lags": sorted(row["recognition_lag"] for row in recognized),
        "episode_count": len(episodes),
        "bridged_false_observation_count": sum(
            int(row["bridged_false_observation_count"]) for row in episodes
        ),
    }


def _interleaved_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_security: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_security[str(row["security_id"])].append(deepcopy(dict(row)))
    output: list[dict[str, Any]] = []
    index = 0
    while True:
        added = False
        for security in sorted(by_security):
            if index < len(by_security[security]):
                output.append(by_security[security][index])
                added = True
        if not added:
            return output
        index += 1


def _chunk_partitions(rows: Sequence[Mapping[str, Any]]) -> list[list[int]]:
    count = len(rows)
    if count == 0:
        return [[]]
    partitions: list[list[int]] = [[1] * count]
    fixed = [3] * (count // 3)
    if count % 3:
        fixed.append(count % 3)
    partitions.append(fixed)
    generator = random.Random(20260723)
    random_sizes: list[int] = []
    remaining = count
    while remaining:
        size = min(generator.randint(1, 4), remaining)
        random_sizes.append(size)
        remaining -= size
    partitions.append(random_sizes)
    boundary_indexes: set[int] = set()
    for index, row in enumerate(rows[:-1], start=1):
        if row.get("raw_state") is False:
            boundary_indexes.add(index)
        next_row = rows[index]
        if next_row.get("raw_state") is True or _v_quality_reason(next_row) is not None:
            boundary_indexes.add(index)
    for boundary in sorted(boundary_indexes):
        partitions.append([boundary, count - boundary])
    unique: list[list[int]] = []
    for partition in partitions:
        if partition not in unique:
            unique.append(partition)
    return unique


def _validate_online_equivalence(
    source: Sequence[Mapping[str, Any]],
    actual: Mapping[str, Any],
    request_name: str,
    m: int,
) -> list[str]:
    normalized = _v_normalize_rows(source, request_name)
    replay_rows = _interleaved_rows(normalized)
    issues: list[str] = []
    for index, chunks in enumerate(_chunk_partitions(replay_rows)):
        replay = replay_exit_lifecycle(
            replay_rows,
            logical_request_name=request_name,
            exit_confirmation_m=m,
            chunk_sizes=chunks,
        )
        for field in ("observation_rows", "trigger_rows", "episode_rows"):
            if replay[field] != actual.get(field):
                issues.append(
                    f"online_replay_mismatch:{request_name}:M{m}:P{index}:{field}"
                )
        if _summary(replay, request_name, m) != _summary(actual, request_name, m):
            issues.append(
                f"online_replay_mismatch:{request_name}:M{m}:P{index}:summary"
            )
    return issues


def _episode_set(candidate: Mapping[str, Any], m: int, disposition: str) -> set[str]:
    return {
        str(trigger["episode_identity"])
        for result in candidate["candidates"]
        if result["exit_confirmation_m"] == m
        for trigger in result["trigger_rows"]
        if trigger["disposition"] == disposition
    }


def _independent_cross_q(
    source_by_request: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    normalized = {
        name: {
            (row["security_id"], row["observation_sequence"]): row
            for row in _v_normalize_rows(source_by_request[name], name)
        }
        for name in REQUEST_ORDER
    }
    checks: list[dict[str, Any]] = []
    for child, parent in zip(REQUEST_ORDER, REQUEST_ORDER[1:]):
        child_rows = normalized[child]
        parent_rows = normalized[parent]
        if set(child_rows) != set(parent_rows):
            raise _IndependentInputError("cross_q_observation_spine_mismatch")
        raw_violations = sum(
            child_rows[key]["raw_state"] is True
            and parent_rows[key]["raw_state"] is not True
            for key in child_rows
        )
        confirmed_violations = sum(
            child_rows[key]["confirmed_state_v1"] is True
            and parent_rows[key]["confirmed_state_v1"] is not True
            for key in child_rows
        )
        checks.append(
            {
                "child": child,
                "parent": parent,
                "raw_violation_count": raw_violations,
                "confirmed_violation_count": confirmed_violations,
                "status": (
                    "passed"
                    if raw_violations == 0 and confirmed_violations == 0
                    else "failed"
                ),
            }
        )
    return checks


def _v_episode_memberships(result: Mapping[str, Any]) -> list[set[tuple[str, int]]]:
    memberships: list[set[tuple[str, int]]] = []
    for episode in result.get("episode_rows", []):
        security = str(episode["security_id"])
        start = int(episode["start_observation_sequence"])
        end = int(episode["end_observation_sequence"])
        memberships.append(
            {
                (security, int(row["observation_sequence"]))
                for row in result.get("observation_rows", [])
                if row["security_id"] == security
                and start <= int(row["observation_sequence"]) <= end
                and row["lifecycle_state"] in {"ACTIVE", "EXIT_PENDING"}
            }
        )
    return memberships


def _independent_candidate_cross_q(
    source_by_request: Mapping[str, Sequence[Mapping[str, Any]]],
    candidate: Mapping[str, Any],
) -> list[dict[str, Any]]:
    input_checks = _independent_cross_q(source_by_request)
    input_by_pair = {(row["child"], row["parent"]): row for row in input_checks}
    actual = {
        (row["logical_request_name"], int(row["exit_confirmation_m"])): row
        for row in candidate.get("candidates", [])
    }
    output: list[dict[str, Any]] = []
    for m in EXIT_CONFIRMATION_VALUES:
        for child, parent in zip(REQUEST_ORDER, REQUEST_ORDER[1:]):
            child_result = actual[(child, m)]
            parent_result = actual[(parent, m)]
            child_active = {
                (row["security_id"], int(row["observation_sequence"]))
                for row in child_result.get("observation_rows", [])
                if row["lifecycle_state"] in {"ACTIVE", "EXIT_PENDING"}
            }
            parent_active = {
                (row["security_id"], int(row["observation_sequence"]))
                for row in parent_result.get("observation_rows", [])
                if row["lifecycle_state"] in {"ACTIVE", "EXIT_PENDING"}
            }
            violations = len(child_active - parent_active)
            children = _v_episode_memberships(child_result)
            parents = _v_episode_memberships(parent_result)
            mapped = 0
            unmapped = 0
            multi = 0
            for keys in children:
                containing = [
                    parent_keys
                    for parent_keys in parents
                    if keys and keys <= parent_keys
                ]
                intersecting = [
                    parent_keys for parent_keys in parents if keys & parent_keys
                ]
                if len(containing) == 1:
                    mapped += 1
                elif len(containing) > 1 or len(intersecting) > 1:
                    multi += 1
                else:
                    unmapped += 1
            input_row = input_by_pair[(child, parent)]
            mapping_status = "passed" if unmapped == 0 and multi == 0 else "failed"
            overall = (
                "passed"
                if input_row["status"] == "passed"
                and violations == 0
                and mapping_status == "passed"
                else "failed"
            )
            output.append(
                {
                    "exit_confirmation_m": m,
                    "child_request": child,
                    "parent_request": parent,
                    "raw_violation_count": input_row["raw_violation_count"],
                    "confirmed_violation_count": input_row["confirmed_violation_count"],
                    "active_or_pending_violation_count": violations,
                    "child_episode_count": len(children),
                    "mapped_child_episode_count": mapped,
                    "unmapped_child_episode_count": unmapped,
                    "multi_parent_child_episode_count": multi,
                    "mapping_status": mapping_status,
                    "overall_status": overall,
                }
            )
    return output


def _v_false_run_inventory(
    observations: Sequence[Mapping[str, Any]],
    triggers: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_security: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in observations:
        by_security[str(row["security_id"])].append(row)
    indexed: dict[str, dict[int, Mapping[str, Any]]] = {}
    for security, rows in by_security.items():
        ordered = sorted(rows, key=lambda row: int(row["observation_sequence"]))
        sequences = [int(row["observation_sequence"]) for row in ordered]
        if len(sequences) != len(set(sequences)) or any(
            right != left + 1 for left, right in zip(sequences, sequences[1:])
        ):
            raise _IndependentInputError("false_run_observation_sequence_invalid")
        indexed[security] = {int(row["observation_sequence"]): row for row in ordered}
    output: list[dict[str, Any]] = []
    for trigger in sorted(
        triggers,
        key=lambda row: (
            row["security_id"],
            row["exit_trigger_observation_sequence"],
            row["trigger_id"],
        ),
    ):
        security = str(trigger["security_id"])
        start = int(trigger["exit_trigger_observation_sequence"])
        rows = indexed[security]
        if start not in rows or rows[start].get("raw_state") is not False:
            raise _IndependentInputError("false_run_trigger_invalid")
        length = 0
        sequence = start
        end_class = "INPUT_END"
        next_available = False
        next_raw = None
        quality = None
        right_censored = True
        while True:
            current = rows[sequence]
            if (
                current.get("raw_state") is not False
                or current.get("quality_reason") is not None
            ):
                raise _IndependentInputError("false_run_internal_state_invalid")
            length += 1
            next_sequence = sequence + 1
            if next_sequence not in rows:
                break
            following = rows[next_sequence]
            quality = following.get("quality_reason")
            if quality is not None:
                end_class = "QUALITY_INTERRUPTION"
                right_censored = False
                break
            if following.get("raw_state") is True:
                end_class = "VALID_RAW_TRUE"
                next_available = True
                next_raw = True
                right_censored = False
                break
            if following.get("raw_state") is not False:
                raise _IndependentInputError("false_run_next_state_invalid")
            sequence = next_sequence
        output.append(
            {
                "trigger_id": trigger["trigger_id"],
                "episode_identity": trigger["episode_identity"],
                "security_id": security,
                "logical_request_name": trigger["logical_request_name"],
                "trigger_observation_sequence": start,
                "trigger_exit_type": trigger["exit_type"],
                "false_run_length": length,
                "run_end_class": end_class,
                "next_valid_observation_available": next_available,
                "next_valid_raw_state": next_raw,
                "quality_reason": quality,
                "right_censored": right_censored,
            }
        )
    return output


def _v_false_run_profile(
    inventory: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    counts = Counter(
        (row["trigger_exit_type"], int(row["false_run_length"])) for row in inventory
    )
    return [
        {
            "trigger_exit_type": exit_type,
            "false_run_length": length,
            "run_count": count,
        }
        for (exit_type, length), count in sorted(counts.items())
    ]


def _v_hazard(inventory: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for streak in (1, 2, 3):
        denominator = sum(
            int(row["false_run_length"]) > streak
            or (
                int(row["false_run_length"]) == streak
                and row["run_end_class"] == "VALID_RAW_TRUE"
            )
            for row in inventory
        )
        numerator = sum(
            int(row["false_run_length"]) == streak
            and row["run_end_class"] == "VALID_RAW_TRUE"
            for row in inventory
        )
        output.append(
            {
                "false_streak": streak,
                "observable_denominator": denominator,
                "recovery_count": numerator,
                "hazard": numerator / denominator if denominator else None,
            }
        )
    return output


def validate_t06_candidate(
    source_by_request: Mapping[str, Sequence[Mapping[str, Any]]],
    candidate: Mapping[str, Any],
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Independently recalculate all lifecycle rows and fail closed on mismatch."""

    loaded = dict(config or load_t06_config())
    verify_accepted_bindings(loaded)
    issues: list[str] = []
    if candidate.get("winner_selected") is not False:
        issues.append("winner_selected_before_formal_review")
    if candidate.get("selected_exit_confirmation_m") is not None:
        issues.append("selected_m_before_formal_review")
    if any(
        candidate.get(field) is not False
        for field in (
            "formal_run_executed",
            "real_score_data_read",
            "formal_artifacts_generated",
        )
    ):
        issues.append("implementation_boundary_violation")
    actual_by_key = {
        (item["logical_request_name"], item["exit_confirmation_m"]): item
        for item in candidate.get("candidates", [])
    }
    expected_summaries: list[dict[str, Any]] = []
    for name in REQUEST_ORDER:
        for m in EXIT_CONFIRMATION_VALUES:
            key = (name, m)
            actual = actual_by_key.get(key)
            if actual is None:
                issues.append(f"candidate_missing:{name}:M{m}")
                continue
            expected = _independent_lifecycle(source_by_request[name], name, m)
            for field in ("observation_rows", "trigger_rows", "episode_rows"):
                if actual.get(field) != expected[field]:
                    issues.append(
                        f"independent_recalculation_mismatch:{name}:M{m}:{field}"
                    )
            issues.extend(
                _validate_online_equivalence(source_by_request[name], actual, name, m)
            )
            inventory = _v_false_run_inventory(
                expected["observation_rows"], expected["trigger_rows"]
            )
            if actual.get("false_run_inventory") != inventory:
                issues.append(f"false_run_inventory_mismatch:{name}:M{m}")
            if actual.get("false_run_length_profile") != _v_false_run_profile(
                inventory
            ):
                issues.append(f"false_run_profile_mismatch:{name}:M{m}")
            if actual.get("recovery_hazard_profile") != _v_hazard(inventory):
                issues.append(f"recovery_hazard_mismatch:{name}:M{m}")
            expected_summaries.append(_summary(expected, name, m))
            source_rows = _v_normalize_rows(source_by_request[name], name)
            output_rows = actual.get("observation_rows", [])
            if len(source_rows) != len(output_rows):
                issues.append(f"daily_row_count_mismatch:{name}:M{m}")
            else:
                for source, output in zip(source_rows, output_rows, strict=True):
                    for field in ("raw_state", "confirmed_state_v1"):
                        if source[field] is not output.get(field):
                            issues.append(
                                f"accepted_daily_fact_modified:{name}:M{m}:{field}"
                            )
                            break
            for trigger in actual.get("trigger_rows", []):
                if trigger["disposition"] == "EXIT_RECOGNIZED":
                    if trigger["recognition_lag"] != m - 1:
                        issues.append(f"recognition_lag_mismatch:{name}:M{m}")
                if (
                    trigger["disposition"] == "QUALITY_TERMINATED"
                    and trigger["termination_observation_sequence"]
                    <= trigger["exit_trigger_observation_sequence"]
                ):
                    issues.append(f"quality_termination_order_invalid:{name}:M{m}")
    if candidate.get("candidate_exit_summary") != expected_summaries:
        issues.append("candidate_summary_reconciliation_mismatch")
    cross_q = _independent_candidate_cross_q(source_by_request, candidate)
    if any(row["overall_status"] != "passed" for row in cross_q):
        issues.append("cross_q_nesting_violation")
    if candidate.get("cross_q_nesting_validation") != cross_q:
        issues.append("cross_q_nesting_reconciliation_mismatch")
    recognized_1 = _episode_set(candidate, 1, "EXIT_RECOGNIZED")
    recognized_2 = _episode_set(candidate, 2, "EXIT_RECOGNIZED")
    recognized_3 = _episode_set(candidate, 3, "EXIT_RECOGNIZED")
    if not recognized_3 <= recognized_2 <= recognized_1:
        issues.append("recognized_episode_set_non_monotone")
    cancelled_2 = _episode_set(candidate, 2, "CANCELLED")
    cancelled_3 = _episode_set(candidate, 3, "CANCELLED")
    if not cancelled_2 <= cancelled_3:
        issues.append("cancelled_episode_set_non_monotone")
    if issues:
        raise T06ValidationError(issues)
    return {
        "task_id": "R2A-T06",
        "status": "passed",
        "independent_recalculation": True,
        "accepted_daily_fact_immutability": True,
        "online_replay_equivalence": True,
        "false_run_inventory_recalculation": "passed",
        "recovery_hazard_recalculation": "passed",
        "recognition_lag_validation": "passed",
        "quality_interruption_validation": "passed",
        "recognized_episode_set_nesting": "passed",
        "cancelled_episode_set_nesting": "passed",
        "cross_q_nesting": "passed",
        "candidate_lifecycle_cross_q_mapping": "passed",
        "mismatch_count": 0,
    }


def validate_t06_result_package(package: Mapping[str, Any]) -> dict[str, Any]:
    """Apply JSON Schema plus independent exact-file inventory checks."""

    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "schemas/r2a/r2a_t06_result_package.schema.json").read_text(
            encoding="utf-8"
        )
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(package), key=str)
    issues = [f"schema:{error.json_path}:{error.message}" for error in errors]
    status = package.get("status")
    if status in {"formal_completed_pending_owner_review", "completed_accepted"}:
        paths = [str(row.get("relative_path")) for row in package.get("files", [])]
        counts = Counter(paths)
        for name in _FORMAL_FILES:
            if counts[name] != 1:
                issues.append(f"formal_file_cardinality:{name}:{counts[name]}")
        extras = sorted(set(paths) - set(_FORMAL_FILES))
        if extras:
            issues.append(f"formal_file_unexpected:{','.join(extras)}")
    if issues:
        raise T06ValidationError(issues)
    return {
        "task_id": "R2A-T06",
        "status": "passed",
        "schema_validation": True,
        "formal_file_inventory_exact": status != "implementation_candidate",
        "issue_count": 0,
    }
