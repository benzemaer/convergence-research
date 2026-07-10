# ruff: noqa: E501

from __future__ import annotations

import csv
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PATHS = ("P_TO_C", "P_TO_T", "P_TO_V", "P_TO_PCT", "P_TO_PCVT")
WS = ("120", "250", "500")
QS = ("0.1", "0.2", "0.3")
LAGS = ("1", "3", "5", "10", "20")


class R1T07ValidationError(RuntimeError):
    pass


def validate_r1_t07_p_onset_fixed_lag_relations(
    *,
    summary_path: Path,
    result_package_path: Path | None = None,
    output_path: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    errors: list[str] = []
    summary = _load(summary_path, errors, "summary")
    if summary.get("task_id") != "R1-T07":
        errors.append("task_id_mismatch")
    if summary.get("status") != "completed":
        errors.append("summary_not_completed")
    outputs = summary.get("output_paths", {})
    required_rows = {
        "fixed_lag_profile_csv": 225,
        "baseline_sensitivity_csv": 225,
        "p_survival_profile_csv": 45,
        "anchor_target_status_profile_csv": 45,
        "anchor_funnel_csv": 9,
        "security_lag_summary_csv": 225,
        "state_reconciliation_csv": 54,
        "lag_alignment_reconciliation_csv": 45,
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
        not outputs.get("year_lag_profile_csv")
        or _csv_count(root / outputs.get("year_lag_profile_csv", {}).get("path", ""))
        <= 0
    ):
        errors.append("year_profile_empty")
    if (
        not outputs.get("q_onset_transition_profile_csv")
        or _csv_count(
            root / outputs.get("q_onset_transition_profile_csv", {}).get("path", "")
        )
        <= 0
    ):
        errors.append("q_transition_profile_empty")

    primary = _rows(outputs, root, "fixed_lag_profile_csv", errors)
    baseline = _rows(outputs, root, "baseline_sensitivity_csv", errors)
    survival = _rows(outputs, root, "p_survival_profile_csv", errors)
    anchor_target = _rows(outputs, root, "anchor_target_status_profile_csv", errors)
    funnel = _rows(outputs, root, "anchor_funnel_csv", errors)
    state = _rows(outputs, root, "state_reconciliation_csv", errors)
    lag_alignment = _rows(outputs, root, "lag_alignment_reconciliation_csv", errors)
    _validate_primary(primary, errors)
    _validate_baseline(baseline, errors)
    _validate_survival(survival, errors)
    _validate_anchor_target(anchor_target, primary, errors)
    _validate_funnel(funnel, errors)
    _validate_state_reconciliation(state, errors)
    _validate_lag_alignment(lag_alignment, errors)
    _validate_summary_checks(summary, errors)
    if result_package_path is not None:
        package = _load(result_package_path, errors, "result_package")
        if package.get("task_id") != "R1-T07":
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
        "task_id": "R1-T07",
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
        raise R1T07ValidationError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _validate_primary(rows: list[dict[str, str]], errors: list[str]) -> None:
    expected = {
        (path, w, q, lag) for path in PATHS for w in WS for q in QS for lag in LAGS
    }
    if {
        (row["transition_path"], row["W"], row["q"], row["lag_k"]) for row in rows
    } != expected:
        errors.append("primary_grid_mismatch")
    if {row["K"] for row in rows} != {"not_applicable"}:
        errors.append("k_grid_violation")
    for row in rows:
        event_total = (
            _int(row, "target_true_event_count")
            + _int(row, "target_false_event_count")
            + _int(row, "target_invalid_event_count")
            + _int(row, "event_right_censored_count")
        )
        control_total = (
            _int(row, "target_true_control_count")
            + _int(row, "target_false_control_count")
            + _int(row, "target_invalid_control_count")
            + _int(row, "control_right_censored_count")
        )
        if event_total != _int(row, "anchor_event_count"):
            errors.append("event_funnel_mismatch")
        if control_total != _int(row, "control_anchor_count"):
            errors.append("control_funnel_mismatch")
        obs = (
            None
            if _int(row, "target_valid_event_count") == 0
            else _int(row, "target_true_event_count")
            / _int(row, "target_valid_event_count")
        )
        base = (
            None
            if _int(row, "target_valid_control_count") == 0
            else _int(row, "target_true_control_count")
            / _int(row, "target_valid_control_count")
        )
        diff = None if obs is None or base is None else obs - base
        rel = None if obs is None or base in (None, 0) else obs / base
        if not _float_matches(_float_or_none(row, "observed_probability"), obs):
            errors.append("observed_probability_formula_mismatch")
        if not _float_matches(_float_or_none(row, "baseline_probability"), base):
            errors.append("baseline_probability_formula_mismatch")
        if not _float_matches(_float_or_none(row, "absolute_difference"), diff):
            errors.append("absolute_difference_formula_mismatch")
        if not _float_matches(_float_or_none(row, "absolute_lift"), diff):
            errors.append("absolute_lift_alias_mismatch")
        if not _float_matches(_float_or_none(row, "relative_lift"), rel):
            errors.append("relative_lift_formula_mismatch")
    for w in WS:
        for q in QS:
            counts = {
                _int(row, "anchor_event_count")
                for row in rows
                if row["W"] == w and row["q"] == q
            }
            if len(counts) != 1:
                errors.append("anchor_count_varies_by_path_or_lag")


def _validate_baseline(rows: list[dict[str, str]], errors: list[str]) -> None:
    if len(rows) != 225:
        return
    for row in rows:
        for key in (
            "primary_stay_out_baseline_probability",
            "unconditional_lag_support_marginal_probability",
            "target_status_standardized_baseline_probability",
            "security_year_standardized_baseline_probability",
        ):
            value = _float_or_none(row, key)
            if value is not None and not (0 <= value <= 1):
                errors.append(f"baseline_probability_out_of_range:{key}")


def _validate_survival(rows: list[dict[str, str]], errors: list[str]) -> None:
    for w in WS:
        for q in QS:
            ordered = sorted(
                [row for row in rows if row["W"] == w and row["q"] == q],
                key=lambda row: _int(row, "lag_k"),
            )
            values = [_int(row, "p_run_survival_true_count") for row in ordered]
            if any(values[i] < values[i + 1] for i in range(len(values) - 1)):
                errors.append("p_survival_increases_with_lag")
            availability = [_int(row, "p_survival_eligible_count") for row in ordered]
            if any(
                availability[i] < availability[i + 1]
                for i in range(len(availability) - 1)
            ):
                errors.append("p_survival_eligibility_increases_with_lag")


def _validate_anchor_target(
    rows: list[dict[str, str]],
    primary: list[dict[str, str]],
    errors: list[str],
) -> None:
    if len(rows) != 45:
        return
    primary_counts = {
        (row["transition_path"], row["W"], row["q"]): _int(row, "anchor_event_count")
        for row in primary
        if row["lag_k"] == "1"
    }
    for row in rows:
        key = (row["transition_path"], row["W"], row["q"])
        if _int(row, "anchor_event_count") != primary_counts.get(key):
            errors.append("anchor_target_anchor_count_mismatch")
        valid = _int(row, "target_valid_at_anchor_count")
        active = _int(row, "target_already_active_at_anchor_count")
        inactive = _int(row, "target_inactive_at_anchor_count")
        if active + inactive != valid:
            errors.append("anchor_target_status_sum_mismatch")


def _validate_funnel(rows: list[dict[str, str]], errors: list[str]) -> None:
    if len(rows) != 9:
        return
    for row in rows:
        category_sum = (
            _int(row, "previous_absent_count")
            + _int(row, "previous_invalid_count")
            + _int(row, "current_invalid_count")
            + _int(row, "onset_count")
            + _int(row, "stay_out_count")
            + _int(row, "continuing_P_count")
            + _int(row, "exit_count")
            + _int(row, "other_count")
        )
        if category_sum < _int(row, "total_rows"):
            errors.append("anchor_funnel_under_counts")
        if _int(row, "onset_count") < 1 or _int(row, "stay_out_count") < 1:
            errors.append("anchor_funnel_missing_event_or_control")


def _validate_state_reconciliation(
    rows: list[dict[str, str]], errors: list[str]
) -> None:
    if len(rows) != 54:
        return
    for row in rows:
        if _int(row, "missing_key_count") != 0:
            errors.append("state_missing_key")
        if _int(row, "row_mismatch_count") != 0:
            errors.append("state_row_mismatch")


def _validate_lag_alignment(rows: list[dict[str, str]], errors: list[str]) -> None:
    if len(rows) != 45:
        return
    for row in rows:
        if _int(row, "offset_mismatch_count") != 0:
            errors.append("lag_offset_mismatch")
    for w in WS:
        for q in QS:
            ordered = sorted(
                [row for row in rows if row["W"] == w and row["q"] == q],
                key=lambda row: _int(row, "lag_k"),
            )
            values = [_int(row, "lag_available_anchor_count") for row in ordered]
            if any(values[i] < values[i + 1] for i in range(len(values) - 1)):
                errors.append("lag_availability_increases_with_lag")


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
    if gates.get("R1-T08_allowed_to_start") is not False:
        errors.append("r1_t08_gate_not_false")
    if gates.get("R2_allowed_to_start") is not False:
        errors.append("r2_gate_not_false")
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
