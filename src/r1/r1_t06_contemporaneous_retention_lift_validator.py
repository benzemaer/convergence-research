from __future__ import annotations

import csv
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


class R1T06ValidationError(RuntimeError):
    pass


def validate_r1_t06_contemporaneous_retention_lift(
    *,
    summary_path: Path,
    result_package_path: Path | None = None,
    output_path: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    errors: list[str] = []
    summary = _load(summary_path, errors, "summary")
    if summary.get("task_id") != "R1-T06":
        errors.append("task_id_mismatch")
    if summary.get("status") != "completed":
        errors.append("summary_not_completed")
    outputs = summary.get("output_paths", {})
    required_rows = {
        "layer_step_profile_csv": 27,
        "denominator_sensitivity_csv": 27,
        "security_step_summary_csv": 27,
        "r0_nested_reconciliation_csv": 36,
        "dimension_state_reconciliation_csv": 36,
        "q_nesting_reconciliation_csv": 78,
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
    year_item = outputs.get("year_step_profile_csv")
    if not year_item or _csv_count(root / year_item.get("path", "")) <= 0:
        errors.append("year_profile_empty")

    primary = _rows(outputs, root, "layer_step_profile_csv", errors)
    denom = _rows(outputs, root, "denominator_sensitivity_csv", errors)
    security = _rows(outputs, root, "security_step_summary_csv", errors)
    nested = _rows(outputs, root, "r0_nested_reconciliation_csv", errors)
    dimension = _rows(outputs, root, "dimension_state_reconciliation_csv", errors)
    q_nesting = _rows(outputs, root, "q_nesting_reconciliation_csv", errors)
    _validate_primary(primary, errors)
    _validate_denominator_sensitivity(denom, errors)
    _validate_security_summary(security, errors)
    _validate_reconciliation(nested, dimension, errors)
    _validate_q_nesting_reconciliation(q_nesting, errors)
    _validate_summary_checks(summary, errors)
    if result_package_path is not None:
        package = _load(result_package_path, errors, "result_package")
        if package.get("task_id") != "R1-T06":
            errors.append("result_package_task_mismatch")
        if package.get("run_id") != summary.get("run_id"):
            errors.append("result_package_run_mismatch")
        if package.get("code_commit") != summary.get("code_commit"):
            errors.append("result_package_commit_mismatch")
        gate = package.get("gate_status", {})
        if gate.get("scientific_review_status") != "pending":
            errors.append("scientific_review_not_pending")
        if gate.get("review_phase") != "author_analysis_complete":
            errors.append("review_phase_not_author_analysis_complete")
        if gate.get("readme_gate_updated") is not False:
            errors.append("readme_gate_updated_in_author_draft")
        if package.get("downstream_gate_allowed") is not False:
            errors.append("downstream_gate_not_false")
    result = {
        "task_id": "R1-T06",
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
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if errors:
        raise R1T06ValidationError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _validate_primary(rows: list[dict[str, str]], errors: list[str]) -> None:
    expected = (
        {
            ("C_GIVEN_P", str(w), str(q))
            for w in (120, 250, 500)
            for q in (0.1, 0.2, 0.3)
        }
        | {
            ("T_GIVEN_PC", str(w), str(q))
            for w in (120, 250, 500)
            for q in (0.1, 0.2, 0.3)
        }
        | {
            ("V_GIVEN_PCT", str(w), str(q))
            for w in (120, 250, 500)
            for q in (0.1, 0.2, 0.3)
        }
    )
    if {(row["step_id"], row["W"], row["q"]) for row in rows} != expected:
        errors.append("primary_grid_mismatch")
    if {row["K"] for row in rows} != {"not_applicable"}:
        errors.append("k_grid_violation")
    for row in rows:
        n11, n10, n01, n00 = (_int(row, key) for key in ("n11", "n10", "n01", "n00"))
        n = _int(row, "N")
        anchor = _int(row, "anchor_true_count")
        target = _int(row, "target_true_count")
        child = _int(row, "child_true_count")
        if n11 + n10 + n01 + n00 != n:
            errors.append("primary_2x2_sum_mismatch")
        if anchor != n11 + n10 or target != n11 + n01:
            errors.append("primary_marginal_count_mismatch")
        if child != n11:
            errors.append("primary_child_count_mismatch")
        if child > anchor or child > target:
            errors.append("primary_child_exceeds_parent")
        expected_retention = None if anchor == 0 else child / anchor
        expected_target = None if n == 0 else target / n
        expected_lift = (
            None if anchor == 0 or target == 0 else expected_retention / expected_target
        )
        expected_delta = (
            None if expected_retention is None else expected_retention - expected_target
        )
        expected_nonanchor = (
            None
            if _int(row, "anchor_false_count") == 0
            else n01 / _int(row, "anchor_false_count")
        )
        expected_delta_nonanchor = (
            None
            if expected_retention is None or expected_nonanchor is None
            else expected_retention - expected_nonanchor
        )
        expected_anchor_rate = None if n == 0 else anchor / n
        expected_child_rate = None if n == 0 else child / n
        expected_joint_excess = (
            None
            if expected_child_rate is None
            else expected_child_rate - expected_anchor_rate * expected_target
        )
        comparisons = {
            "retention": expected_retention,
            "target_marginal_rate": expected_target,
            "lift": expected_lift,
            "delta": expected_delta,
            "nonanchor_target_rate": expected_nonanchor,
            "delta_nonanchor": expected_delta_nonanchor,
            "anchor_rate": expected_anchor_rate,
            "child_joint_rate": expected_child_rate,
            "joint_excess": expected_joint_excess,
        }
        for key, expected_value in comparisons.items():
            if not _float_matches(_float_or_none(row, key), expected_value):
                errors.append(f"primary_formula_mismatch:{key}")
        if (
            expected_retention is not None
            and expected_target is not None
            and expected_lift is not None
        ):
            if abs(expected_retention - expected_lift * expected_target) > 1e-12:
                errors.append("retention_lift_identity_mismatch")
            if (
                abs(expected_child_rate - expected_anchor_rate * expected_retention)
                > 1e-12
            ):
                errors.append("child_rate_identity_mismatch")
            if (
                abs(expected_joint_excess - expected_anchor_rate * expected_delta)
                > 1e-12
            ):
                errors.append("joint_excess_identity_mismatch")
    _validate_q_and_w_response(rows, errors)


def _validate_q_and_w_response(rows: list[dict[str, str]], errors: list[str]) -> None:
    for step in {"C_GIVEN_P", "T_GIVEN_PC", "V_GIVEN_PCT"}:
        for w in ("120", "250", "500"):
            ordered = sorted(
                [row for row in rows if row["step_id"] == step and row["W"] == w],
                key=lambda row: _float(row, "q"),
            )
            if len({_int(row, "N") for row in ordered}) != 1:
                errors.append("q_independent_denominator_violation")
            for key in ("anchor_true_count", "target_true_count", "child_true_count"):
                values = [_int(row, key) for row in ordered]
                if not (values[0] <= values[1] <= values[2]):
                    errors.append(f"q_nesting_violation:{key}")
        for q in ("0.1", "0.2", "0.3"):
            by_w = {
                row["W"]: _int(row, "N")
                for row in rows
                if row["step_id"] == step and row["q"] == q
            }
            if not (by_w["120"] >= by_w["250"] >= by_w["500"]):
                errors.append("w_availability_violation")
    for w in ("120", "250", "500"):
        for q in ("0.1", "0.2", "0.3"):
            by_step = {
                row["step_id"]: _int(row, "N")
                for row in rows
                if row["W"] == w and row["q"] == q
            }
            if not (
                by_step["C_GIVEN_P"] >= by_step["T_GIVEN_PC"] >= by_step["V_GIVEN_PCT"]
            ):
                errors.append("step_denominator_order_violation")


def _validate_denominator_sensitivity(
    rows: list[dict[str, str]], errors: list[str]
) -> None:
    for row in rows:
        if _int(row, "all4_common_denominator") > _int(row, "primary_step_denominator"):
            errors.append("all4_denominator_exceeds_primary")
        if row["step_id"] == "V_GIVEN_PCT":
            if _int(row, "all4_common_denominator") != _int(
                row, "primary_step_denominator"
            ):
                errors.append("v_step_all4_denominator_mismatch")
            for key in ("retention_difference", "lift_difference", "delta_difference"):
                if abs(_float(row, key)) > 1e-12:
                    errors.append(f"v_step_all4_metric_difference:{key}")


def _validate_security_summary(rows: list[dict[str, str]], errors: list[str]) -> None:
    if len(rows) != 27:
        return
    for row in rows:
        if not (0 < _int(row, "security_count_total") <= 800):
            errors.append("security_count_total_mismatch")
        if _int(row, "retention_computable_security_count") <= 0:
            errors.append("security_retention_uncomputable")


def _validate_reconciliation(
    nested: list[dict[str, str]],
    dimension: list[dict[str, str]],
    errors: list[str],
) -> None:
    for row in nested:
        if _int(row, "missing_key_count") != 0:
            errors.append("nested_missing_key")
        if _int(row, "row_mismatch_count") != 0:
            errors.append("nested_row_mismatch")
        if row.get("true_count_mismatch", "").lower() != "false":
            errors.append("nested_true_count_mismatch")
        if row.get("false_count_mismatch", "").lower() != "false":
            errors.append("nested_false_count_mismatch")
        if row.get("null_count_mismatch", "").lower() != "false":
            errors.append("nested_null_count_mismatch")
        if _int(row, "derived_true_count") != _int(row, "r0_true_count"):
            errors.append("nested_true_count_mismatch")
        if _int(row, "derived_false_count") != _int(row, "r0_false_count"):
            errors.append("nested_false_count_mismatch")
        if _int(row, "derived_null_count") != _int(row, "r0_null_count"):
            errors.append("nested_null_count_mismatch")
    for row in dimension:
        if _int(row, "active_mismatch_count") != 0:
            errors.append("dimension_active_mismatch")


def _validate_q_nesting_reconciliation(
    rows: list[dict[str, str]], errors: list[str]
) -> None:
    if len(rows) != 78:
        errors.append("q_nesting_row_count_mismatch")
        return
    expected_scopes = {
        "dimension_active",
        "anchor_active",
        "child_active",
        "denominator_keys",
    }
    if {row.get("scope_type") for row in rows} != expected_scopes:
        errors.append("q_nesting_scope_mismatch")
    denominator_rows = 0
    for row in rows:
        if _int(row, "lower_not_in_higher_count") != 0:
            errors.append("q_nesting_lower_not_in_higher")
        expected_symmetric_difference = _int(row, "lower_not_in_higher_count") + _int(
            row, "higher_not_in_lower_count"
        )
        if _int(row, "symmetric_difference_count") != expected_symmetric_difference:
            errors.append("q_nesting_symmetric_difference_formula")
        if row.get("scope_type") == "denominator_keys":
            denominator_rows += 1
            if _int(row, "higher_not_in_lower_count") != 0:
                errors.append("q_denominator_higher_not_in_lower")
            if _int(row, "symmetric_difference_count") != 0:
                errors.append("q_denominator_symmetric_difference")
            if _int(row, "lower_set_count") != _int(row, "higher_set_count"):
                errors.append("q_denominator_count_mismatch")
    if denominator_rows != 18:
        errors.append("q_denominator_row_count_mismatch")


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
    if gates.get("R1-T07_allowed_to_start") is not False:
        errors.append("r1_t07_gate_not_false")
    if gates.get("downstream_gate_allowed") is not False:
        errors.append("downstream_gate_not_false")


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


def _float_or_none(row: dict[str, str], key: str) -> float | None:
    value = row.get(key)
    return None if value in (None, "") else float(value)


def _float_matches(actual: float | None, expected: float | None) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    return abs(actual - expected) <= 1e-12


def _rel(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
