"""Independent validator for the R2A-T06 implementation candidate."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from src.r2a.r2a_t06_consecutive_failure_exit import (
    EXIT_CONFIRMATION_VALUES,
    REQUEST_ORDER,
    T06Error,
    _exit_type,
    _normalize_rows,
    _stable_id,
    load_t06_config,
    verify_accepted_bindings,
)


class T06ValidationError(ValueError):
    """Fail-closed independent validation error."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(self.issues))


def _independent_lifecycle(
    source: Sequence[Mapping[str, Any]], request_name: str, exit_confirmation_m: int
) -> dict[str, list[dict[str, Any]]]:
    """Recalculate lifecycle without calling the production builder."""

    rows = _normalize_rows(source, request_name)
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
                    raise T06Error("confirmed_interval_ordinal_missing")
                is_active = True
                episode = {
                    "logical_request_name": request_name,
                    "security_id": security_id,
                    "exit_confirmation_m": exit_confirmation_m,
                    "episode_ordinal": ordinal,
                    "episode_id": _stable_id(
                        request_name, security_id, exit_confirmation_m, ordinal
                    ),
                    "episode_identity": _stable_id(request_name, security_id, baseline),
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
                    kind = _exit_type(row)
                    if pending is None:
                        pending = {
                            "logical_request_name": request_name,
                            "security_id": security_id,
                            "exit_confirmation_m": exit_confirmation_m,
                            "trigger_id": _stable_id(
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
            for row in _normalize_rows(source_by_request[name], name)
        }
        for name in REQUEST_ORDER
    }
    checks: list[dict[str, Any]] = []
    for child, parent in zip(REQUEST_ORDER, REQUEST_ORDER[1:]):
        child_rows = normalized[child]
        parent_rows = normalized[parent]
        if set(child_rows) != set(parent_rows):
            raise T06Error("cross_q_observation_spine_mismatch")
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
            expected_summaries.append(_summary(expected, name, m))
            source_rows = _normalize_rows(source_by_request[name], name)
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
    cross_q = _independent_cross_q(source_by_request)
    if any(row["status"] != "passed" for row in cross_q):
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
        "recognition_lag_validation": "passed",
        "quality_interruption_validation": "passed",
        "recognized_episode_set_nesting": "passed",
        "cancelled_episode_set_nesting": "passed",
        "cross_q_nesting": "passed",
        "mismatch_count": 0,
    }
