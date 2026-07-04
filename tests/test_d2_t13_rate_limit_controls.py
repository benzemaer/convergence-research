from __future__ import annotations

import unittest

from scripts.materialize_d2_tnskhdata_full_candidate import (
    RequestThrottle,
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
        return self.rows


class RetryClient:
    def __init__(self) -> None:
        self.daily_attempts = 0

    def stock_basic(self, **kwargs):
        return FakeFrame([{"ts_code": "000001.SZ", "list_date": "20100101"}])

    def trade_cal(self, **kwargs):
        return FakeFrame([{"cal_date": "20260630", "is_open": 1}])

    def daily(self, **kwargs):
        self.daily_attempts += 1
        if self.daily_attempts == 1:
            raise RuntimeError("temporary endpoint error")
        return FakeFrame([{"ts_code": "000001.SZ", "trade_date": kwargs["trade_date"]}])

    def stk_limit(self, **kwargs):
        return FakeFrame([])

    def adj_factor(self, **kwargs):
        return FakeFrame([])

    def stock_st(self, **kwargs):
        return FakeFrame([])

    def suspend_d(self, **kwargs):
        return FakeFrame([])

    def pro_bar(self, **kwargs):
        return FakeFrame([])


class D2T13RateLimitControlsTest(unittest.TestCase):
    def test_request_throttle_intervals_reflect_cli_defaults(self) -> None:
        self.assertEqual(RequestThrottle(200, enabled=True).interval, 0.3)
        self.assertEqual(RequestThrottle(60, enabled=True).interval, 1.0)

    def test_retry_parameters_are_used_for_primary_provider_calls(self) -> None:
        plan = build_fetch_plan(
            [
                {
                    "security_id": "XSHE.000001",
                    "trading_date": "20260630",
                    "universe_id": "u",
                    "time_segment_id": "t",
                }
            ],
            full=True,
            sample_securities=None,
            sample_dates_per_security=None,
        )
        client = RetryClient()
        fetch_provider_evidence(
            client,
            plan,
            requests_per_minute=200,
            pro_bar_requests_per_minute=60,
            retry_max_attempts=2,
            retry_backoff_seconds=0,
        )
        self.assertEqual(client.daily_attempts, 2)


if __name__ == "__main__":
    unittest.main()
