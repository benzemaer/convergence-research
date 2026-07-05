from __future__ import annotations

import unittest

from scripts.materialize_d2_tnskhdata_full_candidate import (
    build_endpoint_tasks,
    build_fetch_plan,
    fetch_provider_evidence,
)


class FakeFrame:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []

    @property
    def empty(self) -> bool:
        return not self.rows

    def to_dict(self, orient: str):
        if orient != "records":
            raise ValueError(orient)
        return self.rows


class FakeProviderClient:
    def __init__(
        self, fail_date_adj_factor: bool = False, fail_pro_bar: bool = False
    ) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fail_date_adj_factor = fail_date_adj_factor
        self.fail_pro_bar = fail_pro_bar

    def stock_basic(self, **kwargs):
        self.calls.append(("stock_basic", kwargs))
        return FakeFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "symbol": "000001",
                    "name": "sample",
                    "market": "main",
                    "exchange": "SZSE",
                    "list_status": kwargs["list_status"],
                    "list_date": "20100101",
                    "delist_date": "",
                }
            ]
        )

    def trade_cal(self, **kwargs):
        self.calls.append(("trade_cal", kwargs))
        return FakeFrame([{"exchange": "SSE", "cal_date": "20260630", "is_open": 1}])

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs))
        return FakeFrame([{"ts_code": "000001.SZ", "trade_date": kwargs["trade_date"]}])

    def stk_limit(self, **kwargs):
        self.calls.append(("stk_limit", kwargs))
        return FakeFrame([{"ts_code": "000001.SZ", "trade_date": kwargs["trade_date"]}])

    def adj_factor(self, **kwargs):
        self.calls.append(("adj_factor", kwargs))
        if self.fail_date_adj_factor and "trade_date" in kwargs:
            raise RuntimeError("date endpoint unavailable")
        return FakeFrame(
            [{"ts_code": "000001.SZ", "trade_date": "20260630", "adj_factor": 1.0}]
        )

    def stock_st(self, **kwargs):
        self.calls.append(("stock_st", kwargs))
        return FakeFrame([])

    def suspend_d(self, **kwargs):
        self.calls.append(("suspend_d", kwargs))
        return FakeFrame([])

    def pro_bar(self, **kwargs):
        self.calls.append(("pro_bar", kwargs))
        if self.fail_pro_bar:
            raise RuntimeError("No such method: pro_bar")
        return FakeFrame(
            [{"ts_code": kwargs["ts_code"], "trade_date": "20260630", "close": 10}]
        )


class D2T13TnskhdataProviderFetchPlanningTest(unittest.TestCase):
    def test_sample_plan_selects_latest_dates_and_maps_ts_code(self) -> None:
        rows = [
            {
                "security_id": "XSHE.000001",
                "trading_date": "20260629",
                "universe_id": "u",
                "time_segment_id": "t",
            },
            {
                "security_id": "XSHE.000001",
                "trading_date": "20260630",
                "universe_id": "u",
                "time_segment_id": "t",
            },
        ]
        plan = build_fetch_plan(
            rows, full=False, sample_securities=1, sample_dates_per_security=1
        )
        self.assertEqual(len(plan.rows), 1)
        self.assertEqual(plan.rows[0]["ts_code"], "000001.SZ")
        self.assertEqual(plan.trade_dates, ["20260630"])

    def test_fetch_uses_date_batch_and_adj_factor_ts_code_fallback(self) -> None:
        rows = [
            {
                "security_id": "XSHE.000001",
                "trading_date": "20260630",
                "universe_id": "u",
                "time_segment_id": "t",
            }
        ]
        plan = build_fetch_plan(
            rows, full=True, sample_securities=None, sample_dates_per_security=None
        )
        client = FakeProviderClient(fail_date_adj_factor=True)
        evidence = fetch_provider_evidence(client, plan)
        self.assertTrue(evidence["adj_factor"])
        self.assertIn(("daily", {"trade_date": "20260630"}), client.calls)
        self.assertTrue(
            any(
                call[0] == "adj_factor" and "ts_code" in call[1]
                for call in client.calls
            )
        )
        self.assertEqual(evidence["_metrics"][0]["primary_provider_error_count"], 1)

    def test_calendar_fetch_date_domain_does_not_use_trade_cal_open_cut(self) -> None:
        rows = [
            {
                "security_id": "XSHE.000001",
                "trading_date": "20260630",
                "universe_id": "u",
                "time_segment_id": "t",
            }
        ]
        plan = build_fetch_plan(
            rows,
            full=True,
            sample_securities=None,
            sample_dates_per_security=None,
            start_date="20260629",
            end_date="20260701",
            fetch_date_domain="calendar",
        )
        tasks = build_endpoint_tasks(plan)
        daily_dates = sorted(
            task.trade_date for task in tasks if task.endpoint == "daily"
        )
        self.assertEqual(daily_dates, ["20260629", "20260630", "20260701"])

    def test_pro_bar_failure_is_reconciliation_warning_not_primary_error(self) -> None:
        rows = [
            {
                "security_id": "XSHE.000001",
                "trading_date": "20260630",
                "universe_id": "u",
                "time_segment_id": "t",
            }
        ]
        plan = build_fetch_plan(
            rows, full=True, sample_securities=None, sample_dates_per_security=None
        )
        evidence = fetch_provider_evidence(
            FakeProviderClient(fail_pro_bar=True),
            plan,
            requests_per_minute=200,
            pro_bar_requests_per_minute=60,
            retry_max_attempts=1,
            retry_backoff_seconds=0,
        )
        metrics = evidence["_metrics"][0]
        self.assertEqual(metrics["primary_provider_error_count"], 0)
        self.assertEqual(metrics["reconciliation_provider_error_count"], 1)
        self.assertEqual(
            metrics["pro_bar_reconciliation_status"], "failed_non_blocking"
        )
        self.assertEqual(metrics["pro_bar_reconciliation_warning_count"], 1)


if __name__ == "__main__":
    unittest.main()
