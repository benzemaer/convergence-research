from __future__ import annotations

import csv
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


class R1T04ValidationError(RuntimeError):
    pass


def validate_r1_t04_state_line_profiles(
    *,
    summary_path: Path,
    result_package_path: Path | None = None,
    output_path: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    errors: list[str] = []
    summary = _load(summary_path, errors, "summary")
    if summary.get("task_id") != "R1-T04":
        errors.append("task_id_mismatch")
    if summary.get("status") != "completed":
        errors.append("summary_not_completed")
    outputs = summary.get("output_paths", {})
    required = {
        "state_line_profile_csv": 14,
        "state_line_profile_json": 14,
        "duration_profile_csv": 14,
        "reference_challenger_comparison_csv": 10,
        "daily_overlap_profile_csv": 10,
        "parent_child_profile_csv": 8,
        "year_concentration_profile_csv": 1,
        "diagnostic_summary": 1,
        "anomaly_scan": 1,
    }
    for name, minimum in required.items():
        item = outputs.get(name)
        if not item:
            errors.append(f"missing_output:{name}")
            continue
        path = root / item["path"]
        if not path.exists():
            errors.append(f"missing_file:{name}")
            continue
        if sha256_file(path) != item.get("sha256"):
            errors.append(f"hash_mismatch:{name}")
        if path.suffix == ".csv" and _csv_count(path) < minimum:
            errors.append(f"row_count:{name}")
    _check_required_profile_metrics(outputs, root, errors)
    checks = summary.get("checks", {})
    if any(value != "passed" for value in checks.values()):
        errors.append("summary_check_failed")
    if summary.get("blocked_reasons"):
        errors.append("blocked_reasons_present")
    if result_package_path is not None:
        package = _load(result_package_path, errors, "result_package")
        if package.get("task_id") != "R1-T04":
            errors.append("result_package_task_mismatch")
        if package.get("run_id") != summary.get("run_id"):
            errors.append("result_package_run_mismatch")
        if package.get("code_commit") != summary.get("code_commit"):
            errors.append("result_package_commit_mismatch")
    result = {
        "task_id": "R1-T04",
        "run_id": summary.get("run_id"),
        "code_commit": summary.get("code_commit"),
        "validator_status": "passed" if not errors else "failed",
        "summary_path": _rel(summary_path, root),
        "summary_sha256": sha256_file(summary_path) if summary_path.exists() else None,
        "result_package_path": _rel(result_package_path, root)
        if result_package_path
        else None,
        "errors": errors,
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(
            (
                json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
        )
    if errors:
        raise R1T04ValidationError(json.dumps(result, ensure_ascii=False))
    return result


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load(path: Path, errors: list[str], name: str) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{name}_load:{exc}")
        return {}


def _csv_count(path: Path) -> int:
    return max(0, len(path.read_text(encoding="utf-8").splitlines()) - 1)


def _check_required_profile_metrics(
    outputs: dict[str, Any], root: Path, errors: list[str]
) -> None:
    state_profiles = {
        row["candidate_config_id"]: row
        for row in _csv_rows(outputs, root, "state_line_profile_csv", errors)
        if row.get("state_line") == "S_PCVT" and row.get("analysis_level") == "raw"
    }
    overlap = _csv_rows(outputs, root, "daily_overlap_profile_csv", errors)
    for row in overlap:
        _require_numeric(
            row,
            (
                "both_onset",
                "reference_only_onset",
                "challenger_only_onset",
                "onset_jaccard",
            ),
            "onset_overlap",
            errors,
        )
        union = (
            _float(row, "both_onset")
            + _float(row, "reference_only_onset")
            + _float(row, "challenger_only_onset")
        )
        if (
            union <= 0
            or abs(_float(row, "onset_jaccard") - _float(row, "both_onset") / union)
            > 1e-12
        ):
            errors.append("onset_overlap_recomputation")
    parent = _csv_rows(outputs, root, "parent_child_profile_csv", errors)
    for row in parent:
        _require_numeric(
            row,
            (
                "child_onset_count",
                "child_onset_parent_active_count",
                "child_start_delay_from_parent_observations",
                "child_duration_share_of_parent_interval",
            ),
            "parent_child_geometry",
            errors,
        )
        if row.get("analysis_level") == "raw":
            if row.get("geometry_unit") != "raw_segment":
                errors.append("raw_parent_child_geometry_unit")
            _require_numeric(
                row,
                (
                    "child_left_censored_start_count",
                    "child_segment_count",
                    "child_segment_contained_in_parent_count",
                ),
                "raw_parent_child_segment",
                errors,
            )
            config_id = row.get("candidate_config_id", "")
            profile = state_profiles.get(config_id)
            if profile is None:
                errors.append("raw_parent_child_state_profile_missing")
            elif (
                _float(row, "child_onset_count")
                + _float(row, "child_left_censored_start_count")
                != _float(row, "child_segment_count")
                or _float(row, "child_onset_count") != _float(profile, "onset_count")
                or _float(row, "child_segment_count")
                != _float(profile, "segment_or_interval_count")
            ):
                errors.append("raw_parent_child_onset_accounting")
        elif row.get("analysis_level") == "confirmed":
            if row.get("geometry_unit") != "confirmed_interval":
                errors.append("confirmed_parent_child_geometry_unit")
            _require_numeric(
                row,
                ("child_interval_count", "child_interval_contained_in_parent_count"),
                "confirmed_parent_child_interval",
                errors,
            )
            if _float(row, "child_onset_count") != _float(row, "child_interval_count"):
                errors.append("confirmed_parent_child_onset_accounting")
        if _float(row, "child_onset_parent_active_count") > _float(
            row, "child_onset_count"
        ):
            errors.append("parent_child_onset_parent_active_exceeds_onset")
        else:
            errors.append("parent_child_analysis_level")
    comparisons = _csv_rows(
        outputs, root, "reference_challenger_comparison_csv", errors
    )
    for row in comparisons:
        _require_numeric(
            row, ("max_year_share_delta",), "comparison_year_delta", errors
        )
    scan_path = _output_path(outputs, root, "anomaly_scan", errors)
    if scan_path and scan_path.exists():
        scan = _load(scan_path, errors, "anomaly_scan")
        for name in (
            "all_null_check",
            "baseline_challenger_check",
            "nested_invariant_check",
        ):
            if scan.get("checks", {}).get(name, {}).get("status") != "passed":
                errors.append(f"anomaly_check:{name}")


def _csv_rows(
    outputs: dict[str, Any], root: Path, name: str, errors: list[str]
) -> list[dict[str, str]]:
    path = _output_path(outputs, root, name, errors)
    if path is None or not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _output_path(
    outputs: dict[str, Any], root: Path, name: str, errors: list[str]
) -> Path | None:
    item = outputs.get(name)
    if not item:
        return None
    path = root / item["path"]
    if not path.exists():
        errors.append(f"missing_file:{name}")
        return None
    return path


def _require_numeric(
    row: dict[str, str], fields: tuple[str, ...], label: str, errors: list[str]
) -> None:
    for field in fields:
        try:
            _float(row, field)
        except (TypeError, ValueError):
            errors.append(f"{label}_missing:{field}")


def _float(row: dict[str, str], field: str) -> float:
    value = row.get(field)
    if value in (None, ""):
        raise ValueError(field)
    return float(value)


def _rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
