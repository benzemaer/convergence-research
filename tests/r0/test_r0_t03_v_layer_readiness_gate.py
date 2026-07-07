from __future__ import annotations

import unittest

from src.r0.input_readiness_gate import (
    BLOCKED,
    DIAGNOSTIC_REQUIRED,
    READY,
    UNKNOWN,
    assert_unknown_guard,
    check_d3_only_lineage,
    evaluate_amount_level_readiness,
    evaluate_turnover_shrink_readiness,
)


def turnover_ready_context() -> dict[str, object]:
    return {
        "turnover_float": 0.012,
        "turnover_field_status": "pass",
        "share_field_status": "pass",
        "provider_turnover_crosscheck_status": "pass",
        "volume_shares": 1200000,
        "float_share_shares": 100000000,
        "trading_status": "normal_trading",
        "corporate_action_flag": "none",
        "suspension_flag": False,
        "window_full": True,
        "valid_trading_days": 80,
        "listing_age_trading_days": 120,
        "corporate_action_types_in_window": [],
        "share_comparability_corporate_action_in_window": False,
        "common_share_basis_policy": "not_required",
        "volume_comparability_policy": "not_required",
    }


def amount_ready_context() -> dict[str, object]:
    return {
        "amount_yuan": 32000000.0,
        "amount_unit": "yuan",
        "amount_volume_unit_status": "pass",
        "zero_amount_flag": False,
        "trading_status": "normal_trading",
        "suspension_flag": False,
        "window_full": True,
        "valid_trading_days": 20,
        "percentile_already_applied": True,
        "apply_additional_percentile": False,
    }


class R0T03VLayerReadinessGateTest(unittest.TestCase):
    def test_turnover_shrink_ready_context_is_ready(self) -> None:
        result = evaluate_turnover_shrink_readiness(turnover_ready_context())
        self.assertEqual(result.status, READY)
        self.assertEqual(result.indicator_id, "V1_TurnoverShrink20_60")

    def test_turnover_window_not_full_is_unknown(self) -> None:
        context = turnover_ready_context()
        context["valid_trading_days"] = 79
        result = evaluate_turnover_shrink_readiness(context)
        self.assertEqual(result.status, UNKNOWN)
        self.assertIn("window_not_full", result.reason_codes)

    def test_turnover_missing_turnover_float_is_not_ready(self) -> None:
        context = turnover_ready_context()
        context.pop("turnover_float")
        result = evaluate_turnover_shrink_readiness(context)
        self.assertNotEqual(result.status, READY)
        self.assertIn("missing_required_field", result.reason_codes)
        self.assertIn("turnover_float_missing", result.reason_codes)

    def test_turnover_float_share_nonpositive_is_unknown(self) -> None:
        context = turnover_ready_context()
        context["float_share_shares"] = 0
        result = evaluate_turnover_shrink_readiness(context)
        self.assertEqual(result.status, UNKNOWN)
        self.assertIn("float_share_nonpositive", result.reason_codes)

    def test_turnover_share_status_invalid_is_unknown(self) -> None:
        context = turnover_ready_context()
        context["share_field_status"] = "invalid"
        result = evaluate_turnover_shrink_readiness(context)
        self.assertEqual(result.status, UNKNOWN)
        self.assertIn("share_field_status_invalid", result.reason_codes)

    def test_turnover_field_status_invalid_is_unknown(self) -> None:
        context = turnover_ready_context()
        context["turnover_field_status"] = "unknown"
        result = evaluate_turnover_shrink_readiness(context)
        self.assertEqual(result.status, UNKNOWN)
        self.assertIn("turnover_field_status_invalid", result.reason_codes)

    def test_turnover_provider_crosscheck_fail_blocks(self) -> None:
        context = turnover_ready_context()
        context["provider_turnover_crosscheck_status"] = "fail"
        result = evaluate_turnover_shrink_readiness(context)
        self.assertEqual(result.status, BLOCKED)
        self.assertIn("provider_turnover_crosscheck_fail", result.reason_codes)

    def test_turnover_suspension_listing_pause_or_zero_volume_needs_diagnostic(
        self,
    ) -> None:
        for field_name, reason_code in (
            ("suspension_in_window", "suspension_in_window"),
            ("listing_pause_in_window", "listing_pause_in_window"),
            ("zero_volume_in_window", "zero_volume_in_window"),
        ):
            context = turnover_ready_context()
            context[field_name] = True
            result = evaluate_turnover_shrink_readiness(context)
            self.assertEqual(result.status, DIAGNOSTIC_REQUIRED)
            self.assertIn(reason_code, result.reason_codes)

    def test_turnover_share_comparability_event_without_policy_is_unknown(
        self,
    ) -> None:
        context = turnover_ready_context()
        context["share_comparability_corporate_action_in_window"] = True
        context["common_share_basis_policy"] = None
        context["volume_comparability_policy"] = None
        result = evaluate_turnover_shrink_readiness(context)
        self.assertEqual(result.status, UNKNOWN)
        self.assertIn(
            "corporate_action_turnover_comparability_policy_missing",
            result.reason_codes,
        )

    def test_amount_level_ready_context_is_ready(self) -> None:
        result = evaluate_amount_level_readiness(amount_ready_context())
        self.assertEqual(result.status, READY)
        self.assertEqual(result.indicator_id, "V2_AmountLevel20Pct")

    def test_amount_missing_or_nonpositive_is_not_ready(self) -> None:
        context = amount_ready_context()
        context.pop("amount_yuan")
        result = evaluate_amount_level_readiness(context)
        self.assertNotEqual(result.status, READY)
        self.assertIn("missing_required_field", result.reason_codes)
        self.assertIn("amount_yuan_missing", result.reason_codes)

        context = amount_ready_context()
        context["amount_yuan"] = 0
        result = evaluate_amount_level_readiness(context)
        self.assertEqual(result.status, UNKNOWN)
        self.assertIn("amount_yuan_nonpositive", result.reason_codes)

    def test_amount_unit_failure_blocks(self) -> None:
        context = amount_ready_context()
        context["amount_volume_unit_status"] = "fail"
        result = evaluate_amount_level_readiness(context)
        self.assertEqual(result.status, BLOCKED)
        self.assertIn("amount_volume_unit_status_fail", result.reason_codes)

    def test_amount_repeated_percentile_is_unknown(self) -> None:
        context = amount_ready_context()
        context["apply_additional_percentile"] = True
        result = evaluate_amount_level_readiness(context)
        self.assertEqual(result.status, UNKNOWN)
        self.assertIn("amount_level_repeated_percentile_forbidden", result.reason_codes)

    def test_amount_suspension_or_zero_amount_needs_diagnostic(self) -> None:
        for field_name, reason_code in (
            ("suspension_in_window", "suspension_in_window"),
            ("zero_amount_in_window", "zero_amount_in_window"),
        ):
            context = amount_ready_context()
            context[field_name] = True
            result = evaluate_amount_level_readiness(context)
            self.assertEqual(result.status, DIAGNOSTIC_REQUIRED)
            self.assertIn(reason_code, result.reason_codes)

    def test_lineage_allows_d3_t11_and_rejects_direct_sources(self) -> None:
        result = check_d3_only_lineage(
            ["d3_t11_volume_amount_share_turnover_candidate"]
        )
        self.assertEqual(result.status, READY)

        result = check_d3_only_lineage(
            ["d3_t11_volume_amount_share_turnover_candidate", "data/raw/vendor.csv"]
        )
        self.assertEqual(result.status, BLOCKED)
        self.assertIn("direct_d1_d2_bypass_detected", result.reason_codes)

    def test_unknown_guard_rejects_false_zero_previous_and_mean(self) -> None:
        for value in (False, 0, "previous", "mean"):
            result = assert_unknown_guard(value)
            self.assertEqual(result.status, UNKNOWN)
            self.assertIn("unknown_not_false_guard", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
