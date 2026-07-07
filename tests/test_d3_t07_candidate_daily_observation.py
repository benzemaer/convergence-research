from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb
from jsonschema import Draft202012Validator

from scripts.generate_d3_t07_candidate_daily_observation import (
    OBSERVATION_TABLE,
    OUTPUT_DUCKDB_NAME,
    d2_t20_candidate_materialization_gate,
    generate_d3_t07_candidate_daily_observation,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d3/d3_t07_candidate_daily_observation_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d3_t07_candidate_daily_observation_contract.schema.json"


class D3T07CandidateDailyObservationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        self.d2_dir = self.base / "data" / "generated" / "d2" / "d2_t20"
        self.d3_dir = (
            self.base
            / "data"
            / "generated"
            / "d3"
            / "d3_t07_candidate_daily_observation"
        )
        self.source_duckdb = self.d2_dir / "d2_t15_tnskhdata_staging.duckdb"
        self.acceptance_report = self.d2_dir / "d2_t20_acceptance_candidate_report.json"
        self.handoff_report = self.d2_dir / "d2_t20_handoff_candidate_report.json"
        self._build_source_duckdb()
        self._write_reports(accepted=True)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _build_source_duckdb(
        self,
        *,
        factor_interval: bool = True,
        duplicate_daily: bool = False,
        invalid_ohlc: bool = False,
        missing_factor: bool = False,
    ) -> None:
        self.source_duckdb.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(self.source_duckdb))
        try:
            conn.execute(
                """
                CREATE TABLE staging_daily_raw (
                  ts_code TEXT,
                  trade_date TEXT,
                  open DOUBLE,
                  high DOUBLE,
                  low DOUBLE,
                  close DOUBLE,
                  vol DOUBLE,
                  amount DOUBLE
                );
                CREATE TABLE d2_source_status (
                  ts_code TEXT,
                  trade_date TEXT,
                  trading_status TEXT,
                  daily_status TEXT,
                  price_limit_status TEXT
                );
                CREATE TABLE d2_factor_evidence (
                  ts_code TEXT,
                  trade_date TEXT,
                  adjustment_factor_status TEXT
                );
                CREATE TABLE staging_stk_limit (
                  ts_code TEXT,
                  trade_date TEXT,
                  up_limit DOUBLE,
                  down_limit DOUBLE
                );
                CREATE TABLE staging_adj_factor (
                  ts_code TEXT,
                  trade_date TEXT,
                  adj_factor DOUBLE
                );
                CREATE TABLE d2_policy_listing_pause_intervals (
                  ts_code TEXT,
                  start_date TEXT,
                  end_date TEXT,
                  policy_type TEXT,
                  evidence_level TEXT,
                  evidence_note TEXT,
                  applied_by_task TEXT
                );
                CREATE TABLE d2_policy_adj_factor_overrides (
                  ts_code TEXT,
                  start_date TEXT,
                  end_date TEXT,
                  policy_type TEXT,
                  policy_factor DOUBLE,
                  evidence_level TEXT,
                  evidence_note TEXT,
                  applied_by_task TEXT
                );
                CREATE TABLE d2_policy_corporate_action_evidence (
                  ts_code TEXT,
                  company_name TEXT,
                  policy_type TEXT,
                  start_date TEXT,
                  end_date TEXT,
                  effective_adj_factor DOUBLE,
                  evidence_level TEXT,
                  evidence_status TEXT,
                  source TEXT,
                  sha256 TEXT,
                  note TEXT,
                  applied_by_task TEXT
                );
                CREATE TABLE d2_policy_evidence_documents (
                  evidence_id TEXT,
                  policy_kind TEXT,
                  ts_code TEXT,
                  document_role TEXT,
                  source TEXT,
                  title TEXT,
                  announcement_date TEXT,
                  url TEXT,
                  sha256 TEXT,
                  evidence_status TEXT,
                  note TEXT,
                  applied_by_task TEXT
                );
                """
            )
            daily_rows = [
                ("AAA.SZ", "20200102", 10.0, 11.0, 9.0, 10.5, 100.0, 1050.0),
                ("BBB.SH", "20200102", 20.0, 22.0, 19.0, 21.0, 200.0, 4200.0),
                ("CCC.SH", "20200102", 30.0, 33.0, 28.0, 32.0, 300.0, 9600.0),
                ("PAU.SZ", "20200102", 5.0, 5.5, 4.5, 5.0, 50.0, 250.0),
            ]
            if duplicate_daily:
                daily_rows.append(daily_rows[0])
            if invalid_ohlc:
                daily_rows.append(("BAD.SZ", "20200102", None, 1.0, 1.0, 1.0, 1.0, 1.0))
            if missing_factor:
                daily_rows.append(
                    ("MISS.SZ", "20200102", 15.0, 16.0, 14.0, 15.5, 150.0, 2325.0)
                )
            conn.executemany(
                "INSERT INTO staging_daily_raw VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                daily_rows,
            )
            source_status_rows = [
                (
                    "AAA.SZ",
                    "20200102",
                    "listed_open_resolved_daily",
                    "resolved",
                    "resolved",
                ),
                (
                    "BBB.SH",
                    "20200102",
                    "listed_open_resolved_daily",
                    "resolved",
                    "resolved",
                ),
                (
                    "CCC.SH",
                    "20200102",
                    "listed_open_resolved_daily",
                    "resolved",
                    "resolved",
                ),
                (
                    "PAU.SZ",
                    "20200102",
                    "listing_pause",
                    "not_applicable_or_expected_empty",
                    "not_applicable_or_expected_empty",
                ),
            ]
            if invalid_ohlc:
                source_status_rows.append(
                    (
                        "BAD.SZ",
                        "20200102",
                        "listed_open_resolved_daily",
                        "resolved",
                        "resolved",
                    )
                )
            if missing_factor:
                source_status_rows.append(
                    (
                        "MISS.SZ",
                        "20200102",
                        "listed_open_resolved_daily",
                        "resolved",
                        "resolved",
                    )
                )
            conn.executemany(
                "INSERT INTO d2_source_status VALUES (?, ?, ?, ?, ?)",
                source_status_rows,
            )
            factor_rows = [
                ("AAA.SZ", "20200102", "resolved"),
                ("BBB.SH", "20200102", "neutral_factor_1_policy"),
                ("CCC.SH", "20200102", "factor_interval_policy"),
                ("PAU.SZ", "20200102", "missing"),
            ]
            if invalid_ohlc:
                factor_rows.append(("BAD.SZ", "20200102", "resolved"))
            if missing_factor:
                factor_rows.append(("MISS.SZ", "20200102", "missing"))
            conn.executemany(
                "INSERT INTO d2_factor_evidence VALUES (?, ?, ?)",
                factor_rows,
            )
            conn.execute(
                "INSERT INTO staging_adj_factor VALUES ('AAA.SZ', '20200102', 2.0)"
            )
            if invalid_ohlc:
                conn.execute(
                    "INSERT INTO staging_adj_factor VALUES ('BAD.SZ', '20200102', 1.0)"
                )
            conn.executemany(
                "INSERT INTO staging_stk_limit VALUES (?, ?, ?, ?)",
                [
                    ("AAA.SZ", "20200102", 11.0, 9.0),
                    ("BBB.SH", "20200102", 22.0, 19.0),
                    ("CCC.SH", "20200102", 33.0, 28.0),
                ],
            )
            conn.executemany(
                "INSERT INTO d2_policy_adj_factor_overrides "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        "BBB.SH",
                        "20200102",
                        "20200102",
                        "neutral_factor_1",
                        1.0,
                        "tnskhdata_adj_factor_hash_verified",
                        "neutral policy",
                        "D2-T20",
                    ),
                    (
                        "CCC.SH",
                        "20200102",
                        "20200102",
                        "factor_interval",
                        None,
                        "tnskhdata_adj_factor_hash_verified",
                        "interval policy",
                        "D2-T20",
                    ),
                ],
            )
            if factor_interval:
                conn.execute(
                    """
                    INSERT INTO d2_policy_corporate_action_evidence
                    VALUES (
                      'CCC.SH',
                      'Synthetic',
                      'factor_interval',
                      '20200101',
                      '20200103',
                      1.5,
                      'tnskhdata_adj_factor_hash_verified',
                      'hash_verified',
                      'tnskhdata.adj_factor',
                      'abc',
                      'synthetic interval',
                      'D2-T20'
                    )
                    """
                )
        finally:
            conn.close()

    def _write_reports(
        self, *, accepted: bool, policy_evidence_pending_hash: bool = False
    ) -> None:
        self.d2_dir.mkdir(parents=True, exist_ok=True)
        acceptance = {
            "d2_acceptance_decision": (
                "accepted_for_d3_candidate_generation"
                if accepted
                else "blocked_pending_policy_evidence"
            ),
            "policy_based_acceptance": accepted,
            "policy_evidence_pending_hash": policy_evidence_pending_hash,
            "formal_duckdb_write_authorized": False,
            "data_version_published": False,
            "d3_rows_generated": False,
            "r0_state_generated": False,
        }
        handoff = {
            "d3_generation_authorized": accepted,
            "data_version_published": False,
            "d3_rows_generated": False,
            "r0_state_generated": False,
        }
        self.acceptance_report.write_text(json.dumps(acceptance), encoding="utf-8")
        self.handoff_report.write_text(json.dumps(handoff), encoding="utf-8")

    def _run_generator(self) -> dict[str, object]:
        return generate_d3_t07_candidate_daily_observation(
            d2_t20_duckdb=self.source_duckdb,
            d2_t20_acceptance_report=self.acceptance_report,
            d2_t20_handoff_report=self.handoff_report,
            output_dir=self.d3_dir,
        )

    def _output_conn(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.d3_dir / OUTPUT_DUCKDB_NAME), read_only=True)

    def _observation_count(self) -> int:
        conn = self._output_conn()
        try:
            return int(
                conn.execute(f"SELECT count(*) FROM {OBSERVATION_TABLE}").fetchone()[0]
            )
        finally:
            conn.close()

    def _handoff_report(self) -> dict[str, object]:
        return json.loads(
            (self.d3_dir / "d3_t07_handoff_candidate_report.json").read_text(
                encoding="utf-8"
            )
        )

    def test_contract_json_passes_schema(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(contract)

    def test_d2_t20_gate_blocks_generation(self) -> None:
        self._write_reports(accepted=False)

        summary = self._run_generator()

        self.assertEqual(
            summary["d3_t07_generation_decision"], "blocked_pending_d2_t20_handoff"
        )
        self.assertFalse(summary["d3_rows_generated"])

    def test_policy_evidence_pending_hash_is_soft_warning(self) -> None:
        acceptance = {
            "d2_acceptance_decision": "accepted_for_d3_candidate_generation",
            "policy_based_acceptance": True,
            "policy_evidence_pending_hash": True,
            "formal_duckdb_write_authorized": False,
            "data_version_published": False,
            "d3_rows_generated": False,
            "r0_state_generated": False,
        }
        handoff = {
            "d3_generation_authorized": True,
            "data_version_published": False,
            "d3_rows_generated": False,
            "r0_state_generated": False,
        }

        hard_gate_passed, hard_reasons, soft_reasons = (
            d2_t20_candidate_materialization_gate(acceptance, handoff)
        )

        self.assertTrue(hard_gate_passed)
        self.assertEqual(hard_reasons, [])
        self.assertIn("policy_evidence_pending_hash", soft_reasons)

    def test_missing_policy_pending_key_with_candidate_evidence_is_soft_warning(
        self,
    ) -> None:
        acceptance = {
            "d2_acceptance_decision": "accepted_for_d3_candidate_generation",
            "policy_based_acceptance": True,
            "policy_evidence_level": "user_attested_and_policy_candidate",
            "formal_duckdb_write_authorized": False,
            "data_version_published": False,
            "d3_rows_generated": False,
            "r0_state_generated": False,
        }
        handoff = {
            "d3_generation_authorized": True,
            "data_version_published": False,
            "d3_rows_generated": False,
            "r0_state_generated": False,
        }

        hard_gate_passed, hard_reasons, soft_reasons = (
            d2_t20_candidate_materialization_gate(acceptance, handoff)
        )

        self.assertTrue(hard_gate_passed)
        self.assertEqual(hard_reasons, [])
        self.assertEqual(soft_reasons, ["policy_evidence_pending_hash"])

    def test_policy_evidence_pending_hash_generates_candidate_with_warnings(
        self,
    ) -> None:
        self._write_reports(accepted=True, policy_evidence_pending_hash=True)

        summary = self._run_generator()
        handoff = self._handoff_report()

        self.assertEqual(
            summary["d3_t07_generation_decision"],
            "accepted_candidate_observation_with_warnings",
        )
        self.assertTrue(summary["candidate_observation_generated"])
        self.assertEqual(
            summary["candidate_generation_soft_warning_reasons"],
            ["policy_evidence_pending_hash"],
        )
        self.assertEqual(
            summary["candidate_quality_tier"], "candidate_evidence_pending"
        )
        self.assertFalse(summary["formal_use_authorized"])
        self.assertFalse(handoff["consumer_readiness"]["evaluated_by_d3"])
        self.assertEqual(handoff["consumer_readiness"]["consumer_profiles"], {})

    def test_generates_normal_neutral_and_factor_interval_rows(self) -> None:
        summary = self._run_generator()

        self.assertEqual(
            summary["d3_t07_generation_decision"], "accepted_candidate_observation"
        )
        self.assertFalse(summary["consumer_readiness"]["evaluated_by_d3"])
        self.assertEqual(summary["consumer_readiness"]["consumer_profiles"], {})
        conn = self._output_conn()
        try:
            rows = conn.execute(
                f"""
                SELECT ts_code, effective_adj_factor, adjusted_open,
                       adj_factor_policy_type, is_policy_adjusted,
                       policy_evidence_status, row_provenance
                FROM {OBSERVATION_TABLE}
                ORDER BY ts_code
                """
            ).fetchall()
            pause_count = conn.execute(
                f"SELECT count(*) FROM {OBSERVATION_TABLE} WHERE is_listing_pause"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(pause_count, 0)
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            rows,
            [
                (
                    "AAA.SZ",
                    2.0,
                    20.0,
                    None,
                    False,
                    None,
                    "d2_t20_candidate:AAA.SZ:20200102:resolved",
                ),
                (
                    "BBB.SH",
                    1.0,
                    20.0,
                    "neutral_factor_1",
                    True,
                    "hash_verified",
                    "d2_t20_candidate:BBB.SH:20200102:neutral_factor_1_policy",
                ),
                (
                    "CCC.SH",
                    1.5,
                    45.0,
                    "factor_interval",
                    True,
                    "hash_verified",
                    "d2_t20_candidate:CCC.SH:20200102:factor_interval_policy",
                ),
            ],
        )

    def test_adjusted_ohlc_uses_effective_factor(self) -> None:
        self._run_generator()
        conn = self._output_conn()
        try:
            row = conn.execute(
                f"""
                SELECT adjusted_open, adjusted_high, adjusted_low, adjusted_close
                FROM {OBSERVATION_TABLE}
                WHERE ts_code = 'CCC.SH'
                """
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, (45.0, 49.5, 42.0, 48.0))

    def test_factor_interval_without_unique_match_blocks(self) -> None:
        self.source_duckdb.unlink()
        self._build_source_duckdb(factor_interval=False)

        summary = self._run_generator()
        quality = json.loads(
            (self.d3_dir / "d3_t07_quality_report.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            summary["d3_t07_generation_decision"],
            "blocked_pending_factor_interval_resolution",
        )
        self.assertFalse(summary["d3_rows_generated"])
        self.assertEqual(quality["factor_interval_unresolved_count"], 1)
        self.assertEqual(quality["generated_observation_row_count"], 0)
        self.assertEqual(self._observation_count(), 0)
        self.assertEqual(self._handoff_report()["d3_candidate_observation_path"], "")

    def test_duplicate_observation_key_blocks(self) -> None:
        self.source_duckdb.unlink()
        self._build_source_duckdb(duplicate_daily=True)

        summary = self._run_generator()
        quality = json.loads(
            (self.d3_dir / "d3_t07_quality_report.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            summary["d3_t07_generation_decision"], "blocked_pending_quality_resolution"
        )
        self.assertFalse(summary["d3_rows_generated"])
        self.assertEqual(quality["duplicate_observation_key_count"], 1)
        self.assertEqual(quality["generated_observation_row_count"], 0)
        self.assertEqual(self._observation_count(), 0)
        self.assertEqual(self._handoff_report()["d3_candidate_observation_path"], "")

    def test_invalid_ohlc_blocks(self) -> None:
        self.source_duckdb.unlink()
        self._build_source_duckdb(invalid_ohlc=True)

        summary = self._run_generator()
        quality = json.loads(
            (self.d3_dir / "d3_t07_quality_report.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            summary["d3_t07_generation_decision"], "blocked_pending_quality_resolution"
        )
        self.assertFalse(summary["d3_rows_generated"])
        self.assertEqual(quality["null_ohlc_count"], 1)
        self.assertEqual(quality["generated_observation_row_count"], 0)
        self.assertEqual(self._observation_count(), 0)
        self.assertEqual(self._handoff_report()["d3_candidate_observation_path"], "")

    def test_missing_effective_adj_factor_blocks_without_rows(self) -> None:
        self.source_duckdb.unlink()
        self._build_source_duckdb(missing_factor=True)

        summary = self._run_generator()
        quality = json.loads(
            (self.d3_dir / "d3_t07_quality_report.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            summary["d3_t07_generation_decision"], "blocked_pending_quality_resolution"
        )
        self.assertFalse(summary["d3_rows_generated"])
        self.assertEqual(quality["missing_effective_adj_factor_count"], 1)
        self.assertEqual(quality["generated_observation_row_count"], 0)
        self.assertEqual(self._observation_count(), 0)
        self.assertEqual(self._handoff_report()["d3_candidate_observation_path"], "")

    def test_source_duckdb_and_staging_adj_factor_are_not_modified(self) -> None:
        before_hash = hashlib.sha256(self.source_duckdb.read_bytes()).hexdigest()
        source_conn = duckdb.connect(str(self.source_duckdb), read_only=True)
        try:
            before_adj_count = source_conn.execute(
                "SELECT count(*) FROM staging_adj_factor"
            ).fetchone()[0]
        finally:
            source_conn.close()

        self._run_generator()

        after_hash = hashlib.sha256(self.source_duckdb.read_bytes()).hexdigest()
        source_conn = duckdb.connect(str(self.source_duckdb), read_only=True)
        try:
            after_adj_count = source_conn.execute(
                "SELECT count(*) FROM staging_adj_factor"
            ).fetchone()[0]
        finally:
            source_conn.close()
        self.assertEqual(after_hash, before_hash)
        self.assertEqual(after_adj_count, before_adj_count)

    def test_forbidden_downstream_outputs_are_not_generated(self) -> None:
        self._run_generator()

        forbidden = {
            "data_version.json",
            "formal_manifest.json",
            "labels.csv",
            "returns.csv",
            "backtest.csv",
            "portfolio.csv",
            "r0_state.csv",
        }
        self.assertFalse(any((self.d3_dir / name).exists() for name in forbidden))
        handoff = self._handoff_report()
        self.assertFalse(handoff["formal_use_authorized"])
        self.assertFalse(handoff["formal_data_version_published"])
        self.assertFalse(handoff["pcvt_values_generated"])
        self.assertFalse(handoff["r0_state_generated"])
        self.assertEqual(
            handoff["consumer_readiness"]["consumer_gate_policy"],
            "evaluated_by_downstream_task",
        )
        for key in (
            "r1_ready_candidate",
            "r2_ready_candidate",
            "r3_ready_candidate",
            "r4_ready_candidate",
            "r5_ready_candidate",
            "r6_ready_candidate",
        ):
            self.assertNotIn(key, handoff)

    def test_direct_cli_help_runs_from_repo_root(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/generate_d3_t07_candidate_daily_observation.py",
                "--help",
            ],
            check=False,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--d2-t20-duckdb", result.stdout)

    def test_readme_advances_to_d3_t12_and_keeps_formal_release_blocked(self) -> None:
        readme = (ROOT / "docs/tasks/README.md").read_text(encoding="utf-8")

        self.assertIn("current_stage: D3", readme)
        self.assertIn(
            "current_task: R0-T10-05 authorized input manifest 与 27 组 full-grid 执行",
            readme,
        )
        self.assertIn(
            "next_planned_task: R0-T11 R0 审计报告与 R1 交接",
            readme,
        )
        self.assertIn(
            "D3-T11` 量额股本换手字段全量候选物化与数据更新：completed via PR #59",
            readme,
        )
        self.assertIn("D3 candidate generation 不等于 formal release", readme)
        self.assertIn(
            "`policy_evidence_pending_hash` 是 candidate warning，"
            "不是 D3 candidate hard blocker",
            readme,
        )


if __name__ == "__main__":
    unittest.main()
