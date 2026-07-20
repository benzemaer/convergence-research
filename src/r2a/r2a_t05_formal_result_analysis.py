"""Independent readback analysis for persisted R2A-T05 formal artifacts.

This module deliberately starts from files written under a RunRoot.  It does
not accept the in-memory candidate used by the runner as its source of truth.
The report is descriptive: it separates CA exit observations, re-entry and
threshold behaviour, cross-q structure, and future-price questions.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb

REQUEST_ORDER = ("CA_q10_k5", "CA_q15_k5", "CA_q20_k5", "CA_q25_k5")
RAW_FALSE_SUBCLASSES = ("A_ONLY_FAIL", "C_ONLY_FAIL", "CA_BOTH_FAIL")
PRIMARY_TERMINATION_CATEGORIES = (
    "raw_false",
    "quality_or_availability_termination",
    "input_end_open_right_censored",
)
MARGIN_FIELDS = ("count", "null_count", "min", "p05", "p50", "p95", "max", "mean")
CSV_TO_CANDIDATE = {
    "request_reconciliation.csv": "request_reconciliation",
    "termination_reason_profile.csv": "termination_reason_profile",
    "raw_false_exit_decomposition.csv": "raw_false_exit_decomposition",
    "threshold_margin_summary.csv": "threshold_margin_summary",
    "quick_reentry_profile.csv": "quick_reentry_profile",
    "cross_q_structure_summary.csv": "cross_q_structure_summary",
    "cross_q_parent_structure_summary.csv": "cross_q_structure_summary",
    "cross_q_child_structure_summary.csv": "cross_q_child_structure_summary",
    "year_profile.csv": "year_profile",
    "security_profile.csv": "security_profile",
    "deterministic_interval_samples.csv": "deterministic_interval_samples",
}


class FormalResultAnalysisError(RuntimeError):
    """Raised when persisted artifact readback cannot be performed."""


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FormalResultAnalysisError(f"json_read_failed:{path}") from error
    if not isinstance(value, dict):
        raise FormalResultAnalysisError(f"json_object_required:{path}")
    return value


def _csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError as error:
        raise FormalResultAnalysisError(f"csv_read_failed:{path}") from error


def _file_identity(root: Path, path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        size = path.stat().st_size
    except OSError as error:
        raise FormalResultAnalysisError(f"artifact_stat_failed:{path}") from error
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": digest.hexdigest(),
        "byte_size": size,
    }


def _number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise FormalResultAnalysisError(f"integer_expected:{value}") from error


def _read_detail_database(path: Path) -> dict[str, Any]:
    try:
        with duckdb.connect(str(path), read_only=True) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='main' AND table_type='BASE TABLE'"
                ).fetchall()
            }
            if tables != {"candidate_json"}:
                raise FormalResultAnalysisError("detail_table_inventory_mismatch")
            row = connection.execute("SELECT payload FROM candidate_json").fetchone()
    except duckdb.Error as error:
        raise FormalResultAnalysisError("detail_database_read_failed") from error
    if row is None:
        raise FormalResultAnalysisError("detail_database_payload_missing")
    try:
        candidate = json.loads(str(row[0]))
    except (TypeError, json.JSONDecodeError) as error:
        raise FormalResultAnalysisError("detail_database_payload_invalid") from error
    if not isinstance(candidate, dict):
        raise FormalResultAnalysisError("detail_database_payload_not_object")
    return candidate


def _read_compact_review(root: Path) -> dict[str, list[dict[str, Any]]]:
    compact = root / "compact-review"
    if not compact.is_dir():
        raise FormalResultAnalysisError("compact_review_directory_missing")
    result: dict[str, list[dict[str, Any]]] = {}
    for filename in sorted(CSV_TO_CANDIDATE):
        path = compact / filename
        if path.is_file():
            result[filename] = _csv_rows(path)
    return result


def _actual_counts(candidate: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in candidate.get("request_reconciliation", []):
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("logical_request_name"))
        actual = row.get("actual", {})
        if isinstance(actual, Mapping):
            result[name] = dict(actual)
    return result


def _request_reconciliation(
    candidate: Mapping[str, Any], expected_counts: Mapping[str, Mapping[str, int]]
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    anomalies: list[str] = []
    source_rows = {
        str(row.get("logical_request_name")): row
        for row in candidate.get("request_reconciliation", [])
        if isinstance(row, Mapping)
    }
    for name in REQUEST_ORDER:
        row = source_rows.get(name)
        if row is None:
            anomalies.append(f"t04_count_mismatch:{name}:missing")
            continue
        actual = dict(row.get("actual", {}))
        expected = dict(expected_counts.get(name, row.get("expected", {})))
        difference = {
            key: _integer(actual.get(key, 0)) - _integer(expected.get(key, 0))
            for key in (
                "raw_true",
                "confirmed_true",
                "intervals",
                "securities_with_interval",
            )
        }
        subset = row.get("subset_violations", {})
        if not isinstance(subset, Mapping):
            subset = {}
        result = {
            "logical_request_name": name,
            "raw_true": _integer(actual.get("raw_true", 0)),
            "confirmed_true": _integer(actual.get("confirmed_true", 0)),
            "interval_count": _integer(actual.get("intervals", 0)),
            "securities_with_interval": _integer(
                actual.get("securities_with_interval", 0)
            ),
            "expected": expected,
            "difference": difference,
            "raw_confirmed_subset_violations": int(subset.get("raw_confirmed", 0)),
            "confirmed_interval_subset_violations": int(
                subset.get("confirmed_interval", 0)
            ),
            "matches_accepted_t04": not any(difference.values()),
        }
        rows.append(result)
        if not result["matches_accepted_t04"]:
            anomalies.append(f"t04_count_mismatch:{name}")
        if (
            result["raw_confirmed_subset_violations"]
            or result["confirmed_interval_subset_violations"]
        ):
            anomalies.append(f"subset_violation:{name}")
    return rows, anomalies


def _termination_summary(
    candidate: Mapping[str, Any],
    reconciliation: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    records = [
        row
        for row in candidate.get("termination_records", [])
        if isinstance(row, Mapping)
    ]
    by_request: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        by_request[str(row.get("logical_request_name"))].append(row)
    q_sensitivity: dict[str, Any] = {}
    anomalies: list[str] = []
    allowed_categories = set(PRIMARY_TERMINATION_CATEGORIES)
    for row in records:
        name = str(row.get("logical_request_name"))
        primary = str(row.get("primary_termination_reason"))
        right_censored = bool(row.get("right_censored"))
        if name not in REQUEST_ORDER:
            anomalies.append(f"unexpected_termination_request:{name}")
        if primary not in allowed_categories:
            anomalies.append(f"termination_category_invalid:{name}:{primary}")
        if right_censored != (primary == "input_end_open_right_censored"):
            anomalies.append(f"censoring_classification_mismatch:{name}")
    for name in REQUEST_ORDER:
        group = by_request[name]
        primary = Counter(str(row.get("primary_termination_reason")) for row in group)
        raw = [
            row for row in group if row.get("primary_termination_reason") == "raw_false"
        ]
        raw_classes = Counter(str(row.get("raw_false_subclass")) for row in raw)
        if any(
            row.get("raw_false_subclass") not in RAW_FALSE_SUBCLASSES for row in raw
        ):
            anomalies.append(f"raw_false_unclassified:{name}")
        q_sensitivity[name] = {
            "all_intervals": next(
                (
                    _integer(row["interval_count"])
                    for row in reconciliation
                    if row["logical_request_name"] == name
                ),
                len(group),
            ),
            "right_censored": primary["input_end_open_right_censored"],
            "quality_availability_termination": primary[
                "quality_or_availability_termination"
            ],
            "raw_false": primary["raw_false"],
            "raw_false_subclasses": {
                subclass: raw_classes[subclass] for subclass in RAW_FALSE_SUBCLASSES
            },
        }
        expected_intervals = next(
            (
                _integer(row["interval_count"])
                for row in reconciliation
                if row["logical_request_name"] == name
            ),
            len(group),
        )
        if len(group) != expected_intervals:
            anomalies.append(f"termination_record_count_mismatch:{name}")
    q20 = dict(q_sensitivity["CA_q20_k5"])
    classifiable = sum(q20["raw_false_subclasses"].values())
    q20["classifiable_raw_false_intervals"] = classifiable
    q20["raw_false_subclass_share"] = {
        key: (None if classifiable == 0 else value / classifiable)
        for key, value in q20["raw_false_subclasses"].items()
    }
    return q20, q_sensitivity, anomalies


def _threshold_analysis(
    candidate: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    rows = [
        row
        for row in candidate.get("threshold_margin_summary", [])
        if isinstance(row, Mapping)
    ]
    anomalies: list[str] = []
    if not rows:
        anomalies.append("threshold_margin_missing")
    report_rows: list[dict[str, Any]] = []
    failure_counts: Counter[str] = Counter()
    for row in rows:
        summary = {field: row.get(field) for field in MARGIN_FIELDS}
        summary.update(
            {
                "logical_request_name": row.get("logical_request_name"),
                "endpoint": row.get("endpoint"),
                "dimension_id": row.get("dimension_id"),
                "margin_name": row.get("margin_name"),
                "gate_failure_counts": row.get("gate_failure_counts", {}),
            }
        )
        report_rows.append(summary)
        count = _integer(row.get("count", 0))
        finite_count = _integer(row.get("finite_count", 0))
        null_count = _integer(row.get("null_count", 0))
        if count < 0 or finite_count < 0 or null_count < 0:
            anomalies.append(
                f"margin_count_invalid:{row.get('logical_request_name')}:{row.get('dimension_id')}:{row.get('margin_name')}"
            )
        if finite_count + null_count != count:
            anomalies.append(
                f"margin_count_not_conserved:{row.get('logical_request_name')}:{row.get('dimension_id')}:{row.get('margin_name')}"
            )
        if summary["gate_failure_counts"]:
            for gate, gate_count in summary["gate_failure_counts"].items():
                failure_counts[f"{summary['dimension_id']}:{gate}"] += _integer(
                    gate_count
                )
        if count and (
            finite_count == 0
            or row.get("all_null")
            or (
                finite_count
                and (
                    row.get("all_zero")
                    or row.get("constant")
                    or (
                        row.get("min") == 1
                        and row.get("max") == 1
                        and finite_count == count
                    )
                )
            )
        ):
            anomalies.append(
                f"degenerate_margin:{row.get('logical_request_name')}:{row.get('dimension_id')}:{row.get('margin_name')}"
            )
    first_failure = None
    if failure_counts:
        first_failure = max(failure_counts, key=failure_counts.get)
    return {
        "rows": report_rows,
        "failure_counts": dict(sorted(failure_counts.items())),
        "most_frequent_failure_dimension_and_class": first_failure,
        "interpretation": (
            "mean_margin describes the main dimension gate; min_margin describes "
            "the weak-min component gate; active_margin is their lower boundary. "
            "These are contemporaneous "
            "CA endpoint distances, not future release labels."
        ),
    }, anomalies


def _reentry_analysis(
    candidate: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows = [
        row
        for row in candidate.get("quick_reentry_profile", [])
        if isinstance(row, Mapping)
    ]
    anomalies: list[str] = []
    result: list[dict[str, Any]] = []
    for row in rows:
        reentered = _integer(row.get("reentered_count", 0))
        clean = _integer(row.get("clean_not_reentered_count", 0))
        denominator = _integer(row.get("observable_denominator", 0))
        if denominator != reentered + clean:
            anomalies.append(
                f"reentry_denominator_not_conserved:{row.get('logical_request_name')}:{row.get('metric')}:{row.get('lag_threshold')}"
            )
        total = _integer(row.get("total_non_right_censored_termination_count", 0))
        quality = _integer(row.get("quality_interrupted_count", 0))
        insufficient = _integer(row.get("insufficient_followup_censored_count", 0))
        if total != reentered + clean + quality + insufficient:
            anomalies.append(
                f"reentry_classification_not_conserved:{row.get('logical_request_name')}:{row.get('metric')}:{row.get('lag_threshold')}"
            )
        reported_rate = _number(row.get("reentry_rate"))
        expected_rate = None if denominator == 0 else reentered / denominator
        if reported_rate != expected_rate and not (
            reported_rate is None and expected_rate is None
        ):
            if (
                reported_rate is None
                or expected_rate is None
                or not math.isclose(
                    reported_rate, expected_rate, rel_tol=1e-12, abs_tol=1e-12
                )
            ):
                anomalies.append(
                    f"reentry_rate_mismatch:{row.get('logical_request_name')}:{row.get('metric')}:{row.get('lag_threshold')}"
                )
        result.append(
            {
                **dict(row),
                "coverage": None if total == 0 else denominator / total,
                "denominator_conserved": denominator == reentered + clean,
                "rate_recomputed": expected_rate,
            }
        )
    return result, anomalies


def _cross_q_analysis(candidate: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    parents = [
        row
        for row in candidate.get("cross_q_structure_summary", [])
        if isinstance(row, Mapping)
    ]
    children = [
        row
        for row in candidate.get("cross_q_child_structure_summary", [])
        if isinstance(row, Mapping)
    ]
    daily = [
        row
        for row in candidate.get("daily_level_identities", [])
        if isinstance(row, Mapping)
    ]
    mappings = [
        row for row in candidate.get("cross_q_mapping", []) if isinstance(row, Mapping)
    ]
    anomalies: list[str] = []
    mapping_keys = [
        (
            row.get("child_request_name"),
            row.get("child_security_id"),
            row.get("child_interval_ordinal"),
        )
        for row in mappings
    ]
    if len(mapping_keys) != len(set(mapping_keys)):
        anomalies.append("parent_mapping_not_unique")
    daily_keys = [
        (
            row.get("security_id"),
            row.get("observation_sequence"),
            row.get("q25_parent_interval_ordinal"),
        )
        for row in daily
    ]
    if len(daily_keys) != len(set(daily_keys)):
        anomalies.append("daily_identity_not_conserved")
    identity_counts = Counter(str(row.get("identity")) for row in daily)
    parent_day_total = sum(
        _integer(row.get("q25_parent_confirmed_day_count", 0)) for row in parents
    )
    if parent_day_total != len(daily):
        anomalies.append("daily_identity_parent_day_mismatch")
    fragmented = sum(
        bool(row.get("q20_fragmented_within_q25_parent")) for row in parents
    )
    shell_days = sum(
        _integer(row.get("q25_only_shell_day_count", 0)) for row in parents
    )
    q20_days = sum(
        _integer(row.get("q20_confirmed_day_count_inside_parent", 0)) for row in parents
    )
    leading = sum(
        _integer(row.get("q25_local_leading_shell_days", 0)) for row in children
    )
    trailing = sum(
        _integer(row.get("q25_local_trailing_shell_days", 0)) for row in children
    )
    return {
        "q25_parent_count": len(parents),
        "q20_child_count": len(children),
        "fragmented_parent_count": fragmented,
        "fragmented_parent_rate": None if not parents else fragmented / len(parents),
        "q25_only_shell_days": shell_days,
        "q20_confirmed_days_inside_parent": q20_days,
        "local_leading_shell_days": leading,
        "local_trailing_shell_days": trailing,
        "local_adjacent_shell_days": leading + trailing,
        "global_daily_identity_counts": dict(sorted(identity_counts.items())),
        "identity_conservation_mismatch": len(daily_keys) - len(set(daily_keys)),
        "parent_mapping_mismatch": sum(
            count > 1 for count in Counter(mapping_keys).values()
        ),
    }, anomalies


def _concentration_analysis(candidate: Mapping[str, Any]) -> dict[str, Any]:
    years = [
        row for row in candidate.get("year_profile", []) if isinstance(row, Mapping)
    ]
    securities = [
        row for row in candidate.get("security_profile", []) if isinstance(row, Mapping)
    ]
    year_counts: Counter[tuple[str, Any]] = Counter()
    security_counts: Counter[tuple[str, Any]] = Counter()
    for row in years:
        year_counts[(str(row.get("logical_request_name")), row.get("year"))] += (
            _integer(row.get("interval_count", 0))
        )
    for row in securities:
        security_counts[
            (str(row.get("logical_request_name")), row.get("security_id"))
        ] += _integer(row.get("interval_count", 0))

    def shares(counts: Counter[tuple[str, Any]]) -> dict[str, Any]:
        totals: Counter[str] = Counter()
        for (name, _), count in counts.items():
            totals[name] += count
        largest = {
            name: {
                "key": key,
                "count": count,
                "share": None if totals[name] == 0 else count / totals[name],
            }
            for (name, key), count in counts.items()
            if count
            == max(
                (
                    value
                    for (candidate_name, _), value in counts.items()
                    if candidate_name == name
                ),
                default=0,
            )
        }
        return {"totals": dict(totals), "largest": largest}

    distribution = [
        _integer(row.get("interval_count", 0))
        for row in securities
        if _integer(row.get("interval_count", 0)) > 0
    ]
    distribution.sort()

    def overall_share(
        rows: Sequence[Mapping[str, Any]], key_name: str
    ) -> dict[str, Any]:
        counts: Counter[tuple[str, Any]] = Counter()
        for row in rows:
            counts[(str(row.get("logical_request_name")), row.get(key_name))] += (
                _integer(row.get("interval_count", 0))
            )
        totals: Counter[str] = Counter()
        for (name, _), count in counts.items():
            totals[name] += count
        largest: dict[str, Any] = {}
        for name in sorted(totals):
            candidates = [
                (key, count)
                for (candidate_name, key), count in counts.items()
                if candidate_name == name
            ]
            key, count = max(candidates, key=lambda item: (item[1], str(item[0])))
            largest[name] = {
                "key": key,
                "count": count,
                "share": None if totals[name] == 0 else count / totals[name],
            }
        return {"totals": dict(totals), "largest": largest}

    def percentile(probability: float) -> int | None:
        if not distribution:
            return None
        index = min(
            len(distribution) - 1,
            int(round((len(distribution) - 1) * probability)),
        )
        return distribution[index]

    years_present = {str(row.get("year")) for row in years}
    security_coverage = {
        name: len(
            {
                str(row.get("security_id"))
                for row in securities
                if str(row.get("logical_request_name")) == name
            }
        )
        for name in sorted({str(row.get("logical_request_name")) for row in securities})
    }
    return {
        "year_interval_distribution": shares(year_counts),
        "year_interval_termination_distribution": {
            str(key): value for key, value in year_counts.items()
        },
        "annual_max_share": overall_share(years, "year"),
        "security_interval_distribution": shares(security_counts),
        "security_interval_termination_distribution": {
            str(key): value for key, value in security_counts.items()
        },
        "security_coverage": security_coverage,
        "security_max_share": overall_share(securities, "security_id"),
        "security_interval_count_quantiles": {
            "p05": percentile(0.05),
            "p50": percentile(0.50),
            "p95": percentile(0.95),
        },
        "2026_partial_year_boundary": "2026" in years_present,
        "interpretation": (
            "Annual and security concentration are inspected as possible "
            "pooled-result drivers, not causal explanations."
        ),
    }


def _artifact_readback(
    root: Path,
    compact: Mapping[str, Sequence[Mapping[str, Any]]],
    candidate: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    anomalies: list[str] = []
    row_counts: dict[str, dict[str, int]] = {}
    for filename, rows in compact.items():
        expected_key = CSV_TO_CANDIDATE.get(filename)
        expected_rows = candidate.get(expected_key, []) if expected_key else []
        row_counts[filename] = {"actual": len(rows), "expected": len(expected_rows)}
        if len(rows) != len(expected_rows):
            anomalies.append(f"compact_row_count_mismatch:{filename}")
    manifest_path = root / "artifact_manifest.json"
    if not manifest_path.is_file():
        anomalies.append("artifact_manifest_missing")
        return {"compact_row_counts": row_counts, "file_hashes": []}, anomalies
    manifest = _json(manifest_path)
    identities = manifest.get("files", [])
    if not isinstance(identities, list):
        anomalies.append("artifact_manifest_files_invalid")
        return {"compact_row_counts": row_counts, "file_hashes": []}, anomalies
    checked: list[dict[str, Any]] = []
    for entry in identities:
        if not isinstance(entry, Mapping):
            anomalies.append("artifact_manifest_entry_invalid")
            continue
        relative = str(entry.get("relative_path"))
        path = root / relative
        if not path.is_file():
            anomalies.append(f"artifact_hash_readback_missing:{relative}")
            continue
        actual = _file_identity(root, path)
        checked.append(actual)
        if actual.get("sha256") != entry.get("sha256") or actual.get(
            "byte_size"
        ) != entry.get("byte_size"):
            anomalies.append(f"artifact_hash_readback_mismatch:{relative}")
    return {"compact_row_counts": row_counts, "file_hashes": checked}, anomalies


def analyze_persisted_formal_artifacts(
    run_root: str | Path,
    *,
    expected_counts: Mapping[str, Mapping[str, int]],
) -> dict[str, Any]:
    """Read detail DB, compact CSV, receipts, summary and log, then analyze."""

    root = Path(run_root).resolve()
    required_json = (
        "input_manifest.json",
        "run_summary.json",
        "formal_authorization.json",
        "independent_validation_receipt.json",
        "formal_determinism_receipt.json",
        "anomaly_scan.json",
    )
    missing = [name for name in required_json if not (root / name).is_file()]
    missing.extend(
        name
        for name in ("execution_log.jsonl", "t05_detail.duckdb")
        if not (root / name).is_file()
    )
    if missing:
        raise FormalResultAnalysisError(
            f"persisted_artifact_missing:{','.join(missing)}"
        )

    candidate = _read_detail_database(root / "t05_detail.duckdb")
    compact = _read_compact_review(root)
    manifest = _json(root / "input_manifest.json")
    run_summary = _json(root / "run_summary.json")
    authorization = _json(root / "formal_authorization.json")
    validation = _json(root / "independent_validation_receipt.json")
    determinism = _json(root / "formal_determinism_receipt.json")
    anomaly_receipt = _json(root / "anomaly_scan.json")
    anomalies: list[str] = []

    reconciliation, reconciliation_anomalies = _request_reconciliation(
        candidate, expected_counts
    )
    anomalies.extend(reconciliation_anomalies)
    q20_exit, q_sensitivity, termination_anomalies = _termination_summary(
        candidate, reconciliation
    )
    anomalies.extend(termination_anomalies)
    threshold_distance, threshold_anomalies = _threshold_analysis(candidate)
    anomalies.extend(threshold_anomalies)
    quick_reentry, reentry_anomalies = _reentry_analysis(candidate)
    anomalies.extend(reentry_anomalies)
    cross_q, cross_q_anomalies = _cross_q_analysis(candidate)
    anomalies.extend(cross_q_anomalies)
    readback, readback_anomalies = _artifact_readback(root, compact, candidate)
    anomalies.extend(readback_anomalies)

    if (
        determinism.get("status") != "passed"
        or determinism.get("build_count") != 2
        or determinism.get("left_fingerprint") != determinism.get("right_fingerprint")
        or any(
            _integer(determinism.get(field, 0)) != 0
            for field in (
                "schema_mismatch_count",
                "key_mismatch_count",
                "row_mismatch_count",
                "value_mismatch_count",
                "ordering_mismatch_count",
            )
        )
    ):
        anomalies.append("determinism_mismatch")
    if validation.get("status") != "passed":
        anomalies.append("independent_validation_blocked")
    if authorization.get("authorization_status") != "authorized_pending_execution":
        anomalies.append("authorization_evidence_incomplete")
    if not authorization.get("authorization_head") or not authorization.get(
        "authorization_parent"
    ):
        anomalies.append("authorization_parent_head_missing")
    if authorization.get("authorization_parent") != manifest.get("source_commit"):
        anomalies.append("authorization_manifest_parent_mismatch")
    if authorization.get("authorization_head") != run_summary.get(
        "authorization_head"
    ) or authorization.get("authorization_parent") != run_summary.get(
        "authorization_parent"
    ):
        anomalies.append("authorization_run_summary_mismatch")
    if authorization.get("reviewed_formal_execution_sha") != run_summary.get(
        "reviewed_formal_execution_sha"
    ):
        anomalies.append("authorization_execution_review_mismatch")
    authorized_manifest_sha = authorization.get("authorized_manifest_sha256")
    if authorized_manifest_sha:
        manifest_identity = _file_identity(root, root / "input_manifest.json")
        if manifest_identity["sha256"] != authorized_manifest_sha or manifest_identity[
            "byte_size"
        ] != authorization.get("authorized_manifest_byte_size"):
            anomalies.append("authorized_manifest_identity_mismatch")
    if run_summary.get("request_summaries") != _actual_counts(candidate):
        anomalies.append("run_summary_artifact_readback_mismatch")
    try:
        last_log = (
            (root / "execution_log.jsonl").read_text(encoding="utf-8").splitlines()[-1]
        )
        if (
            json.loads(last_log).get("event")
            != "formal_run_completed_pending_owner_review"
        ):
            anomalies.append("execution_log_terminal_event_missing")
    except (OSError, IndexError, json.JSONDecodeError):
        anomalies.append("execution_log_readback_failed")
    if anomaly_receipt.get("blocking_anomalies"):
        anomalies.extend(str(item) for item in anomaly_receipt["blocking_anomalies"])

    deduplicated = sorted(set(anomalies))
    return {
        "status": "blocked" if deduplicated else "passed_pending_owner_review",
        "scientific_review_status": "pending_owner_review",
        "blocking_anomalies": deduplicated,
        "upstream_request_reconciliation": reconciliation,
        "q20_exit_structure": q20_exit,
        "cross_q_sensitivity": q_sensitivity,
        "threshold_distance": threshold_distance,
        "quick_reentry": quick_reentry,
        "cross_q_structure": cross_q,
        "year_security_structure": _concentration_analysis(candidate),
        "readback": {
            "detail_database": "read_only",
            "compact_csv": "read",
            "validation_receipt": validation.get("status"),
            "determinism_receipt": determinism.get("status"),
            "run_summary": run_summary.get("status"),
            **readback,
        },
        "boundary": {
            "ca_exit_is_not_future_release": True,
            "future_prices_used": False,
            "q20_selected_as_optimal": False,
            "q20_role": "research_anchor_only",
        },
        "anomaly_receipt": anomaly_receipt,
        "manifest_identity": {
            "source_commit": manifest.get("source_commit"),
            "reviewed_formal_execution_sha": manifest.get(
                "reviewed_formal_execution_sha"
            ),
        },
    }


def _md_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def render_persisted_result_analysis(analysis: Mapping[str, Any]) -> str:
    """Render actual values and interpretations, not a checklist template."""

    lines = [
        "# R2A-T05 formal result analysis",
        "",
        "This report was generated after reading the persisted detail database, "
        "compact CSV files, independent receipts, and run summary.",
        "",
        "## Upstream and request reconciliation",
        "",
        "| request | raw_true | confirmed_true | intervals | securities | "
        "differences | subset violations |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in analysis.get("upstream_request_reconciliation", []):
        lines.append(
            f"| {row['logical_request_name']} | {row['raw_true']} | "
            f"{row['confirmed_true']} | {row['interval_count']} | "
            f"{row['securities_with_interval']} | `{_md_json(row['difference'])}` | "
            f"`{row['raw_confirmed_subset_violations']}/"
            f"{row['confirmed_interval_subset_violations']}` |"
        )
    lines.extend(
        [
            "",
            "The two subset-violation columns are raw-to-confirmed and "
            "confirmed-interval checks; any non-zero value blocks promotion.",
            "",
            "## q20 exit structure and cross-q sensitivity",
            "",
            f"q20 structure: `{_md_json(analysis.get('q20_exit_structure', {}))}`",
            "",
            "four-q sensitivity (comparison only, no q selection): "
            f"`{_md_json(analysis.get('cross_q_sensitivity', {}))}`",
            "",
            "Raw-false subclass shares use raw-false intervals as the "
            "classifiable denominator. They describe contemporaneous CA "
            "state failure, not up/down release direction.",
            "",
            "## Threshold distance",
            "",
            "| request | endpoint | dimension | margin | count | null | min | "
            "p05 | p50 | p95 | max | mean |",
            "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    most_frequent_failure = analysis.get("threshold_distance", {}).get(
        "most_frequent_failure_dimension_and_class"
    )
    for row in analysis.get("threshold_distance", {}).get("rows", []):
        values = {
            field: row.get(field)
            for field in (
                "logical_request_name",
                "endpoint",
                "dimension_id",
                "margin_name",
                *MARGIN_FIELDS,
            )
        }
        lines.append(
            "| {logical_request_name} | {endpoint} | {dimension_id} | "
            "{margin_name} | {count} | {null_count} | {min} | {p05} | "
            "{p50} | {p95} | {max} | {mean} |".format(**values)
        )
    lines.extend(
        [
            "",
            str(analysis.get("threshold_distance", {}).get("interpretation", "")),
            f"Most frequent gate failure dimension/class: `{most_frequent_failure}`.",
            "",
            "## Quick re-entry",
            "",
            "| request | metric | threshold | total non-right-censored | "
            "denominator | reentered | clean not reentered | quality interrupted | "
            "insufficient follow-up | rate | coverage |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in analysis.get("quick_reentry", []):
        lines.append(
            f"| {row.get('logical_request_name')} | {row.get('metric')} | "
            f"{row.get('lag_threshold')} | "
            f"{row.get('total_non_right_censored_termination_count')} | "
            f"{row.get('observable_denominator')} | {row.get('reentered_count')} | "
            f"{row.get('clean_not_reentered_count')} | "
            f"{row.get('quality_interrupted_count')} | "
            f"{row.get('insufficient_followup_censored_count')} | "
            f"{row.get('reentry_rate')} | {row.get('coverage')} |"
        )
    lines.extend(
        [
            "",
            "The observable denominator is required to equal reentered plus "
            "clean-not-reentered; quality-interrupted and insufficient-follow-up "
            "observations remain outside that rate denominator.",
            "",
            "## Cross-q structure",
            "",
            f"`{_md_json(analysis.get('cross_q_structure', {}))}`",
            "",
            "Fragmentation, shell conservation, daily identity counts, and parent "
            "mapping are structural observations; q20 is retained as the research "
            "anchor and is not selected as optimal or canonical.",
            "",
            "## Annual and security concentration",
            "",
            f"`{_md_json(analysis.get('year_security_structure', {}))}`",
            "",
            "Annual and single-security concentration are checked as possible "
            "explanations for pooled patterns. The 2026 flag marks a partial-year "
            "boundary when present.",
            "",
            "## Artifact readback and anomaly gate",
            "",
            f"Readback: `{_md_json(analysis.get('readback', {}))}`",
            "",
            f"Blocking anomalies: `{_md_json(analysis.get('blocking_anomalies', []))}`",
            "",
            "## Boundary",
            "",
            "CA state exit, re-entry/threshold jitter, and cross-q structural "
            "failure are distinct from future-price release. This analysis uses "
            "no future prices, returns, release labels, or direction/intensity "
            "labels, and does not convert q20 into a selected parameter.",
            "",
            f"Promotion status: `{analysis.get('status')}`; scientific review "
            f"status: `{analysis.get('scientific_review_status')}`.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "FormalResultAnalysisError",
    "analyze_persisted_formal_artifacts",
    "render_persisted_result_analysis",
]
