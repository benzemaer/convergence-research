from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_full_candidate import (
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


class CountingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def stock_basic(self, **kwargs):
        self.calls.append(("stock_basic", kwargs))
        return FakeFrame([{"ts_code": "000001.SZ", "list_date": "20100101"}])

    def trade_cal(self, **kwargs):
        self.calls.append(("trade_cal", kwargs))
        return FakeFrame(
            [
                {"cal_date": "20260629", "is_open": 1},
                {"cal_date": "20260630", "is_open": 1},
            ]
        )

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs))
        return FakeFrame([{"ts_code": "000001.SZ", "trade_date": kwargs["trade_date"]}])

    def stk_limit(self, **kwargs):
        self.calls.append(("stk_limit", kwargs))
        return FakeFrame([{"ts_code": "000001.SZ", "trade_date": kwargs["trade_date"]}])

    def adj_factor(self, **kwargs):
        self.calls.append(("adj_factor", kwargs))
        return FakeFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": kwargs["trade_date"],
                    "adj_factor": 1,
                }
            ]
        )

    def stock_st(self, **kwargs):
        self.calls.append(("stock_st", kwargs))
        return FakeFrame([])

    def suspend_d(self, **kwargs):
        self.calls.append(("suspend_d", kwargs))
        return FakeFrame([])

    def pro_bar(self, **kwargs):
        self.calls.append(("pro_bar", kwargs))
        return FakeFrame([])


class D2T13CheckpointResumeTest(unittest.TestCase):
    def _plan(self):
        return build_fetch_plan(
            [
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
            ],
            full=True,
            sample_securities=None,
            sample_dates_per_security=None,
        )

    def test_checkpoint_writes_completed_dates_and_resume_skips_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_dir = Path(tmpdir)
            plan = self._plan()
            first = CountingClient()
            evidence = fetch_provider_evidence(
                first,
                plan,
                retry_max_attempts=1,
                retry_backoff_seconds=0,
                checkpoint_dir=checkpoint_dir,
            )
            self.assertEqual(evidence["_metrics"][0]["resume_checkpoint_count"], 2)
            checkpoint = checkpoint_dir / "tnskhdata_fetch_checkpoint.json"
            self.assertTrue(checkpoint.exists())
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            self.assertEqual(payload["completed_trade_dates"], ["20260629", "20260630"])
            self.assertEqual(payload["failed_trade_dates"], [])
            self.assertEqual(payload["last_successful_trade_date"], "20260630")
            self.assertEqual(payload["request_count"], 15)
            self.assertEqual(payload["rate_limit_count"], 0)

            second = CountingClient()
            fetch_provider_evidence(
                second,
                plan,
                retry_max_attempts=1,
                retry_backoff_seconds=0,
                resume=True,
                checkpoint_dir=checkpoint_dir,
            )
            self.assertFalse(any(name == "daily" for name, _ in second.calls))


if __name__ == "__main__":
    unittest.main()
