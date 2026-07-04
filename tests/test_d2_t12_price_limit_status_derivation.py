from __future__ import annotations

import unittest

from scripts.run_d2_t12_provider_remediation_probe import derive_price_limit_status


class D2T12PriceLimitStatusDerivationTest(unittest.TestCase):
    def test_stk_limit_and_daily_high_or_close_derives_limit_up(self) -> None:
        result = derive_price_limit_status(
            trading_status="normal_trading",
            daily_row={"high": 11.0, "low": 10.0, "close": 10.9},
            stk_limit_row={"up_limit": 11.0, "down_limit": 9.0},
        )
        self.assertEqual(result["price_limit_status"], "limit_up_touched_or_closed")
        self.assertEqual(
            result["price_limit_status_evidence_method"],
            "provider_stk_limit_plus_daily_ohlc",
        )

    def test_stk_limit_and_daily_low_or_close_derives_limit_down(self) -> None:
        result = derive_price_limit_status(
            trading_status="normal_trading",
            daily_row={"high": 10.0, "low": 9.0, "close": 9.2},
            stk_limit_row={"up_limit": 11.0, "down_limit": 9.0},
        )
        self.assertEqual(result["price_limit_status"], "limit_down_touched_or_closed")

    def test_not_touching_limits_derives_not_limited(self) -> None:
        result = derive_price_limit_status(
            trading_status="normal_trading",
            daily_row={"high": 10.5, "low": 9.5, "close": 10.0},
            stk_limit_row={"up_limit": 11.0, "down_limit": 9.0},
        )
        self.assertEqual(result["price_limit_status"], "not_limited")

    def test_non_trading_status_is_not_applicable(self) -> None:
        result = derive_price_limit_status(
            trading_status="market_closed",
            daily_row=None,
            stk_limit_row={"up_limit": 11.0, "down_limit": 9.0},
        )
        self.assertEqual(result["price_limit_status"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
