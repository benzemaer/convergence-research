"""Result-analysis helpers and formal-review skeleton for R2A-T06."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


def false_run_length_profile(
    observations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Compute false-run L without calendar arithmetic or future market labels."""

    rows = sorted(
        observations,
        key=lambda row: (str(row["security_id"]), int(row["observation_sequence"])),
    )
    profile: Counter[tuple[str, int]] = Counter()
    current_security: str | None = None
    run_length = 0
    run_exit_type: str | None = None
    for row in rows:
        security = str(row["security_id"])
        if security != current_security:
            if run_length:
                profile[(run_exit_type or "UNKNOWN", run_length)] += 1
            current_security = security
            run_length = 0
            run_exit_type = None
        quality = row.get("quality_reason")
        if quality is not None or row.get("raw_state") is True:
            if run_length:
                profile[(run_exit_type or "UNKNOWN", run_length)] += 1
            run_length = 0
            run_exit_type = None
        elif row.get("raw_state") is False:
            run_length += 1
            run_exit_type = run_exit_type or str(row.get("exit_type", "UNKNOWN"))
    if run_length:
        profile[(run_exit_type or "UNKNOWN", run_length)] += 1
    return [
        {"exit_type": exit_type, "false_run_length": length, "run_count": count}
        for (exit_type, length), count in sorted(profile.items())
    ]


def recovery_hazard_profile(
    observations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Calculate h1/h2/h3 using only the next available lifecycle observation."""

    by_security: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in observations:
        by_security[str(row["security_id"])].append(row)
    denominators = Counter()
    recoveries = Counter()
    for rows in by_security.values():
        ordered = sorted(rows, key=lambda row: int(row["observation_sequence"]))
        streak = 0
        for index, row in enumerate(ordered):
            if row.get("quality_reason") is not None:
                streak = 0
                continue
            if row.get("raw_state") is False:
                streak += 1
                if streak <= 3 and index + 1 < len(ordered):
                    next_row = ordered[index + 1]
                    if next_row.get("quality_reason") is None:
                        denominators[streak] += 1
                        if next_row.get("raw_state") is True:
                            recoveries[streak] += 1
            else:
                streak = 0
    return [
        {
            "false_streak": streak,
            "observable_denominator": denominators[streak],
            "recovery_count": recoveries[streak],
            "hazard": (
                recoveries[streak] / denominators[streak]
                if denominators[streak]
                else None
            ),
        }
        for streak in (1, 2, 3)
    ]


def detect_candidate_anomalies(candidate: Mapping[str, Any]) -> list[str]:
    """Return implementation-time anomalies; no candidate winner is selected."""

    issues: list[str] = []
    summaries = candidate.get("candidate_exit_summary", [])
    if not summaries:
        issues.append("candidate_summary_empty")
        return issues
    by_request: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in summaries:
        by_request[str(row["logical_request_name"])].append(row)
        m = int(row["exit_confirmation_m"])
        if any(lag != m - 1 for lag in row.get("recognition_lags", [])):
            issues.append(f"recognition_lag_invalid:{row['logical_request_name']}:M{m}")
    for name, rows in by_request.items():
        ordered = sorted(rows, key=lambda row: int(row["exit_confirmation_m"]))
        signatures = {
            (
                row["recognized_exit_count"],
                row["cancelled_exit_count"],
                row["episode_count"],
            )
            for row in ordered
        }
        if len(signatures) == 1 and any(
            row["provisional_exit_count"] for row in ordered
        ):
            issues.append(f"candidate_parameter_nonresponsive:{name}")
    return issues


def render_result_analysis_skeleton(candidate: Mapping[str, Any]) -> str:
    """Render an implementation-only analysis template for future formal review."""

    anomalies = detect_candidate_anomalies(candidate)
    anomaly_text = "none" if not anomalies else ", ".join(anomalies)
    return (
        "# R2A-T06 result analysis\n\n"
        "Status: implementation skeleton; no formal result exists.\n\n"
        "The future review must independently analyze false-run lengths, h1/h2/h3, "
        "recognition lag, cancellations, quality terminations, right censoring, "
        "post-recognition re-entry, fragmentation, exit type, margin, q nesting, "
        "year and security concentration before selecting M.\n\n"
        f"Implementation-candidate anomaly scan: {anomaly_text}.\n\n"
        "No future price, return, path label, trading signal, backtest, q selection, "
        "or M winner is part of this document.\n"
    )
