from __future__ import annotations

import unittest

from scripts.materialize_d2_tnskhdata_full_candidate import (
    FetchPlan,
    acceptance_decision,
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


def _accepted_quality(dates: list[str]) -> dict[str, object]:
    evidence = {
        "stock_basic": [{"ts_code": "000001.SZ", "list_date": "20200103"}],
        "trade_cal": [
            {"cal_date": date, "is_open": 0 if date == "20200101" else 1}
            for date in dates
        ],
        "daily": [_daily("20200104")],
        "stk_limit": [_limit("20200104")],
        "adj_factor": [_factor("20200104")],
        "stock_st": [],
        "suspend_d": [],
        "_metrics": [{"primary_provider_error_count": 0, "rate_limit_count": 0}],
    }
    plan = _plan(dates)
    outputs = build_candidate_outputs(
        plan, evidence, source_snapshot_id="s", artifact_sha256="h"
    )
    quality = build_quality_report(plan, outputs, evidence)
    quality.update(
        {
            "artifact_hashes_complete": True,
            "fetch_stage_only": False,
            "fetch_completeness_decision": "complete",
            "provider_coverage_decision": "complete",
            "unexpected_empty_primary_partition_count": 0,
            "partition_malformed_count": 0,
            "partition_missing_count": 0,
        }
    )
    return quality


class D2T13CalendarDomainQualityGateTest(unittest.TestCase):
    def test_acceptance_passes_when_only_not_applicable_daily_gaps_remain(self) -> None:
        quality = _accepted_quality(["20200101", "20200102", "20200104"])
        self.assertEqual(quality["calendar_date_count"], 3)
        self.assertEqual(quality["source_status_row_count"], 3)
        self.assertEqual(quality["factor_evidence_row_count"], 3)
        self.assertEqual(quality["daily_raw_row_count"], 1)
        self.assertEqual(quality["adjusted_price_row_count"], 1)
        self.assertEqual(quality["missing_daily_total_count"], 2)
        self.assertEqual(quality["missing_daily_not_applicable_count"], 2)
        self.assertEqual(quality["missing_daily_unexpected_count"], 0)
        self.assertFalse(quality["new_share_reconciliation_required"])
        self.assertEqual(
            quality["new_share_reconciliation_status"], "not_requested_optional"
        )
        self.assertEqual(
            acceptance_decision(quality), "accepted_for_d3_candidate_generation"
        )

    def test_acceptance_blocks_listed_open_missing_daily(self) -> None:
        quality = _accepted_quality(["20200101", "20200102", "20200104", "20200106"])
        self.assertEqual(quality["listed_open_missing_daily_count"], 1)
        self.assertEqual(quality["missing_daily_unexpected_count"], 1)
        self.assertEqual(
            acceptance_decision(quality), "blocked_pending_provider_coverage"
        )


if __name__ == "__main__":
    unittest.main()
