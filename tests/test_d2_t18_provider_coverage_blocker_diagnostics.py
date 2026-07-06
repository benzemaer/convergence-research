from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.diagnose_d2_provider_coverage_blockers import (
    OUTPUT_FILES,
    D2T18DiagnosticsError,
    guard_input_duckdb_path,
    guard_output_dir,
    run_diagnostics,
)
from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (
    DuckDBStagingWriter,
    compute_quality_gate,
)


class D2T18ProviderCoverageBlockerDiagnosticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name) / "data" / "generated" / "d2"
        self.duckdb_path = (
            self.base
            / "d2_t17_tnskhdata_endpoint_chunk_candidate"
            / "d2_t15_tnskhdata_staging.duckdb"
        )
        self.output_dir = self.base / "d2_t18_provider_coverage_blocker_diagnostics"
        self._build_candidate_duckdb()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _build_candidate_duckdb(self) -> None:
        writer = DuckDBStagingWriter(self.duckdb_path)
        try:
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
                    {
                        "security_id": "CN.SZSE.000003",
                        "ts_code": "000003.SZ",
                        "universe_id": "u",
                        "time_segment_id": "t",
                    },
                ]
            )
            writer.write_trade_calendar(
                [
                    {"cal_date": "20260105", "is_open": "1"},
                    {"cal_date": "20260106", "is_open": "1"},
                    {"cal_date": "20260107", "is_open": "1"},
                ]
            )
            writer.write_stock_basic(
                [
                    {
                        "ts_code": "000001.SZ",
                        "list_date": "20000101",
                        "delist_date": "",
                    },
                    {
                        "ts_code": "000002.SZ",
                        "list_date": "20000101",
                        "delist_date": "",
                    },
                    {
                        "ts_code": "000003.SZ",
                        "list_date": "20000101",
                        "delist_date": "",
                    },
                ]
            )
            writer.write_endpoint_rows(
                "daily",
                [
                    self._daily("000001.SZ", "20260105"),
                    self._daily("000002.SZ", "20260105"),
                    self._daily("000002.SZ", "20260106"),
                    self._daily("000002.SZ", "20260107"),
                    self._daily("000003.SZ", "20260105"),
                    self._daily("000003.SZ", "20260106"),
                    self._daily("000003.SZ", "20260107"),
                ],
            )
            writer.write_endpoint_rows(
                "adj_factor",
                [
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": "20260105",
                        "adj_factor": 1.0,
                    },
                    {
                        "ts_code": "000002.SZ",
                        "trade_date": "20260105",
                        "adj_factor": 1.0,
                    },
                    {
                        "ts_code": "000002.SZ",
                        "trade_date": "20260107",
                        "adj_factor": 1.0,
                    },
                    {
                        "ts_code": "000003.SZ",
                        "trade_date": "20260107",
                        "adj_factor": 1.0,
                    },
                ],
            )
            writer.write_endpoint_rows(
                "stk_limit",
                [
                    self._stk_limit("000001.SZ", "20260105"),
                    self._stk_limit("000003.SZ", "20260105"),
                    self._stk_limit("000003.SZ", "20260106"),
                    self._stk_limit("000003.SZ", "20260107"),
                ],
            )
            compute_quality_gate(writer.conn)
        finally:
            writer.close()

    @staticmethod
    def _daily(ts_code: str, trade_date: str) -> dict[str, object]:
        return {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "vol": 1000.0,
            "amount": 10500.0,
        }

    @staticmethod
    def _stk_limit(ts_code: str, trade_date: str) -> dict[str, object]:
        return {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "up_limit": 11.0,
            "down_limit": 9.0,
        }

    def _run(self) -> dict[str, object]:
        return run_diagnostics(
            duckdb_path=self.duckdb_path,
            output_dir=self.output_dir,
            top_n_securities=50,
            top_n_dates=50,
            sample_rows_per_gap_type=100,
            fail_if_no_gaps=False,
            write_sql=True,
        )

    def _read_csv(self, name: str) -> list[dict[str, str]]:
        with (self.output_dir / name).open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def test_generates_all_declared_outputs_and_summary_flags(self) -> None:
        summary = self._run()

        for file_name in OUTPUT_FILES:
            self.assertTrue((self.output_dir / file_name).exists(), file_name)
        with (self.output_dir / "d2_t18_coverage_blocker_summary.json").open(
            encoding="utf-8"
        ) as handle:
            persisted = json.load(handle)
        self.assertEqual(summary["task_id"], "D2-T18")
        self.assertEqual(
            persisted["d2_acceptance_observed"], "blocked_pending_provider_coverage"
        )
        self.assertFalse(persisted["d3_generation_authorized"])
        self.assertFalse(persisted["r0_state_generated"])
        self.assertFalse(persisted["data_version_published"])

    def test_gap_counts_and_overlap_are_reported(self) -> None:
        self._run()

        counts = {
            row["gap_type"]: int(row["row_count"])
            for row in self._read_csv("d2_t18_gap_counts_by_type.csv")
        }
        self.assertEqual(counts["listed_open_missing_daily"], 2)
        self.assertEqual(counts["daily_dependency_missing"], 2)
        self.assertEqual(counts["stk_limit_missing"], 3)
        self.assertEqual(counts["unresolved_adjustment_factor"], 5)
        summary = json.loads(
            (self.output_dir / "d2_t18_coverage_blocker_summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            summary["daily_missing_implies_price_limit_dependency_count"], 2
        )

    def test_targeted_repairs_do_not_duplicate_daily_dependency_as_stk_limit(
        self,
    ) -> None:
        self._run()

        repairs = self._read_csv("d2_t18_targeted_repair_candidates.csv")
        repair_keys = {
            (
                row["endpoint"],
                row["ts_code"],
                row["start_date"],
                row["end_date"],
                row["reason"],
            )
            for row in repairs
        }
        self.assertIn(
            (
                "daily",
                "000001.SZ",
                "20260106",
                "20260107",
                "listed_open_missing_daily",
            ),
            repair_keys,
        )
        self.assertIn(
            ("stk_limit", "000002.SZ", "20260105", "20260107", "stk_limit_missing"),
            repair_keys,
        )
        self.assertNotIn(
            (
                "stk_limit",
                "000001.SZ",
                "20260106",
                "20260107",
                "daily_dependency_missing",
            ),
            repair_keys,
        )

    def test_adj_factor_gaps_split_policy_and_targeted_repair(self) -> None:
        self._run()

        repairs = self._read_csv("d2_t18_targeted_repair_candidates.csv")
        self.assertIn(
            {
                "endpoint": "adj_factor",
                "ts_code": "000003.SZ",
                "start_date": "20260105",
                "end_date": "20260106",
                "reason": "unresolved_adjustment_factor",
                "gap_row_count": "2",
                "priority": "P2",
            },
            repairs,
        )
        policies = self._read_csv("d2_t18_gap_policy_candidates.csv")
        self.assertTrue(
            any(
                row["gap_type"] == "unresolved_adjustment_factor"
                and row["recommended_action"] == "allow_adj_factor_carry_forward_policy"
                for row in policies
            )
        )

    def test_intervals_compress_by_expected_trading_dates(self) -> None:
        self._run()

        intervals = self._read_csv("d2_t18_missing_daily_intervals.csv")
        self.assertIn(
            {
                "ts_code": "000001.SZ",
                "gap_type": "listed_open_missing_daily",
                "interval_start": "20260106",
                "interval_end": "20260107",
                "interval_length": "2",
            },
            intervals,
        )

    def test_path_guards_reject_forbidden_inputs_and_formal_output(self) -> None:
        for forbidden in (
            Path("data/raw/d2_t15_tnskhdata_staging.duckdb"),
            Path("data/external/d2_t15_tnskhdata_staging.duckdb"),
            Path("MarketDB/d2_t15_tnskhdata_staging.duckdb"),
            Path("SH000001.day"),
        ):
            with self.assertRaises(D2T18DiagnosticsError):
                guard_input_duckdb_path(forbidden)
        with self.assertRaises(D2T18DiagnosticsError):
            guard_output_dir(Path("data/generated/d2/formal.duckdb"))

    def test_read_only_diagnostics_do_not_mutate_acceptance_or_generate_downstream(
        self,
    ) -> None:
        self._run()

        forbidden_outputs = {
            "data_version.json",
            "manifest.json",
            "pcvt_values.csv",
            "labels.csv",
            "backtest.csv",
            "portfolio.csv",
        }
        self.assertFalse(
            any(path.name in forbidden_outputs for path in self.output_dir.iterdir())
        )
        summary = json.loads(
            (self.output_dir / "d2_t18_coverage_blocker_summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            summary["d2_acceptance_observed"], "blocked_pending_provider_coverage"
        )

    def test_readme_records_d2_t18_done_without_unlocking_d3_or_r0(self) -> None:
        readme = Path("docs/tasks/README.md").read_text(encoding="utf-8")

        self.assertIn("current_stage: D2", readme)
        self.assertIn(
            "current_task: D2-T20 fast coverage policy acceptance",
            readme,
        )
        self.assertIn(
            "next_planned_task: D3-T07 candidate generation from "
            "D2-T20 policy candidate",
            readme,
        )
        self.assertIn(
            "D2-T17` 按 endpoint 配置 D2 runner chunk 策略：completed / "
            "runner available after PR #49",
            readme,
        )
        self.assertIn(
            "D2-T18` provider coverage blocker 诊断与最小修复策略："
            "completed / diagnostics available after PR #50",
            readme,
        )
        self.assertIn(
            "D3-T07 remains blocked until D2 coverage blockers are resolved",
            readme,
        )
        self.assertIn("R0 remains blocked until D3 output exists", readme)


if __name__ == "__main__":
    unittest.main()
