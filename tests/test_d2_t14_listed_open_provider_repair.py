from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_full_candidate import (
    FetchPlan,
    build_candidate_outputs,
    merge_repair_rows_into_partition,
    repair_listed_open_provider_blockers,
)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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


class FakeRepairClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def daily(self, **params):
        self.calls.append(("daily", params))
        if params.get("ts_code") == "000001.SZ":
            return [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260105",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                    "vol": 100,
                    "amount": 1000,
                }
            ]
        if params.get("ts_code") == "000002.SZ":
            return []
        return []

    def stk_limit(self, **params):
        self.calls.append(("stk_limit", params))
        if "ts_code" in params:
            raise TypeError("unexpected argument ts_code")
        return [
            {"ts_code": "000001.SZ", "trade_date": "20260105", "up_limit": 11},
            {"ts_code": "999999.SZ", "trade_date": "20260105", "up_limit": 99},
        ]

    def adj_factor(self, **params):
        self.calls.append(("adj_factor", params))
        return [{"ts_code": "000001.SZ", "trade_date": "20260105", "adj_factor": 1}]

    def suspend_d(self, **params):
        self.calls.append(("suspend_d", params))
        return [
            {
                "ts_code": params["ts_code"],
                "trade_date": params.get("trade_date") or params.get("suspend_date"),
                "suspend_type": "S",
            }
        ]


class D2T14ListedOpenProviderRepairTest(unittest.TestCase):
    def seed_blockers(self, output_dir: Path) -> None:
        rows = [
            {
                "security_id": "XSHE.000001",
                "ts_code": "000001.SZ",
                "trade_date": "20260105",
                "blocker_type": "listed_open_missing_daily",
            },
            {
                "security_id": "XSHE.000002",
                "ts_code": "000002.SZ",
                "trade_date": "20260105",
                "blocker_type": "listed_open_missing_daily",
            },
        ]
        write_csv(output_dir / "d2_t13_listed_open_missing_daily_rows.csv", rows)
        write_csv(
            output_dir / "d2_t13_unresolved_price_limit_rows.csv",
            [rows[0] | {"blocker_type": "unresolved_price_limit"}],
        )
        write_csv(
            output_dir / "d2_t13_unresolved_adj_factor_rows.csv",
            [rows[0] | {"blocker_type": "unresolved_adj_factor"}],
        )

    def test_repair_uses_row_level_keys_filters_fallback_and_merges(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            self.seed_blockers(output_dir)
            write_jsonl(
                output_dir / "partitions/daily/20260105.jsonl",
                [{"ts_code": "600000.SH", "trade_date": "20260105", "close": 1}],
            )
            write_jsonl(output_dir / "partitions/stk_limit/20260105.jsonl", [])
            write_jsonl(output_dir / "partitions/adj_factor/20260105.jsonl", [])
            write_jsonl(output_dir / "partitions/suspend_d/20260105.jsonl", [])
            write_jsonl(
                output_dir / "tnskhdata_source_status_candidate.jsonl",
                [
                    {
                        "security_id": "XSHE.000002",
                        "ts_code": "000002.SZ",
                        "trading_date": "2026-01-05",
                        "trading_status": "listed_open_missing_daily",
                        "daily_applicability": "applicable_unresolved",
                        "price_limit_applicability": "applicable_unresolved",
                        "price_limit_status": "unknown",
                    }
                ],
            )
            write_jsonl(output_dir / "tnskhdata_factor_evidence_candidate.jsonl", [])
            (output_dir / "tnskhdata_quality_report.json").write_text(
                json.dumps(
                    {
                        "missing_daily_unexpected_count": 2,
                        "listed_open_missing_daily_count": 2,
                        "unresolved_price_limit_status_count": 1,
                        "unresolved_adjustment_factor_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "tnskhdata_d2_acceptance_candidate_report.json").write_text(
                json.dumps(
                    {"d2_acceptance_decision": "blocked_pending_provider_coverage"}
                ),
                encoding="utf-8",
            )

            client = FakeRepairClient()
            report = repair_listed_open_provider_blockers(
                client, output_dir=output_dir, plan=None
            )

            self.assertEqual(report["daily_repair_attempted_count"], 2)
            self.assertEqual(report["daily_repair_resolved_count"], 1)
            self.assertEqual(report["suspend_repair_resolved_count"], 1)
            self.assertEqual(report["stk_limit_repair_resolved_count"], 1)
            self.assertEqual(report["adj_factor_repair_resolved_count"], 1)
            self.assertEqual(report["date_only_fallback_call_count"], 1)
            self.assertEqual(report["date_only_fallback_rows_filtered_out_count"], 1)
            daily_calls = [
                params for endpoint, params in client.calls if endpoint == "daily"
            ]
            self.assertEqual(
                {(call.get("ts_code"), call.get("trade_date")) for call in daily_calls},
                {("000001.SZ", "20260105"), ("000002.SZ", "20260105")},
            )
            daily_rows = read_jsonl(output_dir / "partitions/daily/20260105.jsonl")
            self.assertIn("600000.SH", {row["ts_code"] for row in daily_rows})
            self.assertIn("000001.SZ", {row["ts_code"] for row in daily_rows})
            limit_rows = read_jsonl(output_dir / "partitions/stk_limit/20260105.jsonl")
            self.assertEqual({row["ts_code"] for row in limit_rows}, {"000001.SZ"})
            suspend_rows = read_jsonl(
                output_dir / "partitions/suspend_d/20260105.jsonl"
            )
            self.assertEqual(suspend_rows[0]["suspend_date"], "20260105")
            self.assertFalse(report["pro_bar_called"])
            self.assertFalse(report["duckdb_written"])
            self.assertFalse(report["d3_rows_generated"])
            self.assertFalse(report["r0_state_generated"])

    def test_merge_deduplicates_target_key_without_touching_unrelated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            path = output_dir / "partitions/daily/20260105.jsonl"
            write_jsonl(
                path,
                [
                    {"ts_code": "000001.SZ", "trade_date": "20260105", "close": 1},
                    {"ts_code": "600000.SH", "trade_date": "20260105", "close": 2},
                ],
            )
            result = merge_repair_rows_into_partition(
                output_dir,
                "daily",
                "20260105",
                [
                    {"ts_code": "000001.SZ", "trade_date": "20260105", "close": 3},
                    {"ts_code": "000001.SZ", "trade_date": "20260105", "close": 4},
                ],
                {("000001.SZ", "20260105")},
            )
            rows = read_jsonl(path)
            self.assertTrue(result["written"])
            self.assertEqual(result["target_key_duplicate_count"], 1)
            self.assertEqual(
                {row["ts_code"]: row["close"] for row in rows},
                {"000001.SZ": 4, "600000.SH": 2},
            )

    def test_suspend_row_can_reclassify_listed_open_missing_daily(self) -> None:
        plan = FetchPlan(
            rows=[
                {
                    "security_id": "XSHE.000002",
                    "ts_code": "000002.SZ",
                    "trading_date": "20260105",
                    "universe_id": "u",
                    "time_segment_id": "t",
                }
            ],
            ts_codes=["000002.SZ"],
            trade_dates=["20260105"],
            mode="synthetic",
        )
        outputs = build_candidate_outputs(
            plan,
            {
                "stock_basic": [
                    {
                        "ts_code": "000002.SZ",
                        "list_date": "20000101",
                        "delist_date": "",
                    }
                ],
                "trade_cal": [{"cal_date": "20260105", "is_open": "1"}],
                "daily": [],
                "stk_limit": [],
                "adj_factor": [],
                "stock_st": [],
                "suspend_d": [
                    {
                        "ts_code": "000002.SZ",
                        "suspend_date": "20260105",
                        "suspend_type": "S",
                    }
                ],
                "_metrics": [],
            },
            source_snapshot_id="snapshot",
            artifact_sha256="0" * 64,
        )
        self.assertEqual(
            outputs["source_status"][0]["trading_status"],
            "suspended",
        )
        self.assertEqual(
            outputs["source_status"][0]["daily_applicability"],
            "not_applicable_or_expected_empty",
        )


if __name__ == "__main__":
    unittest.main()
