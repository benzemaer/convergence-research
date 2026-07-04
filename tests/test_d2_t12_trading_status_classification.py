from __future__ import annotations

import unittest

from scripts.run_d2_t12_provider_remediation_probe import (
    classify_st_status,
    classify_suspension_status,
    classify_trading_status,
)


class D2T12TradingStatusClassificationTest(unittest.TestCase):
    def test_list_date_before_trade_date_classifies_not_listed_yet(self) -> None:
        self.assertEqual(
            classify_trading_status(
                trading_date="20260702",
                stock_basic={"list_date": "20260703"},
                trade_cal={"is_open": 1},
                daily_row={"close": 10},
                suspend_row=None,
            ),
            "not_listed_yet",
        )

    def test_closed_calendar_classifies_market_closed(self) -> None:
        self.assertEqual(
            classify_trading_status(
                trading_date="20260702",
                stock_basic={"list_date": "20200101"},
                trade_cal={"is_open": 0},
                daily_row=None,
                suspend_row=None,
            ),
            "market_closed",
        )

    def test_suspend_s_classifies_suspended(self) -> None:
        trading = classify_trading_status(
            trading_date="20260702",
            stock_basic={"list_date": "20200101"},
            trade_cal={"is_open": 1},
            daily_row=None,
            suspend_row={"suspend_type": "S"},
        )
        self.assertEqual(trading, "suspended")
        self.assertEqual(
            classify_suspension_status(
                trading_status=trading,
                daily_row=None,
                suspend_row={"suspend_type": "S"},
            ),
            "suspended",
        )

    def test_daily_row_without_suspend_classifies_normal_trading(self) -> None:
        trading = classify_trading_status(
            trading_date="20260702",
            stock_basic={"list_date": "20200101"},
            trade_cal={"is_open": 1},
            daily_row={"close": 10},
            suspend_row=None,
        )
        self.assertEqual(trading, "normal_trading")
        self.assertEqual(
            classify_suspension_status(
                trading_status=trading, daily_row={"close": 10}, suspend_row=None
            ),
            "not_suspended",
        )

    def test_stock_st_primary_and_absence_for_listed_stock(self) -> None:
        self.assertEqual(
            classify_st_status(
                trading_status="normal_trading", stock_st_row={"ts_code": "000001.SZ"}
            )["st_status"],
            "st",
        )
        self.assertEqual(
            classify_st_status(trading_status="normal_trading", stock_st_row=None)[
                "st_status"
            ],
            "not_st",
        )


if __name__ == "__main__":
    unittest.main()
