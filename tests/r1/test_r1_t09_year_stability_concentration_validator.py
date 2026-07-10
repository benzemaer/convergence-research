from __future__ import annotations

import unittest

from src.r1.r1_t09_year_stability_concentration_validator import (
    _check_forbidden_columns,
    _check_interlayer,
    _check_registry,
    _check_state,
    _check_year_keys,
)


class R1T09ValidatorTest(unittest.TestCase):
    def test_registry_rejects_w500(self) -> None:
        rows = [
            {"state_line": state, "W": str(W), "q": "0.2", "K": "3"}
            for state in ("S_PCT", "S_PCVT")
            for W in (120, 250)
        ]
        rows[-1]["W"] = "500"
        errors: list[str] = []
        _check_registry(rows, errors)
        self.assertIn("candidate_registry_not_exact", errors)

    def test_year_key_check_rejects_filtered_zero_year(self) -> None:
        rows = [
            {"candidate_config_id": "x", "state_line": "S_PCT", "year": str(year)}
            for year in range(2017, 2027)
        ]
        errors: list[str] = []
        _check_year_keys(
            rows, ("candidate_config_id", "state_line"), 1, errors, "state"
        )
        self.assertTrue(any(error.startswith("state_year_set") for error in errors))

    def test_state_conservation_rejects_unknown_as_false(self) -> None:
        row = {
            "candidate_config_id": "x",
            "state_line": "S_PCT",
            "year": "2020",
            "eligible_trading_days": "10",
            "valid_day_count": "8",
            "unknown_day_count": "2",
            "blocked_day_count": "0",
            "diagnostic_required_day_count": "0",
            "raw_state_true_count": "1",
            "raw_state_false_count": "9",
            "raw_state_null_count": "0",
            "confirmed_state_true_count": "1",
            "confirmed_state_false_count": "7",
            "confirmed_state_null_count": "2",
            "raw_coverage": "0.1",
            "confirmed_coverage": "0.1",
            "partial_year_observation": "false",
        }
        errors: list[str] = []
        _check_state([row], errors)
        self.assertTrue(any(error.startswith("invalid_not_null") for error in errors))

    def test_partial_year_marker_is_hard_checked(self) -> None:
        row = {
            "candidate_config_id": "x",
            "state_line": "S_PCT",
            "year": "2026",
            "eligible_trading_days": "10",
            "valid_day_count": "10",
            "unknown_day_count": "0",
            "blocked_day_count": "0",
            "diagnostic_required_day_count": "0",
            "raw_state_true_count": "1",
            "raw_state_false_count": "9",
            "raw_state_null_count": "0",
            "confirmed_state_true_count": "1",
            "confirmed_state_false_count": "9",
            "confirmed_state_null_count": "0",
            "raw_coverage": "0.1",
            "confirmed_coverage": "0.1",
            "partial_year_observation": "false",
        }
        errors: list[str] = []
        _check_state([row], errors)
        self.assertTrue(any(error.startswith("partial_year") for error in errors))

    def test_2x2_conservation_is_hard_checked(self) -> None:
        row = {
            "step_id": "C_GIVEN_P",
            "W": "120",
            "year": "2020",
            "N": "9",
            "n11": "1",
            "n10": "2",
            "n01": "3",
            "n00": "4",
            "retention": "0.3333333333333333",
            "target_marginal_rate": "0.4",
            "association_lift": "0.8333333333333333",
            "absolute_increment": "-0.0666666666666667",
        }
        errors: list[str] = []
        _check_interlayer([row], errors)
        self.assertTrue(
            any(error.startswith("interlayer_conservation") for error in errors)
        )

    def test_forbidden_freeze_column_is_rejected(self) -> None:
        errors: list[str] = []
        _check_forbidden_columns({"artifact": [{"freeze_candidate": "x"}]}, errors)
        self.assertEqual(errors, ["forbidden_columns:artifact"])


if __name__ == "__main__":
    unittest.main()
