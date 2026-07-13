from __future__ import annotations

import builtins
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest import mock

import duckdb

from src.r2.r2_t03_event_zone_scan import (
    _fetch_security_intervals,
    _iso_time,
    _iter_security_timelines,
)


@contextmanager
def _forbid_pytz_import():
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pytz" or name.startswith("pytz."):
            raise AssertionError("pytz import forbidden at Python timestamp boundary")
        return original_import(name, globals, locals, fromlist, level)

    with mock.patch("builtins.__import__", side_effect=guarded_import):
        yield


class R2T03TimestampBoundaryTest(unittest.TestCase):
    def test_timeline_fetch_casts_timestamptz_without_pytz(self) -> None:
        con = duckdb.connect()
        try:
            con.execute("SET TimeZone='Asia/Shanghai'")
            con.execute(
                """CREATE TABLE route_daily(
                route_id VARCHAR,security_id VARCHAR,trade_date DATE,
                available_time TIMESTAMPTZ,eligible BOOLEAN,quality_state VARCHAR,
                raw_state BOOLEAN,confirmed_state BOOLEAN,confirmed_start_date DATE,
                confirmation_time TIMESTAMPTZ,confirmed_end_date DATE,
                exit_observation_time TIMESTAMPTZ,state_risk_set_eligible BOOLEAN,
                reason_code VARCHAR,hard_break BOOLEAN,expected_empty_reason VARCHAR,
                source_row_present BOOLEAN)"""
            )
            con.execute(
                """INSERT INTO route_daily VALUES
                ('r','S2','2026-07-14','2026-07-14T15:00:00+08:00',true,'valid',
                 true,true,'2026-07-14','2026-07-14T15:00:00+08:00',NULL,NULL,
                 true,'k3_confirmation',false,NULL,true),
                ('r','S1','2026-07-13','2026-07-13T15:00:00+08:00',true,'valid',
                 false,false,NULL,NULL,NULL,'2026-07-13T15:00:00+08:00',
                 false,'ordinary_false',false,NULL,true),
                ('r','S1','2026-07-14','2026-07-14T15:00:00+08:00',true,'valid',
                 true,true,'2026-07-14','2026-07-14T15:00:00+08:00',NULL,NULL,
                 true,'k3_confirmation',false,NULL,true)"""
            )
            with _forbid_pytz_import():
                grouped = list(_iter_security_timelines(con, "r"))
            self.assertEqual([item[0] for item in grouped], ["S1", "S2"])
            self.assertEqual(
                [row[1].isoformat() for row in grouped[0][1]],
                ["2026-07-13", "2026-07-14"],
            )
            for _, rows in grouped:
                for row in rows:
                    self.assertIsInstance(row[2], str)
                    self.assertTrue(row[8] is None or isinstance(row[8], str))
                    self.assertTrue(row[10] is None or isinstance(row[10], str))
        finally:
            con.close()

    def test_interval_fetch_casts_and_normalizes_timestamptz_without_pytz(
        self,
    ) -> None:
        con = duckdb.connect()
        try:
            con.execute("SET TimeZone='Asia/Shanghai'")
            con.execute(
                """CREATE TABLE route_atomic_interval(
                route_id VARCHAR,security_id VARCHAR,interval_id VARCHAR,
                upstream_source_interval_id VARCHAR,start_date DATE,end_date DATE,
                confirmed_day_count INTEGER,termination_reason VARCHAR,
                exit_observation_time TIMESTAMPTZ,source_geometry_affected BOOLEAN,
                source_termination_affected BOOLEAN,dense_fragment_ordinal INTEGER)"""
            )
            con.execute(
                """INSERT INTO route_atomic_interval VALUES
                ('r','S','b','up-b','2026-07-14','2026-07-15',2,'natural_state_exit',
                 NULL,false,false,2),
                ('r','S','a','up-a','2026-07-12','2026-07-13',2,'natural_state_exit',
                 '2026-07-14T15:00:00+08:00',true,false,1)"""
            )
            with _forbid_pytz_import():
                rows = _fetch_security_intervals(con, "r", "S")
            self.assertEqual([row["interval_id"] for row in rows], ["a", "b"])
            self.assertEqual(
                rows[0]["exit_observation_time"], "2026-07-14T15:00:00+08:00"
            )
            self.assertEqual(rows[1]["exit_observation_time"], "")
            self.assertEqual(rows[0]["upstream_source_interval_id"], "up-a")
            self.assertEqual(rows[0]["start_date"], "2026-07-12")
            self.assertEqual(rows[0]["end_date"], "2026-07-13")
            self.assertEqual(rows[0]["confirmed_day_count"], 2)
            self.assertTrue(rows[0]["source_geometry_affected"])
            self.assertFalse(rows[0]["source_termination_affected"])
            self.assertEqual(rows[0]["dense_fragment_ordinal"], 1)
        finally:
            con.close()

    def test_iso_time_normalizes_supported_representations_exactly(self) -> None:
        expected = "2026-07-13T15:00:00+08:00"
        shanghai = timezone(timedelta(hours=8))
        values = [
            datetime(2026, 7, 13, 15, 0, tzinfo=shanghai),
            "2026-07-13 15:00:00+08",
            "2026-07-13 15:00:00+0800",
            expected,
        ]
        self.assertEqual([_iso_time(value) for value in values], [expected] * 4)
        self.assertEqual(_iso_time(None), "")
        self.assertEqual(_iso_time(""), "")

    def test_normalized_timestamp_round_trips_as_timestamptz_without_pytz(
        self,
    ) -> None:
        con = duckdb.connect()
        try:
            con.execute("SET TimeZone='Asia/Shanghai'")
            con.execute("CREATE TABLE timestamp_probe(value TIMESTAMPTZ)")
            normalized = _iso_time("2026-07-13 15:00:00+08")
            con.execute(
                "INSERT INTO timestamp_probe VALUES (?::TIMESTAMPTZ)", [normalized]
            )
            with _forbid_pytz_import():
                observed = con.execute(
                    """SELECT CAST(value AS DATE),extract(hour FROM value),
                    epoch(value),typeof(value) FROM timestamp_probe"""
                ).fetchone()
            self.assertEqual(observed[0].isoformat(), "2026-07-13")
            self.assertEqual(observed[1], 15)
            self.assertEqual(observed[2], 1783926000.0)
            self.assertEqual(observed[3], "TIMESTAMP WITH TIME ZONE")
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
