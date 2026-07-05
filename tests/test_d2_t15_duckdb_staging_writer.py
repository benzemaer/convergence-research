from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb

from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (
    DuckDBStagingWriter,
)


class D2T15DuckDBStagingWriterTest(unittest.TestCase):
    def test_single_writer_creates_required_tables_and_writes_fake_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "d2_t15_tnskhdata_staging.duckdb"
            writer = DuckDBStagingWriter(db_path)
            try:
                self.assertIsNotNone(writer.conn)
                writer.write_security_universe(
                    [
                        {
                            "security_id": "CN.SZSE.000001",
                            "ts_code": "000001.SZ",
                            "universe_id": "CSI800_STATIC_2026_06",
                            "time_segment_id": (
                                "DR001_STATIC_BACKFILL_20160101_20260630"
                            ),
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
                            "close": 10.5,
                            "pre_close": 10,
                            "vol": 100,
                            "amount": 1000,
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
                    "suspend_d",
                    [
                        {
                            "ts_code": "000001.SZ",
                            "trade_date": "20260106",
                            "suspend_type": "S",
                        }
                    ],
                )

                tables = {
                    row[0] for row in writer.conn.execute("SHOW TABLES").fetchall()
                }
                self.assertGreaterEqual(
                    tables,
                    {
                        "staging_security_universe",
                        "staging_daily_raw",
                        "staging_adj_factor",
                        "staging_suspend_d",
                        "d2_quality_summary",
                    },
                )
                self.assertEqual(
                    writer.conn.execute(
                        "SELECT count(*) FROM staging_daily_raw"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    writer.conn.execute(
                        "SELECT suspend_date FROM staging_suspend_d"
                    ).fetchone()[0],
                    "20260106",
                )
            finally:
                writer.close()

            conn = duckdb.connect(str(db_path))
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT count(*) FROM staging_security_universe"
                    ).fetchone()[0],
                    1,
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
