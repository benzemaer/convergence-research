from __future__ import annotations

import copy
import unittest

from src.r1.r1_t09_year_stability_concentration import (
    CONFIG_PATH,
    ROOT,
    R1T09Error,
    _build_anomaly_scan,
    _load_json,
    _step_metrics,
    _validate_frozen_registry,
    build_concentration_summary,
    build_leave_one_year_out,
    build_reference_challenger_comparison,
    concentration_metrics,
    metric_sign,
)


def state_rows(state_line: str = "S_PCT", W: int = 120) -> list[dict[str, object]]:
    result = []
    for year in range(2016, 2027):
        count = 0 if year == 2016 else year - 2015
        result.append(
            {
                "candidate_config_id": f"R0_W{W}_Q20_K3_WEAK_D010",
                "state_line": state_line,
                "W": W,
                "q": 0.2,
                "K": 3,
                "year": year,
                "eligible_trading_days": 100,
                "valid_day_count": 90,
                "unknown_day_count": 10,
                "blocked_day_count": 0,
                "diagnostic_required_day_count": 0,
                "confirmed_state_true_count": count,
                "confirmed_state_false_count": 90 - count,
                "confirmed_state_null_count": 10,
                "confirmed_coverage": count / 100,
                "raw_state_true_count": count * 2,
                "raw_state_false_count": 90 - count * 2,
                "raw_state_null_count": 10,
                "raw_coverage": count * 2 / 100,
                "confirmed_unique_security_count": count,
                "partial_year_observation": year == 2026,
            }
        )
    return result


def interval_rows(state_line: str = "S_PCT", W: int = 120) -> list[dict[str, object]]:
    return [
        {
            "candidate_config_id": f"R0_W{W}_Q20_K3_WEAK_D010",
            "state_line": state_line,
            "W": W,
            "year": year,
            "confirmed_interval_count": max(0, year - 2016),
            "fragment_rate": 0.5,
            "interval_year_share": (year - 2016) / 55 if year > 2016 else 0,
        }
        for year in range(2016, 2027)
    ]


def step_rows(step_id: str = "C_GIVEN_P", W: int = 120) -> list[dict[str, object]]:
    result = []
    for year in range(2016, 2027):
        n11, n10, n01, n00 = year - 2010, 10, 5, 80
        metrics = _step_metrics(n11, n10, n01, n00)
        result.append(
            {
                "step_id": step_id,
                "W": W,
                "q": 0.2,
                "year": year,
                "n11": n11,
                "n10": n10,
                "n01": n01,
                "n00": n00,
                "N": metrics["N"],
                "anchor_true_count": n11 + n10,
                "child_true_count": n11,
                "absolute_increment": metrics["delta"],
                "association_lift": metrics["lift"],
                "step_denominator_year_share": 1 / 11,
                "child_year_share": n11 / sum(y - 2010 for y in range(2016, 2027)),
            }
        )
    return result


class R1T09YearStabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _load_json(CONFIG_PATH)

    def test_frozen_registry_is_exact(self) -> None:
        _validate_frozen_registry(self.config)

    def test_forbidden_candidate_extension_is_rejected(self) -> None:
        config = copy.deepcopy(self.config)
        extra = copy.deepcopy(config["candidate_registry"][0])
        extra["W"] = 500
        config["candidate_registry"].append(extra)
        with self.assertRaises(R1T09Error):
            _validate_frozen_registry(config)

    def test_zero_state_year_is_retained_in_concentration(self) -> None:
        metrics = concentration_metrics(
            state_rows(),
            count_key="confirmed_state_true_count",
            eligible_key="eligible_trading_days",
            valid_key="valid_day_count",
            coverage_key="confirmed_coverage",
        )
        self.assertEqual(metrics["zero_state_year_count"], 1)
        self.assertEqual(metrics["evaluable_year_count"], 11)

    def test_concentration_hhi_and_effective_years(self) -> None:
        rows = state_rows()
        metrics = concentration_metrics(
            rows,
            count_key="confirmed_state_true_count",
            eligible_key="eligible_trading_days",
            valid_key="valid_day_count",
            coverage_key="confirmed_coverage",
        )
        shares = [int(row["confirmed_state_true_count"]) / 65 for row in rows]
        expected_hhi = sum(value * value for value in shares)
        self.assertAlmostEqual(metrics["year_hhi"], expected_hhi)
        self.assertAlmostEqual(metrics["effective_year_count"], 1 / expected_hhi)

    def test_top_two_share_is_recomputed(self) -> None:
        metrics = concentration_metrics(
            state_rows(),
            count_key="confirmed_state_true_count",
            eligible_key="eligible_trading_days",
            valid_key="valid_day_count",
            coverage_key="confirmed_coverage",
        )
        self.assertAlmostEqual(metrics["top2_year_state_share"], 21 / 65)

    def test_leave_one_year_out_candidate_conserves_counts(self) -> None:
        rows = build_leave_one_year_out(state_rows(), interval_rows(), [], self.config)
        removed_2026 = next(row for row in rows if row["removed_year"] == 2026)
        self.assertEqual(removed_2026["confirmed_state_days_without_year"], 54)
        self.assertTrue(removed_2026["partial_year_removed"])

    def test_leave_one_year_out_step_rebuilds_2x2(self) -> None:
        rows = build_leave_one_year_out([], [], step_rows(), self.config)
        first = rows[0]
        self.assertEqual(
            first["N_without_year"],
            first["n11_without_year"]
            + first["n10_without_year"]
            + first["n01_without_year"]
            + first["n00_without_year"],
        )

    def test_metric_sign_uses_frozen_tolerance(self) -> None:
        self.assertEqual(metric_sign(1e-13), "zero")
        self.assertEqual(metric_sign(-0.1), "negative")
        self.assertEqual(metric_sign(1.1, center=1.0), "positive")

    def test_direction_conflict_warning_is_triggered(self) -> None:
        rows = step_rows()
        rows[0]["absolute_increment"] = -0.1
        rows[0]["association_lift"] = 0.8
        summary = build_concentration_summary([], [], rows, self.config)
        self.assertIn("year_direction_conflict_warning", summary[0]["warnings"])

    def test_single_year_majority_warning_is_triggered(self) -> None:
        rows = state_rows()
        rows[-1]["confirmed_state_true_count"] = 1000
        rows[-1]["confirmed_coverage"] = 10.0
        summary = build_concentration_summary(rows, interval_rows(), [], self.config)
        confirmed = next(row for row in summary if row["analysis_level"] == "confirmed")
        self.assertEqual(
            confirmed["candidate_stability_status"],
            "year_stability_supported_with_warning",
        )
        self.assertIn("single_year_majority_warning", confirmed["warnings"])

    def test_w_pair_preserves_availability_difference(self) -> None:
        state = (
            state_rows(W=120)
            + state_rows(W=250)
            + state_rows("S_PCVT", 120)
            + state_rows("S_PCVT", 250)
        )
        for row in state:
            if row["W"] == 120:
                row["valid_day_count"] = 95
        compared = build_reference_challenger_comparison(
            state,
            interval_rows(W=120)
            + interval_rows(W=250)
            + interval_rows("S_PCVT", 120)
            + interval_rows("S_PCVT", 250),
        )
        self.assertEqual(compared[0]["availability_difference"], 5)
        self.assertIn(
            "availability_difference_requires_caution", compared[0]["warnings"]
        )

    def test_anomaly_scan_summarizes_availability_and_partial_year(self) -> None:
        state = state_rows(W=120) + state_rows(W=250)
        state[11].update(
            {
                "valid_day_count": 0,
                "unknown_day_count": 100,
                "raw_state_true_count": 0,
                "raw_state_false_count": 0,
                "raw_state_null_count": 100,
                "confirmed_state_true_count": 0,
                "confirmed_state_false_count": 0,
                "confirmed_state_null_count": 100,
            }
        )
        comparisons = [
            {"state_line": "S_PCT", "year": 2016, "availability_difference": 10}
        ]
        concentration = [
            {
                "summary_scope": "candidate_state",
                "evaluable_year_count": 11,
                "nonzero_year_count": 10,
                "max_year_state_share": 0.2,
                "warnings": "",
            },
            {
                "summary_scope": "interlayer_step",
                "max_year_child_share": 0.2,
                "warnings": "",
            },
        ]
        reconciliation = [{"scope_id": "other", "mismatch_count": 0}]
        anomaly = _build_anomaly_scan(
            "run",
            "commit",
            ROOT / "data/interim/r1_t09_test",
            state,
            [],
            [],
            concentration,
            [],
            comparisons,
            reconciliation,
        )
        warning_ids = {row["check_id"] for row in anomaly["material_warnings"]}
        self.assertIn("availability_difference_requires_caution", warning_ids)
        self.assertIn("partial_year_observation", warning_ids)
        self.assertIn("boundary_year_zero_valid_denominator", warning_ids)
        required_checks = {
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
        }
        self.assertEqual(set(anomaly["checks"]), required_checks)


if __name__ == "__main__":
    unittest.main()
