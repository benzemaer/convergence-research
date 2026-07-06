from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
from jsonschema import Draft202012Validator

from scripts.audit_d3_t08_research_dataset_registry import (
    OUTPUT_DUCKDB_NAME,
    TARGET_TABLES,
    D3T08AuditError,
    audit_d3_t08_research_dataset_registry,
    guard_source_d3_t07_duckdb,
    guard_source_d3_t07_report,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d3/d3_t08_research_dataset_registry_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d3_t08_research_dataset_registry_contract.schema.json"
SOURCE_TABLE = "d3_candidate_daily_observation"


class D3T08ResearchDatasetRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        self.d3_t07_dir = (
            self.base
            / "data"
            / "generated"
            / "d3"
            / "d3_t07_candidate_daily_observation"
        )
        self.d3_t08_dir = (
            self.base / "data" / "generated" / "d3" / "d3_t08_research_dataset_registry"
        )
        self.source_duckdb = (
            self.d3_t07_dir / "d3_t07_candidate_daily_observation.duckdb"
        )
        self.quality_report = self.d3_t07_dir / "d3_t07_quality_report.json"
        self.handoff_report = self.d3_t07_dir / "d3_t07_handoff_candidate_report.json"
        self._build_source_duckdb()
        self._write_reports(accepted=True)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _build_source_duckdb(
        self,
        *,
        duplicate: bool = False,
        raw_invalid: bool = False,
        adjusted_invalid: bool = False,
        factor_invalid: bool = False,
        factor_mismatch: bool = False,
        listing_pause: bool = False,
        missing_lineage: bool = False,
    ) -> None:
        self.source_duckdb.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(self.source_duckdb))
        try:
            conn.execute(
                f"""
                CREATE TABLE {SOURCE_TABLE} (
                  ts_code TEXT,
                  trade_date TEXT,
                  open DOUBLE,
                  high DOUBLE,
                  low DOUBLE,
                  close DOUBLE,
                  vol DOUBLE,
                  amount DOUBLE,
                  effective_adj_factor DOUBLE,
                  adjusted_open DOUBLE,
                  adjusted_high DOUBLE,
                  adjusted_low DOUBLE,
                  adjusted_close DOUBLE,
                  trading_status TEXT,
                  daily_status TEXT,
                  price_limit_status TEXT,
                  adjustment_factor_status TEXT,
                  up_limit DOUBLE,
                  down_limit DOUBLE,
                  is_limit_up BOOLEAN,
                  is_limit_down BOOLEAN,
                  is_listing_pause BOOLEAN,
                  is_policy_adjusted BOOLEAN,
                  adj_factor_policy_type TEXT,
                  adj_factor_policy_source TEXT,
                  policy_evidence_status TEXT,
                  policy_evidence_level TEXT,
                  source_task_id TEXT,
                  d2_source_duckdb TEXT,
                  generated_by_task TEXT,
                  row_provenance TEXT
                )
                """
            )
            rows = []
            start = datetime.strptime("20200101", "%Y%m%d")
            for offset in range(85):
                trade_date = (start + timedelta(days=offset)).strftime("%Y%m%d")
                open_price = 10.0 + offset / 100.0
                rows.append(
                    self._row(
                        ts_code="AAA.SZ",
                        trade_date=trade_date,
                        open_price=open_price,
                        factor=2.0,
                        policy_type=None,
                    )
                )
            for ts_code, factor, policy_type in (
                ("BBB.SH", 1.0, "neutral_factor_1"),
                ("CCC.SH", 1.5, "factor_interval"),
            ):
                for offset in range(3):
                    trade_date = (start + timedelta(days=offset)).strftime("%Y%m%d")
                    rows.append(
                        self._row(
                            ts_code=ts_code,
                            trade_date=trade_date,
                            open_price=20.0 + offset,
                            factor=factor,
                            policy_type=policy_type,
                        )
                    )
            if duplicate:
                rows.append(rows[0])
            if raw_invalid:
                rows.append(
                    self._row(
                        ts_code="BADRAW.SZ",
                        trade_date="20200101",
                        open_price=-1.0,
                        factor=1.0,
                        policy_type=None,
                    )
                )
            if adjusted_invalid:
                row = list(
                    self._row(
                        ts_code="BADADJ.SZ",
                        trade_date="20200101",
                        open_price=10.0,
                        factor=1.0,
                        policy_type=None,
                    )
                )
                row[9] = -10.0
                rows.append(tuple(row))
            if factor_invalid:
                rows.append(
                    self._row(
                        ts_code="BADFAC.SZ",
                        trade_date="20200101",
                        open_price=10.0,
                        factor=-1.0,
                        policy_type=None,
                    )
                )
            if factor_mismatch:
                row = list(
                    self._row(
                        ts_code="MISMATCH.SZ",
                        trade_date="20200101",
                        open_price=10.0,
                        factor=2.0,
                        policy_type=None,
                    )
                )
                row[12] = 999.0
                rows.append(tuple(row))
            if listing_pause:
                row = list(
                    self._row(
                        ts_code="PAUSE.SZ",
                        trade_date="20200101",
                        open_price=10.0,
                        factor=1.0,
                        policy_type=None,
                    )
                )
                row[13] = "listing_pause"
                row[21] = True
                rows.append(tuple(row))
            if missing_lineage:
                row = list(
                    self._row(
                        ts_code="NOLINE.SZ",
                        trade_date="20200101",
                        open_price=10.0,
                        factor=1.0,
                        policy_type=None,
                    )
                )
                row[27] = None
                row[29] = None
                row[30] = ""
                rows.append(tuple(row))
            conn.executemany(
                f"INSERT INTO {SOURCE_TABLE} VALUES ({','.join(['?'] * 31)})",
                rows,
            )
        finally:
            conn.close()

    def _row(
        self,
        *,
        ts_code: str,
        trade_date: str,
        open_price: float,
        factor: float,
        policy_type: str | None,
    ) -> tuple[object, ...]:
        high = open_price + 1.0
        low = open_price - 1.0
        close = open_price + 0.5
        is_policy = policy_type is not None
        return (
            ts_code,
            trade_date,
            open_price,
            high,
            low,
            close,
            100.0,
            1000.0,
            factor,
            open_price * factor,
            high * factor,
            low * factor,
            close * factor,
            "listed_open_resolved_daily",
            "resolved",
            "resolved",
            "resolved" if policy_type is None else f"{policy_type}_policy",
            high,
            low,
            False,
            False,
            False,
            is_policy,
            policy_type,
            "tnskhdata_adj_factor_hash_verified" if is_policy else None,
            "hash_verified" if is_policy else None,
            "tnskhdata_adj_factor_hash_verified" if is_policy else None,
            "D2-T20",
            "synthetic_d2_source.duckdb",
            "D3-T07",
            f"d2_t20_candidate:{ts_code}:{trade_date}",
        )

    def _write_reports(self, *, accepted: bool, quality_blocker: bool = False) -> None:
        self.d3_t07_dir.mkdir(parents=True, exist_ok=True)
        quality = {
            "d3_t07_generation_decision": (
                "accepted_candidate_observation"
                if accepted
                else "blocked_pending_quality_resolution"
            ),
            "duplicate_observation_key_count": 1 if quality_blocker else 0,
            "null_ohlc_count": 0,
            "non_positive_price_count": 0,
            "high_low_violation_count": 0,
            "missing_effective_adj_factor_count": 0,
            "factor_interval_unresolved_count": 0,
            "listing_pause_excluded_count": 2,
        }
        handoff = {
            "d3_t07_generation_decision": (
                "accepted_candidate_observation"
                if accepted
                else "blocked_pending_quality_resolution"
            ),
            "d3_candidate_observation_generated": accepted,
            "formal_data_version_published": False,
            "labels_generated": False,
            "returns_generated": False,
            "pcvt_values_generated": False,
            "r0_state_generated": False,
        }
        self.quality_report.write_text(json.dumps(quality), encoding="utf-8")
        self.handoff_report.write_text(json.dumps(handoff), encoding="utf-8")

    def _run_audit(self) -> dict[str, object]:
        return audit_d3_t08_research_dataset_registry(
            d3_t07_duckdb=self.source_duckdb,
            d3_t07_quality_report=self.quality_report,
            d3_t07_handoff_report=self.handoff_report,
            output_dir=self.d3_t08_dir,
        )

    def _output_conn(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.d3_t08_dir / OUTPUT_DUCKDB_NAME), read_only=True)

    def test_contract_json_passes_schema(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(contract)

    def test_d3_t07_handoff_blocks_audit(self) -> None:
        self._write_reports(accepted=False)

        summary = self._run_audit()

        self.assertEqual(
            summary["d3_t08_generation_decision"],
            "blocked_pending_d3_t07_candidate_observation",
        )
        self.assertFalse(summary["research_dataset_registry_generated"])

    def test_d3_t07_quality_blocker_blocks_audit(self) -> None:
        self._write_reports(accepted=True, quality_blocker=True)

        summary = self._run_audit()

        self.assertEqual(
            summary["d3_t08_generation_decision"],
            "blocked_pending_d3_t07_candidate_observation",
        )
        self.assertFalse(summary["research_dataset_registry_generated"])

    def test_source_path_guard_rejects_d2_raw_and_wrong_filename(self) -> None:
        bad_paths = [
            self.base
            / "data"
            / "generated"
            / "d2"
            / "d2_t20"
            / "d3_t07_candidate_daily_observation.duckdb",
            self.base / "data" / "raw" / "d3_t07_candidate_daily_observation.duckdb",
            self.d3_t07_dir / "other.duckdb",
        ]
        for path in bad_paths:
            with self.subTest(path=path):
                with self.assertRaises(D3T08AuditError):
                    guard_source_d3_t07_duckdb(path)
        guard_source_d3_t07_duckdb(self.source_duckdb)

    def test_report_path_guard_rejects_wrong_filename(self) -> None:
        with self.assertRaises(D3T08AuditError):
            guard_source_d3_t07_report(
                self.d3_t07_dir / "other_quality.json",
                expected_name="d3_t07_quality_report.json",
            )
        guard_source_d3_t07_report(
            self.quality_report, expected_name="d3_t07_quality_report.json"
        )
        guard_source_d3_t07_report(
            self.handoff_report,
            expected_name="d3_t07_handoff_candidate_report.json",
        )

    def test_invalid_input_path_fails_before_outputs_are_created(self) -> None:
        bad_duckdb = (
            self.base
            / "data"
            / "generated"
            / "d2"
            / "d2_t20"
            / "d3_t07_candidate_daily_observation.duckdb"
        )
        with self.assertRaises(D3T08AuditError):
            audit_d3_t08_research_dataset_registry(
                d3_t07_duckdb=bad_duckdb,
                d3_t07_quality_report=self.quality_report,
                d3_t07_handoff_report=self.handoff_report,
                output_dir=self.d3_t08_dir,
            )
        self.assertFalse((self.d3_t08_dir / OUTPUT_DUCKDB_NAME).exists())
        self.assertFalse((self.d3_t08_dir / "d3_t08_quality_report.json").exists())

    def test_accepted_synthetic_observation_generates_registry_tables(self) -> None:
        summary = self._run_audit()

        self.assertEqual(
            summary["d3_t08_generation_decision"],
            "accepted_research_dataset_registry_with_warnings",
        )
        self.assertTrue(summary["research_dataset_registry_generated"])
        conn = self._output_conn()
        try:
            counts = {
                table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in TARGET_TABLES
            }
            registry = conn.execute(
                """
                SELECT row_count, security_count, generated_by_task,
                       formal_data_version_published, pcvt_values_generated,
                       r0_state_generated
                FROM d3_research_dataset_registry
                """
            ).fetchone()
            policies = {
                row[0]: row[1]
                for row in conn.execute(
                    """
                    SELECT policy_type, row_count
                    FROM d3_research_dataset_policy_usage
                    """
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertEqual(counts["d3_research_dataset_registry"], 1)
        self.assertGreater(counts["d3_research_dataset_schema_catalog"], 20)
        self.assertGreater(counts["d3_research_dataset_window_capacity"], 80)
        self.assertEqual(registry, (91, 3, "D3-T08", False, False, False))
        self.assertEqual(policies["provider_resolved"], 85)
        self.assertEqual(policies["neutral_factor_1"], 3)
        self.assertEqual(policies["factor_interval"], 3)
        self.assertEqual(policies["listing_pause_excluded"], 2)

    def test_core_quality_blockers_do_not_generate_registry(self) -> None:
        cases = [
            ("duplicate_observation_key_count", {"duplicate": True}),
            ("raw_ohlc_invalid_count", {"raw_invalid": True}),
            ("adjusted_ohlc_invalid_count", {"adjusted_invalid": True}),
            ("effective_adj_factor_invalid_count", {"factor_invalid": True}),
            ("adjusted_factor_mismatch_count", {"factor_mismatch": True}),
            ("is_listing_pause_true_count", {"listing_pause": True}),
            ("row_provenance_missing_count", {"missing_lineage": True}),
        ]
        for blocker, kwargs in cases:
            with self.subTest(blocker=blocker):
                self.source_duckdb.unlink(missing_ok=True)
                self._build_source_duckdb(**kwargs)
                summary = self._run_audit()
                quality = json.loads(
                    (self.d3_t08_dir / "d3_t08_quality_report.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    summary["d3_t08_generation_decision"],
                    "blocked_pending_research_dataset_quality",
                )
                self.assertFalse(summary["research_dataset_registry_generated"])
                self.assertGreater(quality[blocker], 0)
                conn = self._output_conn()
                try:
                    registry_count = conn.execute(
                        "SELECT count(*) FROM d3_research_dataset_registry"
                    ).fetchone()[0]
                finally:
                    conn.close()
                self.assertEqual(registry_count, 0)

    def test_window_capacity_uses_past_windows_without_cross_security(self) -> None:
        self._run_audit()
        conn = self._output_conn()
        try:
            rows = conn.execute(
                """
                SELECT ts_code, trade_date, valid_price_window_count_20
                FROM d3_research_dataset_window_capacity
                WHERE (ts_code = 'AAA.SZ' AND trade_date IN ('20200101', '20200120'))
                   OR (ts_code = 'BBB.SH' AND trade_date = '20200101')
                ORDER BY ts_code, trade_date
                """
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(
            rows,
            [
                ("AAA.SZ", "20200101", 1),
                ("AAA.SZ", "20200120", 20),
                ("BBB.SH", "20200101", 1),
            ],
        )

    def test_output_schema_and_files_exclude_research_outcomes(self) -> None:
        self._run_audit()
        forbidden_files = {
            "data_version.json",
            "formal_manifest.json",
            "labels.csv",
            "returns.csv",
            "future_outcomes.csv",
            "backtest.csv",
            "portfolio.csv",
            "r0_state.csv",
            "pcvt_values.csv",
            "pcvt_scores.csv",
            "state_labels.csv",
        }
        self.assertFalse(
            any((self.d3_t08_dir / name).exists() for name in forbidden_files)
        )
        conn = self._output_conn()
        try:
            found = conn.execute(
                """
                SELECT lower(column_name)
                FROM information_schema.columns
                WHERE lower(column_name) IN (
                  'pcvt_value',
                  'pcvt_score',
                  'pcvt_state',
                  'q_threshold',
                  'state',
                  'label',
                  'future_return'
                )
                """
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(found, [])

    def test_source_duckdb_is_not_modified(self) -> None:
        before_hash = hashlib.sha256(self.source_duckdb.read_bytes()).hexdigest()

        self._run_audit()

        after_hash = hashlib.sha256(self.source_duckdb.read_bytes()).hexdigest()
        self.assertEqual(after_hash, before_hash)

    def test_direct_cli_help_runs_from_repo_root(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/audit_d3_t08_research_dataset_registry.py",
                "--help",
            ],
            check=False,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--d3-t07-duckdb", result.stdout)

    def test_readme_advances_to_d3_t08_and_keeps_r0_state_blocked(self) -> None:
        readme = (ROOT / "docs/tasks/README.md").read_text(encoding="utf-8")

        self.assertIn("current_stage: D3", readme)
        self.assertIn(
            "current_task: D3-T08 research dataset registry and "
            "route-agnostic base quality",
            readme,
        )
        self.assertIn(
            "next_planned_task: R0-T01 PCVT candidate indicator specification",
            readme,
        )
        self.assertIn(
            "D3-T07` 从 D2-T20 evidence-verified candidate "
            "生成标准日频观测表：completed via PR #53",
            readme,
        )
        self.assertIn("Formal data_version remains blocked", readme)
        self.assertIn(
            "R0 state remains blocked until PCVT candidate indicators and "
            "later gates are accepted",
            readme,
        )


if __name__ == "__main__":
    unittest.main()
