from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from .r1_t09_year_stability_concentration import (
    ROOT,
    _as_bool,
    _load_json,
    _write_json,
    build_concentration_summary,
    build_leave_one_year_out,
    sha256_file,
)


class R1T09ValidationError(RuntimeError):
    pass


def validate_r1_t09_outputs(
    *, config_path: Path, output_dir: Path, output_path: Path
) -> dict[str, Any]:
    config = _load_json(config_path)
    errors: list[str] = []
    rows = {
        "registry": _read(output_dir / "r1_t09_candidate_registry.csv"),
        "state": _read(output_dir / "r1_t09_year_state_profile.csv"),
        "interval": _read(output_dir / "r1_t09_year_interval_profile.csv"),
        "clipped": _read(output_dir / "r1_t09_calendar_year_clipped_geometry.csv"),
        "interlayer": _read(output_dir / "r1_t09_year_interlayer_profile.csv"),
        "concentration": _read(output_dir / "r1_t09_year_concentration_summary.csv"),
        "loyo": _read(output_dir / "r1_t09_leave_one_year_out.csv"),
        "comparison": _read(
            output_dir / "r1_t09_reference_challenger_year_comparison.csv"
        ),
        "reconciliation": _read(output_dir / "r1_t09_upstream_reconciliation.csv"),
    }
    expected_counts = {
        "registry": 4,
        "state": 44,
        "interval": 44,
        "clipped": 44,
        "interlayer": 66,
        "concentration": 14,
        "loyo": 110,
        "comparison": 22,
    }
    for name, count in expected_counts.items():
        if len(rows[name]) != count:
            errors.append(f"row_count:{name}:{len(rows[name])}!={count}")
    _check_registry(rows["registry"], errors)
    _check_year_keys(
        rows["state"], ("candidate_config_id", "state_line"), 4, errors, "state"
    )
    _check_year_keys(
        rows["interval"], ("candidate_config_id", "state_line"), 4, errors, "interval"
    )
    _check_year_keys(
        rows["clipped"], ("candidate_config_id", "state_line"), 4, errors, "clipped"
    )
    _check_year_keys(rows["interlayer"], ("step_id", "W", "q"), 6, errors, "interlayer")
    _check_state(rows["state"], errors)
    _check_intervals(rows["state"], rows["interval"], rows["clipped"], errors)
    _check_interlayer(rows["interlayer"], errors)
    _check_recomputed(rows, config, errors)
    _check_forbidden_columns(rows, errors)
    mismatch_count = sum(_int(row, "mismatch_count") for row in rows["reconciliation"])
    if mismatch_count:
        errors.append(f"upstream_reconciliation_mismatch_count:{mismatch_count}")
    anomaly = _load_json(output_dir / "r1_t09_anomaly_scan.json")
    if anomaly.get("scan_status") != "passed" or anomaly.get("blocking_findings"):
        errors.append("anomaly_scan_not_passed")
    summary = _load_json(output_dir / "r1_t09_experiment_summary.json")
    for artifact_name, metadata in summary.get("artifacts", {}).items():
        path = ROOT / metadata["path"]
        if not path.exists() or sha256_file(path) != metadata["sha256"]:
            errors.append(f"summary_artifact_hash:{artifact_name}")
        if path.suffix == ".csv" and len(_read(path)) != int(metadata["row_count"]):
            errors.append(f"summary_artifact_row_count:{artifact_name}")
    result = {
        "task_id": "R1-T09",
        "run_id": summary.get("run_id"),
        "code_commit": summary.get("code_commit"),
        "validator": "r1_t09_year_stability_concentration_validator",
        "validator_status": "passed" if not errors else "failed",
        "errors": errors,
        "candidate_count": len(rows["registry"]),
        "year_state_rows": len(rows["state"]),
        "year_interval_rows": len(rows["interval"]),
        "year_interlayer_rows": len(rows["interlayer"]),
        "leave_one_year_out_rows": len(rows["loyo"]),
        "reconciliation_mismatch_count": mismatch_count,
    }
    _write_json(output_path, result)
    return result


def _check_registry(rows: list[dict[str, str]], errors: list[str]) -> None:
    actual = {
        (row["state_line"], int(row["W"]), float(row["q"]), int(row["K"]))
        for row in rows
    }
    expected = {
        ("S_PCT", 120, 0.2, 3),
        ("S_PCT", 250, 0.2, 3),
        ("S_PCVT", 120, 0.2, 3),
        ("S_PCVT", 250, 0.2, 3),
    }
    if actual != expected:
        errors.append("candidate_registry_not_exact")


def _check_year_keys(
    rows: list[dict[str, str]],
    keys: tuple[str, ...],
    expected_groups: int,
    errors: list[str],
    label: str,
) -> None:
    groups: dict[tuple[str, ...], set[int]] = {}
    for row in rows:
        groups.setdefault(tuple(row[key] for key in keys), set()).add(int(row["year"]))
    if len(groups) != expected_groups:
        errors.append(f"{label}_group_count")
    for key, years in groups.items():
        if years != set(range(2016, 2027)):
            errors.append(f"{label}_year_set:{key}")


def _check_state(rows: list[dict[str, str]], errors: list[str]) -> None:
    for row in rows:
        eligible = _int(row, "eligible_trading_days")
        raw_total = sum(
            _int(row, key)
            for key in (
                "raw_state_true_count",
                "raw_state_false_count",
                "raw_state_null_count",
            )
        )
        confirmed_total = sum(
            _int(row, key)
            for key in (
                "confirmed_state_true_count",
                "confirmed_state_false_count",
                "confirmed_state_null_count",
            )
        )
        validity_total = sum(
            _int(row, key)
            for key in (
                "valid_day_count",
                "unknown_day_count",
                "blocked_day_count",
                "diagnostic_required_day_count",
            )
        )
        if (
            raw_total != eligible
            or confirmed_total != eligible
            or validity_total != eligible
        ):
            errors.append(
                f"state_conservation:{row['candidate_config_id']}:{row['state_line']}:{row['year']}"
            )
        invalid = (
            _int(row, "unknown_day_count")
            + _int(row, "blocked_day_count")
            + _int(row, "diagnostic_required_day_count")
        )
        if (
            _int(row, "raw_state_null_count") != invalid
            or _int(row, "confirmed_state_null_count") != invalid
        ):
            errors.append(
                f"invalid_not_null:{row['candidate_config_id']}:{row['state_line']}:{row['year']}"
            )
        if _as_bool(row["partial_year_observation"]) != (int(row["year"]) == 2026):
            errors.append(f"partial_year:{row['candidate_config_id']}:{row['year']}")
        _check_close(
            _float(row, "raw_coverage"),
            _int(row, "raw_state_true_count") / eligible,
            errors,
            "raw_coverage",
        )
        _check_close(
            _float(row, "confirmed_coverage"),
            _int(row, "confirmed_state_true_count") / eligible,
            errors,
            "confirmed_coverage",
        )


def _check_intervals(
    state: list[dict[str, str]],
    intervals: list[dict[str, str]],
    clipped: list[dict[str, str]],
    errors: list[str],
) -> None:
    state_groups = _group(state, ("candidate_config_id", "state_line"))
    interval_groups = _group(intervals, ("candidate_config_id", "state_line"))
    clipped_index = {
        (row["candidate_config_id"], row["state_line"], row["year"]): row
        for row in clipped
    }
    for key, state_rows in state_groups.items():
        confirmed_days = sum(
            _int(row, "confirmed_state_true_count") for row in state_rows
        )
        duration = sum(
            _int(row, "confirmed_interval_total_duration")
            for row in interval_groups[key]
        )
        if confirmed_days != duration:
            errors.append(f"interval_duration_pooled:{key}")
        for row in state_rows:
            clipped_row = clipped_index[(key[0], key[1], row["year"])]
            if _int(clipped_row, "calendar_year_clipped_duration_total") != _int(
                row, "confirmed_state_true_count"
            ):
                errors.append(f"clipped_duration:{key}:{row['year']}")
    for row in intervals:
        count = _int(row, "confirmed_interval_count")
        for numerator, rate in (
            ("single_day_fragment_count", "fragment_rate"),
            ("open_interval_count", "open_interval_ratio"),
            ("cross_year_interval_count", "cross_year_interval_ratio"),
        ):
            expected = _int(row, numerator) / count if count else None
            _check_close(
                _optional_float(row, rate), expected, errors, f"interval_formula:{rate}"
            )


def _check_interlayer(rows: list[dict[str, str]], errors: list[str]) -> None:
    for row in rows:
        cells = sum(_int(row, key) for key in ("n11", "n10", "n01", "n00"))
        if cells != _int(row, "N"):
            errors.append(
                f"interlayer_conservation:{row['step_id']}:{row['W']}:{row['year']}"
            )
        n11, n10, n01 = (_int(row, key) for key in ("n11", "n10", "n01"))
        N = _int(row, "N")
        retention = n11 / (n11 + n10) if n11 + n10 else None
        marginal = (n11 + n01) / N if N else None
        lift = retention / marginal if retention is not None and marginal else None
        delta = (
            retention - marginal
            if retention is not None and marginal is not None
            else None
        )
        for key, expected in (
            ("retention", retention),
            ("target_marginal_rate", marginal),
            ("association_lift", lift),
            ("absolute_increment", delta),
        ):
            _check_close(
                _optional_float(row, key), expected, errors, f"interlayer_formula:{key}"
            )


def _check_recomputed(
    rows: dict[str, list[dict[str, str]]], config: dict[str, Any], errors: list[str]
) -> None:
    normalized_state = [_convert(row) for row in rows["state"]]
    normalized_interval = [_convert(row) for row in rows["interval"]]
    normalized_interlayer = [_convert(row) for row in rows["interlayer"]]
    expected_concentration = build_concentration_summary(
        normalized_state, normalized_interval, normalized_interlayer, config
    )
    actual_concentration = rows["concentration"]
    if len(expected_concentration) != len(actual_concentration):
        errors.append("concentration_recompute_row_count")
    expected_by_key = {_summary_key(row): row for row in expected_concentration}
    for row in actual_concentration:
        expected = expected_by_key.get(_summary_key(row))
        if expected is None:
            errors.append(f"concentration_key:{_summary_key(row)}")
            continue
        for key in (
            "max_year_state_share",
            "top2_year_state_share",
            "year_hhi",
            "effective_year_count",
            "delta_weighted_mean",
            "delta_unweighted_median",
            "min_year_delta",
            "max_year_delta",
        ):
            if key in expected:
                _check_close(
                    _optional_float(row, key),
                    expected.get(key),
                    errors,
                    f"concentration_formula:{key}",
                )
        if row.get("candidate_stability_status") != expected.get(
            "candidate_stability_status"
        ) or row.get("warnings", "") != expected.get("warnings", ""):
            errors.append(f"concentration_status:{_summary_key(row)}")
    expected_loyo = build_leave_one_year_out(
        normalized_state, normalized_interval, normalized_interlayer, config
    )
    actual_loyo = rows["loyo"]
    expected_loyo_index = {_loyo_key(row): row for row in expected_loyo}
    for row in actual_loyo:
        expected = expected_loyo_index.get(_loyo_key(row))
        if expected is None:
            errors.append(f"loyo_key:{_loyo_key(row)}")
            continue
        for key in (
            "confirmed_state_days_without_year",
            "N_without_year",
            "n11_without_year",
            "n10_without_year",
            "n01_without_year",
            "n00_without_year",
        ):
            if expected.get(key) is not None and _int(row, key) != int(expected[key]):
                errors.append(f"loyo_count:{key}:{_loyo_key(row)}")
        for key in (
            "confirmed_coverage_without_year",
            "remaining_year_hhi",
            "retention_without_year",
            "target_marginal_without_year",
            "lift_without_year",
            "delta_without_year",
        ):
            if key in expected:
                _check_close(
                    _optional_float(row, key),
                    expected.get(key),
                    errors,
                    f"loyo_formula:{key}",
                )
        if _as_bool(row["sign_flip"]) != bool(expected["sign_flip"]):
            errors.append(f"loyo_sign_flip:{_loyo_key(row)}")


def _check_forbidden_columns(
    rows: dict[str, list[dict[str, str]]], errors: list[str]
) -> None:
    forbidden = {
        "freeze_candidate",
        "winner",
        "best_window",
        "best_candidate",
        "yearly_null_pass",
    }
    for name, artifact_rows in rows.items():
        if artifact_rows and forbidden & set(artifact_rows[0]):
            errors.append(f"forbidden_columns:{name}")


def _summary_key(row: dict[str, Any]) -> tuple[Any, ...]:
    if row["summary_scope"] == "candidate_state":
        return (
            row["summary_scope"],
            row.get("candidate_config_id"),
            row.get("state_line"),
            row.get("analysis_level"),
        )
    return (
        row["summary_scope"],
        row.get("step_id"),
        str(row.get("W")),
        str(row.get("q")),
    )


def _loyo_key(row: dict[str, Any]) -> tuple[Any, ...]:
    if row["scope_type"] == "candidate_state":
        return (
            row["scope_type"],
            row.get("candidate_config_id"),
            row.get("state_line"),
            str(row.get("removed_year")),
        )
    return (
        row["scope_type"],
        row.get("step_id"),
        str(row.get("W")),
        str(row.get("q")),
        str(row.get("removed_year")),
    )


def _convert(row: dict[str, str]) -> dict[str, Any]:
    converted: dict[str, Any] = {}
    for key, value in row.items():
        if value == "":
            converted[key] = None
        elif value.lower() in ("true", "false"):
            converted[key] = value.lower() == "true"
        else:
            try:
                converted[key] = int(value)
            except ValueError:
                try:
                    converted[key] = float(value)
                except ValueError:
                    converted[key] = value
    return converted


def _group(
    rows: list[dict[str, str]], keys: tuple[str, ...]
) -> dict[tuple[str, ...], list[dict[str, str]]]:
    result: dict[tuple[str, ...], list[dict[str, str]]] = {}
    for row in rows:
        result.setdefault(tuple(row[key] for key in keys), []).append(row)
    return result


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise R1T09ValidationError(f"missing artifact: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _int(row: dict[str, str], key: str) -> int:
    return int(row.get(key) or 0)


def _float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def _optional_float(row: dict[str, str], key: str) -> float | None:
    value = row.get(key)
    return None if value in (None, "") else float(value)


def _check_close(actual: Any, expected: Any, errors: list[str], label: str) -> None:
    if actual is None and expected is None:
        return
    if (
        actual is None
        or expected is None
        or not math.isclose(
            float(actual), float(expected), rel_tol=1e-10, abs_tol=1e-12
        )
    ):
        errors.append(label)
