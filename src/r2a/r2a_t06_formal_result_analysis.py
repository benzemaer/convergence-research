"""Independent readback analysis for persisted R2A-T06 formal artifacts."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import duckdb

from src.r2a.r2a_t06_result_package import SCIENTIFIC_FILES, scientific_inventory


class FormalResultAnalysisError(RuntimeError):
    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code if detail is None else f"{reason_code}: {detail}")


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FormalResultAnalysisError("persisted_json_invalid", str(path)) from error
    if not isinstance(value, dict):
        raise FormalResultAnalysisError("persisted_json_object_required", str(path))
    return value


def _csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise FormalResultAnalysisError("persisted_csv_invalid", str(path)) from error


def _integer(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError) as error:
        raise FormalResultAnalysisError(
            "persisted_integer_invalid", str(value)
        ) from error


def _detail_counts(path: Path) -> dict[str, int]:
    tables = (
        "observations",
        "triggers",
        "episodes",
        "m_candidate_mapping",
        "cross_q_parent_mapping",
    )
    try:
        with duckdb.connect(str(path), read_only=True) as connection:
            existing = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM duckdb_tables() WHERE schema_name='main'"
                ).fetchall()
            }
            if existing != set(tables):
                raise FormalResultAnalysisError("detail_table_inventory_mismatch")
            counts = {
                table: int(
                    connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                )
                for table in tables
            }
            observations = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT payload FROM observations"
                ).fetchall()
            ]
            counts.update(
                {
                    "observation_raw_true": sum(
                        row.get("raw_state") is True for row in observations
                    ),
                    "observation_raw_false": sum(
                        row.get("raw_state") is False for row in observations
                    ),
                    "observation_raw_null": sum(
                        row.get("raw_state") is None for row in observations
                    ),
                }
            )
            return counts
    except duckdb.Error as error:
        raise FormalResultAnalysisError("detail_database_read_failed") from error


def _parameter_response(rows: list[dict[str, str]]) -> tuple[dict[str, Any], list[str]]:
    by_q: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_q[row["logical_request_name"]].append(row)
    anomalies: list[str] = []
    response: dict[str, Any] = {}
    for name, items in by_q.items():
        ordered = sorted(items, key=lambda row: _integer(row["exit_confirmation_m"]))
        m_values = [_integer(row["exit_confirmation_m"]) for row in ordered]
        if m_values != [1, 2, 3]:
            anomalies.append(f"m_candidate_inventory_invalid:{name}")
        signatures = {
            (
                _integer(row["recognized_exit_count"]),
                _integer(row["cancelled_exit_count"]),
                _integer(row["episode_count"]),
            )
            for row in ordered
        }
        if len(signatures) == 1 and sum(
            _integer(row["provisional_exit_count"]) for row in ordered
        ):
            anomalies.append(f"m_parameter_nonresponsive:{name}")
        response[name] = {"m_values": m_values, "distinct_signatures": len(signatures)}
    if tuple(sorted(by_q)) != tuple(
        sorted(("CA_q10_k5", "CA_q15_k5", "CA_q20_k5", "CA_q25_k5"))
    ):
        anomalies.append("four_q_inventory_invalid")
    return response, anomalies


def _lag_checks(rows: list[dict[str, str]]) -> tuple[dict[str, int], list[str]]:
    anomalies: list[str] = []
    totals = Counter()
    for row in rows:
        m = _integer(row["exit_confirmation_m"])
        count = _integer(row["recognized_count"])
        anomaly = _integer(row["anomaly_lag_count"])
        lag = _integer(row["recognition_lag"])
        totals[f"M{m}"] += count
        if count and lag != m - 1:
            anomalies.append(f"recognition_lag_invalid:M{m}:lag{lag}")
        if anomaly:
            anomalies.append(f"recognition_lag_anomaly_count:M{m}:{anomaly}")
    return dict(totals), sorted(set(anomalies))


def _cross_q(rows: list[dict[str, str]]) -> list[str]:
    anomalies = []
    if len(rows) != 9:
        anomalies.append("cross_q_row_count_invalid")
    for row in rows:
        if _integer(row["active_or_pending_violation_count"]):
            anomalies.append("cross_q_active_pending_violation")
        if _integer(row["unmapped_child_episode_count"]):
            anomalies.append("unmapped_child_episode")
        if _integer(row["multi_parent_child_episode_count"]):
            anomalies.append("multi_parent_child_episode")
        if (
            row.get("mapping_status") != "passed"
            or row.get("overall_status") != "passed"
        ):
            anomalies.append("cross_q_mapping_failed")
    return sorted(set(anomalies))


def _false_run_hazard(
    false_rows: list[dict[str, str]],
    hazard_rows: list[dict[str, str]],
    summary: list[dict[str, str]],
) -> tuple[dict[str, Any], list[str]]:
    anomalies: list[str] = []
    false_totals: Counter[tuple[str, int]] = Counter()
    for row in false_rows:
        length = _integer(row["false_run_length"])
        count = _integer(row["run_count"])
        if length < 1 or count < 0:
            anomalies.append("false_run_inventory_invalid")
        false_totals[(row["q"], _integer(row["exit_confirmation_m"]))] += count
    expected = {
        (row["logical_request_name"], _integer(row["exit_confirmation_m"])): _integer(
            row["provisional_exit_count"]
        )
        for row in summary
    }
    if dict(false_totals) != expected:
        anomalies.append("false_run_inventory_not_trigger_anchored")
    for row in hazard_rows:
        denominator = _integer(row["observable_denominator"])
        recovery = _integer(row["recovery_count"])
        if denominator < 0 or recovery < 0 or recovery > denominator:
            anomalies.append("hazard_denominator_invalid")
    exit_totals = Counter()
    for row in false_rows:
        exit_totals[row["trigger_exit_type"]] += _integer(row["run_count"])
    total = sum(exit_totals.values())
    if total >= 100 and max(exit_totals.values(), default=0) / total > 0.98:
        anomalies.append("single_exit_type_abnormal_dominance")
    return {
        "trigger_totals": {
            f"{key[0]}:M{key[1]}": value for key, value in false_totals.items()
        }
    }, sorted(set(anomalies))


def _concentration(
    year_rows: list[dict[str, str]], security_rows: list[dict[str, str]]
) -> tuple[dict[str, Any], list[str]]:
    anomalies: list[str] = []
    output: dict[str, Any] = {}
    for label, rows, dimension in (
        ("year", year_rows, "year"),
        ("security", security_rows, "security_id"),
    ):
        groups: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
        for row in rows:
            groups[(row["logical_request_name"], _integer(row["exit_confirmation_m"]))][
                row[dimension]
            ] += _integer(row["recognized_exit_count"])
        maxima = {}
        for key, counts in groups.items():
            total = sum(counts.values())
            share = max(counts.values()) / total if total else None
            maxima[f"{key[0]}:M{key[1]}"] = share
            threshold = 0.80 if label == "year" else 0.50
            if total >= 100 and share is not None and share > threshold:
                anomalies.append(f"{label}_concentration_abnormal:{key[0]}:M{key[1]}")
        output[label] = maxima
    return output, anomalies


def analyze_persisted_formal_artifacts(
    scientific_root: str | Path,
    *,
    require_result_analysis: bool = True,
) -> dict[str, Any]:
    """Read persisted files independently; builder memory is not an input."""

    root = Path(scientific_root)
    if require_result_analysis:
        scientific_inventory(root)
    else:
        actual = {path.name for path in root.iterdir() if path.is_file()}
        expected = set(SCIENTIFIC_FILES) - {"result_analysis.md"}
        if actual != expected:
            raise FormalResultAnalysisError("pre_analysis_file_inventory_mismatch")
    summary = _csv(root / "candidate_exit_summary.csv")
    false_rows = _csv(root / "false_run_length_profile.csv")
    hazard_rows = _csv(root / "recovery_hazard_profile.csv")
    lag_rows = _csv(root / "recognition_lag_profile.csv")
    cross_rows = _csv(root / "cross_q_nesting_validation.csv")
    year_rows = _csv(root / "year_profile.csv")
    security_rows = _csv(root / "security_profile.csv")
    validation = _json(root / "validation_receipt.json")
    run_summary = _json(root / "run_summary.json")
    detail_counts = _detail_counts(root / "t06_detail.duckdb")

    anomalies: list[str] = []
    observation_count = detail_counts["observations"]
    if observation_count and detail_counts["observation_raw_true"] == observation_count:
        anomalies.append("all_one")
    if observation_count and detail_counts["observation_raw_null"] == observation_count:
        anomalies.append("all_null")
    if not summary:
        anomalies.append("candidate_summary_empty")
    elif all(_integer(row["provisional_exit_count"]) == 0 for row in summary):
        anomalies.append("all_zero")
    if any(all(row.get(key, "") == "" for row in summary) for key in summary[0]):
        anomalies.append("all_null_column")
    response, found = _parameter_response(summary)
    anomalies.extend(found)
    lags, found = _lag_checks(lag_rows)
    anomalies.extend(found)
    false_analysis, found = _false_run_hazard(false_rows, hazard_rows, summary)
    anomalies.extend(found)
    anomalies.extend(_cross_q(cross_rows))
    concentration, found = _concentration(year_rows, security_rows)
    anomalies.extend(found)

    required_validation = (
        "independent_recalculation",
        "accepted_daily_fact_immutability",
        "m1_baseline_exact_reproduction",
        "quality_interruption_fail_closed",
        "recognized_cancelled_set_nesting",
        "trigger_anchored_false_run",
        "hazard_recalculation",
        "online_replay_equivalence",
        "parallel_consistency",
        "deterministic_output",
        "cross_q_nesting",
        "availability_evaluability_reconciliation",
    )
    if validation.get("status") != "passed" or any(
        validation.get(key) is not True for key in required_validation
    ):
        anomalies.append("validation_receipt_incomplete_or_failed")
    if run_summary.get("selected_exit_confirmation_m") is not None:
        anomalies.append("runner_selected_m_forbidden")
    if run_summary.get("winner_selected") is not False:
        anomalies.append("runner_winner_selected_forbidden")
    if run_summary.get("request_summaries") != run_summary.get("accepted_counts"):
        anomalies.append("t04_t05_count_reconciliation_failed")
    if detail_counts["m_candidate_mapping"] != 12:
        anomalies.append("detail_m_candidate_inventory_invalid")
    expected_parent_mappings = sum(
        _integer(row["mapped_child_episode_count"]) for row in cross_rows
    )
    if detail_counts["cross_q_parent_mapping"] != expected_parent_mappings:
        anomalies.append("detail_cross_q_mapping_inventory_invalid")
    if (
        require_result_analysis
        and not (root / "result_analysis.md").read_text(encoding="utf-8").strip()
    ):
        anomalies.append("result_analysis_empty")
    anomalies = sorted(set(anomalies))
    return {
        "task_id": "R2A-T06",
        "status": "blocked" if anomalies else "passed",
        "result_analysis_status": "completed_blocked"
        if anomalies
        else "completed_passed",
        "blocking_anomaly_count": len(anomalies),
        "blocking_anomalies": anomalies,
        "selected_exit_confirmation_m": None,
        "winner_selected": False,
        "sections": {
            "t04_t05_reconciliation": run_summary.get("request_summaries"),
            "m_parameter_response": response,
            "false_run_and_hazard": false_analysis,
            "recognition_lag": lags,
            "cross_q": {"row_count": len(cross_rows)},
            "concentration": concentration,
            "online_parallel_determinism": {
                key: validation.get(key) for key in required_validation[-5:]
            },
            "availability_evaluability": validation.get(
                "availability_evaluability_reconciliation"
            ),
            "detail_counts": detail_counts,
        },
    }


def render_persisted_result_analysis(analysis: Mapping[str, Any]) -> str:
    anomalies = analysis.get("blocking_anomalies", [])
    status = analysis["result_analysis_status"]
    return (
        "# R2A-T06 formal result analysis\n\n"
        f"Status: `{status}`. This report was generated from persisted "
        "artifacts, not builder-memory counts.\n\n"
        "## Pre-registered review scope\n\n"
        "The review covers T04/T05 count reconciliation; M=1 baseline "
        "reproduction; M=1→2→3 response; trigger-anchored false-run L and "
        "h1/h2/h3; recognized, cancelled and censored exits; post-recognition "
        "re-entry; episode fragmentation and span; A_ONLY_FAIL/C_ONLY_FAIL/"
        "CA_BOTH_FAIL; threshold margins; q10/q15/q20/q25 nesting; year and "
        "security concentration; online/batch/parallel/determinism; and "
        "availability/evaluability reconciliation.\n\n"
        f"Blocking anomalies ({len(anomalies)}): "
        f"`{json.dumps(anomalies, ensure_ascii=False)}`.\n\n"
        "## Selection boundary\n\n"
        "The formal run leaves `selected_exit_confirmation_m=null` and "
        "`winner_selected=false`. The runner and validator do not select a "
        "winner. Owner review of the actual artifacts and this report is "
        "required before any selection or DONE artifact.\n\n"
        "最小充分复杂度规则：先判断 M=2 是否实质消除单日抖动；只有 M=2 "
        "不足时才评估 M=3 的增量价值；若 M=3 只是统一增加一天延迟、没有稳定降低 "
        "recognition 后重入，不得选择 M=3；若 M=2 没有实质改善，允许保留 M=1；"
        "不得根据未来收益、路径标签、模型准确率或回测选择 M。\n\n"
        "`formal_completed_pending_owner_review` 不得创建 DONE，不得推进 "
        "R2A-T07 或 R3。\n"
    )


__all__ = [
    "FormalResultAnalysisError",
    "analyze_persisted_formal_artifacts",
    "render_persisted_result_analysis",
]
