from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (
    DuckDBStagingWriter,
    compute_quality_gate,
)
from scripts.run_d2_t19_targeted_provider_repair import (
    CANONICAL_DUCKDB_NAME,
    D2T19RepairError,
    build_repair_plan,
    guard_output_dir,
    guard_source_duckdb,
    run_d2_t19_repair,
)


class FakeProvider:
    def __init__(self, *, daily_mode: str = "primary", fail: bool = False) -> None:
        self.daily_mode = daily_mode
        self.fail = fail
        self.calls: list[tuple[str, dict[str, str]]] = []

    def daily(self, **params: str) -> list[dict[str, object]]:
        self.calls.append(("daily", dict(params)))
        if self.fail:
            raise RuntimeError("provider failure with secret=redacted")
        if (
            self.daily_mode == "primary"
            and "ts_code" in params
            and "start_date" in params
        ):
            return [
                self._daily(params["ts_code"], "20260106"),
                self._daily(params["ts_code"], "20260107"),
            ]
        if self.daily_mode == "fallback" and "trade_date" in params:
            return [
                self._daily("000001.SZ", params["trade_date"]),
                self._daily("999999.SZ", params["trade_date"]),
            ]
        return []

    def stk_limit(self, **params: str) -> list[dict[str, object]]:
        self.calls.append(("stk_limit", dict(params)))
        if self.fail:
            raise RuntimeError("provider failure")
        if "ts_code" in params:
            return []
        if "start_date" in params and "end_date" in params:
            return [
                self._stk_limit("000002.SZ", "20260105"),
                self._stk_limit("000002.SZ", "20260106"),
                self._stk_limit("000002.SZ", "20260107"),
                self._stk_limit("999999.SZ", "20260106"),
            ]
        return []

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


class D2T19TargetedProviderRepairTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name) / "data" / "generated" / "d2"
        self.source_dir = self.base / "d2_t17_tnskhdata_endpoint_chunk_candidate"
        self.source_duckdb = self.source_dir / CANONICAL_DUCKDB_NAME
        self.d2_t18_dir = self.base / "d2_t18_provider_coverage_blocker_diagnostics"
        self.output_dir = self.base / "d2_t19_targeted_repair_candidate"
        self._build_source_duckdb()
        self._write_d2_t18_outputs()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _build_source_duckdb(self) -> None:
        writer = DuckDBStagingWriter(self.source_duckdb)
        try:
            writer.write_security_universe(
                [
                    self._security("000001.SZ"),
                    self._security("000002.SZ"),
                    self._security("000003.SZ"),
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
                    FakeProvider._daily("000001.SZ", "20260105"),
                    FakeProvider._daily("000002.SZ", "20260105"),
                    FakeProvider._daily("000002.SZ", "20260106"),
                    FakeProvider._daily("000002.SZ", "20260107"),
                    FakeProvider._daily("000003.SZ", "20260105"),
                    FakeProvider._daily("000003.SZ", "20260106"),
                    FakeProvider._daily("000003.SZ", "20260107"),
                ],
            )
            writer.write_endpoint_rows(
                "adj_factor",
                [
                    self._adj("000001.SZ", "20260105"),
                    self._adj("000001.SZ", "20260106"),
                    self._adj("000001.SZ", "20260107"),
                    self._adj("000002.SZ", "20260105"),
                    self._adj("000002.SZ", "20260106"),
                    self._adj("000002.SZ", "20260107"),
                ],
            )
            writer.write_endpoint_rows(
                "stk_limit",
                [
                    FakeProvider._stk_limit("000001.SZ", "20260105"),
                    FakeProvider._stk_limit("000003.SZ", "20260105"),
                    FakeProvider._stk_limit("000003.SZ", "20260106"),
                    FakeProvider._stk_limit("000003.SZ", "20260107"),
                ],
            )
            compute_quality_gate(writer.conn)
        finally:
            writer.close()

    @staticmethod
    def _security(ts_code: str) -> dict[str, str]:
        return {
            "security_id": f"CN.{ts_code}",
            "ts_code": ts_code,
            "universe_id": "u",
            "time_segment_id": "t",
        }

    @staticmethod
    def _adj(ts_code: str, trade_date: str) -> dict[str, object]:
        return {"ts_code": ts_code, "trade_date": trade_date, "adj_factor": 1.0}

    def _write_d2_t18_outputs(self) -> None:
        self.d2_t18_dir.mkdir(parents=True, exist_ok=True)
        with (self.d2_t18_dir / "d2_t18_targeted_repair_candidates.csv").open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "endpoint",
                    "ts_code",
                    "start_date",
                    "end_date",
                    "reason",
                    "gap_row_count",
                    "priority",
                ],
            )
            writer.writeheader()
            writer.writerows(
                [
                    {
                        "endpoint": "daily",
                        "ts_code": "000001.SZ",
                        "start_date": "20260106",
                        "end_date": "20260107",
                        "reason": "listed_open_missing_daily",
                        "gap_row_count": "2",
                        "priority": "P0",
                    },
                    {
                        "endpoint": "stk_limit",
                        "ts_code": "000001.SZ",
                        "start_date": "20260106",
                        "end_date": "20260107",
                        "reason": "daily_dependency_missing",
                        "gap_row_count": "2",
                        "priority": "P1",
                    },
                    {
                        "endpoint": "stk_limit",
                        "ts_code": "000002.SZ",
                        "start_date": "20260105",
                        "end_date": "20260107",
                        "reason": "stk_limit_missing",
                        "gap_row_count": "3",
                        "priority": "P1",
                    },
                ]
            )
        with (self.d2_t18_dir / "d2_t18_gap_policy_candidates.csv").open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "gap_type",
                    "ts_code",
                    "recommended_action",
                    "gap_row_count",
                    "policy_reason",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "gap_type": "unresolved_adjustment_factor",
                    "ts_code": "000003.SZ",
                    "recommended_action": "manual_review",
                    "gap_row_count": "3",
                    "policy_reason": "synthetic policy candidate",
                }
            )

    def _read_csv(self, name: str) -> list[dict[str, str]]:
        with (self.output_dir / name).open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def test_dry_run_plan_only_generates_plan_without_provider_call(self) -> None:
        provider = FakeProvider()

        summary = run_d2_t19_repair(
            source_duckdb=self.source_duckdb,
            d2_t18_dir=self.d2_t18_dir,
            output_dir=self.output_dir,
            dry_run_plan=True,
            client=provider,
        )

        self.assertTrue(summary["dry_run_plan"])
        self.assertFalse(summary["remote_provider_called"])
        self.assertEqual(provider.calls, [])
        self.assertFalse((self.output_dir / CANONICAL_DUCKDB_NAME).exists())
        plan = [
            json.loads(line)
            for line in (self.output_dir / "d2_t19_repair_plan.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual([row["endpoint"] for row in plan], ["daily", "stk_limit"])
        self.assertNotIn("daily_dependency_missing", {row["reason"] for row in plan})

    def test_no_remote_fetch_copies_duckdb_and_keeps_source_unmodified(self) -> None:
        before = self._source_daily_count("000001.SZ")

        summary = run_d2_t19_repair(
            source_duckdb=self.source_duckdb,
            d2_t18_dir=self.d2_t18_dir,
            output_dir=self.output_dir,
            no_remote_fetch=True,
        )

        self.assertFalse(summary["remote_provider_called"])
        self.assertTrue((self.output_dir / CANONICAL_DUCKDB_NAME).exists())
        self.assertEqual(self._source_daily_count("000001.SZ"), before)
        acceptance = json.loads(
            (
                self.output_dir / "d2_t19_post_repair_acceptance_candidate_report.json"
            ).read_text(encoding="utf-8")
        )
        self.assertNotEqual(
            acceptance["d2_acceptance_decision"],
            "accepted_for_d3_candidate_generation",
        )

    def test_daily_primary_and_stk_limit_fallback_repair_copy_only(self) -> None:
        provider = FakeProvider(daily_mode="primary")

        summary = run_d2_t19_repair(
            source_duckdb=self.source_duckdb,
            d2_t18_dir=self.d2_t18_dir,
            output_dir=self.output_dir,
            execute_provider_repair=True,
            client=provider,
            retry_backoff_seconds=0,
            sleeper=lambda _seconds: None,
        )

        self.assertTrue(summary["remote_provider_called"])
        self.assertEqual(self._source_daily_count("000001.SZ"), 1)
        conn = duckdb.connect(str(self.output_dir / CANONICAL_DUCKDB_NAME))
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM staging_daily_raw WHERE ts_code='000001.SZ'"
                ).fetchone()[0],
                3,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM staging_stk_limit WHERE ts_code='000002.SZ'"
                ).fetchone()[0],
                3,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM staging_stk_limit WHERE ts_code='999999.SZ'"
                ).fetchone()[0],
                0,
            )
        finally:
            conn.close()
        statuses = {row["status"] for row in self._read_csv_like_jsonl_ledger()}
        self.assertIn("succeeded", statuses)
        self.assertIn("succeeded_after_fallback", statuses)

    def test_daily_trade_date_fallback_filters_non_target_rows(self) -> None:
        provider = FakeProvider(daily_mode="fallback")

        run_d2_t19_repair(
            source_duckdb=self.source_duckdb,
            d2_t18_dir=self.d2_t18_dir,
            output_dir=self.output_dir,
            execute_provider_repair=True,
            client=provider,
            retry_backoff_seconds=0,
            sleeper=lambda _seconds: None,
        )

        self.assertTrue(
            any(
                "trade_date" in params
                for endpoint, params in provider.calls
                if endpoint == "daily"
            )
        )
        conn = duckdb.connect(str(self.output_dir / CANONICAL_DUCKDB_NAME))
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM staging_daily_raw WHERE ts_code='999999.SZ'"
                ).fetchone()[0],
                0,
            )
        finally:
            conn.close()

    def test_repair_delta_and_policy_evidence_are_written_without_adj_factor_write(
        self,
    ) -> None:
        run_d2_t19_repair(
            source_duckdb=self.source_duckdb,
            d2_t18_dir=self.d2_t18_dir,
            output_dir=self.output_dir,
            execute_provider_repair=True,
            client=FakeProvider(),
            retry_backoff_seconds=0,
            sleeper=lambda _seconds: None,
        )

        delta = {
            row["metric"]: int(row["delta"])
            for row in self._read_csv("d2_t19_repaired_gap_delta.csv")
        }
        self.assertEqual(delta["listed_open_missing_daily_count"], -2)
        self.assertEqual(delta["price_limit_daily_dependency_missing_count"], -2)
        self.assertLess(delta["unresolved_price_limit_status_count"], 0)
        evidence = self._read_csv("d2_t19_policy_evidence.csv")
        self.assertEqual(evidence[0]["ts_code"], "000003.SZ")
        self.assertIn(
            evidence[0]["recommended_policy"],
            {
                "neutral_factor_1_policy_candidate",
                "carry_forward_policy_candidate",
                "manual_review_required",
                "keep_blocked",
            },
        )
        conn = duckdb.connect(str(self.output_dir / CANONICAL_DUCKDB_NAME))
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM staging_adj_factor WHERE ts_code='000003.SZ'"
                ).fetchone()[0],
                0,
            )
        finally:
            conn.close()

    def test_provider_failure_does_not_make_acceptance_accepted(self) -> None:
        run_d2_t19_repair(
            source_duckdb=self.source_duckdb,
            d2_t18_dir=self.d2_t18_dir,
            output_dir=self.output_dir,
            execute_provider_repair=True,
            client=FakeProvider(fail=True),
            retry_max_attempts=1,
            retry_backoff_seconds=0,
            sleeper=lambda _seconds: None,
        )

        acceptance = json.loads(
            (
                self.output_dir / "d2_t19_post_repair_acceptance_candidate_report.json"
            ).read_text(encoding="utf-8")
        )
        self.assertNotEqual(
            acceptance["d2_acceptance_decision"],
            "accepted_for_d3_candidate_generation",
        )
        summary = json.loads(
            (self.output_dir / "d2_t19_repair_run_summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(summary["d3_generation_authorized"])
        self.assertFalse(summary["r0_state_generated"])
        self.assertFalse(summary["pcvt_values_generated"])

    def test_forbidden_outputs_are_not_generated(self) -> None:
        run_d2_t19_repair(
            source_duckdb=self.source_duckdb,
            d2_t18_dir=self.d2_t18_dir,
            output_dir=self.output_dir,
            no_remote_fetch=True,
        )

        forbidden = {
            "data_version.json",
            "manifest.json",
            "pcvt_values.csv",
            "labels.csv",
            "returns.csv",
            "backtest.csv",
            "portfolio.csv",
        }
        self.assertFalse(
            any(path.name in forbidden for path in self.output_dir.iterdir())
        )

    def test_path_guards_reject_forbidden_paths(self) -> None:
        for path in (
            Path("data/raw/d2_t15_tnskhdata_staging.duckdb"),
            Path("data/external/d2_t15_tnskhdata_staging.duckdb"),
            Path("MarketDB/d2_t15_tnskhdata_staging.duckdb"),
            Path("SH000001.day"),
        ):
            with self.assertRaises(D2T19RepairError):
                guard_source_duckdb(path)
        with self.assertRaises(D2T19RepairError):
            guard_output_dir(Path("data/generated/d2/formal.duckdb"))

    def test_build_repair_plan_param_strategies(self) -> None:
        plan = build_repair_plan(self.d2_t18_dir)
        strategies = {task.endpoint: task.param_strategy for task in plan}
        self.assertEqual(
            strategies["daily"],
            "primary_ts_code_start_end_then_trade_date_fallback",
        )
        self.assertEqual(
            strategies["stk_limit"],
            "primary_ts_code_start_end_then_date_range_fallback_filtered_to_ts_code",
        )

    def test_readme_advances_to_d2_t19_without_unlocking_d3_or_r0(self) -> None:
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
            "D2-T18` provider coverage blocker 诊断与最小修复策略："
            "completed / diagnostics available after PR #50",
            readme,
        )
        self.assertIn(
            "D3-T07 remains blocked until D2 coverage blockers are resolved",
            readme,
        )
        self.assertIn("R0 remains blocked until D3 output exists", readme)

    def _source_daily_count(self, ts_code: str) -> int:
        conn = duckdb.connect(str(self.source_duckdb))
        try:
            return int(
                conn.execute(
                    "SELECT count(*) FROM staging_daily_raw WHERE ts_code = ?",
                    [ts_code],
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def _read_csv_like_jsonl_ledger(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in (self.output_dir / "d2_t19_repair_ledger.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    unittest.main()
