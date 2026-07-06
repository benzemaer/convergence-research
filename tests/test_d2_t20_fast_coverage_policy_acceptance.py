from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb

from scripts.apply_d2_t20_fast_coverage_policy import (
    CANONICAL_DUCKDB_NAME,
    D2T20PolicyError,
    apply_d2_t20_policy,
    guard_output_dir,
    guard_source_duckdb,
    load_policy_evidence_manifest,
)
from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (
    DuckDBStagingWriter,
    compute_quality_gate,
)


class D2T20FastCoveragePolicyAcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name) / "data" / "generated" / "d2"
        self.source_dir = (
            self.base / "d2_t19_targeted_repair_candidate_r2_token_refresh"
        )
        self.source_duckdb = self.source_dir / CANONICAL_DUCKDB_NAME
        self.output_dir = self.base / "d2_t20_fast_coverage_policy_candidate"
        self.manifest_path = Path("configs/d2/d2_t20_policy_evidence_manifest.v1.json")
        self._build_source_duckdb()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _build_source_duckdb(self) -> None:
        writer = DuckDBStagingWriter(self.source_duckdb)
        try:
            writer.write_security_universe(
                [
                    self._security("000155.SZ"),
                    self._security("688981.SH"),
                    self._security("689009.SH"),
                ]
            )
            writer.write_trade_calendar(
                [
                    {"cal_date": "20160510", "is_open": "1"},
                    {"cal_date": "20160511", "is_open": "1"},
                    {"cal_date": "20200102", "is_open": "1"},
                    {"cal_date": "20200103", "is_open": "1"},
                    {"cal_date": "20201029", "is_open": "1"},
                    {"cal_date": "20201030", "is_open": "1"},
                ]
            )
            writer.write_stock_basic(
                [
                    {
                        "ts_code": "000155.SZ",
                        "list_date": "20000101",
                        "delist_date": "20171217",
                    },
                    {
                        "ts_code": "688981.SH",
                        "list_date": "20200101",
                        "delist_date": "",
                    },
                    {
                        "ts_code": "689009.SH",
                        "list_date": "20201029",
                        "delist_date": "",
                    },
                ]
            )
            writer.write_endpoint_rows(
                "daily",
                [
                    self._daily("688981.SH", "20200102"),
                    self._daily("688981.SH", "20200103"),
                    self._daily("688981.SH", "20201029"),
                    self._daily("688981.SH", "20201030"),
                    self._daily("689009.SH", "20201029"),
                    self._daily("689009.SH", "20201030"),
                ],
            )
            writer.write_endpoint_rows(
                "adj_factor",
                [
                    self._adj("000155.SZ", "20160510"),
                    self._adj("000155.SZ", "20160511"),
                ],
            )
            writer.write_endpoint_rows(
                "stk_limit",
                [
                    self._stk_limit("688981.SH", "20200102"),
                    self._stk_limit("688981.SH", "20200103"),
                    self._stk_limit("688981.SH", "20201029"),
                    self._stk_limit("688981.SH", "20201030"),
                    self._stk_limit("689009.SH", "20201029"),
                    self._stk_limit("689009.SH", "20201030"),
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
    def _adj(ts_code: str, trade_date: str) -> dict[str, object]:
        return {"ts_code": ts_code, "trade_date": trade_date, "adj_factor": 1.0}

    @staticmethod
    def _stk_limit(ts_code: str, trade_date: str) -> dict[str, object]:
        return {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "up_limit": 11.0,
            "down_limit": 9.0,
        }

    def _run_authorized(self) -> dict[str, object]:
        return apply_d2_t20_policy(
            source_duckdb=self.source_duckdb,
            output_dir=self.output_dir,
            allow_user_attested_listing_pause=True,
            allow_neutral_adj_factor_policy=True,
            authorize_d3_candidate=True,
        )

    def _run_authorized_with_evidence(
        self,
        *,
        output_dir: Path | None = None,
        allow_pending_hash: bool = False,
        manifest_path: Path | None = None,
    ) -> dict[str, object]:
        return apply_d2_t20_policy(
            source_duckdb=self.source_duckdb,
            output_dir=output_dir or self.output_dir,
            allow_user_attested_listing_pause=True,
            allow_neutral_adj_factor_policy=True,
            authorize_d3_candidate=True,
            policy_evidence_manifest=manifest_path or self.manifest_path,
            require_policy_evidence=True,
            allow_pending_evidence_hash=allow_pending_hash,
        )

    def _source_daily_count(self) -> int:
        conn = duckdb.connect(str(self.source_duckdb))
        try:
            return int(
                conn.execute("SELECT count(*) FROM staging_daily_raw").fetchone()[0]
            )
        finally:
            conn.close()

    def _target_daily_count(self) -> int:
        conn = duckdb.connect(str(self.output_dir / CANONICAL_DUCKDB_NAME))
        try:
            return int(
                conn.execute("SELECT count(*) FROM staging_daily_raw").fetchone()[0]
            )
        finally:
            conn.close()

    def _read_csv(self, name: str) -> list[dict[str, str]]:
        with (self.output_dir / name).open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def _read_jsonl(self, name: str) -> list[dict[str, object]]:
        with (self.output_dir / name).open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_source_duckdb_is_copied_and_source_is_not_modified(self) -> None:
        before_daily = self._source_daily_count()

        self._run_authorized()

        self.assertTrue((self.output_dir / CANONICAL_DUCKDB_NAME).exists())
        self.assertEqual(self._source_daily_count(), before_daily)
        self.assertEqual(self._target_daily_count(), before_daily)

    def test_listing_pause_policy_clears_missing_daily_and_dependency(self) -> None:
        self._run_authorized()

        conn = duckdb.connect(str(self.output_dir / CANONICAL_DUCKDB_NAME))
        try:
            pause_rows = conn.execute(
                "SELECT ts_code, policy_type, evidence_level "
                "FROM d2_policy_listing_pause_intervals "
                "WHERE ts_code='000155.SZ'"
            ).fetchall()
            self.assertEqual(
                pause_rows, [("000155.SZ", "listing_pause", "user_attested")]
            )
            statuses = conn.execute(
                """
                SELECT DISTINCT trading_status, daily_status, price_limit_status
                FROM d2_source_status
                WHERE ts_code = '000155.SZ'
                ORDER BY 1, 2, 3
                """
            ).fetchall()
            self.assertEqual(
                statuses,
                [
                    (
                        "listing_pause",
                        "not_applicable_or_expected_empty",
                        "not_applicable_or_expected_empty",
                    )
                ],
            )
        finally:
            conn.close()
        quality = json.loads(
            (self.output_dir / "d2_t20_post_policy_quality_report.json").read_text(
                encoding="utf-8"
            )
        )["quality"]
        self.assertEqual(quality["listed_open_missing_daily_count"], 0)
        self.assertEqual(quality["price_limit_daily_dependency_missing_count"], 0)

    def test_neutral_factor_policy_clears_adjustment_factor_without_provider_rows(
        self,
    ) -> None:
        self._run_authorized()

        conn = duckdb.connect(str(self.output_dir / CANONICAL_DUCKDB_NAME))
        try:
            policy_rows = conn.execute(
                "SELECT ts_code, policy_type, policy_factor, evidence_level "
                "FROM d2_policy_adj_factor_overrides "
                "WHERE ts_code IN ('688981.SH', '689009.SH') "
                "ORDER BY ts_code"
            ).fetchall()
            self.assertEqual(
                policy_rows,
                [
                    (
                        "688981.SH",
                        "neutral_factor_1",
                        1.0,
                        "tnskhdata_adj_factor_hash_verified",
                    ),
                    (
                        "689009.SH",
                        "neutral_factor_1",
                        1.0,
                        "tnskhdata_adj_factor_hash_verified",
                    ),
                ],
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM staging_adj_factor WHERE ts_code='688981.SH'"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM staging_adj_factor WHERE ts_code='689009.SH'"
                ).fetchone()[0],
                0,
            )
        finally:
            conn.close()
        quality = json.loads(
            (self.output_dir / "d2_t20_post_policy_quality_report.json").read_text(
                encoding="utf-8"
            )
        )["quality"]
        self.assertEqual(quality["unresolved_adjustment_factor_count"], 0)

    def test_missing_explicit_authorization_does_not_accept(self) -> None:
        apply_d2_t20_policy(
            source_duckdb=self.source_duckdb,
            output_dir=self.output_dir,
            allow_user_attested_listing_pause=True,
            allow_neutral_adj_factor_policy=True,
            authorize_d3_candidate=False,
        )

        acceptance = json.loads(
            (self.output_dir / "d2_t20_acceptance_candidate_report.json").read_text(
                encoding="utf-8"
            )
        )
        handoff = json.loads(
            (self.output_dir / "d2_t20_handoff_candidate_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotEqual(
            acceptance["d2_acceptance_decision"],
            "accepted_for_d3_candidate_generation",
        )
        self.assertFalse(handoff["d3_generation_authorized"])

    def test_authorized_policy_can_accept_and_authorize_d3_without_r0(self) -> None:
        summary = self._run_authorized()

        acceptance = json.loads(
            (self.output_dir / "d2_t20_acceptance_candidate_report.json").read_text(
                encoding="utf-8"
            )
        )
        handoff = json.loads(
            (self.output_dir / "d2_t20_handoff_candidate_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            acceptance["d2_acceptance_decision"],
            "accepted_for_d3_candidate_generation",
        )
        self.assertTrue(acceptance["policy_based_acceptance"])
        self.assertTrue(handoff["d3_generation_authorized"])
        self.assertEqual(
            handoff["d3_handoff_decision"], "d3_candidate_generation_authorized"
        )
        self.assertFalse(handoff["r0_state_generated"])
        self.assertTrue(summary["d3_generation_authorized"])

    def test_delta_reports_blockers_zero_and_daily_rows_unchanged(self) -> None:
        self._run_authorized()

        delta = {row["metric"]: row for row in self._read_csv("d2_t20_gap_delta.csv")}
        self.assertEqual(delta["listed_open_missing_daily_count"]["after_count"], "0")
        self.assertEqual(
            delta["price_limit_daily_dependency_missing_count"]["after_count"], "0"
        )
        self.assertEqual(
            delta["unresolved_price_limit_status_count"]["after_count"], "0"
        )
        self.assertEqual(
            delta["unresolved_adjustment_factor_count"]["after_count"], "0"
        )
        self.assertEqual(delta["daily_raw_row_count"]["delta"], "0")
        remaining = self._read_csv("d2_t20_remaining_coverage_gaps.csv")
        self.assertEqual(remaining, [])

    def test_forbidden_outputs_are_not_generated(self) -> None:
        self._run_authorized()

        forbidden = {
            "data_version.json",
            "manifest.json",
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
            with self.assertRaises(D2T20PolicyError):
                guard_source_duckdb(path)
        with self.assertRaises(D2T20PolicyError):
            guard_output_dir(Path("data/generated/d2/formal.duckdb"))

    def test_risk_register_and_handoff_notes_are_written(self) -> None:
        self._run_authorized()

        risk = (self.output_dir / "d2_t20_policy_risk_register.md").read_text(
            encoding="utf-8"
        )
        notes = (self.output_dir / "d2_t20_d3_handoff_notes.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("manifest absent", risk)
        self.assertIn("neutral_factor_1", risk)
        self.assertIn("listing_pause", notes)
        self.assertIn("policy rows", notes)
        self.assertIn("policy_evidence_status", notes)
        self.assertIn("neutral factor policy flags", notes)

    def test_policy_evidence_manifest_is_readable(self) -> None:
        manifest = load_policy_evidence_manifest(self.manifest_path)

        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertEqual(manifest["task_id"], "D2-T20")
        self.assertEqual(manifest["manifest_id"], "d2_t20_policy_evidence_manifest.v1")
        for row in manifest["listing_pause_intervals"]:
            self.assertIn("ts_code", row)
            self.assertIn("start_date", row)
            self.assertIn("end_date", row)
            roles = {
                document["document_role"] for document in row["evidence_documents"]
            }
            self.assertEqual(
                roles,
                {"pause_listing_announcement", "resume_listing_announcement"},
            )
            for document in row["evidence_documents"]:
                for key in (
                    "source",
                    "title",
                    "announcement_date",
                    "url",
                    "sha256",
                    "evidence_status",
                ):
                    self.assertIn(key, document)
                self.assertEqual(document["evidence_status"], "hash_verified")
                self.assertTrue(document["sha256"])
        self.assertEqual(
            {row["ts_code"] for row in manifest["adj_factor_policy_evidence"]},
            {"688981.SH", "689009.SH"},
        )
        self.assertTrue(
            all(
                row["expected_d2_t18_policy_candidate"]
                for row in manifest["adj_factor_policy_evidence"]
            )
        )
        self.assertNotIn("supplementary" + "_factor_observations", manifest)

    def test_listing_pause_evidence_documents_are_written(self) -> None:
        self._run_authorized_with_evidence()

        conn = duckdb.connect(str(self.output_dir / CANONICAL_DUCKDB_NAME))
        try:
            rows = conn.execute(
                """
                SELECT ts_code, document_role, evidence_status
                FROM d2_policy_evidence_documents
                WHERE ts_code = '000155.SZ'
                ORDER BY document_role
                """
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(
            rows,
            [
                ("000155.SZ", "pause_listing_announcement", "hash_verified"),
                ("000155.SZ", "resume_listing_announcement", "hash_verified"),
            ],
        )

    def test_required_policy_evidence_without_pending_hash_blocks_acceptance(
        self,
    ) -> None:
        manifest = load_policy_evidence_manifest(self.manifest_path)
        assert manifest is not None
        manifest["listing_pause_intervals"][0]["evidence_documents"][0]["sha256"] = ""
        manifest["listing_pause_intervals"][0]["evidence_documents"][0][
            "evidence_status"
        ] = "missing_hash"
        missing_hash_path = self.base / "missing_hash_manifest.json"
        missing_hash_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        self._run_authorized_with_evidence(manifest_path=missing_hash_path)

        acceptance = json.loads(
            (self.output_dir / "d2_t20_acceptance_candidate_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            acceptance["d2_acceptance_decision"], "blocked_pending_policy_evidence"
        )
        self.assertFalse(acceptance["policy_based_acceptance"])
        self.assertTrue(acceptance["policy_evidence_pending_hash"])
        self.assertEqual(
            acceptance["policy_evidence_blocker"], "d2_t20_policy_evidence_missing_hash"
        )
        self.assertIn(
            "d2_t20_policy_evidence_missing_hash",
            acceptance["quality_blockers"],
        )

    def test_completed_policy_evidence_accepts_without_pending_hash_flag(self) -> None:
        summary = self._run_authorized_with_evidence()

        acceptance = json.loads(
            (self.output_dir / "d2_t20_acceptance_candidate_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            acceptance["d2_acceptance_decision"],
            "accepted_for_d3_candidate_generation",
        )
        self.assertTrue(acceptance["policy_based_acceptance"])
        self.assertFalse(acceptance["policy_evidence_pending_hash"])
        self.assertEqual(
            acceptance["policy_evidence_level"],
            "official_or_mirror_hash_verified_and_tnskhdata_adj_factor_verified",
        )
        self.assertTrue(summary["policy_evidence_gate_passed"])

    def test_adj_factor_policy_evidence_target_mismatch_blocks(self) -> None:
        manifest = load_policy_evidence_manifest(self.manifest_path)
        assert manifest is not None
        manifest["adj_factor_policy_evidence"] = [
            row
            for row in manifest["adj_factor_policy_evidence"]
            if row["ts_code"] != "688981.SH"
        ]
        mismatch_path = self.base / "mismatch_manifest.json"
        mismatch_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        self._run_authorized_with_evidence(
            output_dir=self.base / "d2_t20_mismatch",
            manifest_path=mismatch_path,
        )

        acceptance = json.loads(
            (
                self.base
                / "d2_t20_mismatch"
                / "d2_t20_acceptance_candidate_report.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            acceptance["d2_acceptance_decision"], "blocked_pending_policy_evidence"
        )
        self.assertEqual(
            acceptance["policy_evidence_blocker"],
            "d2_t20_policy_evidence_target_mismatch",
        )

    def test_factor_interval_evidence_does_not_create_provider_adj_factor_row(
        self,
    ) -> None:
        self._run_authorized_with_evidence()

        conn = duckdb.connect(str(self.output_dir / CANONICAL_DUCKDB_NAME))
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM staging_adj_factor WHERE ts_code='689009.SH'"
                ).fetchone()[0],
                0,
            )
            rows = conn.execute(
                """
                SELECT ts_code, min(effective_adj_factor), max(effective_adj_factor),
                       count(*), min(evidence_status)
                FROM d2_policy_corporate_action_evidence
                WHERE ts_code = '689009.SH'
                GROUP BY ts_code
                """
            ).fetchall()
            policy_rows = conn.execute(
                """
                SELECT policy_type, policy_factor
                FROM d2_policy_adj_factor_overrides
                WHERE ts_code = '689009.SH'
                """
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [("689009.SH", 1.0, 1.0332, 5, "hash_verified")])
        self.assertEqual(policy_rows, [("factor_interval", None)])

    def test_policy_plan_and_ledger_match_manifest_recommended_policies(self) -> None:
        self._run_authorized_with_evidence()

        plan = json.loads(
            (self.output_dir / "d2_t20_policy_plan.json").read_text(encoding="utf-8")
        )
        targets = {row["ts_code"]: row for row in plan["adj_factor_policy_targets"]}
        self.assertNotIn("neutral_adj_factor_overrides", plan)
        self.assertEqual(
            targets["688981.SH"]["recommended_policy"],
            "neutral_factor_1_policy_candidate",
        )
        self.assertEqual(targets["688981.SH"]["policy_type"], "neutral_factor_1")
        self.assertEqual(
            targets["689009.SH"]["recommended_policy"],
            "factor_interval_policy_candidate",
        )
        self.assertEqual(targets["689009.SH"]["policy_type"], "factor_interval")
        self.assertEqual(targets["689009.SH"]["factor_interval_count"], 5)

        ledger = {
            row["ts_code"]: row
            for row in self._read_jsonl("d2_t20_policy_ledger.jsonl")
            if row["policy_kind"] == "adj_factor_policy"
        }
        self.assertEqual(ledger["688981.SH"]["policy_type"], "neutral_factor_1")
        self.assertEqual(ledger["689009.SH"]["policy_kind"], "adj_factor_policy")
        self.assertEqual(ledger["689009.SH"]["policy_type"], "factor_interval")

    def test_repo_tracked_files_do_not_contain_removed_mistyped_target_terms(
        self,
    ) -> None:
        for term in ("688" + "728.SH", "\u683c\u79d1\u5fae"):
            result = subprocess.run(
                ["git", "grep", "-n", term, "--", "."],
                check=False,
                cwd=Path.cwd(),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stdout)

    def test_readme_advances_to_d2_t20_and_keeps_r0_blocked(self) -> None:
        readme = Path("docs/tasks/README.md").read_text(encoding="utf-8")

        self.assertIn("current_stage: D2", readme)
        self.assertIn("current_task: D2-T20 fast coverage policy acceptance", readme)
        self.assertIn(
            "next_planned_task: D3-T07 candidate generation from "
            "D2-T20 policy candidate",
            readme,
        )
        self.assertIn(
            "D2-T19` targeted repair and coverage policy evidence：completed / "
            "stk_limit targeted repair succeeded; daily repair empty due to "
            "listing pause",
            readme,
        )
        self.assertIn(
            "D3-T07 remains blocked until D2 coverage blockers are resolved",
            readme,
        )
        self.assertIn("R0 remains blocked until D3 output exists", readme)

    def test_cli_help_runs_from_repo_root(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/apply_d2_t20_fast_coverage_policy.py",
                "--help",
            ],
            check=False,
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--source-duckdb", result.stdout)
        self.assertIn("--authorize-d3-candidate", result.stdout)


if __name__ == "__main__":
    unittest.main()
