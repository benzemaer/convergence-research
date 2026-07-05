from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_full_candidate import (
    diagnose_missing_with_pro_bar,
)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    columns = [
        "security_id",
        "ts_code",
        "trade_date",
        "trading_status",
        "daily_applicability",
        "price_limit_applicability",
        "adjustment_factor_applicability",
        "suspension_status",
        "st_status",
        "price_limit_status",
        "adjustment_factor_status",
        "partition_path",
        "blocker_type",
        "source_candidate_file",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class FakeProBarClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def pro_bar(self, **params):
        self.calls.append(params)
        return [
            {
                "ts_code": params["ts_code"],
                "trade_date": params["start_date"],
                "close": 10,
            }
        ]


class D2T14ProBarDiagnosticOnlyTest(unittest.TestCase):
    def test_pro_bar_diagnostic_does_not_write_canonical_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            write_csv(
                output_dir / "d2_t13_listed_open_missing_daily_rows.csv",
                [
                    {
                        "security_id": "XSHE.000001",
                        "ts_code": "000001.SZ",
                        "trade_date": "20260105",
                        "blocker_type": "listed_open_missing_daily",
                    }
                ],
            )
            client = FakeProBarClient()
            report = diagnose_missing_with_pro_bar(client, output_dir=output_dir)
            self.assertEqual(report["pro_bar_diagnostic_attempted_count"], 1)
            self.assertEqual(report["pro_bar_diagnostic_returned_count"], 1)
            self.assertFalse(report["canonical_daily_partition_written"])
            self.assertFalse(report["canonical_adj_factor_partition_written"])
            self.assertFalse(report["canonical_adjusted_price_written"])
            self.assertFalse(report["d2_acceptance_changed"])
            self.assertFalse(report["pro_bar_canonical_write_allowed"])
            self.assertFalse(report["duckdb_written"])
            self.assertFalse(report["d3_rows_generated"])
            self.assertFalse(report["r0_state_generated"])
            self.assertFalse((output_dir / "partitions/daily/20260105.jsonl").exists())
            self.assertFalse(
                (output_dir / "tnskhdata_adjusted_price_candidate.jsonl").exists()
            )
            persisted = json.loads(
                (
                    output_dir / "d2_t13_pro_bar_missing_row_diagnostic_report.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(persisted, report)


if __name__ == "__main__":
    unittest.main()
