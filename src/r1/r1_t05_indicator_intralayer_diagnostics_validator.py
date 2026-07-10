from __future__ import annotations

import csv
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


class R1T05ValidationError(RuntimeError):
    pass


def validate_r1_t05_indicator_intralayer_diagnostics(
    *,
    summary_path: Path,
    result_package_path: Path | None = None,
    output_path: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    errors: list[str] = []
    summary = _load(summary_path, errors, "summary")
    if summary.get("task_id") != "R1-T05":
        errors.append("task_id_mismatch")
    if summary.get("status") != "completed":
        errors.append("summary_not_completed")
    outputs = summary.get("output_paths", {})
    required_rows = {
        "indicator_raw_distribution_csv": 8,
        "indicator_score_distribution_csv": 24,
        "indicator_hit_duration_csv": 72,
        "intralayer_correlation_csv": 12,
        "intralayer_threshold_structure_csv": 36,
        "intralayer_diagnostic_summary_csv": 12,
        "r0_t06_reconciliation_csv": 72,
    }
    for name, expected in required_rows.items():
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
        if _csv_count(path) != expected:
            errors.append(f"row_count:{name}")
    if (
        _csv_count(
            root / outputs.get("validity_reason_profile_csv", {}).get("path", "")
        )
        <= 0
    ):
        errors.append("validity_reason_profile_empty")
    _validate_raw_distribution(outputs, root, errors)
    _validate_score_distribution(outputs, root, errors)
    _validate_hit_duration(outputs, root, errors)
    _validate_correlation(outputs, root, errors)
    _validate_threshold(outputs, root, errors)
    _validate_reconciliation(outputs, root, errors)
    _validate_summary_checks(summary, errors)
    if result_package_path is not None:
        package = _load(result_package_path, errors, "result_package")
        if package.get("task_id") != "R1-T05":
            errors.append("result_package_task_mismatch")
        if package.get("run_id") != summary.get("run_id"):
            errors.append("result_package_run_mismatch")
        if package.get("code_commit") != summary.get("code_commit"):
            errors.append("result_package_commit_mismatch")
        gate = package.get("gate_status", {})
        if gate.get("scientific_review_status") != "pending":
            errors.append("scientific_review_not_pending")
        if package.get("downstream_gate_allowed") is not False:
            errors.append("downstream_gate_not_false")
    result = {
        "task_id": "R1-T05",
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
        raise R1T05ValidationError(json.dumps(result, ensure_ascii=False))
    return result


def _validate_raw_distribution(
    outputs: dict[str, Any], root: Path, errors: list[str]
) -> None:
    rows = _rows(outputs, root, "indicator_raw_distribution_csv", errors)
    ids = {row["indicator_id"] for row in rows}
    if ids != {
        "P1_NATR14",
        "P2_LogRange20",
        "C1_LogMASpread_5_60",
        "C2_AdjVWAPSpread_5_60",
        "T1_ER20",
        "T2_AbsTrendT20",
        "V1_TurnoverShrink20_60",
        "V2_AmountLevel20Pct",
    }:
        errors.append("indicator_registry_mismatch")
    for row in rows:
        if _int(row, "domain_violation_count") != 0:
            errors.append("raw_domain_violation")
        if row["indicator_id"] == "C2_AdjVWAPSpread_5_60" and (
            _int(row, "valid_count") != 1659385
            or _int(row, "unknown_count") != 38879
            or _int(row, "blocked_count") != 32505
        ):
            errors.append("c2_repaired_count_mismatch")
        if (
            row["indicator_id"] == "V2_AmountLevel20Pct"
            and row["raw_source_indicator_id"] != "V2_LogAmount20_base"
        ):
            errors.append("v2_mapping_mismatch")


def _validate_score_distribution(
    outputs: dict[str, Any], root: Path, errors: list[str]
) -> None:
    rows = _rows(outputs, root, "indicator_score_distribution_csv", errors)
    by_indicator: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if _int(row, "score_formula_mismatch_count") != 0:
            errors.append("score_formula_mismatch")
        if _int(row, "percentile_bounds_violation_count") != 0:
            errors.append("percentile_bounds_violation")
        if _int(row, "current_value_in_reference_set_true_count") != 0:
            errors.append("current_value_in_reference_set_true")
        if _int(row, "non_midrank_tie_method_count") != 0:
            errors.append("tie_method_not_midrank")
        by_indicator.setdefault(row["indicator_id"], []).append(row)
    for rows_for_indicator in by_indicator.values():
        rows_for_indicator.sort(key=lambda row: int(row["W"]))
        eligible = [_int(row, "eligible_count") for row in rows_for_indicator]
        unknown = [
            _float(row, "unknown_count") / _float(row, "total_row_count")
            for row in rows_for_indicator
        ]
        if not (eligible[0] >= eligible[1] >= eligible[2]):
            errors.append("w_eligible_not_monotone")
        if not (unknown[0] <= unknown[1] <= unknown[2]):
            errors.append("w_unknown_not_monotone")


def _validate_hit_duration(
    outputs: dict[str, Any], root: Path, errors: list[str]
) -> None:
    rows = _rows(outputs, root, "indicator_hit_duration_csv", errors)
    by_indicator: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        if _int(row, "segment_count") != _int(row, "strict_onset_count") + _int(
            row, "left_censored_start_count"
        ):
            errors.append("indicator_segment_onset_mismatch")
        if _int(row, "total_hit_duration") != _int(row, "hit_true_day_count"):
            errors.append("indicator_duration_total_mismatch")
        by_indicator.setdefault((row["indicator_id"], row["W"]), []).append(row)
    for rows_for_key in by_indicator.values():
        rows_for_key.sort(key=lambda row: float(row["q"]))
        hits = [_int(row, "hit_true_day_count") for row in rows_for_key]
        if not (hits[0] <= hits[1] <= hits[2]):
            errors.append("q_hit_count_not_nested")


def _validate_correlation(
    outputs: dict[str, Any], root: Path, errors: list[str]
) -> None:
    rows = _rows(outputs, root, "intralayer_correlation_csv", errors)
    if {(row["layer"], row["W"]) for row in rows} != {
        (layer, str(w)) for layer in ("P", "C", "T", "V") for w in (120, 250, 500)
    }:
        errors.append("correlation_grid_mismatch")
    for row in rows:
        if (
            abs(
                _float(row, "pooled_spearman_score")
                - _float(row, "pooled_spearman_percentile")
            )
            > 1e-12
        ):
            errors.append("spearman_reconciliation_mismatch")


def _validate_threshold(outputs: dict[str, Any], root: Path, errors: list[str]) -> None:
    rows = _rows(outputs, root, "intralayer_threshold_structure_csv", errors)
    by_layer: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        if _int(row, "both_hit") + _int(row, "indicator_a_only") + _int(
            row, "indicator_b_only"
        ) + _int(row, "neither") != _int(row, "common_eligible_rows"):
            errors.append("threshold_2x2_sum_mismatch")
        if _int(row, "joint_segment_count") != _int(
            row, "joint_strict_onset_count"
        ) + _int(row, "joint_left_censored_start_count"):
            errors.append("joint_segment_onset_mismatch")
        if _int(row, "joint_total_duration") != _int(row, "both_hit"):
            errors.append("joint_duration_total_mismatch")
        by_layer.setdefault((row["layer"], row["W"]), []).append(row)
    for rows_for_key in by_layer.values():
        rows_for_key.sort(key=lambda row: float(row["q"]))
        both = [_int(row, "both_hit") for row in rows_for_key]
        neither = [_int(row, "neither") for row in rows_for_key]
        if not (both[0] <= both[1] <= both[2]):
            errors.append("q_both_hit_not_nested")
        if not (neither[0] >= neither[1] >= neither[2]):
            errors.append("q_neither_not_monotone")


def _validate_reconciliation(
    outputs: dict[str, Any], root: Path, errors: list[str]
) -> None:
    rows = _rows(outputs, root, "r0_t06_reconciliation_csv", errors)
    for row in rows:
        if _int(row, "active_mismatch_count") != 0:
            errors.append("r0_t06_active_mismatch")


def _validate_summary_checks(summary: dict[str, Any], errors: list[str]) -> None:
    checks = summary.get("checks", {})
    if not checks:
        errors.append("summary_checks_missing")
    for name, status in checks.items():
        if status != "passed":
            errors.append(f"summary_check_failed:{name}")
    if summary.get("blocked_reasons"):
        errors.append("blocked_reasons_present")
    gates = summary.get("downstream_gates", {})
    if gates.get("R1-T06_allowed_to_start") is not False:
        errors.append("r1_t06_gate_not_false")


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path, errors: list[str], name: str) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{name}_load:{exc}")
        return {}


def _rows(
    outputs: dict[str, Any], root: Path, name: str, errors: list[str]
) -> list[dict[str, str]]:
    item = outputs.get(name)
    if not item:
        errors.append(f"missing_output:{name}")
        return []
    path = root / item["path"]
    if not path.exists():
        errors.append(f"missing_file:{name}")
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _csv_count(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open(encoding="utf-8", newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def _int(row: dict[str, str], key: str) -> int:
    value = row.get(key)
    if value in (None, ""):
        return 0
    return int(float(value))


def _float(row: dict[str, str], key: str) -> float:
    value = row.get(key)
    if value in (None, ""):
        raise ValueError(key)
    return float(value)


def _rel(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
