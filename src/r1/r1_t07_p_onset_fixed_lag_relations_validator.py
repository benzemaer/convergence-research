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
    _validate_baseline(baseline, primary, errors)
    _validate_survival(survival, errors)
    _validate_anchor_target(anchor_target, primary, errors)
    _validate_funnel(funnel, errors)
    _validate_state_reconciliation(state, errors)
    _validate_lag_alignment(lag_alignment, errors)
    _validate_bootstrap(summary, root, errors)
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
    degenerate_bootstrap_rows = 0
    bootstrap_checked_rows = 0
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
        diff_low = _float_or_none(row, "absolute_difference_ci_low")
        diff_high = _float_or_none(row, "absolute_difference_ci_high")
        obs_low = _float_or_none(row, "observed_probability_ci_low")
        obs_high = _float_or_none(row, "observed_probability_ci_high")
        base_low = _float_or_none(row, "baseline_probability_ci_low")
        base_high = _float_or_none(row, "baseline_probability_ci_high")
        if obs is not None and base is not None and diff is not None:
            bootstrap_checked_rows += 1
            if (
                diff_low is None
                or diff_high is None
                or obs_low is None
                or obs_high is None
                or base_low is None
                or base_high is None
            ):
                errors.append("bootstrap_interval_missing")
            elif not (
                obs_low <= obs <= obs_high
                and base_low <= base <= base_high
                and diff_low <= diff <= diff_high
            ):
                errors.append("bootstrap_interval_excludes_point_estimate")
            elif (
                _float_matches(diff_low, diff)
                and _float_matches(diff_high, diff)
                and _float_matches(obs_low, obs)
                and _float_matches(obs_high, obs)
                and _float_matches(base_low, base)
                and _float_matches(base_high, base)
            ):
                degenerate_bootstrap_rows += 1
            status = row.get("descriptive_status")
            if diff_low is not None and diff_high is not None:
                expected_status = (
                    "positive_interval_separated"
                    if diff_low > 0
                    else "negative_interval_separated"
                    if diff_high < 0
                    else "interval_overlaps_zero"
                )
                if status != expected_status:
                    errors.append("descriptive_status_ci_mismatch")
    for w in WS:
        for q in QS:
            counts = {
                _int(row, "anchor_event_count")
                for row in rows
                if row["W"] == w and row["q"] == q
            }
            if len(counts) != 1:
                errors.append("anchor_count_varies_by_path_or_lag")
    if bootstrap_checked_rows and degenerate_bootstrap_rows == bootstrap_checked_rows:
        errors.append("bootstrap_intervals_degenerate")


def _validate_baseline(
    rows: list[dict[str, str]],
    primary: list[dict[str, str]],
    errors: list[str],
) -> None:
    if len(rows) != 225:
        return
    primary_event_denominator = {
        (row["transition_path"], row["W"], row["q"], row["lag_k"]): _int(
            row, "target_valid_event_count"
        )
        for row in primary
    }
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
        matched = _int(row, "security_year_matched_anchor_count")
        target_matched = _int(row, "target_status_matched_event_count")
        target_true = _int(row, "target_status_matched_true_count")
        event_denom = primary_event_denominator.get(
            (row["transition_path"], row["W"], row["q"], row["lag_k"])
        )
        if event_denom is not None and (
            matched > event_denom or target_matched > event_denom
        ):
            errors.append("security_year_standardization_denominator_mismatch")
        target_coverage = _float_or_none(row, "target_status_matched_event_coverage")
        target_observed = _float_or_none(
            row, "target_status_matched_observed_probability"
        )
        target_baseline = _float_or_none(
            row, "target_status_standardized_baseline_probability"
        )
        target_difference = _float_or_none(
            row, "target_status_standardized_absolute_difference"
        )
        if event_denom is not None and not _float_matches(
            target_coverage, target_matched / event_denom
        ):
            errors.append("target_status_matched_coverage_mismatch")
        expected_observed = (
            None if target_matched == 0 else target_true / target_matched
        )
        if not _float_matches(target_observed, expected_observed):
            errors.append("target_status_matched_observed_probability_mismatch")
        expected_difference = (
            None
            if target_observed is None or target_baseline is None
            else target_observed - target_baseline
        )
        if not _float_matches(target_difference, expected_difference):
            errors.append("target_status_standardized_estimand_mismatch")
        coverage = _float_or_none(row, "security_year_coverage")
        if coverage is not None and not (0 <= coverage <= 1):
            errors.append("security_year_coverage_out_of_range")


def _validate_survival(rows: list[dict[str, str]], errors: list[str]) -> None:
    for row in rows:
        for key in (
            "PCT_target_valid_given_surviving_P_run_count",
            "PCT_target_true_given_surviving_P_run_count",
            "PCT_target_given_surviving_P_run_probability",
        ):
            if key not in row:
                errors.append(f"survival_pct_target_field_missing:{key}")
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
        if category_sum != _int(row, "total_rows"):
            errors.append("anchor_funnel_partition_mismatch")
        if _int(row, "onset_count") < 1 or _int(row, "stay_out_count") < 1:
            errors.append("anchor_funnel_missing_event_or_control")


def _validate_state_reconciliation(
    rows: list[dict[str, str]], errors: list[str]
) -> None:
    if len(rows) != 54:
        return
    for row in rows:
        if _int(row, "r0_key_count") != _int(row, "derived_key_count"):
            errors.append("state_key_count_mismatch")
        if _int(row, "r0_true_count") + _int(row, "r0_false_count") + _int(
            row, "r0_null_count"
        ) != _int(row, "r0_key_count"):
            errors.append("state_r0_count_partition_mismatch")
        if _int(row, "derived_true_count") + _int(row, "derived_false_count") + _int(
            row, "derived_null_count"
        ) != _int(row, "derived_key_count"):
            errors.append("state_derived_count_partition_mismatch")
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


def _validate_bootstrap(summary: dict[str, Any], root: Path, errors: list[str]) -> None:
    configured = summary.get("bootstrap", {})
    if configured.get("cluster_key") != "security_id":
        errors.append("bootstrap_cluster_key_mismatch")
    if configured.get("B_boot") != 2000:
        errors.append("bootstrap_B_boot_mismatch")
    if not isinstance(configured.get("seed"), int):
        errors.append("bootstrap_seed_missing")
    if configured.get("max_failed_replicates") != 0:
        errors.append("bootstrap_failed_replicate_policy_mismatch")
    diagnostic_item = summary.get("output_paths", {}).get("diagnostic_summary")
    if not diagnostic_item:
        errors.append("bootstrap_diagnostic_summary_missing")
        return
    diagnostic_path = root / diagnostic_item["path"]
    diagnostic = _load(diagnostic_path, errors, "bootstrap_diagnostic_summary")
    actual = diagnostic.get("bootstrap", {})
    if actual.get("B_boot") != configured.get("B_boot"):
        errors.append("bootstrap_actual_B_boot_mismatch")
    if actual.get("seed") != configured.get("seed"):
        errors.append("bootstrap_actual_seed_mismatch")
    if actual.get("interval_rows_written") != len(PATHS) * len(WS) * len(QS) * len(
        LAGS
    ):
        errors.append("bootstrap_interval_row_count_mismatch")
    if actual.get("failed_replicates") != configured.get("max_failed_replicates"):
        errors.append("bootstrap_failed_replicates_not_zero")


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
