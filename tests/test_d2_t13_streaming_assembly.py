from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_full_candidate import (
    FetchPlan,
    _write_jsonl,
    assemble_partitioned_artifacts,
    verify_partitioned_fetch_completeness,
)


class D2T13StreamingAssemblyTest(unittest.TestCase):
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

    def _write_partitions(self, root: Path) -> None:
        for status in ("L", "D", "P", "G"):
            _write_jsonl(
                root / "partitions" / "stock_basic" / f"{status}.jsonl",
                [
                    {
                        "ts_code": "000001.SZ",
                        "list_status": status,
                        "list_date": "20100101",
                    }
                ],
            )
        _write_jsonl(
            root / "partitions" / "trade_cal" / "range.jsonl",
            [{"cal_date": "20260630", "is_open": 1}],
        )
        _write_jsonl(
            root / "partitions" / "daily" / "20260630.jsonl",
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260630",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "pre_close": 9.8,
                    "vol": 100,
                    "amount": 200,
                }
            ],
        )
        _write_jsonl(
            root / "partitions" / "stk_limit" / "20260630.jsonl",
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260630",
                    "up_limit": 11,
                    "down_limit": 9,
                }
            ],
        )
        _write_jsonl(
            root / "partitions" / "adj_factor" / "20260630.jsonl",
            [{"ts_code": "000001.SZ", "trade_date": "20260630", "adj_factor": 1.2}],
        )
        _write_jsonl(root / "partitions" / "stock_st" / "20260630.jsonl", [])
        _write_jsonl(root / "partitions" / "suspend_d" / "20260630.jsonl", [])

    def test_assembly_overwrites_old_sample_artifacts_and_computes_quality(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_partitions(root)
            (root / "tnskhdata_daily_raw_candidate.jsonl").write_text(
                "old\n", encoding="utf-8"
            )
            verification = verify_partitioned_fetch_completeness(self._plan(), root)
            quality = assemble_partitioned_artifacts(self._plan(), root, verification)
            self.assertFalse(quality["fetch_stage_only"])
            self.assertEqual(quality["daily_raw_row_count"], 1)
            self.assertNotIn(
                "old",
                (root / "tnskhdata_daily_raw_candidate.jsonl").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertEqual(quality["amount_unit_status"], "resolved_thousand_yuan")


if __name__ == "__main__":
    unittest.main()
