from __future__ import annotations

import json
import unittest
from pathlib import Path

import duckdb

from src.r2.r2_t05_canonical_materialization import (
    _canonical_json,
    _create_output_schema,
    _event_identity,
    _materialize_daily,
)
from src.r2.r2_t05_independent_validator import _independent_daily_asof_mismatch

ROOT = Path(__file__).resolve().parents[2]


class R2T05CanonicalMaterializationContractTest(unittest.TestCase):
    def test_config_freezes_two_selected_versions_and_exclusions(self) -> None:
        config = json.loads(
            (
                ROOT
                / "configs/r2/r2_t05_canonical_state_event_zone_materialization.v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(len(config["selected_versions"]), 2)
        self.assertEqual({row["W"] for row in config["selected_versions"]}, {120})
        self.assertEqual({row["d"] for row in config["selected_versions"]}, {2})
        self.assertEqual({row["g"] for row in config["selected_versions"]}, {1})
        self.assertEqual(config["exclusions"]["W250_materialized_version_count"], 0)
        self.assertEqual(
            config["exclusions"]["shared_q_independent_state_version_count"], 0
        )
        self.assertEqual(config["exclusions"]["PCT_parent_product_count"], 0)

    def test_event_identity_is_independent_of_revision_and_later_components(
        self,
    ) -> None:
        config = {
            "contract_version": "r2_t02_confirmed_event_zone_state_machine_contract.v8"
        }
        version = {"state_version_id": "state-a"}
        first = (
            "cell-a",
            "scan-a",
            "000001.SZ",
            "component_001",
            "2020-01-02",
            "2020-01-03T15:00:00+08:00",
        )
        event_id, payload, _ = _event_identity(config, version, first)
        revised_id, revised_payload, _ = _event_identity(config, version, first)
        self.assertEqual(event_id, revised_id)
        self.assertEqual(payload, revised_payload)
        self.assertNotIn("zone_revision", payload)
        self.assertNotIn("component_002", payload)

    def test_event_identity_separates_state_version_and_security(self) -> None:
        config = {
            "contract_version": "r2_t02_confirmed_event_zone_state_machine_contract.v8"
        }
        first = (
            "cell-a",
            "scan-a",
            "000001.SZ",
            "component_001",
            "2020-01-02",
            "2020-01-03T15:00:00+08:00",
        )
        base = _event_identity(config, {"state_version_id": "state-a"}, first)[0]
        other_state = _event_identity(config, {"state_version_id": "state-b"}, first)[0]
        other_security = _event_identity(
            config,
            {"state_version_id": "state-a"},
            (*first[:2], "000002.SZ", *first[3:]),
        )[0]
        self.assertNotEqual(base, other_state)
        self.assertNotEqual(base, other_security)

    def test_public_schema_has_closed_primary_keys(self) -> None:
        con = duckdb.connect(":memory:")
        _create_output_schema(con)
        daily_columns = {
            row[0]
            for row in con.execute("DESCRIBE r2_canonical_daily_state").fetchall()
        }
        self.assertIn("qualified_event_risk_set_eligible", daily_columns)
        for table in (
            "r2_canonical_daily_state",
            "r2_canonical_event_zone",
            "r2_canonical_event_membership",
        ):
            columns = {row[0] for row in con.execute(f'DESCRIBE "{table}"').fetchall()}
            self.assertGreater(len(columns), 10)
        constraints = con.execute(
            "SELECT table_name,constraint_type FROM duckdb_constraints() WHERE table_name LIKE 'r2_canonical_%'"
        ).fetchall()
        self.assertGreaterEqual(sum(row[1] == "PRIMARY KEY" for row in constraints), 3)
        con.close()

    def test_daily_asof_join_is_scoped_by_state_version(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute("CREATE SCHEMA src")
        con.execute(
            """
            CREATE TABLE src.route_daily(
              route_id VARCHAR, security_id VARCHAR, trade_date DATE,
              available_time TIMESTAMPTZ, eligible BOOLEAN, raw_state BOOLEAN,
              confirmed_state BOOLEAN, confirmation_time TIMESTAMPTZ,
              state_risk_set_eligible BOOLEAN, quality_state VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO src.route_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "primary-a",
                    "000001.SZ",
                    "2024-01-02",
                    "2024-01-02 11:00:00+08:00",
                    True,
                    True,
                    True,
                    "2024-01-02 10:00:00+08:00",
                    True,
                    "valid",
                ),
                (
                    "strict-a",
                    "000001.SZ",
                    "2024-01-02",
                    "2024-01-02 11:00:00+08:00",
                    True,
                    True,
                    True,
                    "2024-01-02 10:00:00+08:00",
                    True,
                    "valid",
                ),
                (
                    "primary-b",
                    "000001.SZ",
                    "2024-01-02",
                    "2024-01-02 11:00:00+08:00",
                    True,
                    True,
                    True,
                    "2024-01-02 10:00:00+08:00",
                    True,
                    "valid",
                ),
                (
                    "strict-b",
                    "000001.SZ",
                    "2024-01-02",
                    "2024-01-02 11:00:00+08:00",
                    True,
                    True,
                    True,
                    "2024-01-02 10:00:00+08:00",
                    True,
                    "valid",
                ),
            ],
        )
        _create_output_schema(con)
        con.execute(
            """
            CREATE TEMP TABLE t05_selected_versions(
              state_version_id VARCHAR, state_line VARCHAR, window_track_id VARCHAR,
              source_candidate_cell_id VARCHAR, primary_route_id VARCHAR,
              strict_core_route_id VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO t05_selected_versions VALUES (?,?,?,?,?,?)",
            [
                ("state-a", "S_PCT", "W120", "cell-a", "primary-a", "strict-a"),
                ("state-b", "S_PCVT", "W120", "cell-b", "primary-b", "strict-b"),
            ],
        )
        con.executemany(
            "INSERT INTO r2_canonical_event_zone VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "state-a",
                    "event-a",
                    "000001.SZ",
                    "2024-01-02",
                    "2024-01-02 08:00:00+08:00",
                    "2024-01-02",
                    "2024-01-02 12:00:00+08:00",
                    "2024-01-02 12:00:00+08:00",
                    "FINALIZED",
                    "sample_end_open_zone",
                    False,
                    False,
                    1,
                    0,
                    0,
                    1,
                    1,
                    1.0,
                    0.0,
                    1,
                ),
                (
                    "state-a",
                    "event-future",
                    "000001.SZ",
                    "2024-01-03",
                    "2024-01-03 08:00:00+08:00",
                    "2024-01-03",
                    "2024-01-03 12:00:00+08:00",
                    "2024-01-03 12:00:00+08:00",
                    "FINALIZED",
                    "sample_end_open_zone",
                    False,
                    False,
                    1,
                    0,
                    0,
                    1,
                    1,
                    1.0,
                    0.0,
                    1,
                ),
                (
                    "state-b",
                    "event-b",
                    "000001.SZ",
                    "2024-01-02",
                    "2024-01-02 08:00:00+08:00",
                    "2024-01-02",
                    "2024-01-02 12:00:00+08:00",
                    "2024-01-02 12:00:00+08:00",
                    "FINALIZED",
                    "sample_end_open_zone",
                    False,
                    False,
                    1,
                    0,
                    0,
                    1,
                    1,
                    1.0,
                    0.0,
                    1,
                ),
            ],
        )
        con.executemany(
            """
            INSERT INTO r2_canonical_event_membership VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    "state-a",
                    "event-a",
                    "000001.SZ",
                    "2024-01-02",
                    True,
                    True,
                    False,
                    True,
                    True,
                    False,
                    False,
                    False,
                    "QUALIFIED_ACTIVE",
                    1,
                    "2024-01-02 09:00:00+08:00",
                    True,
                    True,
                ),
                (
                    "state-a",
                    "event-future",
                    "000001.SZ",
                    "2024-01-03",
                    True,
                    True,
                    False,
                    True,
                    True,
                    False,
                    False,
                    False,
                    "QUALIFIED_ACTIVE",
                    1,
                    "2024-01-02 11:00:00+08:00",
                    True,
                    True,
                ),
                (
                    "state-b",
                    "event-b",
                    "000001.SZ",
                    "2024-01-02",
                    True,
                    True,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                    "FINALIZED",
                    1,
                    "2024-01-02 10:00:00+08:00",
                    True,
                    False,
                ),
            ],
        )
        _materialize_daily(con, "synthetic-run")
        rows = con.execute(
            """
            SELECT state_version_id,component_qualified_as_of,event_status_as_of,
                   active_event_id_as_of,qualified_event_risk_set_eligible
            FROM r2_canonical_daily_state ORDER BY state_version_id
            """
        ).fetchall()
        self.assertEqual(
            rows,
            [
                ("state-a", True, "QUALIFIED_ACTIVE", "event-a", True),
                ("state-b", False, "FINALIZED", None, False),
            ],
        )
        self.assertEqual(
            _independent_daily_asof_mismatch(con, "state-a", "primary-a"), 0
        )
        self.assertEqual(
            _independent_daily_asof_mismatch(con, "state-b", "primary-b"), 0
        )
        con.execute(
            "UPDATE r2_canonical_daily_state SET active_event_id_as_of='event-b' WHERE state_version_id='state-a'"
        )
        self.assertEqual(
            _independent_daily_asof_mismatch(con, "state-a", "primary-a"), 1
        )
        con.close()

    def test_canonical_serialization_is_sorted_and_compact(self) -> None:
        payload = _canonical_json({"b": 2, "a": 1})
        self.assertEqual(payload, b'{"a":1,"b":2}')
        self.assertNotIn(b" ", payload)


if __name__ == "__main__":
    unittest.main()
