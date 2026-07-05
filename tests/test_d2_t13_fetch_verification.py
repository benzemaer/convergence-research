from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_full_candidate import (
    FetchPlan,
    _write_jsonl,
    verify_partitioned_fetch_completeness,
)


class D2T13FetchVerificationTest(unittest.TestCase):
    def _plan(self) -> FetchPlan:
        return FetchPlan(
            rows=[
                {
                    "security_id": "XSHE.000001",
                    "trading_date": "20260630",
                    "universe_id": "u",
                    "time_segment_id": "t",
                    "mapping_status": "resolved",
                    "ts_code": "000001.SZ",
                }
            ],
            ts_codes=["000001.SZ"],
            trade_dates=["20260630"],
            mode="full",
        )

    def _write_complete_partitions(self, root: Path) -> None:
        for status in ("L", "D", "P", "G"):
            _write_jsonl(root / "partitions" / "stock_basic" / f"{status}.jsonl", [])
        _write_jsonl(root / "partitions" / "trade_cal" / "range.jsonl", [])
        for endpoint in ("daily", "stk_limit", "adj_factor"):
            _write_jsonl(
                root / "partitions" / endpoint / "20260630.jsonl",
                [{"ts_code": "000001.SZ", "trade_date": "20260630"}],
            )
        for endpoint in ("stock_st", "suspend_d"):
            _write_jsonl(root / "partitions" / endpoint / "20260630.jsonl", [])

    def test_complete_partitions_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_complete_partitions(root)
            report = verify_partitioned_fetch_completeness(self._plan(), root)
            self.assertEqual(report["fetch_completeness_decision"], "complete")
            self.assertEqual(report["endpoint_partition_counts"]["daily"], 1)

    def test_missing_partition_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_complete_partitions(root)
            (root / "partitions" / "stk_limit" / "20260630.jsonl").unlink()
            report = verify_partitioned_fetch_completeness(self._plan(), root)
            self.assertEqual(report["fetch_completeness_decision"], "incomplete")
            self.assertTrue(report["missing_partitions"])

    def test_malformed_partition_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_complete_partitions(root)
            (root / "partitions" / "daily" / "20260630.jsonl").write_text("{bad")
            report = verify_partitioned_fetch_completeness(self._plan(), root)
            self.assertEqual(report["fetch_completeness_decision"], "incomplete")
            self.assertTrue(report["malformed_partitions"])


if __name__ == "__main__":
    unittest.main()
