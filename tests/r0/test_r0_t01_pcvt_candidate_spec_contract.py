from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r0/r0_t01_pcvt_candidate_spec.v1.json"
SCHEMA_PATH = ROOT / "schemas/r0/r0_t01_pcvt_candidate_spec.schema.json"

EXPECTED_INDICATORS = {
    "P1_NATR14",
    "P2_LogRange20",
    "C1_LogMASpread_5_60",
    "C2_AdjVWAPSpread_5_60",
    "T1_ER20",
    "T2_AbsTrendT20",
    "V1_TurnoverShrink20_60",
    "V2_AmountLevel20Pct",
}
REQUIRED_PROHIBITED_OUTPUTS = {
    "pcvt_values",
    "pcvt_percentiles",
    "pcvt_scores",
    "pcvt_states",
    "future_labels",
    "future_returns",
    "backtest",
    "portfolio",
    "formal_data_version",
}


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class R0T01PCVTCandidateSpecContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.config = load_json(CONFIG_PATH)
        cls.indicators = cls.config["candidate_indicators"]
        cls.indicators_by_id = {
            indicator["indicator_id"]: indicator for indicator in cls.indicators
        }

    def test_config_passes_schema_validation(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema, format_checker=FormatChecker()).validate(
            self.config
        )

    def test_indicator_ids_are_complete(self) -> None:
        self.assertEqual(set(self.indicators_by_id), EXPECTED_INDICATORS)
        self.assertEqual(len(self.indicators_by_id), len(EXPECTED_INDICATORS))

    def test_each_pcvt_layer_has_exactly_two_indicators(self) -> None:
        layer_counts = Counter(indicator["pcvt_layer"] for indicator in self.indicators)
        self.assertEqual(layer_counts, {"P": 2, "C": 2, "T": 2, "V": 2})

    def test_all_indicator_directions_are_lower_is_more_convergent(self) -> None:
        self.assertTrue(
            all(
                indicator["raw_value_direction"] == "lower_is_more_convergent"
                for indicator in self.indicators
            )
        )

    def test_percentile_policy_is_per_security_strict_past_not_cross_sectional(
        self,
    ) -> None:
        policy = self.config["percentile_policy"]
        self.assertEqual(policy["scope"], "per_security_strict_past_history")
        self.assertFalse(policy["cross_sectional_percentile"])

    def test_current_value_is_not_in_reference_set(self) -> None:
        self.assertFalse(
            self.config["percentile_policy"]["current_value_in_reference_set"]
        )

    def test_score_formula_is_one_minus_percentile(self) -> None:
        self.assertEqual(
            self.config["score_policy"]["indicator_score_formula"], "1 - percentile"
        )
        self.assertTrue(
            all(
                indicator["score_formula"] == "1 - strict_past_percentile"
                for indicator in self.indicators
            )
        )

    def test_dimension_rule_baseline_is_weak(self) -> None:
        self.assertEqual(self.config["dimension_rule"]["baseline"], "weak")
        self.assertEqual(
            self.config["candidate_grid"]["baseline"]["dimension_rule"], "weak"
        )

    def test_weak_delta_is_fixed_at_point_ten(self) -> None:
        self.assertEqual(self.config["dimension_rule"]["weak_delta"], 0.1)
        self.assertEqual(self.config["candidate_grid"]["baseline"]["weak_delta"], 0.1)

    def test_strict_rule_and_sidecar_are_inactive(self) -> None:
        rule = self.config["dimension_rule"]
        self.assertFalse(rule["strict_rule_active"])
        self.assertFalse(rule["strict_sidecar_authorized"])

    def test_main_grid_size_is_twenty_seven(self) -> None:
        grid = self.config["candidate_grid"]
        self.assertEqual(grid["main_grid_size"], 27)
        self.assertFalse(grid["dimension_rule_grid_authorized"])

    def test_c2_requires_adjusted_vwap_policy(self) -> None:
        c2 = self.indicators_by_id["C2_AdjVWAPSpread_5_60"]
        self.assertEqual(c2["c2_policy"]["required_policy"], "adjusted_vwap_policy")
        self.assertTrue(
            c2["c2_policy"][
                "raw_vwap_across_corporate_action_window_forbidden_as_adjusted_vwap"
            ]
        )

    def test_v1_turnover_requires_comparability_or_common_share_basis_policy(
        self,
    ) -> None:
        v1 = self.indicators_by_id["V1_TurnoverShrink20_60"]
        self.assertEqual(v1["raw_metric_name"], "TurnoverShrink20_60")
        self.assertIn("turnover_float", v1["required_fields"])
        self.assertIn("float_share_shares", v1["required_fields"])
        self.assertEqual(v1["v1_policy"]["raw_fact_field"], "turnover_float")
        self.assertEqual(v1["v1_policy"]["denominator_field"], "float_share_shares")
        required = set(v1["v1_policy"]["required_policy_any_of"])
        self.assertIn("volume_comparability_policy", required)
        self.assertIn("common_share_basis_policy", required)
        self.assertTrue(
            v1["v1_policy"]["suspension_and_zero_volume_not_ordinary_low_participation"]
        )

    def test_t2_declares_residual_se_zero_slope_nonzero_handling(self) -> None:
        t2 = self.indicators_by_id["T2_AbsTrendT20"]
        rule = t2["t2_policy"]["residual_se_zero_slope_nonzero_rule"]
        self.assertIn("must_not_set_to_0", rule)
        self.assertIn("strong_trend", rule)
        self.assertIn("unknown_diagnostic_required", rule)

    def test_state_family_contains_pct_and_pcvt(self) -> None:
        core_lines = set(self.config["state_family"]["core_lines"])
        self.assertIn("S_PCT", core_lines)
        self.assertIn("S_PCVT", core_lines)

    def test_unknown_is_not_negation(self) -> None:
        self.assertTrue(self.config["state_family"]["unknown_not_negation"])

    def test_prohibited_outputs_cover_all_required_non_goals(self) -> None:
        prohibited = set(self.config["prohibited_outputs"])
        self.assertTrue(REQUIRED_PROHIBITED_OUTPUTS.issubset(prohibited))


if __name__ == "__main__":
    unittest.main()
