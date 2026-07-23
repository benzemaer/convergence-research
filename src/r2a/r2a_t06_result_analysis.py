"""Trigger-anchored result-analysis helpers for R2A-T06."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


class T06AnalysisError(ValueError):
    pass


def _indexed_observations(
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, dict[int, Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in observations:
        grouped[str(row["security_id"])].append(row)
    indexed: dict[str, dict[int, Mapping[str, Any]]] = {}
    for security, rows in grouped.items():
        ordered = sorted(rows, key=lambda row: int(row["observation_sequence"]))
        sequences = [int(row["observation_sequence"]) for row in ordered]
        if len(sequences) != len(set(sequences)):
            raise T06AnalysisError("duplicate_observation_identity")
        if any(right != left + 1 for left, right in zip(sequences, sequences[1:])):
            raise T06AnalysisError("observation_sequence_gap")
        indexed[security] = {int(row["observation_sequence"]): row for row in ordered}
    return indexed


def build_false_run_inventory(
    observations: Sequence[Mapping[str, Any]],
    triggers: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Measure L only for valid provisional triggers emitted by the lifecycle."""

    indexed = _indexed_observations(observations)
    inventory: list[dict[str, Any]] = []
    seen: set[str] = set()
    for trigger in sorted(
        triggers,
        key=lambda row: (
            str(row["security_id"]),
            int(row["exit_trigger_observation_sequence"]),
            str(row["trigger_id"]),
        ),
    ):
        trigger_id = str(trigger["trigger_id"])
        if trigger_id in seen:
            raise T06AnalysisError("duplicate_trigger_identity")
        seen.add(trigger_id)
        security = str(trigger["security_id"])
        start = int(trigger["exit_trigger_observation_sequence"])
        rows = indexed.get(security)
        if rows is None or start not in rows:
            raise T06AnalysisError("trigger_observation_missing")
        first = rows[start]
        if (
            first.get("raw_state") is not False
            or first.get("quality_reason") is not None
        ):
            raise T06AnalysisError("trigger_not_valid_raw_false")
        length = 0
        sequence = start
        end_class = "INPUT_END"
        next_available = False
        next_raw: bool | None = None
        quality_reason = None
        right_censored = True
        while True:
            row = rows[sequence]
            if (
                row.get("raw_state") is not False
                or row.get("quality_reason") is not None
            ):
                raise T06AnalysisError("false_run_internal_state_invalid")
            length += 1
            next_sequence = sequence + 1
            if next_sequence not in rows:
                break
            next_row = rows[next_sequence]
            quality_reason = next_row.get("quality_reason")
            if quality_reason is not None:
                end_class = "QUALITY_INTERRUPTION"
                right_censored = False
                break
            if next_row.get("raw_state") is True:
                end_class = "VALID_RAW_TRUE"
                next_available = True
                next_raw = True
                right_censored = False
                break
            if next_row.get("raw_state") is not False:
                raise T06AnalysisError("next_valid_raw_state_invalid")
            sequence = next_sequence
        inventory.append(
            {
                "trigger_id": trigger_id,
                "episode_identity": trigger["episode_identity"],
                "security_id": security,
                "logical_request_name": trigger["logical_request_name"],
                "trigger_observation_sequence": start,
                "trigger_exit_type": trigger["exit_type"],
                "false_run_length": length,
                "run_end_class": end_class,
                "next_valid_observation_available": next_available,
                "next_valid_raw_state": next_raw,
                "quality_reason": quality_reason,
                "right_censored": right_censored,
            }
        )
    return inventory


def false_run_length_profile(
    inventory: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    profile = Counter(
        (str(row["trigger_exit_type"]), int(row["false_run_length"]))
        for row in inventory
    )
    return [
        {
            "trigger_exit_type": exit_type,
            "false_run_length": length,
            "run_count": count,
        }
        for (exit_type, length), count in sorted(profile.items())
    ]


def recovery_hazard_profile(
    inventory: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for streak in (1, 2, 3):
        denominator = 0
        numerator = 0
        for run in inventory:
            length = int(run["false_run_length"])
            if length > streak:
                denominator += 1
            elif length == streak and run["run_end_class"] == "VALID_RAW_TRUE":
                denominator += 1
                numerator += 1
        output.append(
            {
                "false_streak": streak,
                "observable_denominator": denominator,
                "recovery_count": numerator,
                "hazard": numerator / denominator if denominator else None,
            }
        )
    return output


def detect_candidate_anomalies(candidate: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    summaries = candidate.get("candidate_exit_summary", [])
    if not summaries:
        return ["candidate_summary_empty"]
    by_request: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in summaries:
        by_request[str(row["logical_request_name"])].append(row)
        m = int(row["exit_confirmation_m"])
        if any(lag != m - 1 for lag in row.get("recognition_lags", [])):
            issues.append(f"recognition_lag_invalid:{row['logical_request_name']}:M{m}")
    for name, rows in by_request.items():
        signatures = {
            (
                row["recognized_exit_count"],
                row["cancelled_exit_count"],
                row["episode_count"],
            )
            for row in rows
        }
        if len(signatures) == 1 and any(row["provisional_exit_count"] for row in rows):
            issues.append(f"candidate_parameter_nonresponsive:{name}")
    return issues


def render_result_analysis_skeleton(candidate: Mapping[str, Any]) -> str:
    anomalies = detect_candidate_anomalies(candidate)
    anomaly_text = "none" if not anomalies else ", ".join(anomalies)
    return (
        "# R2A-T06 result analysis\n\n"
        "Status: implementation skeleton; no formal result exists.\n\n"
        "Future review must independently analyze trigger-anchored false-run lengths, "
        "h1/h2/h3, recognition lag, cancellation, quality censoring, re-entry, "
        "fragmentation, q nesting, year and security concentration before selecting "
        "M.\n\n"
        f"Implementation-candidate anomaly scan: {anomaly_text}.\n\n"
        "No future price, return, path label, trading signal, backtest, q selection, "
        "or M winner is part of this document.\n"
    )
