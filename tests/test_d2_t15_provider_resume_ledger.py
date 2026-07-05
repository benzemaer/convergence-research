from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (
    FetchLedgerEntry,
    SecurityMajorFetchTask,
    fetch_task_with_provider,
    filter_tasks_for_resume,
)


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def daily(self, **params):
        self.calls.append(("daily", params))
        return [
            {
                "ts_code": params["ts_code"],
                "trade_date": params["start_date"],
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
            }
        ]

    def stk_limit(self, **params):
        self.calls.append(("stk_limit", params))
        if "ts_code" in params:
            raise TypeError("unexpected argument ts_code")
        return [
            {
                "ts_code": "000001.SZ",
                "trade_date": params["start_date"],
                "up_limit": 11,
                "down_limit": 9,
            },
            {
                "ts_code": "999999.SZ",
                "trade_date": params["start_date"],
                "up_limit": 99,
                "down_limit": 1,
            },
        ]


class D2T15ProviderResumeLedgerTest(unittest.TestCase):
    def task(self, endpoint: str = "daily") -> SecurityMajorFetchTask:
        return SecurityMajorFetchTask(
            task_id=f"{endpoint}:000001.SZ:20260101:20261231:test",
            endpoint=endpoint,
            ts_code="000001.SZ",
            start_date="20260101",
            end_date="20261231",
            param_variant="ts_code_start_end",
            task_hash=f"hash-{endpoint}",
        )

    def test_resume_skips_completed_task_with_matching_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "d2_t15_fetch_ledger.jsonl"
            task = self.task()
            entry = FetchLedgerEntry(
                task_id=task.task_id,
                endpoint=task.endpoint,
                ts_code=task.ts_code,
                start_date=task.start_date,
                end_date=task.end_date,
                param_variant=task.param_variant,
                task_hash=task.task_hash,
                status="succeeded",
                attempt_count=1,
                row_count=1,
                accepted_row_count=1,
                error_category=None,
                error_message_redacted=None,
                started_at="2026-01-01T00:00:00Z",
                completed_at="2026-01-01T00:00:01Z",
                elapsed_seconds=1,
            )
            path.write_text(json.dumps(entry.__dict__) + "\n", encoding="utf-8")

            remaining = filter_tasks_for_resume([task], path, resume=True)

            self.assertEqual(remaining, [])

    def test_fetch_records_fallback_and_filters_unrelated_rows(self) -> None:
        provider = FakeProvider()
        rows, ledger = fetch_task_with_provider(provider, self.task("stk_limit"))

        self.assertEqual(ledger.status, "succeeded_after_fallback")
        self.assertEqual(ledger.attempt_count, 2)
        self.assertEqual(ledger.accepted_row_count, 1)
        self.assertEqual(rows[0]["ts_code"], "000001.SZ")
        self.assertEqual(
            [endpoint for endpoint, _ in provider.calls],
            ["stk_limit", "stk_limit"],
        )

    def test_daily_fetch_uses_ts_code_range(self) -> None:
        provider = FakeProvider()
        rows, ledger = fetch_task_with_provider(provider, self.task("daily"))

        self.assertEqual(ledger.status, "succeeded")
        self.assertEqual(ledger.attempt_count, 1)
        self.assertEqual(rows[0]["ts_code"], "000001.SZ")
        self.assertEqual(provider.calls[0][1]["ts_code"], "000001.SZ")


if __name__ == "__main__":
    unittest.main()
