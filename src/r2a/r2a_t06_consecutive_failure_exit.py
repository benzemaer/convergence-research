"""R2A-T06 consecutive-failure exit lifecycle implementation candidate.

This module is deliberately limited to accepted daily state facts and synthetic
implementation inputs.  It never reads Score, price, return, future-path, or
transaction data.  ``raw_state`` and ``confirmed_state_v1`` are copied without
mutation into an independent lifecycle layer.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r2a/r2a_t06_consecutive_failure_exit.v1.json"
CONFIG_SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t06_consecutive_failure_exit.schema.json"

TASK_ID = "R2A-T06"
IMPLEMENTATION_VERSION = "r2a_t06_consecutive_failure_exit.v1"
REQUEST_ORDER = ("CA_q10_k5", "CA_q15_k5", "CA_q20_k5", "CA_q25_k5")
EXIT_CONFIRMATION_VALUES = (1, 2, 3)
QUALITY_REASON_PRECEDENCE = (
    "expected_observation_missing",
    "expected_observation_listing_pause",
    "selected_dimension_blocked",
    "selected_dimension_diagnostic_required",
    "selected_dimension_unknown",
    "selected_dimension_not_eligible",
    "selected_dimension_score_non_finite",
)
FORBIDDEN_FIELDS = {
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


class T06Error(ValueError):
    """Fail-closed T06 error with a stable reason code."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        message = reason_code if detail is None else f"{reason_code}: {detail}"
        super().__init__(message)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise T06Error("json_input_invalid", str(path)) from error
    if not isinstance(value, dict):
        raise T06Error("json_object_required", str(path))
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_t06_config(path: Path | None = None) -> dict[str, Any]:
    """Load the versioned implementation contract and verify its JSON schema."""

    config = _json(path or CONFIG_PATH)
    schema = _json(CONFIG_SCHEMA_PATH)
    errors = sorted(Draft202012Validator(schema).iter_errors(config), key=str)
    if errors:
        raise T06Error("t06_config_schema_invalid", errors[0].message)
    return config


def verify_accepted_bindings(
    config: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Bind T05 closure and return authoritative request identities.

    The request panel is read from the accepted T05 handoff, never reconstructed
    from request nicknames.
    """

    loaded = dict(config or load_t06_config())
    binding = loaded["accepted_t05_binding"]
    handoff_path = ROOT / binding["relative_path"]
    done_path = ROOT / binding["done_relative_path"]
    if not handoff_path.is_file():
        raise T06Error("accepted_t05_handoff_missing")
    if _sha256(handoff_path) != binding["sha256"]:
        raise T06Error("accepted_t05_handoff_hash_mismatch")
    if not done_path.is_file():
        raise T06Error("accepted_t05_done_missing")
    handoff = _json(handoff_path)
    done = _json(done_path)
    if handoff.get("status") != "completed_accepted":
        raise T06Error("accepted_t05_status_mismatch")
    gate = handoff.get("downstream_gate", {})
    if gate.get("R2A-T05_DONE") != "present":
        raise T06Error("accepted_t05_done_gate_mismatch")
    if gate.get("R2A-T06_allowed_to_start") != "true_after_PR_115_merge":
        raise T06Error("t06_start_gate_mismatch")
    if done.get("accepted_handoff_sha256") != binding["sha256"]:
        raise T06Error("accepted_t05_done_binding_mismatch")
    selection = handoff.get("selection", {})
    if (
        selection.get("q_selection_status") != "not_selected"
        or selection.get("canonical_dynamic_request_selected") is not False
    ):
        raise T06Error("selection_boundary_mismatch")
    if handoff.get("scientific_result_summary", {}).get("research_anchor_role") != (
        "exit_mechanism_decomposition"
    ):
        raise T06Error("research_anchor_role_mismatch")
    requests = handoff.get("request_reconciliation")
    if not isinstance(requests, list):
        raise T06Error("accepted_request_panel_missing")
    by_name = {str(item["logical_request_name"]): deepcopy(item) for item in requests}
    if tuple(by_name) != REQUEST_ORDER:
        raise T06Error("accepted_request_order_mismatch")
    for name, item in by_name.items():
        if (
            item.get("selected_dimensions") != ["C", "A"]
            or item.get("confirmation_k") != 5
            or item.get("selection_status") != "evaluated_not_selected"
        ):
            raise T06Error("accepted_request_identity_mismatch", name)
        expected_counts = loaded["accepted_t05_counts"][name]
        actual_counts = {
            key: int(item[key])
            for key in (
                "raw_true",
                "confirmed_true",
                "intervals",
                "securities_with_interval",
            )
        }
        if actual_counts != expected_counts:
            raise T06Error("accepted_t05_count_mismatch", name)
    return by_name


def _forbidden_path(value: Any, prefix: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            name = str(key).lower()
            path = f"{prefix}.{key}" if prefix else str(key)
            if name in FORBIDDEN_FIELDS or name.startswith("future_"):
                return path
            found = _forbidden_path(nested, path)
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _forbidden_path(nested, f"{prefix}[{index}]")
            if found:
                return found
    return None


def _quality_reason(row: Mapping[str, Any]) -> str | None:
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


def _exit_type(row: Mapping[str, Any]) -> str:
    active = row.get("dimension_active")
    if not isinstance(active, Mapping) or set(active) != {"C", "A"}:
        raise T06Error("dimension_active_required_for_valid_row")
    c_active = active["C"]
    a_active = active["A"]
    if c_active is False and a_active is True:
        return "C_ONLY_FAIL"
    if c_active is True and a_active is False:
        return "A_ONLY_FAIL"
    if c_active is False and a_active is False:
        return "CA_BOTH_FAIL"
    raise T06Error("raw_false_exit_type_invalid")


def _normalize_rows(
    observations: Sequence[Mapping[str, Any]], request_name: str
) -> list[dict[str, Any]]:
    rows = [deepcopy(dict(row)) for row in observations]
    forbidden = _forbidden_path(rows)
    if forbidden:
        raise T06Error("forbidden_future_or_trading_field", forbidden)
    rows.sort(
        key=lambda row: (str(row["security_id"]), int(row["observation_sequence"]))
    )
    seen: set[tuple[str, int]] = set()
    previous: dict[str, int] = {}
    for row in rows:
        security_id = str(row.get("security_id", ""))
        sequence = row.get("observation_sequence")
        if (
            not security_id
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
        ):
            raise T06Error("observation_identity_invalid")
        key = (security_id, sequence)
        if key in seen:
            raise T06Error("duplicate_observation_identity", str(key))
        seen.add(key)
        if security_id in previous and sequence != previous[security_id] + 1:
            raise T06Error("observation_sequence_gap", str(key))
        previous[security_id] = sequence
        row_request = row.get("logical_request_name", request_name)
        if row_request != request_name:
            raise T06Error("observation_request_mismatch")
        row["logical_request_name"] = request_name
        if "confirmed_state_v1" not in row and "confirmed_state" in row:
            row["confirmed_state_v1"] = row["confirmed_state"]
        if row.get("confirmed_state_v1") not in (True, False, None):
            raise T06Error("confirmed_state_v1_domain_invalid")
        quality = _quality_reason(row)
        if quality is None and row.get("raw_state") not in (True, False):
            raise T06Error("valid_raw_state_domain_invalid")
        if row.get("confirmed_state_v1") is True and row.get("raw_state") is not True:
            raise T06Error("accepted_confirmed_raw_mismatch")
        row["quality_reason"] = quality
    return rows


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def build_exit_lifecycle(
    observations: Sequence[Mapping[str, Any]],
    *,
    logical_request_name: str,
    exit_confirmation_m: int,
) -> dict[str, Any]:
    """Build one M candidate without mutating accepted daily state facts."""

    if exit_confirmation_m not in EXIT_CONFIRMATION_VALUES:
        raise T06Error("exit_confirmation_m_invalid")
    rows = _normalize_rows(observations, logical_request_name)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["security_id"])].append(row)

    output_rows: list[dict[str, Any]] = []
    triggers: list[dict[str, Any]] = []
    episodes: list[dict[str, Any]] = []
    for security_id in sorted(grouped):
        active = False
        pending: dict[str, Any] | None = None
        episode: dict[str, Any] | None = None
        episode_ordinal = -1
        security_output_start = len(output_rows)
        for source in grouped[security_id]:
            row = deepcopy(source)
            sequence = int(row["observation_sequence"])
            lifecycle_state = "INACTIVE"
            fail_streak = 0
            trigger_time = None
            trigger_sequence = None
            recognition_time = None
            recognition_sequence = None
            cancelled = False
            cancellation_time = None
            termination_class = None
            quality_reason = row.pop("quality_reason")

            if (
                not active
                and quality_reason is None
                and row["confirmed_state_v1"] is True
            ):
                active = True
                episode_ordinal += 1
                baseline_ordinal = row.get("confirmed_interval_ordinal")
                if baseline_ordinal is None:
                    raise T06Error("confirmed_interval_ordinal_missing")
                episode = {
                    "logical_request_name": logical_request_name,
                    "security_id": security_id,
                    "exit_confirmation_m": exit_confirmation_m,
                    "episode_ordinal": episode_ordinal,
                    "episode_id": _stable_id(
                        logical_request_name,
                        security_id,
                        exit_confirmation_m,
                        episode_ordinal,
                    ),
                    "episode_identity": _stable_id(
                        logical_request_name, security_id, int(baseline_ordinal)
                    ),
                    "baseline_anchor_interval_ordinal": int(baseline_ordinal),
                    "start_time": row.get("trading_date"),
                    "start_observation_sequence": sequence,
                    "active_observation_count": 0,
                    "bridged_false_observation_count": 0,
                }

            if active:
                assert episode is not None
                if quality_reason is not None:
                    lifecycle_state = "QUALITY_TERMINATED"
                    termination_class = "QUALITY_TERMINATED"
                    if pending is not None:
                        pending["disposition"] = "QUALITY_TERMINATED"
                        pending["quality_reason"] = quality_reason
                        pending["termination_time"] = row.get("trading_date")
                        pending["termination_observation_sequence"] = sequence
                        triggers.append(pending)
                        pending = None
                    episode.update(
                        {
                            "end_time": row.get("trading_date"),
                            "end_observation_sequence": sequence,
                            "termination_class": termination_class,
                            "quality_reason": quality_reason,
                            "right_censored": False,
                        }
                    )
                    episodes.append(episode)
                    episode = None
                    active = False
                elif row["raw_state"] is True:
                    lifecycle_state = "ACTIVE"
                    episode["active_observation_count"] += 1
                    if pending is not None:
                        pending["disposition"] = "CANCELLED"
                        pending["provisional_exit_cancelled"] = True
                        pending["cancellation_time"] = row.get("trading_date")
                        pending["cancellation_observation_sequence"] = sequence
                        triggers.append(pending)
                        trigger_time = pending["exit_trigger_time"]
                        trigger_sequence = pending["exit_trigger_observation_sequence"]
                        cancelled = True
                        cancellation_time = row.get("trading_date")
                        pending = None
                else:
                    exit_type = _exit_type(row)
                    if pending is None:
                        trigger_id = _stable_id(
                            logical_request_name,
                            security_id,
                            episode["baseline_anchor_interval_ordinal"],
                            sequence,
                        )
                        pending = {
                            "logical_request_name": logical_request_name,
                            "security_id": security_id,
                            "exit_confirmation_m": exit_confirmation_m,
                            "trigger_id": trigger_id,
                            "episode_id": episode["episode_id"],
                            "episode_identity": episode["episode_identity"],
                            "baseline_anchor_interval_ordinal": episode[
                                "baseline_anchor_interval_ordinal"
                            ],
                            "exit_trigger_time": row.get("trading_date"),
                            "exit_trigger_observation_sequence": sequence,
                            "exit_type": exit_type,
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
                        lifecycle_state = "EXIT_RECOGNIZED"
                        recognition_time = row.get("trading_date")
                        recognition_sequence = sequence
                        pending["disposition"] = "EXIT_RECOGNIZED"
                        pending["exit_recognition_time"] = recognition_time
                        pending["exit_recognition_observation_sequence"] = sequence
                        pending["recognition_lag"] = sequence - int(trigger_sequence)
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
                        active = False
                        termination_class = "EXIT_RECOGNIZED"
                    else:
                        lifecycle_state = "EXIT_PENDING"

            output_rows.append(
                {
                    **row,
                    "exit_confirmation_m": exit_confirmation_m,
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
                    "quality_reason": quality_reason,
                    "right_censored": False,
                }
            )

        if active:
            assert episode is not None
            last_row = output_rows[-1]
            if pending is not None:
                last_row["lifecycle_state"] = "PENDING_RIGHT_CENSORED"
                last_row["termination_class"] = "PENDING_RIGHT_CENSORED"
                last_row["right_censored"] = True
                pending["disposition"] = "PENDING_RIGHT_CENSORED"
                triggers.append(pending)
                termination_class = "PENDING_RIGHT_CENSORED"
            else:
                last_row["right_censored"] = True
                termination_class = "ACTIVE_RIGHT_CENSORED"
            episode.update(
                {
                    "end_time": last_row.get("trading_date"),
                    "end_observation_sequence": last_row["observation_sequence"],
                    "termination_class": termination_class,
                    "quality_reason": None,
                    "right_censored": True,
                }
            )
            episodes.append(episode)
        if len(output_rows) == security_output_start:
            raise T06Error("empty_security_group")

    return {
        "logical_request_name": logical_request_name,
        "exit_confirmation_m": exit_confirmation_m,
        "observation_rows": output_rows,
        "trigger_rows": triggers,
        "episode_rows": episodes,
    }


def _candidate_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    triggers = result["trigger_rows"]
    episodes = result["episode_rows"]
    dispositions = Counter(row["disposition"] for row in triggers)
    recognized = [row for row in triggers if row["disposition"] == "EXIT_RECOGNIZED"]
    return {
        "logical_request_name": result["logical_request_name"],
        "exit_confirmation_m": result["exit_confirmation_m"],
        "provisional_exit_count": len(triggers),
        "recognized_exit_count": len(recognized),
        "cancelled_exit_count": dispositions["CANCELLED"],
        "quality_terminated_pending_count": dispositions["QUALITY_TERMINATED"],
        "pending_right_censored_count": dispositions["PENDING_RIGHT_CENSORED"],
        "cancel_rate": (
            dispositions["CANCELLED"] / len(triggers) if triggers else None
        ),
        "recognition_lags": sorted(row["recognition_lag"] for row in recognized),
        "episode_count": len(episodes),
        "bridged_false_observation_count": sum(
            int(row["bridged_false_observation_count"]) for row in episodes
        ),
    }


def _validate_cross_q_input(
    source_by_request: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    normalized = {
        name: _normalize_rows(source_by_request[name], name) for name in REQUEST_ORDER
    }
    for child, parent in zip(REQUEST_ORDER, REQUEST_ORDER[1:]):
        child_rows = {
            (row["security_id"], row["observation_sequence"]): row
            for row in normalized[child]
        }
        parent_rows = {
            (row["security_id"], row["observation_sequence"]): row
            for row in normalized[parent]
        }
        if set(child_rows) != set(parent_rows):
            raise T06Error("cross_q_observation_spine_mismatch")
        raw_violations = 0
        confirmed_violations = 0
        for key, child_row in child_rows.items():
            parent_row = parent_rows[key]
            if child_row["raw_state"] is True and parent_row["raw_state"] is not True:
                raw_violations += 1
            if (
                child_row["confirmed_state_v1"] is True
                and parent_row["confirmed_state_v1"] is not True
            ):
                confirmed_violations += 1
        if raw_violations or confirmed_violations:
            raise T06Error("cross_q_nesting_violation")
        checks.append(
            {
                "child": child,
                "parent": parent,
                "raw_violation_count": 0,
                "confirmed_violation_count": 0,
                "status": "passed",
            }
        )
    return checks


def build_t06_candidate(
    source_by_request: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    config: Mapping[str, Any] | None = None,
    worker_count: int = 1,
) -> dict[str, Any]:
    """Build all q x M synthetic candidates with deterministic ordering."""

    if isinstance(worker_count, bool) or not isinstance(worker_count, int):
        raise T06Error("worker_count_invalid")
    if worker_count < 1:
        raise T06Error("worker_count_invalid")
    loaded = dict(config or load_t06_config())
    identities = verify_accepted_bindings(loaded)
    if tuple(source_by_request) != REQUEST_ORDER:
        raise T06Error("candidate_request_order_mismatch")
    nesting = _validate_cross_q_input(source_by_request)
    jobs = [
        (name, int(exit_confirmation_m))
        for name in REQUEST_ORDER
        for exit_confirmation_m in loaded["exit_confirmation_m_candidates"]
    ]

    def build_job(job: tuple[str, int]) -> dict[str, Any]:
        name, exit_confirmation_m = job
        return build_exit_lifecycle(
            source_by_request[name],
            logical_request_name=name,
            exit_confirmation_m=exit_confirmation_m,
        )

    if worker_count == 1:
        candidates = [build_job(job) for job in jobs]
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            candidates = list(executor.map(build_job, jobs))
    return {
        "task_id": TASK_ID,
        "implementation_version": IMPLEMENTATION_VERSION,
        "status": "implementation_candidate",
        "q_selection_status": "not_selected",
        "canonical_dynamic_request_selected": False,
        "winner_selected": False,
        "formal_run_executed": False,
        "real_score_data_read": False,
        "formal_artifacts_generated": False,
        "request_identities": [identities[name] for name in REQUEST_ORDER],
        "cross_q_nesting_validation": nesting,
        "candidates": candidates,
        "candidate_exit_summary": [_candidate_summary(item) for item in candidates],
    }


def candidate_to_json(candidate: Mapping[str, Any]) -> str:
    """Return canonical deterministic JSON with exactly one trailing LF."""

    return (
        json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
