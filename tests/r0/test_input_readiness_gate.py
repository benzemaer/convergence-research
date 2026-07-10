from __future__ import annotations

import unittest

from src.r0.input_readiness_gate import (
    BLOCKED,
    DIAGNOSTIC_REQUIRED,
    READY,
    UNKNOWN,
    assert_unknown_guard,
    check_d3_only_lineage,
    evaluate_c2_readiness,
    evaluate_v1_readiness,
)


def c2_ready_context() -> dict[str, object]:
    return {
        "amount": 1000000,
        "volume": 100000,
        "amount_unit": "yuan",
        "volume_unit": "share",
        "amount_volume_unit_status": "pass",
        "raw_low": 9.5,
        "raw_high": 10.5,
        "daily_vwap_range_status": "pass",
        "corporate_action_flag": "none",
        "adjusted_vwap_policy": "common_corporate_action_basis",
        "trading_status": "normal_trading",
        "corporate_action_window": False,
    }


def v1_ready_context() -> dict[str, object]:
    return {
        "volume": 100000,
        "volume_unit": "share",
        "trading_status": "normal_trading",
        "corporate_action_flag": "none",
        "suspension_flag": False,
        "window_full": True,
        "valid_trading_days": 80,
        "listing_age_trading_days": 120,
        "share_comparability_corporate_action_in_window": False,
    }


class InputReadinessGateTest(unittest.TestCase):
    def test_c2_ready_without_corporate_action_window(self) -> None:
        result = evaluate_c2_readiness(c2_ready_context())
        self.assertEqual(result.status, READY)
        self.assertIn("ready_no_blocker", result.reason_codes)

    def test_c2_amount_unit_unknown_is_not_ready(self) -> None:
        context = c2_ready_context()
        context["amount_unit"] = "unknown"
        result = evaluate_c2_readiness(context)
        self.assertIn(result.status, {UNKNOWN, BLOCKED})
        self.assertIn("amount_unit_unknown", result.reason_codes)

    def test_c2_volume_unit_unknown_is_not_ready(self) -> None:
        context = c2_ready_context()
        context["volume_unit"] = "unknown"
        result = evaluate_c2_readiness(context)
        self.assertIn(result.status, {UNKNOWN, BLOCKED})
        self.assertIn("volume_unit_unknown", result.reason_codes)

    def test_c2_daily_vwap_range_fail_blocks_or_requires_diagnostic(self) -> None:
        context = c2_ready_context()
        context["daily_vwap_range_status"] = "fail"
        result = evaluate_c2_readiness(context)
        self.assertIn(result.status, {BLOCKED, DIAGNOSTIC_REQUIRED})
        self.assertIn("daily_vwap_range_fail", result.reason_codes)

    def test_c2_missing_adjusted_vwap_policy_field_is_not_ready(self) -> None:
        context = c2_ready_context()
        context.pop("adjusted_vwap_policy")
        result = evaluate_c2_readiness(context)
        self.assertIn(result.status, {UNKNOWN, BLOCKED})
        self.assertIn("missing_required_field", result.reason_codes)

    def test_c2_unknown_adjusted_vwap_policy_is_not_ready(self) -> None:
        context = c2_ready_context()
        context["adjusted_vwap_policy"] = "unknown"
        result = evaluate_c2_readiness(context)
        self.assertIn(result.status, {UNKNOWN, BLOCKED})
        self.assertIn("adjusted_vwap_policy_missing", result.reason_codes)

    def test_c2_corporate_action_window_missing_adjusted_policy(self) -> None:
        context = c2_ready_context()
        context["corporate_action_window"] = True
        context["adjusted_vwap_policy"] = None
        result = evaluate_c2_readiness(context)
        self.assertIn(result.status, {UNKNOWN, BLOCKED})
        self.assertIn("adjusted_vwap_policy_missing", result.reason_codes)
        self.assertIn(
            "corporate_action_window_without_common_basis", result.reason_codes
        )

    def test_c2_raw_vwap_across_corporate_action_not_adjusted_ready(self) -> None:
        context = c2_ready_context()
        context["corporate_action_window"] = True
        context["adjusted_vwap_policy"] = None
        context["raw_vwap_used_as_adjusted_vwap"] = True
        result = evaluate_c2_readiness(context)
        self.assertNotEqual(result.status, READY)
        self.assertIn(
            "corporate_action_window_without_common_basis", result.reason_codes
        )

    def test_c2_zero_volume_or_suspension_window_not_ready(self) -> None:
        context = c2_ready_context()
        context["zero_volume_in_window"] = True
        result = evaluate_c2_readiness(context)
        self.assertEqual(result.status, DIAGNOSTIC_REQUIRED)
        self.assertIn("zero_volume_in_window", result.reason_codes)

        context = c2_ready_context()
        context["suspension_in_window"] = True
        result = evaluate_c2_readiness(context)
        self.assertEqual(result.status, DIAGNOSTIC_REQUIRED)
        self.assertIn("suspension_in_window", result.reason_codes)

    def test_v1_ready_without_share_comparability_event(self) -> None:
        result = evaluate_v1_readiness(v1_ready_context())
        self.assertEqual(result.status, READY)

    def test_v1_window_not_full_is_unknown(self) -> None:
        context = v1_ready_context()
        context["window_full"] = False
        result = evaluate_v1_readiness(context)
        self.assertEqual(result.status, UNKNOWN)
        self.assertIn("window_not_full", result.reason_codes)

    def test_v1_suspension_in_window_requires_diagnostic(self) -> None:
        context = v1_ready_context()
        context["suspension_in_window"] = True
        result = evaluate_v1_readiness(context)
        self.assertEqual(result.status, DIAGNOSTIC_REQUIRED)
        self.assertIn("suspension_in_window", result.reason_codes)

    def test_v1_zero_volume_in_window_requires_diagnostic(self) -> None:
        context = v1_ready_context()
        context["zero_volume_in_window"] = True
        result = evaluate_v1_readiness(context)
        self.assertEqual(result.status, DIAGNOSTIC_REQUIRED)
        self.assertIn("zero_volume_in_window", result.reason_codes)

    def test_v1_share_change_without_policy_is_unknown(self) -> None:
        context = v1_ready_context()
        context["share_comparability_corporate_action_in_window"] = True
        result = evaluate_v1_readiness(context)
        self.assertEqual(result.status, UNKNOWN)
        self.assertIn(
            "corporate_action_volume_comparability_policy_missing",
            result.reason_codes,
        )

    def test_v1_share_change_with_volume_policy_is_ready(self) -> None:
        context = v1_ready_context()
        context["share_comparability_corporate_action_in_window"] = True
        context["volume_comparability_policy"] = "common_share_basis"
        result = evaluate_v1_readiness(context)
        self.assertEqual(result.status, READY)

    def test_v1_volume_unit_unknown_is_not_ready(self) -> None:
        context = v1_ready_context()
        context["volume_unit"] = "unknown"
        result = evaluate_v1_readiness(context)
        self.assertIn(result.status, {UNKNOWN, BLOCKED})
        self.assertIn("volume_unit_unknown", result.reason_codes)

    def test_lineage_allowed_d3_sources_are_ready(self) -> None:
        result = check_d3_only_lineage(
            ["d3_candidate_daily_observation", "d3_t08_research_dataset_registry"]
        )
        self.assertEqual(result.status, READY)

    def test_lineage_prohibited_sources_are_blocked(self) -> None:
        for source in (
            "d1.raw_market_prices",
            "d2.adjusted_market_prices",
            "data/raw/snapshot.parquet",
            "data/external/vendor.csv",
            "MarketDB/prices.duckdb",
            "SH000001.day",
        ):
            result = check_d3_only_lineage(["d3_candidate_daily_observation", source])
            self.assertEqual(result.status, BLOCKED)
            self.assertIn("direct_d1_d2_bypass_detected", result.reason_codes)

    def test_unknown_not_false_zero_previous_or_mean(self) -> None:
        for value in (False, 0, "previous", "mean"):
            result = assert_unknown_guard(value)
            self.assertEqual(result.status, UNKNOWN)
            self.assertIn("unknown_not_false_guard", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
