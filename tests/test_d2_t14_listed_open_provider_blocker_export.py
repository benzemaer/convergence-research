from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_full_candidate import (
    export_listed_open_provider_blockers,
)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


class D2T14ListedOpenProviderBlockerExportTest(unittest.TestCase):
    def test_readme_advances_to_d2_t14_and_preserves_d3_blocks(self) -> None:
        readme = Path("docs/tasks/README.md").read_text(encoding="utf-8")
        self.assertIn("current_stage: D2", readme)
        self.assertIn("current_task: D2-T14", readme)
        self.assertIn("next_planned_task: D3-T07", readme)
        self.assertIn(
            "D2-T13` tnskhdata全量候选物化与D2验收交接：completed via PR #45",
            readme,
        )
        self.assertIn(
            "D2-T14` listed-open 行级 provider 修复诊断：in_progress via current PR",
            readme,
        )
        self.assertIn(
            "D3-T07` 标准日频观测表正式生成与 candidate data_version 发布："
            "blocked pending D2 formal materialization",
            readme,
        )
        self.assertIn("R0 remains blocked", readme)

    def test_export_provider_blockers_from_candidate_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            write_jsonl(
                output_dir / "tnskhdata_source_status_candidate.jsonl",
                [
                    {
                        "security_id": "XSHE.000001",
                        "ts_code": "000001.SZ",
                        "trading_date": "2026-01-05",
                        "trading_status": "listed_open_missing_daily",
                        "daily_applicability": "applicable_unresolved",
                        "price_limit_applicability": "applicable",
                        "price_limit_status": "unknown",
                        "suspension_status": "not_suspended",
                        "st_status": "normal",
                    },
                    {
                        "security_id": "XSHG.600000",
                        "ts_code": "600000.SH",
                        "trading_date": "2026-01-05",
                        "trading_status": "trading",
                        "daily_applicability": "applicable_resolved",
                        "price_limit_applicability": "applicable",
                        "price_limit_status": "resolved",
                    },
                ],
            )
            write_jsonl(
                output_dir / "tnskhdata_factor_evidence_candidate.jsonl",
                [
                    {
                        "security_id": "XSHE.000001",
                        "ts_code": "000001.SZ",
                        "trading_date": "2026-01-05",
                        "adjustment_factor_applicability": "applicable",
                        "adjustment_factor_status": "missing",
                    },
                    {
                        "security_id": "XSHG.600000",
                        "ts_code": "600000.SH",
                        "trading_date": "2026-01-05",
                        "adjustment_factor_applicability": "applicable",
                        "adjustment_factor_status": "resolved",
                    },
                ],
            )

            summary = export_listed_open_provider_blockers(output_dir)

            missing = read_csv(output_dir / "d2_t13_listed_open_missing_daily_rows.csv")
            price_limit = read_csv(
                output_dir / "d2_t13_unresolved_price_limit_rows.csv"
            )
            adj_factor = read_csv(output_dir / "d2_t13_unresolved_adj_factor_rows.csv")
            self.assertEqual(len(missing), 1)
            self.assertEqual(len(price_limit), 1)
            self.assertEqual(len(adj_factor), 1)
            self.assertEqual(missing[0]["trade_date"], "20260105")
            self.assertEqual(
                missing[0]["partition_path"], "partitions/daily/20260105.jsonl"
            )
            self.assertEqual(
                price_limit[0]["partition_path"],
                "partitions/stk_limit/20260105.jsonl",
            )
            self.assertEqual(
                adj_factor[0]["partition_path"],
                "partitions/adj_factor/20260105.jsonl",
            )
            self.assertEqual(summary["listed_open_missing_daily_count"], 1)
            self.assertEqual(summary["unresolved_price_limit_count"], 1)
            self.assertEqual(summary["unresolved_adj_factor_count"], 1)
            self.assertEqual(summary["daily_price_limit_overlap_count"], 1)
            self.assertFalse(summary["remote_provider_called"])
            self.assertFalse(summary["duckdb_written"])
            self.assertFalse(summary["d3_rows_generated"])
            self.assertFalse(summary["r0_state_generated"])
            persisted_summary = json.loads(
                (output_dir / "d2_t13_provider_blocker_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(persisted_summary, summary)


if __name__ == "__main__":
    unittest.main()
