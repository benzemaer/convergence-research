from __future__ import annotations

import unittest
from pathlib import Path

from scripts.validate_d2_market_quality_pcvt_dependency import (
    MarketQualityPCVTValidationError,
    classify_gap_attribution,
    classify_trading_constraint,
    validate_amount_volume_units,
    validate_continuous_ohlc_integrity,
    validate_daily_vwap_range,
    validate_no_future_fields,
    validate_no_row_level_price_payload,
    validate_pcvt_indicator_readiness,
    validate_raw_ohlcv_integrity,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/validate_d2_market_quality_pcvt_dependency.py"


def valid_raw_row() -> dict[str, object]:
    return {
        "security_id": "CN.SSE.600519",
        "trading_date": "2024-12-16",
        "raw_open": 100.0,
        "raw_high": 110.0,
        "raw_low": 90.0,
        "raw_close": 105.0,
        "volume": 1000,
        "amount": 100000,
        "trading_status": "normal_trading",
        "price_limit_status": "none",
    }


class ValidateD2MarketQualityPCVTDependencyTest(unittest.TestCase):
    def test_validator_accepts_valid_raw_and_continuous_rows(self) -> None:
        validate_raw_ohlcv_integrity(valid_raw_row())
        validate_continuous_ohlc_integrity(
            {
                "adj_open": 100.0,
                "adj_high": 110.0,
                "adj_low": 90.0,
                "adj_close": 105.0,
                "adjustment_factor": 1.0,
                "adjustment_method": "identity_no_adjustment",
                "adjustment_revision": "v1",
            }
        )

    def test_validator_rejects_invalid_ohlc_and_nonpositive_prices(self) -> None:
        for patch in [
            {"raw_high": 80.0},
            {"raw_low": 120.0},
            {"raw_close": 0.0},
            {"volume": -1},
            {"amount": -1},
        ]:
            row = valid_raw_row() | patch
            with self.assertRaises(MarketQualityPCVTValidationError):
                validate_raw_ohlcv_integrity(row)

    def test_validator_rejects_missing_or_unknown_constraints(self) -> None:
        for key in ["trading_status", "price_limit_status"]:
            row = valid_raw_row()
            del row[key]
            with self.assertRaises(MarketQualityPCVTValidationError):
                validate_raw_ohlcv_integrity(row)
        row = valid_raw_row() | {"trading_status": "unknown"}
        with self.assertRaises(MarketQualityPCVTValidationError):
            validate_raw_ohlcv_integrity(row)

    def test_trading_constraint_classification(self) -> None:
        suspended = classify_trading_constraint(
            valid_raw_row() | {"trading_status": "suspended"}
        )
        self.assertFalse(suspended["valid_indicator_day"])
        zero = classify_trading_constraint(
            valid_raw_row() | {"trading_status": "zero_volume"}
        )
        self.assertFalse(zero["ordinary_low_participation"])
        limited = classify_trading_constraint(
            valid_raw_row() | {"trading_status": "limit_up"}
        )
        self.assertEqual(limited["readiness"], "diagnostic_required")

    def test_price_limit_status_unknown_downgrades_readiness(self) -> None:
        result = classify_trading_constraint(
            valid_raw_row()
            | {"trading_status": "normal_trading", "price_limit_status": "unknown"}
        )
        self.assertEqual(result["readiness"], "diagnostic_required")
        self.assertEqual(result["constraint"], "unknown_price_limit_status")

    def test_price_limit_status_invalid_rejected(self) -> None:
        with self.assertRaises(MarketQualityPCVTValidationError):
            classify_trading_constraint(
                valid_raw_row() | {"price_limit_status": "bad_status"}
            )

    def test_normal_trading_with_none_price_limit_is_ready(self) -> None:
        result = classify_trading_constraint(
            valid_raw_row()
            | {"trading_status": "normal_trading", "price_limit_status": "none"}
        )
        self.assertEqual(result["readiness"], "ready")
        self.assertEqual(result["constraint"], "normal_trading")

    def test_normal_trading_with_limit_price_status_is_diagnostic_required(
        self,
    ) -> None:
        result = classify_trading_constraint(
            valid_raw_row()
            | {"trading_status": "normal_trading", "price_limit_status": "limit_up"}
        )
        self.assertEqual(result["readiness"], "diagnostic_required")
        self.assertEqual(result["constraint"], "limit_up")

    def test_amount_volume_units_and_vwap_range(self) -> None:
        self.assertEqual(
            validate_amount_volume_units(
                {"amount_unit": "unknown", "volume_unit": "share"}
            ),
            "unit_validation_required",
        )
        validate_daily_vwap_range(
            valid_raw_row()
            | {
                "amount": 100000,
                "volume": 1000,
                "amount_unit": "yuan",
                "volume_unit": "share",
            }
        )
        with self.assertRaises(MarketQualityPCVTValidationError):
            validate_daily_vwap_range(
                valid_raw_row()
                | {
                    "amount": 10000000,
                    "volume": 100,
                    "amount_unit": "yuan",
                    "volume_unit": "share",
                }
            )

    def test_gap_attribution_guardrails(self) -> None:
        with self.assertRaises(MarketQualityPCVTValidationError):
            classify_gap_attribution(
                {"gap_attribution": "market_gap", "corporate_action_flag": True}
            )
        with self.assertRaises(MarketQualityPCVTValidationError):
            classify_gap_attribution(
                {"gap_attribution": "unknown", "treated_as_none": True}
            )

    def test_no_future_or_row_level_payload_fields(self) -> None:
        for field in [
            "future_return",
            "label",
            "breakout_direction",
            "target",
            "outcome",
        ]:
            with self.assertRaises(MarketQualityPCVTValidationError):
                validate_no_future_fields({field: 1})
        with self.assertRaises(MarketQualityPCVTValidationError):
            validate_no_row_level_price_payload({"raw_rows": [{"raw_close": 1.0}]})

    def test_pcvt_indicator_readiness(self) -> None:
        self.assertEqual(
            validate_pcvt_indicator_readiness(
                "P1_NATR14",
                {"has_full_window": True, "continuous_quality_pass": True},
            ),
            "ready_after_full_window_pull",
        )
        self.assertEqual(
            validate_pcvt_indicator_readiness(
                "C2_AdjVWAPSpread_5_60",
                {"amount_unit": "unknown", "volume_unit": "share"},
            ),
            "unit_validation_required",
        )
        self.assertEqual(
            validate_pcvt_indicator_readiness(
                "V1_VolShrink20_60",
                {"volume_unit": "share", "adjusted_volume_policy_accepted": False},
            ),
            "partial_pending_volume_unit_validation_and_adjusted_volume_policy",
        )
        self.assertEqual(
            validate_pcvt_indicator_readiness(
                "V2_AmountLevel20Pct",
                {"amount_unit": "yuan", "strict_past_percentile_history": True},
            ),
            "ready_after_amount_unit_validation_and_history_window_pull",
        )

    def test_validator_source_has_no_external_or_data_access(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8").lower()
        for token in [
            "baostock",
            "requests",
            "urllib",
            "duckdb",
            "data/raw",
            "data/external",
        ]:
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
