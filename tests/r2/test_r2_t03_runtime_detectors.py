from __future__ import annotations

# ruff: noqa: E501 -- SQL mutation fixtures remain readable as full statements.
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.r2.r2_t03_event_zone_scan import _input_binding
from src.r2.r2_t03_runtime_gates import (
    _binding_checks,
    _evaluate_frozen_gates,
    _structural_check_specs,
)


class R2T03RuntimeDetectorTest(unittest.TestCase):
    def _sql(self, check_id: str) -> str:
        return next(row[2] for row in _structural_check_specs() if row[0] == check_id)

    def test_raw_false_gap_detector_covers_natural_finalized_zone(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE cell_registry(candidate_cell_id VARCHAR,g INTEGER)")
        con.execute(
            "CREATE TABLE event_zone(candidate_cell_id VARCHAR,max_raw_false_gap_days INTEGER,status VARCHAR)"
        )
        con.execute("INSERT INTO cell_registry VALUES ('c',1)")
        con.execute("INSERT INTO event_zone VALUES ('c',2,'FINALIZED')")
        self.assertEqual(
            con.execute(self._sql("raw_false_gap_days_exceed_g")).fetchone()[0], 1
        )

    def test_revision_detector_finds_time_series_regression(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            """CREATE TABLE event_zone_membership_daily(candidate_cell_id VARCHAR,
            security_id VARCHAR,scan_event_id VARCHAR,trade_date DATE,
            zone_revision_as_of INTEGER,event_zone_member BOOLEAN)"""
        )
        con.execute(
            "INSERT INTO event_zone_membership_daily VALUES "
            "('c','S','e','2026-01-01',2,true),"
            "('c','S','e','2026-01-02',1,true)"
        )
        self.assertEqual(
            con.execute(self._sql("event_zone_revision_regression")).fetchone()[0], 1
        )

    def test_revision_detector_ignores_nonmember_reentry_rows(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            """CREATE TABLE event_zone_membership_daily(candidate_cell_id VARCHAR,
            security_id VARCHAR,scan_event_id VARCHAR,trade_date DATE,
            zone_revision_as_of INTEGER,event_zone_member BOOLEAN);
            INSERT INTO event_zone_membership_daily VALUES
            ('c','S','e','2026-01-01',1,true),
            ('c','S','e','2026-01-02',0,false);"""
        )
        self.assertEqual(
            con.execute(self._sql("event_zone_revision_regression")).fetchone()[0], 0
        )

    def test_bridge_bounds_use_frozen_segment_granularity(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            """CREATE TABLE event_zone_bridge_segment(merge_accepted BOOLEAN,
            preconfirmation_gap_day_count INTEGER,raw_false_gap_day_count INTEGER,
            total_nonconfirmed_gap_day_count INTEGER,K INTEGER,g INTEGER);
            INSERT INTO event_zone_bridge_segment VALUES
            (true,4,2,6,3,2),(true,5,2,7,3,2);"""
        )
        self.assertEqual(
            con.execute(
                self._sql("preconfirmation_days_exceed_k_minus_one_bound")
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            con.execute(
                self._sql("total_nonconfirmed_gap_days_exceed_k_bound")
            ).fetchone()[0],
            1,
        )

    def test_forbidden_field_detector_scans_all_output_tables(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE supplemental_output(future_return DOUBLE)")
        self.assertEqual(
            con.execute(self._sql("forbidden_output_field")).fetchone()[0], 1
        )

    def test_unqualified_reentry_requires_terminal_ledger_path(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            """CREATE TABLE reentry_attempt(candidate_cell_id VARCHAR,security_id VARCHAR,
            reentry_attempt_id VARCHAR,outcome VARCHAR);
            CREATE TABLE transition_entity_ledger(candidate_cell_id VARCHAR,security_id VARCHAR,
            entity_kind VARCHAR,entity_id VARCHAR,to_state VARCHAR,transition_ordinal INTEGER);
            INSERT INTO reentry_attempt VALUES ('c','S','r','unqualified_reentry');
            INSERT INTO transition_entity_ledger VALUES ('c','S','reentry','r','REENTRY_PENDING_QUALIFICATION',1);"""
        )
        self.assertEqual(
            con.execute(self._sql("unqualified_reentry_unfinalized")).fetchone()[0], 1
        )

    def test_global_engineering_rules_are_not_metric_column_lookups(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute(
            """CREATE TABLE metric_results(candidate_cell_id VARCHAR,route_id VARCHAR,
            state_line VARCHAR,qualified_event_count INTEGER);
            INSERT INTO metric_results VALUES ('c','r','S_PCT',10);
            CREATE TABLE atomic_baseline_profile(candidate_cell_id VARCHAR,
            atomic_confirmed_interval_count INTEGER,confirmed_state_days INTEGER);
            INSERT INTO atomic_baseline_profile VALUES ('c',1,1);
            CREATE TABLE route_daily(route_id VARCHAR,security_id VARCHAR,
            confirmed_state BOOLEAN);
            INSERT INTO route_daily VALUES ('r','S',true);"""
        )
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "registry.csv"
            registry.write_text(
                "gate_id,metric_id,operator,threshold,state_line,implementation_stage\n"
                "duplicate_primary_key,duplicate_primary_key,==,0,GLOBAL,"
                "r2_t02_reference_executable\n",
                encoding="utf-8",
            )
            self.assertEqual(_evaluate_frozen_gates(con, registry), [])
        con.close()

    def test_real_input_binding_payload_closes_runtime_detector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "r2-t03@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "R2 T03 Test"], cwd=root, check=True
            )
            subprocess.run(
                ["git", "config", "core.autocrlf", "false"], cwd=root, check=True
            )
            config_path = root / "config.json"
            config_path.write_bytes(b'{"formal_source_paths":["source.txt"]}\n')
            (root / "source.txt").write_bytes(b"committed source\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True
            )
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
            readiness = {
                "files": {"source.txt": {"status": "passed"}},
                "superseded_input_detected": False,
            }
            payload = _input_binding(
                {"formal_source_paths": ["source.txt"]},
                config_path,
                head,
                readiness,
                root,
            )
            self.assertEqual(payload["status"], "passed")
            output_dir = root / "out"
            output_dir.mkdir()
            (output_dir / "r2_t03_source_readiness.json").write_text(
                json.dumps(readiness), encoding="utf-8"
            )
            (output_dir / "r2_t03_input_binding.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            binding_row = next(
                row
                for row in _binding_checks(output_dir)
                if row["check_id"] == "input_binding_mismatch"
            )
            self.assertEqual(binding_row["observed_value"], 0)
            self.assertEqual(binding_row["status"], "passed")


if __name__ == "__main__":
    unittest.main()
