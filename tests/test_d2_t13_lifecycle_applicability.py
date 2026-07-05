from __future__ import annotations

import unittest

from scripts.materialize_d2_tnskhdata_full_candidate import (
    FetchPlan,
    build_candidate_outputs,
    build_quality_report,
)


def _row(trading_date: str) -> dict[str, str]:
    return {
        "security_id": "XSHE.000001",
        "ts_code": "000001.SZ",
        "trading_date": trading_date,
        "universe_id": "u",
        "time_segment_id": "t",
        "mapping_status": "resolved",
    }


def _plan(dates: list[str]) -> FetchPlan:
    return FetchPlan(
        rows=[_row(date) for date in dates],
        ts_codes=["000001.SZ"],
        trade_dates=dates,
        mode="full",
        fetch_date_domain="calendar",
    )


def _daily(trading_date: str) -> dict[str, object]:
    return {
        "ts_code": "000001.SZ",
        "trade_date": trading_date,
        "open": 10,
        "high": 11,
        "low": 9,
        "close": 10,
        "vol": 100,
        "amount": 200,
    }


def _limit(trading_date: str) -> dict[str, object]:
    return {
        "ts_code": "000001.SZ",
        "trade_date": trading_date,
        "up_limit": 11,
        "down_limit": 9,
    }


def _factor(trading_date: str) -> dict[str, object]:
    return {
        "ts_code": "000001.SZ",
        "trade_date": trading_date,
        "adj_factor": 1.2,
    }


class D2T13LifecycleApplicabilityTest(unittest.TestCase):
    def test_lifecycle_and_calendar_missing_rows_are_not_applicable(self) -> None:
        dates = ["20200101", "20200102", "20200104", "20200105", "20200107"]
        evidence = {
            "stock_basic": [
                {
                    "ts_code": "000001.SZ",
                    "list_date": "20200103",
                    "delist_date": "20200106",
                }
            ],
            "trade_cal": [
                {"cal_date": "20200101", "is_open": 0},
                {"cal_date": "20200102", "is_open": 1},
                {"cal_date": "20200104", "is_open": 1},
                {"cal_date": "20200105", "is_open": 1},
                {"cal_date": "20200107", "is_open": 1},
            ],
            "daily": [_daily("20200104")],
            "stk_limit": [_limit("20200104")],
            "adj_factor": [_factor("20200104")],
            "stock_st": [],
            "suspend_d": [
                {
                    "ts_code": "000001.SZ",
                    "suspend_date": "20200105",
                    "suspend_type": "S",
                }
            ],
            "_metrics": [{"primary_provider_error_count": 0, "rate_limit_count": 0}],
        }
        outputs = build_candidate_outputs(
            _plan(dates), evidence, source_snapshot_id="s", artifact_sha256="h"
        )
        by_date = {row["trading_date"]: row for row in outputs["source_status"]}
        self.assertEqual(by_date["20200101"]["trading_status"], "non_trading_day")
        self.assertEqual(by_date["20200102"]["trading_status"], "pre_listing")
        self.assertEqual(by_date["20200104"]["trading_status"], "trading")
        self.assertEqual(by_date["20200105"]["trading_status"], "suspended")
        self.assertEqual(by_date["20200107"]["trading_status"], "post_delist")
        self.assertEqual(
            by_date["20200102"]["price_limit_applicability"], "not_applicable"
        )
        factor_by_date = {
            row["trading_date"]: row for row in outputs["factor_evidence"]
        }
        self.assertEqual(
            factor_by_date["20200102"]["adjustment_factor_applicability"],
            "not_applicable",
        )
        quality = build_quality_report(_plan(dates), outputs, evidence)
        self.assertEqual(quality["source_status_row_count"], len(dates))
        self.assertEqual(quality["factor_evidence_row_count"], len(dates))
        self.assertEqual(quality["adjusted_price_row_count"], 1)
        self.assertEqual(quality["daily_raw_row_count"], 1)
        self.assertEqual(quality["missing_daily_unexpected_count"], 0)
        self.assertEqual(quality["unresolved_price_limit_status_count"], 0)
        self.assertEqual(quality["unresolved_adjustment_factor_count"], 0)


if __name__ == "__main__":
    unittest.main()
