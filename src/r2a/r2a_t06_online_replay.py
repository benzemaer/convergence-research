"""Stateful one-observation-at-a-time replay for R2A-T06."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from src.r2a.r2a_t06_consecutive_failure_exit import (
    EXIT_CONFIRMATION_VALUES,
    T06Error,
    _exit_type,
    _normalize_rows,
    _stable_id,
)


def initialize_security_state(
    security_id: str, logical_request_name: str, exit_confirmation_m: int
) -> dict[str, Any]:
    if exit_confirmation_m not in EXIT_CONFIRMATION_VALUES:
        raise T06Error("exit_confirmation_m_invalid")
    return {
        "security_id": security_id,
        "logical_request_name": logical_request_name,
        "exit_confirmation_m": exit_confirmation_m,
        "active": False,
        "pending": None,
        "current_episode": None,
        "episode_ordinal": -1,
        "last_observation_sequence": None,
        "completed_observation_rows": [],
        "completed_trigger_rows": [],
        "completed_episode_rows": [],
        "finalized": False,
    }


def consume_observation(state: dict[str, Any], source: Mapping[str, Any]) -> None:
    """Consume exactly one observation while retaining all carry state."""

    if state["finalized"]:
        raise T06Error("online_state_already_finalized")
    rows = _normalize_rows([source], state["logical_request_name"])
    row = rows[0]
    if row["security_id"] != state["security_id"]:
        raise T06Error("online_security_mismatch")
    sequence = int(row["observation_sequence"])
    previous = state["last_observation_sequence"]
    if previous is not None and sequence != previous + 1:
        raise T06Error("observation_sequence_gap")
    state["last_observation_sequence"] = sequence
    quality = row.pop("quality_reason")
    lifecycle_state = "INACTIVE"
    fail_streak = 0
    trigger_time = None
    trigger_sequence = None
    recognition_time = None
    recognition_sequence = None
    cancelled = False
    cancellation_time = None
    termination_class = None

    if not state["active"] and quality is None and row["confirmed_state_v1"] is True:
        baseline = row.get("confirmed_interval_ordinal")
        if baseline is None:
            raise T06Error("confirmed_interval_ordinal_missing")
        state["active"] = True
        state["episode_ordinal"] += 1
        state["current_episode"] = {
            "logical_request_name": state["logical_request_name"],
            "security_id": state["security_id"],
            "exit_confirmation_m": state["exit_confirmation_m"],
            "episode_ordinal": state["episode_ordinal"],
            "episode_id": _stable_id(
                state["logical_request_name"],
                state["security_id"],
                state["exit_confirmation_m"],
                state["episode_ordinal"],
            ),
            "episode_identity": _stable_id(
                state["logical_request_name"], state["security_id"], int(baseline)
            ),
            "baseline_anchor_interval_ordinal": int(baseline),
            "start_time": row.get("trading_date"),
            "start_observation_sequence": sequence,
            "active_observation_count": 0,
            "bridged_false_observation_count": 0,
        }

    if state["active"]:
        episode = state["current_episode"]
        assert episode is not None
        pending = state["pending"]
        if quality is not None:
            lifecycle_state = "QUALITY_TERMINATED"
            termination_class = "QUALITY_TERMINATED"
            if pending is not None:
                pending.update(
                    {
                        "disposition": "QUALITY_TERMINATED",
                        "quality_reason": quality,
                        "termination_time": row.get("trading_date"),
                        "termination_observation_sequence": sequence,
                    }
                )
                state["completed_trigger_rows"].append(pending)
                state["pending"] = None
            episode.update(
                {
                    "end_time": row.get("trading_date"),
                    "end_observation_sequence": sequence,
                    "termination_class": termination_class,
                    "quality_reason": quality,
                    "right_censored": False,
                }
            )
            state["completed_episode_rows"].append(episode)
            state["current_episode"] = None
            state["active"] = False
        elif row["raw_state"] is True:
            lifecycle_state = "ACTIVE"
            episode["active_observation_count"] += 1
            if pending is not None:
                pending.update(
                    {
                        "disposition": "CANCELLED",
                        "provisional_exit_cancelled": True,
                        "cancellation_time": row.get("trading_date"),
                        "cancellation_observation_sequence": sequence,
                    }
                )
                state["completed_trigger_rows"].append(pending)
                trigger_time = pending["exit_trigger_time"]
                trigger_sequence = pending["exit_trigger_observation_sequence"]
                cancelled = True
                cancellation_time = row.get("trading_date")
                state["pending"] = None
        else:
            if pending is None:
                pending = {
                    "logical_request_name": state["logical_request_name"],
                    "security_id": state["security_id"],
                    "exit_confirmation_m": state["exit_confirmation_m"],
                    "trigger_id": _stable_id(
                        state["logical_request_name"],
                        state["security_id"],
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
                    "exit_type": _exit_type(row),
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
                state["pending"] = pending
            pending["false_run_length_observed"] += 1
            episode["bridged_false_observation_count"] += 1
            fail_streak = int(pending["false_run_length_observed"])
            trigger_time = pending["exit_trigger_time"]
            trigger_sequence = pending["exit_trigger_observation_sequence"]
            if fail_streak == state["exit_confirmation_m"]:
                lifecycle_state = "EXIT_RECOGNIZED"
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
                state["completed_trigger_rows"].append(pending)
                episode.update(
                    {
                        "end_time": recognition_time,
                        "end_observation_sequence": sequence,
                        "termination_class": "EXIT_RECOGNIZED",
                        "quality_reason": None,
                        "right_censored": False,
                    }
                )
                state["completed_episode_rows"].append(episode)
                state["pending"] = None
                state["current_episode"] = None
                state["active"] = False
                termination_class = "EXIT_RECOGNIZED"
            else:
                lifecycle_state = "EXIT_PENDING"

    state["completed_observation_rows"].append(
        {
            **row,
            "exit_confirmation_m": state["exit_confirmation_m"],
            "lifecycle_state": lifecycle_state,
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


def finalize_security_state(state: dict[str, Any]) -> None:
    if state["finalized"]:
        raise T06Error("online_state_already_finalized")
    if state["active"]:
        episode = state["current_episode"]
        assert episode is not None
        last = state["completed_observation_rows"][-1]
        pending = state["pending"]
        if pending is not None:
            last.update(
                {
                    "lifecycle_state": "PENDING_RIGHT_CENSORED",
                    "termination_class": "PENDING_RIGHT_CENSORED",
                    "right_censored": True,
                }
            )
            pending["disposition"] = "PENDING_RIGHT_CENSORED"
            state["completed_trigger_rows"].append(pending)
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
        state["completed_episode_rows"].append(episode)
    state["finalized"] = True


def replay_exit_lifecycle(
    observations: Sequence[Mapping[str, Any]],
    *,
    logical_request_name: str,
    exit_confirmation_m: int,
    chunk_sizes: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Replay interleaved securities while carrying state across chunks."""

    rows = [deepcopy(dict(row)) for row in observations]
    if chunk_sizes is None:
        chunk_sizes = [1] * len(rows)
    if any(
        isinstance(size, bool) or not isinstance(size, int) or size < 1
        for size in chunk_sizes
    ):
        raise T06Error("online_chunk_size_invalid")
    if sum(chunk_sizes) != len(rows):
        raise T06Error("online_chunk_partition_mismatch")
    states: dict[str, dict[str, Any]] = {}
    offset = 0
    for size in chunk_sizes:
        for row in rows[offset : offset + size]:
            security_id = str(row.get("security_id", ""))
            if security_id not in states:
                states[security_id] = initialize_security_state(
                    security_id, logical_request_name, exit_confirmation_m
                )
            consume_observation(states[security_id], row)
        offset += size
    for security_id in sorted(states):
        finalize_security_state(states[security_id])
    observation_rows = sorted(
        (
            row
            for state in states.values()
            for row in state["completed_observation_rows"]
        ),
        key=lambda row: (row["security_id"], row["observation_sequence"]),
    )
    trigger_rows = sorted(
        (row for state in states.values() for row in state["completed_trigger_rows"]),
        key=lambda row: (
            row["security_id"],
            row["exit_trigger_observation_sequence"],
        ),
    )
    episode_rows = sorted(
        (row for state in states.values() for row in state["completed_episode_rows"]),
        key=lambda row: (row["security_id"], row["episode_ordinal"]),
    )
    return {
        "logical_request_name": logical_request_name,
        "exit_confirmation_m": exit_confirmation_m,
        "observation_rows": observation_rows,
        "trigger_rows": trigger_rows,
        "episode_rows": episode_rows,
    }
