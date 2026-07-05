from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (
    DuckDBStagingWriter,
    build_acceptance_reports,
    compute_quality_gate,
    run_quality_reports,
)


class D2T15D3HandoffGateTest(unittest.TestCase):
    def test_accepted_quality_only_allows_handoff_decision_not_d3_rows(self) -> None:
        quality = {
            "listed_open_missing_daily_count": 0,
            "unresolved_adjustment_factor_count": 0,
            "unresolved_price_limit_status_count": 0,
            "duplicate_daily_key_count": 0,
            "duplicate_adj_factor_key_count": 0,
            "duplicate_stk_limit_key_count": 0,
            "duplicate_suspend_key_count": 0,
            "null_ohlc_count": 0,
            "non_positive_price_count": 0,
            "high_low_violation_count": 0,
            "provider_error_count": 0,
            "rate_limit_count": 0,
            "timeout_count": 0,
        }

        acceptance, handoff = build_acceptance_reports(quality)

        self.assertEqual(
            acceptance["d2_acceptance_decision"],
            "accepted_for_d3_candidate_generation",
        )
        self.assertEqual(
            handoff["d3_handoff_decision"], "d3_candidate_generation_allowed"
        )
        self.assertFalse(acceptance["formal_duckdb_write_authorized"])
        self.assertFalse(acceptance["d3_rows_generated"])
        self.assertFalse(acceptance["pcvt_values_generated"])
        self.assertFalse(acceptance["r0_state_generated"])
        self.assertFalse(handoff["d3_generation_authorized"])
        self.assertFalse(handoff["d3_rows_generated"])
        self.assertFalse(handoff["data_version_published"])

    def test_no_remote_quality_reports_write_candidate_reports_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            db_path = output_dir / "d2_t15_tnskhdata_staging.duckdb"
            writer = DuckDBStagingWriter(db_path)
            try:
                writer.write_security_universe(
                    [
                        {
                            "security_id": "CN.SZSE.000001",
                            "ts_code": "000001.SZ",
                            "universe_id": "u",
                            "time_segment_id": "t",
                        }
                    ]
                )
                writer.write_trade_calendar([{"cal_date": "20260105", "is_open": "1"}])
                writer.write_stock_basic(
                    [
                        {
                            "ts_code": "000001.SZ",
                            "list_date": "20000101",
                            "delist_date": "",
                        }
                    ]
                )
                writer.write_endpoint_rows(
                    "daily",
                    [
                        {
                            "ts_code": "000001.SZ",
                            "trade_date": "20260105",
                            "open": 10,
                            "high": 11,
                            "low": 9,
                            "close": 10,
                        }
                    ],
                )
                writer.write_endpoint_rows(
                    "adj_factor",
                    [
                        {
                            "ts_code": "000001.SZ",
                            "trade_date": "20260105",
                            "adj_factor": 1,
                        }
                    ],
                )
                writer.write_endpoint_rows(
                    "stk_limit",
                    [
                        {
                            "ts_code": "000001.SZ",
                            "trade_date": "20260105",
                            "up_limit": 11,
                            "down_limit": 9,
                        }
                    ],
                )
                self.assertEqual(
                    compute_quality_gate(writer.conn)[
                        "listed_open_missing_daily_count"
                    ],
                    0,
                )
            finally:
                writer.close()

            result = run_quality_reports(output_dir, db_path)

            self.assertEqual(
                result["acceptance"]["d2_acceptance_decision"],
                "accepted_for_d3_candidate_generation",
            )
            self.assertFalse(result["acceptance"]["d3_rows_generated"])
            self.assertFalse(
                (output_dir / "d3_daily_market_observations.jsonl").exists()
            )
            self.assertFalse((output_dir / "r0_state.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
