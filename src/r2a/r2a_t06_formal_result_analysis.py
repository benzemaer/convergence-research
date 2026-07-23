"""Independent readback analysis for persisted R2A-T06 formal artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import math
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


def _detail_data(path: Path) -> dict[str, Any]:
    tables = (
        "observations",
        "triggers",
        "episodes",
        "m_candidate_mapping",
        "cross_q_parent_mapping",
        "post_recognition_outcomes",
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
            payloads = {
                table: [
                    json.loads(row[0])
                    for row in connection.execute(
                        f'SELECT payload FROM "{table}"'
                    ).fetchall()
                ]
                for table in tables
            }
            observations = payloads["observations"]
            counts = {table: len(rows) for table, rows in payloads.items()}
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
            return {"counts": counts, "rows": payloads}
    except duckdb.Error as error:
        raise FormalResultAnalysisError("detail_database_read_failed") from error


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise FormalResultAnalysisError(
            "persisted_number_invalid", str(value)
        ) from error
    if not math.isfinite(parsed):
        raise FormalResultAnalysisError("persisted_number_non_finite", str(value))
    return parsed


def _same_number(left: Any, right: Any) -> bool:
    left_value = _number(left)
    right_value = _number(right)
    if left_value is None or right_value is None:
        return left_value is right_value
    return math.isclose(left_value, right_value, rel_tol=1e-12, abs_tol=1e-12)


def _percentile(values: list[int], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction + 0.999999))
    return float(ordered[index])


REENTRY_SPECS = (
    ("raw_reentry", 1),
    ("raw_reentry", 3),
    ("raw_reentry", 5),
    ("confirmed_reentry", 5),
    ("confirmed_reentry", 10),
)
REQUESTS = ("CA_q10_k5", "CA_q15_k5", "CA_q20_k5", "CA_q25_k5")
EXIT_TYPES = ("A_ONLY_FAIL", "C_ONLY_FAIL", "CA_BOTH_FAIL")


def _reentry_analysis(
    rows: list[dict[str, str]], detail: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[str]]:
    anomalies: list[str] = []
    compact_keys = {
        (
            row.get("logical_request_name", ""),
            _integer(row.get("exit_confirmation_m")),
        )
        for row in rows
    }
    if (
        compact_keys != {(name, m) for name in REQUESTS for m in (1, 2, 3)}
        or len(rows) != 12
    ):
        anomalies.append("reentry_compact_inventory_invalid")
    detail_keys = [
        (
            item.get("logical_request_name"),
            item.get("exit_confirmation_m"),
            item.get("trigger_id"),
            item.get("metric"),
            item.get("horizon"),
        )
        for item in detail
    ]
    if len(detail_keys) != len(set(detail_keys)):
        anomalies.append("reentry_detail_duplicate_key")
    allowed_outcomes = {
        "REENTERED",
        "CLEAN_NOT_REENTERED",
        "QUALITY_INTERRUPTED",
        "INPUT_END_CENSORED",
    }
    grouped: dict[tuple[str, int, str, int], Counter[str]] = defaultdict(Counter)
    for item in detail:
        key = (
            str(item.get("logical_request_name")),
            _integer(item.get("exit_confirmation_m")),
            str(item.get("metric")),
            _integer(item.get("horizon")),
        )
        outcome = str(item.get("outcome"))
        if outcome not in allowed_outcomes:
            anomalies.append("reentry_detail_outcome_invalid")
        grouped[key][outcome] += 1
    comparisons: dict[str, Any] = {}
    rates: dict[tuple[str, str, int, int], float | None] = {}
    for row in rows:
        name = row.get("logical_request_name", "")
        m = _integer(row.get("exit_confirmation_m"))
        recognized = _integer(row.get("recognized_count"))
        if name not in REQUESTS or m not in (1, 2, 3):
            anomalies.append("reentry_q_m_inventory_invalid")
        for metric, horizon in REENTRY_SPECS:
            base = f"{metric}_{horizon}"
            counts = grouped[(name, m, metric, horizon)]
            expected = {
                "reentered_count": counts["REENTERED"],
                "clean_not_reentered_count": counts["CLEAN_NOT_REENTERED"],
                "quality_interrupted_count": counts["QUALITY_INTERRUPTED"],
                "input_end_censored_count": counts["INPUT_END_CENSORED"],
            }
            if sum(expected.values()) != recognized:
                anomalies.append("reentry_detail_count_reconciliation_failed")
            denominator = (
                expected["reentered_count"] + expected["clean_not_reentered_count"]
            )
            rate = expected["reentered_count"] / denominator if denominator else None
            for suffix, value in expected.items():
                if _integer(row.get(f"{base}_{suffix}")) != value:
                    anomalies.append("reentry_compact_detail_mismatch")
            if _integer(row.get(f"{base}_clean_denominator")) != denominator:
                anomalies.append("reentry_clean_denominator_mismatch")
            if not _same_number(row.get(f"{base}_rate"), rate):
                anomalies.append("reentry_rate_mismatch")
            if expected["reentered_count"] > denominator or denominator < 0:
                anomalies.append("reentry_denominator_invalid")
            rates[(name, metric, horizon, m)] = rate
            comparisons[f"{name}:M{m}:{base}"] = {
                "clean_denominator": denominator,
                "reentered_count": expected["reentered_count"],
                "reentry_rate": rate,
                "quality_interrupted_count": expected["quality_interrupted_count"],
                "input_end_censored_count": expected["input_end_censored_count"],
            }
    deltas: dict[str, Any] = {}
    for name in REQUESTS:
        for metric, horizon in REENTRY_SPECS:
            values = [rates.get((name, metric, horizon, m)) for m in (1, 2, 3)]
            deltas[f"{name}:{metric}_{horizon}"] = {
                "M2_minus_M1": None
                if values[0] is None or values[1] is None
                else values[1] - values[0],
                "M3_minus_M2": None
                if values[1] is None or values[2] is None
                else values[2] - values[1],
            }
    return {"by_q_m_metric": comparisons, "rate_deltas": deltas}, sorted(set(anomalies))


def _fragmentation_analysis(
    rows: list[dict[str, str]], episodes: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[str]]:
    anomalies: list[str] = []
    compact_keys = {
        (
            row.get("logical_request_name", ""),
            _integer(row.get("exit_confirmation_m")),
        )
        for row in rows
    }
    if (
        compact_keys != {(name, m) for name in REQUESTS for m in (1, 2, 3)}
        or len(rows) != 12
    ):
        anomalies.append("fragmentation_inventory_invalid")
    grouped: dict[tuple[str, int], list[int]] = defaultdict(list)
    for item in episodes:
        grouped[
            (
                str(item.get("logical_request_name")),
                _integer(item.get("exit_confirmation_m")),
            )
        ].append(
            _integer(item.get("end_observation_sequence"))
            - _integer(item.get("start_observation_sequence"))
            + 1
        )
    values: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("logical_request_name", ""),
            _integer(row.get("exit_confirmation_m")),
        )
        spans = grouped[key]
        expected = {
            "episode_count": len(spans),
            "median_span": float(sorted(spans)[len(spans) // 2])
            if spans and len(spans) % 2
            else (
                (sorted(spans)[len(spans) // 2 - 1] + sorted(spans)[len(spans) // 2])
                / 2
            )
            if spans
            else None,
            "p90_span": _percentile(spans, 0.9),
            "p95_span": _percentile(spans, 0.95),
            "max_span": max(spans) if spans else None,
        }
        if _integer(row.get("episode_count")) != expected["episode_count"]:
            anomalies.append("fragmentation_episode_count_mismatch")
        for field in ("median_span", "p90_span", "p95_span", "max_span"):
            if not _same_number(row.get(field), expected[field]):
                anomalies.append("fragmentation_span_mismatch")
        if spans and any(value < 1 for value in spans):
            anomalies.append("fragmentation_span_scale_invalid")
        if spans and not (
            expected["median_span"]
            <= expected["p90_span"]
            <= expected["p95_span"]
            <= expected["max_span"]
        ):
            anomalies.append("fragmentation_span_order_invalid")
        values[key] = expected
    deltas: dict[str, Any] = {}
    for name in REQUESTS:
        series = [values.get((name, m), {}) for m in (1, 2, 3)]
        if all(series):
            counts = [item["episode_count"] for item in series]
            if counts[1] > counts[0] or counts[2] > counts[1]:
                anomalies.append(f"fragmentation_episode_count_nonmonotonic:{name}")
            deltas[name] = {
                "M2_minus_M1_episode_count": counts[1] - counts[0],
                "M3_minus_M2_episode_count": counts[2] - counts[1],
                "M2_minus_M1_median_span": series[1]["median_span"]
                - series[0]["median_span"],
                "M3_minus_M2_median_span": series[2]["median_span"]
                - series[1]["median_span"],
            }
    return {
        "values": {f"{k[0]}:M{k[1]}": v for k, v in values.items()},
        "deltas": deltas,
    }, sorted(set(anomalies))


def _margin_analysis(
    rows: list[dict[str, str]],
    observations: list[dict[str, Any]],
    triggers: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    anomalies: list[str] = []
    expected_keys = {
        (name, m, exit_type, dimension)
        for name in REQUESTS
        for m in (1, 2, 3)
        for exit_type in EXIT_TYPES
        for dimension in ("C", "A")
    }
    actual_keys = {
        (
            row.get("logical_request_name", ""),
            _integer(row.get("exit_confirmation_m")),
            row.get("trigger_exit_type", ""),
            row.get("dimension_id", ""),
        )
        for row in rows
    }
    if actual_keys != expected_keys or len(rows) != len(expected_keys):
        anomalies.append("margin_combination_inventory_invalid")
    observation_by_key = {
        (
            str(item.get("logical_request_name")),
            _integer(item.get("exit_confirmation_m")),
            str(item.get("security_id")),
            _integer(item.get("observation_sequence")),
        ): item
        for item in observations
    }
    grouped: dict[tuple[str, int, str, str], list[float]] = defaultdict(list)
    exit_coverage: Counter[str] = Counter()
    for trigger in triggers:
        name = str(trigger.get("logical_request_name"))
        m = _integer(trigger.get("exit_confirmation_m"))
        exit_type = str(trigger.get("exit_type"))
        exit_coverage[exit_type] += 1
        observation = observation_by_key.get(
            (
                name,
                m,
                str(trigger.get("security_id")),
                _integer(trigger.get("exit_trigger_observation_sequence")),
            ),
            {},
        )
        margins = observation.get("dimension_margin", {})
        for dimension in ("C", "A"):
            value = margins.get(dimension) if isinstance(margins, Mapping) else None
            parsed = _number(value)
            if parsed is not None:
                grouped[(name, m, exit_type, dimension)].append(parsed)
    dimension_coverage: Counter[str] = Counter()
    for row in rows:
        key = (
            row.get("logical_request_name", ""),
            _integer(row.get("exit_confirmation_m")),
            row.get("trigger_exit_type", ""),
            row.get("dimension_id", ""),
        )
        values = grouped[key]
        expected = {
            "observable_count": len(values),
            "mean_margin": sum(values) / len(values) if values else None,
            "min_margin": min(values) if values else None,
            "max_margin": max(values) if values else None,
        }
        if _integer(row.get("observable_count")) != expected["observable_count"]:
            anomalies.append("margin_observable_count_mismatch")
        for field in ("mean_margin", "min_margin", "max_margin"):
            if not _same_number(row.get(field), expected[field]):
                anomalies.append("margin_statistic_mismatch")
        if _integer(row.get("observable_count")) > 0 and any(
            row.get(field, "") == ""
            for field in ("mean_margin", "min_margin", "max_margin")
        ):
            anomalies.append("margin_observed_statistic_null")
        dimension_coverage[str(key[3])] += expected["observable_count"]
    total = sum(exit_coverage.values())
    dominant = max(exit_coverage.values(), default=0) / total if total else None
    if total >= 100 and dominant is not None and dominant > 0.98:
        anomalies.append("single_exit_type_abnormal_dominance")
    return {
        "exit_type_coverage": dict(exit_coverage),
        "dimension_observable_coverage": dict(dimension_coverage),
        "dominant_exit_type_share": dominant,
    }, sorted(set(anomalies))


def _sample_analysis(
    rows: list[dict[str, str]], episodes: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[str]]:
    anomalies: list[str] = []
    if not rows:
        anomalies.append("deterministic_sample_empty")
    hashes = [row.get("sample_hash", "") for row in rows]
    if len(hashes) != len(set(hashes)):
        anomalies.append("deterministic_sample_hash_duplicate")
    for row in rows:
        if (
            not row.get("episode_id")
            or not row.get("episode_identity")
            or row.get("logical_request_name") not in REQUESTS
            or _integer(row.get("exit_confirmation_m")) not in (1, 2, 3)
        ):
            anomalies.append("deterministic_sample_identity_invalid")
    expected = []
    for episode in episodes:
        token = "|".join(
            str(value)
            for value in (
                episode.get("logical_request_name"),
                episode.get("exit_confirmation_m"),
                episode.get("episode_id"),
            )
        )
        expected.append(
            {
                "logical_request_name": str(episode.get("logical_request_name")),
                "exit_confirmation_m": str(episode.get("exit_confirmation_m")),
                "security_id": str(episode.get("security_id")),
                "episode_id": str(episode.get("episode_id")),
                "episode_identity": str(episode.get("episode_identity")),
                "sample_hash": hashlib.sha256(token.encode()).hexdigest(),
            }
        )
    expected = sorted(expected, key=lambda row: row["sample_hash"])[:100]
    normalized = [{key: str(value) for key, value in row.items()} for row in rows]
    if normalized != expected:
        anomalies.append("deterministic_sample_detail_mismatch")
    return {"row_count": len(rows), "unique_hash_count": len(set(hashes))}, sorted(
        set(anomalies)
    )


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
    reentry_rows = _csv(root / "post_recognition_reentry.csv")
    fragmentation_rows = _csv(root / "episode_fragmentation_profile.csv")
    margin_rows = _csv(root / "exit_type_margin_profile.csv")
    cross_rows = _csv(root / "cross_q_nesting_validation.csv")
    year_rows = _csv(root / "year_profile.csv")
    security_rows = _csv(root / "security_profile.csv")
    sample_rows = _csv(root / "deterministic_episode_samples.csv")
    validation = _json(root / "validation_receipt.json")
    run_summary = _json(root / "run_summary.json")
    detail = _detail_data(root / "t06_detail.duckdb")
    detail_counts = detail["counts"]
    detail_rows = detail["rows"]

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
    reentry_analysis, found = _reentry_analysis(
        reentry_rows, detail_rows["post_recognition_outcomes"]
    )
    anomalies.extend(found)
    fragmentation_analysis, found = _fragmentation_analysis(
        fragmentation_rows, detail_rows["episodes"]
    )
    anomalies.extend(found)
    margin_analysis, found = _margin_analysis(
        margin_rows, detail_rows["observations"], detail_rows["triggers"]
    )
    anomalies.extend(found)
    sample_analysis, found = _sample_analysis(sample_rows, detail_rows["episodes"])
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
    request_count_projection = {
        name: {
            key: receipt.get(key)
            for key in (
                "raw_true",
                "confirmed_true",
                "intervals",
                "securities_with_interval",
            )
        }
        for name, receipt in run_summary.get("request_summaries", {}).items()
    }
    if request_count_projection != run_summary.get("accepted_counts"):
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
            "post_recognition_reentry": reentry_analysis,
            "episode_fragmentation": fragmentation_analysis,
            "exit_type_margin": margin_analysis,
            "deterministic_samples": sample_analysis,
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
    sections = analysis["sections"]
    reentry = json.dumps(
        sections["post_recognition_reentry"], ensure_ascii=False, sort_keys=True
    )
    fragmentation = json.dumps(
        sections["episode_fragmentation"], ensure_ascii=False, sort_keys=True
    )
    margin = json.dumps(
        sections["exit_type_margin"], ensure_ascii=False, sort_keys=True
    )
    samples = json.dumps(
        sections["deterministic_samples"], ensure_ascii=False, sort_keys=True
    )
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
        "## Persisted core-table readback\n\n"
        "Post-recognition re-entry counts, horizon-specific denominators, rates "
        "and M deltas: `"
        f"{reentry}`.\n\n"
        "Episode fragmentation counts, spans and M deltas: `"
        f"{fragmentation}`.\n\n"
        "Exit-type and dimension-margin coverage: `"
        f"{margin}`.\n\n"
        "Deterministic sample validation: `"
        f"{samples}`.\n\n"
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
