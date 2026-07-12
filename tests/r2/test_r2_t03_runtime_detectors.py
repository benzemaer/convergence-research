from __future__ import annotations

# ruff: noqa: E501 -- SQL mutation fixtures remain readable as full statements.
import unittest

import duckdb

from src.r2.r2_t03_runtime_gates import _structural_check_specs


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
            security_id VARCHAR,scan_event_id VARCHAR,trade_date DATE,zone_revision_as_of INTEGER)"""
        )
        con.execute(
            "INSERT INTO event_zone_membership_daily VALUES ('c','S','e','2026-01-01',2),('c','S','e','2026-01-02',1)"
        )
        self.assertEqual(
            con.execute(self._sql("event_zone_revision_regression")).fetchone()[0], 1
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


if __name__ == "__main__":
    unittest.main()
