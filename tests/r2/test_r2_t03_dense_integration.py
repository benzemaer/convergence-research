from __future__ import annotations

# ruff: noqa: E501 -- SQL fixtures remain readable as complete statements.
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.r2.r2_t03_event_zone_scan import (
    R2T03Error,
    _bind_dense_interval_lineage,
    _create_atomic_daily_view,
    _create_output_schema,
    _materialize_canonical_daily_and_intervals,
    run_scan,
)
from src.r2.r2_t03_independent_validator import (
    _earliest_oracle_decision,
    source_timeline_oracle,
)


class R2T03DenseIntegrationTest(unittest.TestCase):
    def test_expected_empty_resets_k3_once_and_propagates_to_atomic_daily(self) -> None:
        con = duckdb.connect()
        _create_output_schema(con)
        con.execute(
            "INSERT INTO cell_registry VALUES ('c','r','primary','S_PCT',120,3,.2,.2,.25,.2,1,0)"
        )
        con.execute(
            """CREATE TABLE route_source_daily(route_id VARCHAR,security_id VARCHAR,
            trade_date DATE,available_time TIMESTAMPTZ,eligible BOOLEAN,quality_state VARCHAR,
            raw_state BOOLEAN,confirmed_state BOOLEAN,confirmed_start_date DATE,
            confirmation_time TIMESTAMPTZ,state_risk_set_eligible BOOLEAN,
            expected_empty_reason VARCHAR,source_row_present BOOLEAN)"""
        )
        dates = [f"2026-01-0{i}" for i in range(1, 8)]
        for index, date in enumerate(dates):
            empty = index == 3
            con.execute(
                "INSERT INTO route_source_daily VALUES ('r','S',?,?::TIMESTAMPTZ,?,?,?,?,NULL,NULL,false,?,?)",
                [
                    date,
                    f"{date}T15:00:00+08:00",
                    not empty,
                    "expected_empty" if empty else "valid",
                    None if empty else True,
                    False,
                    "suspended" if empty else None,
                    not empty,
                ],
            )
        _materialize_canonical_daily_and_intervals(con)
        _create_atomic_daily_view(con)
        observed = con.execute(
            "SELECT confirmed_state FROM route_daily ORDER BY trade_date"
        ).fetchall()
        self.assertEqual(
            observed,
            [(False,), (False,), (True,), (False,), (False,), (False,), (True,)],
        )
        self.assertEqual(
            con.execute(
                "SELECT confirmed_state FROM atomic_confirmed_daily ORDER BY trade_date"
            ).fetchall(),
            observed,
        )
        _assert_canonical_daily_fixture(con)
        oracle = source_timeline_oracle(
            [
                {
                    "security_id": "S",
                    "trade_date": date,
                    "available_time": f"{date}T15:00:00+08:00",
                    "eligible": not (i == 3),
                    "quality_state": "expected_empty" if i == 3 else "valid",
                    "raw_state": None if i == 3 else True,
                }
                for i, date in enumerate(dates)
            ],
            expected_dates=dates,
            d=1,
            g=0,
        )
        self.assertEqual(
            [row[0] for row in observed],
            [row["confirmed_state"] for row in oracle["timeline"]],
        )
        con.close()

    def test_dense_fragment_ids_separate_from_actual_upstream_identity(self) -> None:
        con = duckdb.connect()
        _create_output_schema(con)
        con.execute(
            "CREATE TABLE route_source_daily(route_id VARCHAR,security_id VARCHAR,trade_date DATE,source_row_present BOOLEAN)"
        )
        con.execute(
            "INSERT INTO route_source_daily VALUES ('r','S','2026-01-04',false)"
        )
        con.execute(
            """CREATE TABLE authorized_upstream_interval(route_id VARCHAR,security_id VARCHAR,
            upstream_source_interval_id VARCHAR,raw_start_date DATE,confirmed_start_date DATE,
            interval_end_date DATE,last_observed_date DATE,confirmed_day_count INTEGER,
            normalized_termination_reason VARCHAR)"""
        )
        con.execute(
            "INSERT INTO authorized_upstream_interval VALUES ('r','S','real-r0-id','2026-01-01','2026-01-03','2026-01-09','2026-01-10',7,'natural_state_exit')"
        )
        con.execute(
            """INSERT INTO route_atomic_interval VALUES
            ('r','S','dense-a',NULL,'2026-01-03','2026-01-03',1,'quality_interruption','2026-01-04T15:00:00+08:00',false,false,1),
            ('r','S','dense-b',NULL,'2026-01-07','2026-01-09',3,'natural_state_exit','2026-01-10T15:00:00+08:00',false,false,1)"""
        )
        _bind_dense_interval_lineage(con)
        rows = con.execute(
            "SELECT interval_id,upstream_source_interval_id,dense_fragment_ordinal FROM route_atomic_interval ORDER BY interval_id"
        ).fetchall()
        self.assertEqual(
            rows, [("dense-a", "real-r0-id", 1), ("dense-b", "real-r0-id", 2)]
        )
        con.close()

    def test_termination_only_expected_empty_is_flagged(self) -> None:
        con = duckdb.connect()
        _create_output_schema(con)
        con.execute(
            "CREATE TABLE route_source_daily(route_id VARCHAR,security_id VARCHAR,trade_date DATE,source_row_present BOOLEAN)"
        )
        con.execute(
            "INSERT INTO route_source_daily VALUES ('r','S','2026-01-04',false)"
        )
        con.execute(
            """CREATE TABLE authorized_upstream_interval(route_id VARCHAR,security_id VARCHAR,
            upstream_source_interval_id VARCHAR,raw_start_date DATE,confirmed_start_date DATE,
            interval_end_date DATE,last_observed_date DATE,confirmed_day_count INTEGER,
            normalized_termination_reason VARCHAR)"""
        )
        con.execute(
            "INSERT INTO authorized_upstream_interval VALUES ('r','S','source','2026-01-01','2026-01-03','2026-01-03','2026-01-05',1,'natural_state_exit')"
        )
        con.execute(
            "INSERT INTO route_atomic_interval VALUES ('r','S','dense',NULL,'2026-01-03','2026-01-03',1,'quality_interruption','2026-01-04T15:00:00+08:00',false,false,1)"
        )
        _bind_dense_interval_lineage(con)
        self.assertEqual(
            con.execute(
                "SELECT source_geometry_affected,source_termination_affected FROM route_atomic_interval"
            ).fetchone(),
            (False, True),
        )
        con.close()

    def test_earliest_irreversible_gap_decision(self) -> None:
        false_row = {
            "eligible": True,
            "quality_state": "valid",
            "raw_state": False,
            "hard_break": False,
        }
        blocked = {
            "eligible": False,
            "quality_state": "blocked",
            "raw_state": None,
            "hard_break": True,
        }
        self.assertEqual(
            _earliest_oracle_decision([false_row, blocked], 0),
            "raw_false_gap_exceeds_g",
        )
        self.assertEqual(
            _earliest_oracle_decision([blocked, false_row], 0), "quality_break"
        )

    def test_nonempty_formal_output_directory_fails_before_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "R2-T03-test"
            output.mkdir()
            (output / "existing.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(R2T03Error, "formal_run_output_dir_not_empty"):
                run_scan(Path("missing-config.json"), output)


def _assert_canonical_daily_fixture(con: duckdb.DuckDBPyConnection) -> None:
    self_checks = [
        "SELECT count(*)-7 FROM route_daily",
        "SELECT count(*) FROM route_daily WHERE NOT source_row_present AND (confirmed_state OR state_risk_set_eligible)",
        "SELECT count(*) FROM route_daily WHERE confirmed_state AND raw_state IS DISTINCT FROM true",
    ]
    for sql in self_checks:
        if con.execute(sql).fetchone()[0]:
            raise AssertionError(sql)


if __name__ == "__main__":
    unittest.main()
