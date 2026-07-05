from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (
    DuckDBStagingWriter,
    compute_quality_gate,
    d2_acceptance_decision,
)


class D2T15DuckDBQualityGateTest(unittest.TestCase):
    def build_writer(self) -> DuckDBStagingWriter:
        self.tmpdir = tempfile.TemporaryDirectory()
        writer = DuckDBStagingWriter(
            Path(self.tmpdir.name) / "d2_t15_tnskhdata_staging.duckdb"
        )
        writer.write_security_universe(
            [
                {
                    "security_id": "CN.SZSE.000001",
                    "ts_code": "000001.SZ",
                    "universe_id": "u",
                    "time_segment_id": "t",
                },
                {
                    "security_id": "CN.SZSE.000002",
                    "ts_code": "000002.SZ",
                    "universe_id": "u",
                    "time_segment_id": "t",
                },
            ]
        )
        writer.write_trade_calendar(
            [
                {"cal_date": "20260105", "is_open": "1"},
                {"cal_date": "20260106", "is_open": "1"},
            ]
        )
        writer.write_stock_basic(
            [
                {"ts_code": "000001.SZ", "list_date": "20000101", "delist_date": ""},
                {"ts_code": "000002.SZ", "list_date": "20000101", "delist_date": ""},
            ]
        )
        return writer

    def tearDown(self) -> None:
        if hasattr(self, "tmpdir"):
            self.tmpdir.cleanup()

    def test_quality_gate_reclassifies_suspend_and_daily_dependency(self) -> None:
        writer = self.build_writer()
        try:
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
                        "adj_factor": 1.0,
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
            writer.write_endpoint_rows(
                "suspend_d",
                [
                    {
                        "ts_code": "000002.SZ",
                        "suspend_date": "20260105",
                        "suspend_type": "S",
                    }
                ],
            )

            quality = compute_quality_gate(writer.conn)

            self.assertEqual(quality["expected_listed_open_security_date_count"], 4)
            self.assertEqual(quality["suspended_security_date_count"], 1)
            self.assertEqual(quality["listed_open_missing_daily_count"], 2)
            self.assertEqual(quality["price_limit_daily_dependency_missing_count"], 2)
            self.assertEqual(quality["unresolved_price_limit_status_count"], 0)
            self.assertEqual(quality["unresolved_adjustment_factor_count"], 2)
            self.assertEqual(quality["adj_factor_carry_forward_required_count"], 1)
            suspended_price_limit_status = writer.conn.execute(
                """
                SELECT price_limit_status
                FROM d2_source_status
                WHERE ts_code = '000002.SZ' AND trade_date = '20260105'
                """
            ).fetchone()[0]
            self.assertEqual(
                suspended_price_limit_status, "not_applicable_or_expected_empty"
            )
            status = writer.conn.execute(
                """
                SELECT price_limit_status
                FROM d2_source_status
                WHERE ts_code = '000002.SZ' AND trade_date = '20260106'
                """
            ).fetchone()[0]
            self.assertEqual(status, "daily_dependency_missing")
            gap_types = {
                row[0]
                for row in writer.conn.execute(
                    """
                    SELECT DISTINCT gap_type
                    FROM d2_coverage_gaps
                    WHERE ts_code = '000002.SZ' AND trade_date = '20260105'
                    """
                ).fetchall()
            }
            self.assertEqual(gap_types, set())
            self.assertEqual(
                d2_acceptance_decision(quality), "blocked_pending_provider_coverage"
            )
        finally:
            writer.close()

    def test_unmapped_security_blocks_acceptance(self) -> None:
        writer = self.build_writer()
        try:
            writer.write_security_mapping_diagnostics(
                [
                    {
                        "security_id": "CN.SZSE.000001",
                        "ts_code": "000001.SZ",
                        "mapping_status": "resolved",
                        "mapping_blocking_reasons": [],
                    },
                    {
                        "security_id": "BAD.CODE",
                        "ts_code": "",
                        "mapping_status": "unresolved",
                        "mapping_blocking_reasons": ["unsupported_security_id_format"],
                    },
                ]
            )

            quality = compute_quality_gate(writer.conn)

            self.assertEqual(quality["configured_security_count"], 2)
            self.assertEqual(quality["mapped_security_count"], 1)
            self.assertEqual(quality["unmapped_security_count"], 1)
            self.assertEqual(
                d2_acceptance_decision(
                    {
                        **quality,
                        "listed_open_missing_daily_count": 0,
                        "unresolved_adjustment_factor_count": 0,
                        "unresolved_price_limit_status_count": 0,
                    }
                ),
                "blocked_pending_provider_coverage",
            )
        finally:
            writer.close()

    def test_duplicate_and_price_quality_block_acceptance(self) -> None:
        writer = self.build_writer()
        try:
            duplicate_bad_rows = [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260105",
                    "open": 10,
                    "high": 8,
                    "low": 9,
                    "close": 10,
                },
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260105",
                    "open": 0,
                    "high": 8,
                    "low": 9,
                    "close": None,
                },
            ]
            writer.write_endpoint_rows("daily", duplicate_bad_rows)

            quality = compute_quality_gate(writer.conn)

            self.assertEqual(quality["duplicate_daily_key_count"], 1)
            self.assertEqual(quality["null_ohlc_count"], 1)
            self.assertEqual(quality["non_positive_price_count"], 1)
            self.assertEqual(quality["high_low_violation_count"], 2)
            self.assertEqual(
                d2_acceptance_decision(
                    {
                        **quality,
                        "listed_open_missing_daily_count": 0,
                        "unresolved_adjustment_factor_count": 0,
                        "unresolved_price_limit_status_count": 0,
                    }
                ),
                "blocked_pending_quality_resolution",
            )
        finally:
            writer.close()


if __name__ == "__main__":
    unittest.main()
