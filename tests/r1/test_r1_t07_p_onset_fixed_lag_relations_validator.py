# ruff: noqa: E501

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from src.r1.r1_t07_p_onset_fixed_lag_relations_validator import (
    R1T07ValidationError,
    validate_r1_t07_p_onset_fixed_lag_relations,
)

PATHS = ("P_TO_C", "P_TO_T", "P_TO_V", "P_TO_PCT", "P_TO_PCVT")
WS = (120, 250, 500)
QS = (0.1, 0.2, 0.3)
LAGS = (1, 3, 5, 10, 20)


class R1T07ValidatorTest(unittest.TestCase):
    def test_complete_author_draft_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            result = validate_r1_t07_p_onset_fixed_lag_relations(
                summary_path=summary,
                result_package_path=package,
                root=root,
            )
            self.assertEqual(result["validator_status"], "passed")

    def test_absolute_lift_alias_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            primary = root / "r1_t07_fixed_lag_profile.csv"
            rows = _read_rows(primary)
            rows[0]["absolute_lift"] = "999"
            _write_csv(primary, rows)
            _refresh_summary_hash(root, summary, "fixed_lag_profile_csv")
            with self.assertRaises(R1T07ValidationError) as raised:
                validate_r1_t07_p_onset_fixed_lag_relations(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("absolute_lift_alias_mismatch", str(raised.exception))

    def test_degenerate_bootstrap_intervals_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            primary = root / "r1_t07_fixed_lag_profile.csv"
            rows = _read_rows(primary)
            for row in rows:
                row["observed_probability_ci_low"] = row["observed_probability"]
                row["observed_probability_ci_high"] = row["observed_probability"]
                row["baseline_probability_ci_low"] = row["baseline_probability"]
                row["baseline_probability_ci_high"] = row["baseline_probability"]
                row["absolute_difference_ci_low"] = row["absolute_difference"]
                row["absolute_difference_ci_high"] = row["absolute_difference"]
            _write_csv(primary, rows)
            _refresh_summary_hash(root, summary, "fixed_lag_profile_csv")
            with self.assertRaises(R1T07ValidationError) as raised:
                validate_r1_t07_p_onset_fixed_lag_relations(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("bootstrap_intervals_degenerate", str(raised.exception))

    def test_anchor_funnel_overcount_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            funnel = root / "r1_t07_anchor_funnel.csv"
            rows = _read_rows(funnel)
            rows[0]["current_invalid_count"] = str(
                int(rows[0]["current_invalid_count"]) + 1
            )
            _write_csv(funnel, rows)
            _refresh_summary_hash(root, summary, "anchor_funnel_csv")
            with self.assertRaises(R1T07ValidationError) as raised:
                validate_r1_t07_p_onset_fixed_lag_relations(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("anchor_funnel_partition_mismatch", str(raised.exception))

    def test_security_year_denominator_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            baseline = root / "r1_t07_baseline_sensitivity.csv"
            rows = _read_rows(baseline)
            rows[0]["security_year_matched_anchor_count"] = "999"
            _write_csv(baseline, rows)
            _refresh_summary_hash(root, summary, "baseline_sensitivity_csv")
            with self.assertRaises(R1T07ValidationError) as raised:
                validate_r1_t07_p_onset_fixed_lag_relations(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn(
                "security_year_standardization_denominator_mismatch",
                str(raised.exception),
            )

    def test_author_draft_scientific_review_must_remain_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary, package = _write_fixture(root)
            payload = json.loads(package.read_text(encoding="utf-8"))
            payload["gate_status"]["scientific_review_status"] = "passed"
            package.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            with self.assertRaises(R1T07ValidationError) as raised:
                validate_r1_t07_p_onset_fixed_lag_relations(
                    summary_path=summary,
                    result_package_path=package,
                    root=root,
                )
            self.assertIn("scientific_review_not_pending", str(raised.exception))


def _write_fixture(root: Path) -> tuple[Path, Path]:
    primary = []
    for path in PATHS:
        for w in WS:
            for q in QS:
                for lag in LAGS:
                    event_valid = 80 - lag
                    control_valid = 100 - lag
                    event_true = 20
                    control_true = 10
                    obs = event_true / event_valid
                    base = control_true / control_valid
                    diff = obs - base
                    primary.append(
                        {
                            "task_id": "R1-T07",
                            "run_id": "R1-T07-SYNTH",
                            "code_commit": "a" * 40,
                            "transition_path": path,
                            "W": str(w),
                            "q": str(q),
                            "K": "not_applicable",
                            "lag_k": str(lag),
                            "anchor_event_count": "100",
                            "control_anchor_count": "120",
                            "lag_available_anchor_count": "100",
                            "lag_available_control_count": "120",
                            "target_valid_event_count": str(event_valid),
                            "target_true_event_count": str(event_true),
                            "target_false_event_count": str(event_valid - event_true),
                            "target_invalid_event_count": str(100 - event_valid),
                            "event_right_censored_count": "0",
                            "target_valid_control_count": str(control_valid),
                            "target_true_control_count": str(control_true),
                            "target_false_control_count": str(
                                control_valid - control_true
                            ),
                            "target_invalid_control_count": str(120 - control_valid),
                            "control_right_censored_count": "0",
                            "observed_probability": str(obs),
                            "baseline_probability": str(base),
                            "absolute_difference": str(diff),
                            "absolute_lift": str(diff),
                            "relative_lift": str(obs / base),
                            "observed_probability_ci_low": str(obs - 0.01),
                            "observed_probability_ci_high": str(obs + 0.01),
                            "baseline_probability_ci_low": str(base - 0.01),
                            "baseline_probability_ci_high": str(base + 0.01),
                            "absolute_difference_ci_low": str(diff - 0.02),
                            "absolute_difference_ci_high": str(diff + 0.02),
                            "relative_lift_ci_low": str(obs / base - 0.1),
                            "relative_lift_ci_high": str(obs / base + 0.1),
                            "empirical_p": "",
                            "descriptive_status": "positive_interval_separated",
                            "warnings": "",
                        }
                    )
    _write_csv(root / "r1_t07_fixed_lag_profile.csv", primary)
    _write_csv(root / "r1_t07_baseline_sensitivity.csv", _baseline_rows(primary))
    _write_csv(root / "r1_t07_p_survival_profile.csv", _survival_rows())
    _write_csv(root / "r1_t07_anchor_target_status_profile.csv", _anchor_target_rows())
    _write_csv(root / "r1_t07_anchor_funnel.csv", _funnel_rows())
    _write_csv(root / "r1_t07_year_lag_profile.csv", primary[:10])
    _write_csv(root / "r1_t07_security_lag_summary.csv", _security_rows(primary))
    _write_csv(root / "r1_t07_state_reconciliation.csv", _state_rows())
    _write_csv(
        root / "r1_t07_q_onset_transition_profile.csv",
        [
            {
                "W": "250",
                "q_low": "0.1",
                "q_high": "0.2",
                "lower_transition_class": "onset",
                "higher_transition_class": "continuing_P",
                "row_count": "1",
                "lower_onset_reclassified_count": "1",
                "higher_onset_new_count": "0",
                "interpretation": "onset_set_not_required_nested",
            }
        ],
    )
    _write_csv(root / "r1_t07_lag_alignment_reconciliation.csv", _lag_rows())
    summary_payload = {
        "task_id": "R1-T07",
        "status": "completed",
        "run_id": "R1-T07-SYNTH",
        "code_commit": "a" * 40,
        "checks": {
            name: "passed"
            for name in (
                "primary_output_nonempty",
                "all_zero_check",
                "all_one_check",
                "all_null_check",
                "validity_rate_check",
                "coverage_check",
                "parameter_response_check",
                "baseline_challenger_check",
                "nested_invariant_check",
                "funnel_accounting_check",
                "denominator_integrity_check",
                "sample_size_check",
                "upstream_consistency_check",
                "scale_shift_check",
                "time_alignment_check",
                "future_leakage_check",
                "post_hoc_selection_check",
                "conclusion_support_check",
            )
        },
        "blocked_reasons": [],
        "downstream_gates": {
            "R1-T08_allowed_to_start": False,
            "R2_allowed_to_start": False,
            "downstream_gate_allowed": False,
        },
        "output_paths": {},
    }
    role_by_file = {
        "r1_t07_fixed_lag_profile.csv": "fixed_lag_profile_csv",
        "r1_t07_baseline_sensitivity.csv": "baseline_sensitivity_csv",
        "r1_t07_p_survival_profile.csv": "p_survival_profile_csv",
        "r1_t07_anchor_target_status_profile.csv": "anchor_target_status_profile_csv",
        "r1_t07_anchor_funnel.csv": "anchor_funnel_csv",
        "r1_t07_year_lag_profile.csv": "year_lag_profile_csv",
        "r1_t07_security_lag_summary.csv": "security_lag_summary_csv",
        "r1_t07_state_reconciliation.csv": "state_reconciliation_csv",
        "r1_t07_q_onset_transition_profile.csv": "q_onset_transition_profile_csv",
        "r1_t07_lag_alignment_reconciliation.csv": "lag_alignment_reconciliation_csv",
    }
    for file_name, role in role_by_file.items():
        path = root / file_name
        summary_payload["output_paths"][role] = {
            "path": file_name,
            "sha256": _sha(path),
        }
    summary = root / "summary.json"
    summary.write_text(json.dumps(summary_payload, sort_keys=True), encoding="utf-8")
    package = root / "package.json"
    package.write_text(
        json.dumps(
            {
                "task_id": "R1-T07",
                "run_id": "R1-T07-SYNTH",
                "code_commit": "a" * 40,
                "gate_status": {
                    "scientific_review_status": "pending",
                    "review_phase": "author_analysis_complete",
                    "readme_gate_updated": False,
                },
                "downstream_gate_allowed": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return summary, package


def _baseline_rows(primary: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "transition_path": row["transition_path"],
            "W": row["W"],
            "q": row["q"],
            "K": row["K"],
            "lag_k": row["lag_k"],
            "primary_stay_out_baseline_probability": row["baseline_probability"],
            "unconditional_lag_support_marginal_probability": row[
                "baseline_probability"
            ],
            "target_status_standardized_baseline_probability": row[
                "baseline_probability"
            ],
            "security_year_standardized_baseline_probability": row[
                "baseline_probability"
            ],
            "security_year_matched_anchor_count": row["target_valid_event_count"],
            "security_year_unmatched_stratum_count": "0",
            "security_year_coverage": "1",
            "observed_probability": row["observed_probability"],
            "primary_absolute_difference": row["absolute_difference"],
            "target_status_standardized_absolute_difference": row[
                "absolute_difference"
            ],
            "security_year_standardized_absolute_difference": row[
                "absolute_difference"
            ],
            "warnings": "",
        }
        for row in primary
    ]


def _survival_rows() -> list[dict[str, str]]:
    rows = []
    for w in WS:
        for q in QS:
            prev = 100
            for lag in LAGS:
                current = prev - lag
                rows.append(
                    {
                        "W": str(w),
                        "q": str(q),
                        "K": "not_applicable",
                        "lag_k": str(lag),
                        "anchor_event_count": "100",
                        "p_survival_eligible_count": str(100 - lag),
                        "p_run_survival_true_count": str(current),
                        "P_survival_probability": "0.5",
                        "P_active_at_k_probability": "0.6",
                        "reentered_after_exit_count": "1",
                        "PCT_target_valid_given_surviving_P_run_count": "50",
                        "PCT_target_true_given_surviving_P_run_count": "10",
                        "PCT_target_given_surviving_P_run_probability": "0.2",
                    }
                )
                prev = current
    return rows


def _anchor_target_rows() -> list[dict[str, str]]:
    return [
        {
            "transition_path": path,
            "W": str(w),
            "q": str(q),
            "K": "not_applicable",
            "anchor_event_count": "100",
            "target_valid_at_anchor_count": "90",
            "target_already_active_at_anchor_count": "30",
            "target_already_active_at_anchor_rate": "0.3333333333333333",
            "target_inactive_at_anchor_count": "60",
            "target_inactive_at_anchor_rate": "0.6666666666666666",
            "target_at_k_probability_among_target_active_at_anchor_onsets": "0.5",
            "target_at_k_probability_among_target_inactive_at_anchor_onsets": "0.2",
        }
        for path in PATHS
        for w in WS
        for q in QS
    ]


def _funnel_rows() -> list[dict[str, str]]:
    return [
        {
            "W": str(w),
            "q": str(q),
            "K": "not_applicable",
            "total_rows": "1000",
            "previous_absent_count": "10",
            "previous_invalid_count": "10",
            "current_invalid_count": "10",
            "onset_count": "100",
            "stay_out_count": "120",
            "continuing_P_count": "200",
            "exit_count": "100",
            "other_count": "450",
        }
        for w in WS
        for q in QS
    ]


def _security_rows(primary: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "transition_path": row["transition_path"],
            "W": row["W"],
            "q": row["q"],
            "K": row["K"],
            "lag_k": row["lag_k"],
            "event_security_count": "10",
            "per_security_median_effect": row["absolute_difference"],
            "positive_security_count": "10",
            "negative_security_count": "0",
            "zero_security_count": "0",
            "pooled_absolute_difference": row["absolute_difference"],
            "pooled_vs_security_median_sign_consistency": "true",
        }
        for row in primary
    ]


def _state_rows() -> list[dict[str, str]]:
    return [
        {
            "W": str(w),
            "q": str(q),
            "state_name": state,
            "r0_key_count": "10",
            "derived_key_count": "10",
            "r0_true_count": "1",
            "r0_false_count": "9",
            "r0_null_count": "0",
            "derived_true_count": "1",
            "derived_false_count": "9",
            "derived_null_count": "0",
            "missing_key_count": "0",
            "row_mismatch_count": "0",
        }
        for state in ("P", "C", "T", "V", "S_PCT", "S_PCVT")
        for w in WS
        for q in QS
    ]


def _lag_rows() -> list[dict[str, str]]:
    return [
        {
            "W": str(w),
            "q": str(q),
            "K": "not_applicable",
            "lag_k": str(lag),
            "anchor_event_count": "100",
            "lag_available_anchor_count": str(100 - lag),
            "right_censored_anchor_count": str(lag),
            "exact_offset_count": str(100 - lag),
            "offset_mismatch_count": "0",
            "min_target_date": "20200101",
            "max_target_date": "20200131",
        }
        for w in WS
        for q in QS
        for lag in LAGS
    ]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _refresh_summary_hash(root: Path, summary: Path, role: str) -> None:
    payload = json.loads(summary.read_text(encoding="utf-8"))
    path = root / payload["output_paths"][role]["path"]
    payload["output_paths"][role]["sha256"] = _sha(path)
    summary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
