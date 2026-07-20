"""Result-analysis helpers for the R2A-T05 implementation candidate.

This module is deliberately usable after a future formal run, but it does not
create or bless formal artifacts.  It starts from the registered research
question and definitions, then scans the actual result rows supplied by the
caller for degeneration, reconciliation failures and impossible hierarchy.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from src.r2a.r2a_t05_validator import detect_result_anomalies


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def scan_candidate_results(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Scan actual candidate rows and return an analysis receipt."""

    issues = list(detect_result_anomalies(candidate))
    reconciliation = list(candidate.get("request_reconciliation", []))
    if len(reconciliation) != 4:
        issues.append("request_count_not_four")
    if any(row.get("matches_accepted_t04") is not True for row in reconciliation):
        issues.append("accepted_t04_count_mismatch")
    if candidate.get("cross_q_structure_summary"):
        for row in candidate["cross_q_structure_summary"]:
            if int(row.get("q25_only_shell_day_count", 0)) != int(
                row.get("q25_parent_confirmed_day_count", 0)
            ) - int(row.get("q20_confirmed_day_count_inside_parent", 0)):
                issues.append("cross_q_shell_count_not_conserved")
            if int(row.get("q10_confirmed_day_count_inside_parent", 0)) > int(
                row.get("q15_confirmed_day_count_inside_parent", 0)
            ):
                issues.append("cross_q_q10_q15_day_order_reversed")
            if int(row.get("q15_confirmed_day_count_inside_parent", 0)) > int(
                row.get("q20_confirmed_day_count_inside_parent", 0)
            ):
                issues.append("cross_q_q15_q20_day_order_reversed")
            if int(row.get("q20_confirmed_day_count_inside_parent", 0)) > int(
                row.get("q25_parent_confirmed_day_count", 0)
            ):
                issues.append("cross_q_q20_q25_day_order_reversed")
    if candidate.get("cross_q_child_structure_summary"):
        for row in candidate["cross_q_child_structure_summary"]:
            if int(row.get("q25_local_adjacent_shell_days", 0)) != int(
                row.get("q25_local_leading_shell_days", 0)
            ) + int(row.get("q25_local_trailing_shell_days", 0)):
                issues.append("cross_q_child_shell_count_not_conserved")
    margins = list(candidate.get("threshold_margin_summary", []))
    finite_margins = [
        _finite(row.get("min"))
        for row in margins
        if _finite(row.get("min")) is not None
    ]
    if any(abs(value) > 1.1 for value in finite_margins):
        issues.append("margin_magnitude_out_of_domain")
    if candidate.get("daily_level_identities"):
        daily = candidate["daily_level_identities"]
        daily_keys = {
            (
                row.get("security_id"),
                row.get("observation_sequence"),
                row.get("q25_parent_interval_ordinal"),
            )
            for row in daily
        }
        if len(daily_keys) != len(daily):
            issues.append("daily_identity_key_not_unique")
        if len(daily) != sum(
            int(row.get("q25_parent_confirmed_day_count", 0))
            for row in candidate.get("cross_q_structure_summary", [])
        ):
            issues.append("daily_identity_count_not_conserved")
        allowed = {
            "Q10_CORE",
            "Q15_NOT_Q10_CORE",
            "Q20_NOT_Q15_ANCHOR",
            "Q25_NOT_Q20_SHELL",
        }
        if any(row.get("identity") not in allowed for row in daily):
            issues.append("daily_identity_invalid")
    issues = sorted(set(issues))
    return {
        "status": "blocked" if issues else "candidate_review_pending",
        "scientific_review_status": "not_applicable_implementation_candidate",
        "blocking_anomalies": issues,
        "research_question_reviewed_first": True,
        "definitions_reviewed_first": True,
        "actual_result_rows_scanned": True,
        "formal_run_executed": False,
        "formal_artifacts_generated": False,
        "R2A-T05_DONE": "absent",
        "R2A-T06_allowed_to_start": False,
    }


def render_result_analysis(
    candidate: Mapping[str, Any],
    *,
    validation_receipt: Mapping[str, Any] | None = None,
) -> str:
    """Render an independent review note without claiming scientific acceptance."""

    analysis = scan_candidate_results(candidate)
    receipt = validation_receipt or {}
    lines = [
        "# R2A-T05 result analysis (implementation candidate)",
        "",
        "## Research question and registered definitions",
        "",
        (
            "This review covers only why accepted CA intervals terminate, endpoint "
            "C/A threshold margins, observation-sequence re-entry, and strict "
            "q10/q15/q20/q25 interval structure. It does not define or inspect a "
            "release label, direction, intensity, transaction outcome, or future path."
        ),
        "",
        (
            "The q20 request is the research anchor for exit-mechanism decomposition "
            "only. It is not selected, optimal, canonical, or a winner. The accepted "
            "T04 interval and termination semantics are unchanged; no interval was "
            "merged, delayed, or reclassified outside the registered categories."
        ),
        "",
        "## Candidate facts scanned",
        "",
        f"- Requests reconciled: {len(candidate.get('request_reconciliation', []))}",
        (
            f"- Termination records scanned: "
            f"{len(candidate.get('termination_records', []))}"
        ),
        (
            f"- Cross-q q25 parent summaries scanned: "
            f"{len(candidate.get('cross_q_structure_summary', []))}"
        ),
        (
            f"- Daily hierarchy rows scanned: "
            f"{len(candidate.get('daily_level_identities', []))}"
        ),
        f"- Independent validator status: {receipt.get('status', 'not_run')}",
        "",
        "## Anomaly scan",
        "",
    ]
    anomalies = analysis["blocking_anomalies"]
    if anomalies:
        lines.append("Blocking anomalies were found:")
        lines.extend(f"- `{item}`" for item in anomalies)
    else:
        lines.append(
            "No implementation-candidate anomaly was found in the supplied "
            "synthetic result rows."
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            (
                "This is not a formal result review. Real Score data was not read, "
                "no formal artifacts or DONE were generated, and T06 is not started "
                "or allowed to start. A future formal run must independently reconcile "
                "T04 counts, read the actual result package immediately, and stop on "
                "any unresolved zero/NULL/constant output, hierarchy violation, "
                "mapping ambiguity, or availability inconsistency."
            ),
            "",
            f"`analysis_status={analysis['status']}`",
            "",
        ]
    )
    return "\n".join(lines)


def analyze_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return machine-readable analysis; no scientific pass is emitted."""

    return scan_candidate_results(candidate)


def analysis_to_json(analysis: Mapping[str, Any]) -> str:
    return json.dumps(
        analysis, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


__all__ = [
    "analysis_to_json",
    "analyze_candidate",
    "render_result_analysis",
    "scan_candidate_results",
]
