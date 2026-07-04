from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_full_candidate import materialize_full_candidate

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (
        ROOT / "configs/d2/tnskhdata_full_materialization_acceptance_contract.v1.json"
    ).read_text(encoding="utf-8")
)


class FakeFrame:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []

    @property
    def empty(self) -> bool:
        return not self.rows

    def to_dict(self, orient: str):
        return self.rows


class CompleteFakeClient:
    def stock_basic(self, **kwargs):
        return FakeFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "list_status": kwargs["list_status"],
                    "list_date": "20100101",
                }
            ]
        )

    def trade_cal(self, **kwargs):
        return FakeFrame(
            [{"cal_date": "20260630", "is_open": 1, "pretrade_date": "20260629"}]
        )

    def daily(self, **kwargs):
        return FakeFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": kwargs["trade_date"],
                    "open": 10,
                    "high": 10.5,
                    "low": 9.5,
                    "close": 10,
                    "pre_close": 9.8,
                    "vol": 100,
                    "amount": 200,
                }
            ]
        )

    def stk_limit(self, **kwargs):
        return FakeFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": kwargs["trade_date"],
                    "up_limit": 11,
                    "down_limit": 9,
                }
            ]
        )

    def adj_factor(self, **kwargs):
        return FakeFrame(
            [{"ts_code": "000001.SZ", "trade_date": "20260630", "adj_factor": 1.2}]
        )

    def stock_st(self, **kwargs):
        return FakeFrame([])

    def suspend_d(self, **kwargs):
        return FakeFrame([])

    def pro_bar(self, **kwargs):
        return FakeFrame([])


class D2T13FullVsSampleGateTest(unittest.TestCase):
    def _candidate_path(self, tmp: Path) -> Path:
        path = tmp / "candidate.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "security_id": "XSHE.000001",
                        "trading_date": "20260630",
                        "universe_id": "u",
                        "time_segment_id": "t",
                    }
                ]
            ),
            encoding="utf-8",
        )
        return path

    def test_sample_run_never_outputs_full_d2_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            result = materialize_full_candidate(
                contract=CONTRACT,
                candidate_universe=self._candidate_path(tmp),
                output_dir=tmp / "generated",
                start_date="20160101",
                end_date="20260630",
                enable_remote_fetch=False,
                client=CompleteFakeClient(),
                full=False,
                sample_securities=1,
                sample_dates_per_security=1,
            )
            self.assertEqual(result["run_mode"], "sample")
            self.assertTrue(result["sample_mode"])
            self.assertEqual(
                result["sample_acceptance_decision"],
                "accepted_for_sample_candidate_generation",
            )
            self.assertEqual(
                result["d2_acceptance_decision"],
                "blocked_pending_tnskhdata_full_materialization_run",
            )
            self.assertEqual(
                result["d3_handoff_decision"], "d3_candidate_generation_blocked"
            )

    def test_full_run_can_output_d2_acceptance_without_d3_or_duckdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            result = materialize_full_candidate(
                contract=CONTRACT,
                candidate_universe=self._candidate_path(tmp),
                output_dir=tmp / "generated",
                start_date="20160101",
                end_date="20260630",
                enable_remote_fetch=False,
                client=CompleteFakeClient(),
                full=True,
            )
            self.assertEqual(result["run_mode"], "full")
            self.assertFalse(result["sample_mode"])
            self.assertIsNone(result["sample_acceptance_decision"])
            self.assertEqual(
                result["d2_acceptance_decision"], "accepted_for_d3_candidate_generation"
            )
            self.assertEqual(
                result["d3_handoff_decision"], "d3_candidate_generation_allowed"
            )
            self.assertFalse(result["duckdb_written"])
            self.assertFalse(result["d3_rows_generated"])
            self.assertFalse(result["r0_state_generated"])


if __name__ == "__main__":
    unittest.main()
