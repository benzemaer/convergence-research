from __future__ import annotations

import json
import unittest
from pathlib import Path

import duckdb

from src.r2.r2_t05_canonical_materialization import (
    _canonical_json,
    _create_output_schema,
    _daily_semantic_audit,
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
            CREATE TABLE src.cell_registry(
              candidate_cell_id VARCHAR, route_id VARCHAR
            );
            CREATE TABLE src.qualified_component(
              candidate_cell_id VARCHAR, security_id VARCHAR, component_id VARCHAR,
              start_date DATE, end_date DATE, qualified BOOLEAN,
              event_qualification_time TIMESTAMPTZ
            );
            CREATE TABLE src.event_zone(
              candidate_cell_id VARCHAR, security_id VARCHAR, scan_event_id VARCHAR,
              first_component_id VARCHAR, zone_finalization_time TIMESTAMPTZ,
              status VARCHAR
            );
            CREATE TABLE src.event_zone_bridge_segment(
              candidate_cell_id VARCHAR, security_id VARCHAR, scan_event_id VARCHAR,
              left_component_id VARCHAR, right_component_id VARCHAR,
              merge_accepted BOOLEAN
            );
            CREATE TABLE src.reentry_attempt(
              candidate_cell_id VARCHAR, security_id VARCHAR, scan_event_id VARCHAR,
              source_component_id VARCHAR, start_date DATE, end_date DATE,
              outcome VARCHAR
            );
            CREATE TABLE src.event_zone_membership_daily(
              candidate_cell_id VARCHAR, security_id VARCHAR, trade_date DATE,
              available_time TIMESTAMPTZ, evaluation_time TIMESTAMPTZ,
              scan_event_id VARCHAR, zone_status_as_of VARCHAR,
              event_zone_member BOOLEAN, component_qualified_as_of BOOLEAN,
              is_raw_false_bridge BOOLEAN, prequalification_member BOOLEAN,
              unqualified_reentry_member BOOLEAN
            );
            """
        )
        con.executemany(
            "INSERT INTO src.cell_registry VALUES (?,?)",
            [("cell-a", "primary-a"), ("cell-b", "primary-b")],
        )
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
                    False,
                    True,
                    False,
                    False,
                    False,
                    "QUALIFIED_ACTIVE",
                    1,
                    "2024-01-02 11:00:00+08:00",
                    True,
                    False,
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
        con.executemany(
            "INSERT INTO src.event_zone VALUES (?,?,?,?,?,?)",
            [
                (
                    "cell-a",
                    "000001.SZ",
                    "scan-a",
                    "comp-a",
                    "2024-01-02 12:00:00+08:00",
                    "FINALIZED",
                ),
                (
                    "cell-b",
                    "000001.SZ",
                    "scan-b",
                    "comp-b",
                    "2024-01-02 10:00:00+08:00",
                    "FINALIZED",
                ),
            ],
        )
        con.executemany(
            "INSERT INTO src.qualified_component VALUES (?,?,?,?,?,?,?)",
            [
                (
                    "cell-a",
                    "000001.SZ",
                    "comp-a",
                    "2024-01-02",
                    "2024-01-02",
                    True,
                    "2024-01-02 10:00:00+08:00",
                ),
                (
                    "cell-b",
                    "000001.SZ",
                    "comp-b",
                    "2024-01-02",
                    "2024-01-02",
                    False,
                    "2024-01-02 10:00:00+08:00",
                ),
            ],
        )
        con.execute(
            """
            CREATE TEMP TABLE t05_event_map(
              state_version_id VARCHAR, source_candidate_cell_id VARCHAR,
              source_scan_event_id VARCHAR, security_id VARCHAR,
              first_component_id VARCHAR, first_component_start_date DATE,
              first_qualification_time TIMESTAMPTZ, canonical_event_id VARCHAR,
              identity_payload VARCHAR, identity_payload_sha256 VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO t05_event_map VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "state-a", "cell-a", "scan-a", "000001.SZ", "comp-a",
                    "2024-01-02", "2024-01-02 10:00:00+08:00", "event-a", "{}", "hash-a",
                ),
                (
                    "state-b", "cell-b", "scan-b", "000001.SZ", "comp-b",
                    "2024-01-02", "2024-01-02 10:00:00+08:00", "event-b", "{}", "hash-b",
                ),
            ],
        )
        con.execute(
            """
            CREATE TEMP TABLE t05_component_map AS
            SELECT canonical_event_id,state_version_id,source_candidate_cell_id,
                   source_scan_event_id,security_id,first_component_id component_id
            FROM t05_event_map
            """
        )
        con.execute(
            """
            INSERT INTO r2_t05_event_id_lineage
            SELECT state_version_id,source_candidate_cell_id,source_scan_event_id,
                   security_id,first_component_id,canonical_event_id,
                   identity_payload,identity_payload_sha256,'synthetic-run'
            FROM t05_event_map
            """
        )
        con.execute(
            """
            INSERT INTO src.event_zone_membership_daily VALUES
            ('cell-a','000001.SZ','2024-01-02','2024-01-02 11:00:00+08:00',
             '2024-01-02 11:00:00+08:00','scan-a','QUALIFIED_ACTIVE',true,true,
             false,false,false)
            """
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
            "UPDATE r2_canonical_daily_state SET component_qualified_as_of=false, qualified_event_risk_set_eligible=false WHERE state_version_id='state-a'"
        )
        semantic = _daily_semantic_audit(con, "state-a")
        self.assertGreater(semantic["daily_component_qualified_key_mismatch"], 0)
        self.assertGreater(semantic["qualified_component_transition_mismatch"], 0)
        self.assertEqual(
            _independent_daily_asof_mismatch(con, "state-a", "primary-a"), 1
        )
        con.execute(
            "UPDATE r2_canonical_daily_state SET component_qualified_as_of=true, qualified_event_risk_set_eligible=true WHERE state_version_id='state-a'"
        )
        con.execute(
            "UPDATE r2_canonical_daily_state SET active_event_id_as_of='event-b' WHERE state_version_id='state-a'"
        )
        self.assertEqual(
            _independent_daily_asof_mismatch(con, "state-a", "primary-a"), 1
        )
        con.close()

    def test_independent_validator_enforces_reentry_component_semantics(self) -> None:
        con = duckdb.connect(":memory:")
        con.execute("CREATE SCHEMA src")
        con.execute(
            """
            CREATE TABLE src.cell_registry(candidate_cell_id VARCHAR,route_id VARCHAR);
            CREATE TABLE src.route_daily(
              route_id VARCHAR,security_id VARCHAR,trade_date DATE,
              available_time TIMESTAMPTZ
            );
            CREATE TABLE src.event_zone_membership_daily(
              candidate_cell_id VARCHAR,security_id VARCHAR,trade_date DATE,
              available_time TIMESTAMPTZ,evaluation_time TIMESTAMPTZ,
              scan_event_id VARCHAR,zone_status_as_of VARCHAR,
              event_zone_member BOOLEAN,is_raw_false_bridge BOOLEAN,
              prequalification_member BOOLEAN,unqualified_reentry_member BOOLEAN
            );
            CREATE TABLE src.event_zone(
              candidate_cell_id VARCHAR,security_id VARCHAR,scan_event_id VARCHAR,
              first_component_id VARCHAR,zone_finalization_time TIMESTAMPTZ,
              status VARCHAR
            );
            CREATE TABLE src.event_zone_bridge_segment(
              candidate_cell_id VARCHAR,security_id VARCHAR,scan_event_id VARCHAR,
              left_component_id VARCHAR,right_component_id VARCHAR,
              merge_accepted BOOLEAN
            );
            CREATE TABLE src.reentry_attempt(
              candidate_cell_id VARCHAR,security_id VARCHAR,scan_event_id VARCHAR,
              source_component_id VARCHAR,start_date DATE,end_date DATE,
              outcome VARCHAR
            );
            CREATE TABLE src.qualified_component(
              candidate_cell_id VARCHAR,security_id VARCHAR,component_id VARCHAR,
              start_date DATE,end_date DATE,qualified BOOLEAN,
              event_qualification_time TIMESTAMPTZ
            );
            CREATE TABLE r2_t05_event_id_lineage(
              state_version_id VARCHAR,source_candidate_cell_id VARCHAR,
              source_scan_event_id VARCHAR,security_id VARCHAR,
              first_component_id VARCHAR,canonical_event_id VARCHAR,
              identity_payload VARCHAR,identity_payload_sha256 VARCHAR,
              source_run_id VARCHAR
            );
            CREATE TABLE r2_canonical_daily_state(
              state_version_id VARCHAR,security_id VARCHAR,trade_date DATE,
              candidate_config_id VARCHAR,state_risk_set_eligible BOOLEAN,
              component_qualified_as_of BOOLEAN,event_status_as_of VARCHAR,
              active_event_id_as_of VARCHAR,
              qualified_event_risk_set_eligible BOOLEAN
            );
            """
        )
        con.executemany(
            "INSERT INTO src.cell_registry VALUES (?,?)",
            [("cell-a", "route-a"), ("cell-b", "route-b")],
        )
        con.executemany(
            "INSERT INTO src.route_daily VALUES (?,?,?,?)",
            [
                (route, "000001.SZ", date, f"{date} 12:00:00+08:00")
                for route in ("route-a", "route-b")
                for date in ("2024-01-03", "2024-01-04")
            ],
        )
        con.executemany(
            "INSERT INTO src.event_zone VALUES (?,?,?,?,?,?)",
            [
                ("cell-a", "000001.SZ", "scan-a", "old-a", None, "QUALIFIED_ACTIVE"),
                ("cell-b", "000001.SZ", "scan-b", "base-b", None, "REENTRY_PENDING_QUALIFICATION"),
            ],
        )
        con.execute(
            "INSERT INTO src.event_zone_bridge_segment VALUES (?,?,?,?,?,?)",
            ("cell-a", "000001.SZ", "scan-a", "old-a", "accepted-a", True),
        )
        con.execute(
            "INSERT INTO src.reentry_attempt VALUES (?,?,?,?,?,?,?)",
            (
                "cell-b", "000001.SZ", "scan-b", "unqualified-b",
                "2024-01-03", "2024-01-04", "unqualified_reentry",
            ),
        )
        con.executemany(
            "INSERT INTO src.qualified_component VALUES (?,?,?,?,?,?,?)",
            [
                ("cell-a", "000001.SZ", "old-a", "2024-01-01", "2024-01-02", False, None),
                ("cell-a", "000001.SZ", "accepted-a", "2024-01-03", "2024-01-04", True, "2024-01-04 10:00:00+08:00"),
                ("cell-b", "000001.SZ", "base-b", "2024-01-01", "2024-01-02", False, None),
                ("cell-b", "000001.SZ", "unqualified-b", "2024-01-03", "2024-01-04", False, None),
            ],
        )
        con.executemany(
            "INSERT INTO src.event_zone_membership_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("cell-a", "000001.SZ", "2024-01-03", "2024-01-03 12:00:00+08:00", "2024-01-03 12:00:00+08:00", "scan-a", "REENTRY_PENDING_QUALIFICATION", True, False, False, False),
                ("cell-a", "000001.SZ", "2024-01-04", "2024-01-04 12:00:00+08:00", "2024-01-04 12:00:00+08:00", "scan-a", "QUALIFIED_ACTIVE", True, False, False, False),
                ("cell-b", "000001.SZ", "2024-01-03", "2024-01-03 12:00:00+08:00", "2024-01-03 12:00:00+08:00", "scan-b", "REENTRY_PENDING_QUALIFICATION", True, False, False, True),
                ("cell-b", "000001.SZ", "2024-01-04", "2024-01-04 12:00:00+08:00", "2024-01-04 12:00:00+08:00", "scan-b", "REENTRY_PENDING_QUALIFICATION", True, False, False, True),
            ],
        )
        con.executemany(
            "INSERT INTO r2_t05_event_id_lineage VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("state-a", "cell-a", "scan-a", "000001.SZ", "old-a", "event-a", "{}", "hash-a", "test"),
                ("state-b", "cell-b", "scan-b", "000001.SZ", "base-b", "event-b", "{}", "hash-b", "test"),
            ],
        )
        con.executemany(
            "INSERT INTO r2_canonical_daily_state VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("state-a", "000001.SZ", "2024-01-03", "cell-a", True, False, "REENTRY_PENDING_QUALIFICATION", "event-a", False),
                ("state-a", "000001.SZ", "2024-01-04", "cell-a", True, True, "QUALIFIED_ACTIVE", "event-a", True),
                ("state-b", "000001.SZ", "2024-01-03", "cell-b", True, False, "REENTRY_PENDING_QUALIFICATION", "event-b", False),
                ("state-b", "000001.SZ", "2024-01-04", "cell-b", True, False, "REENTRY_PENDING_QUALIFICATION", "event-b", False),
            ],
        )
        self.assertEqual(_independent_daily_asof_mismatch(con, "state-a", "route-a"), 0)
        self.assertEqual(_independent_daily_asof_mismatch(con, "state-b", "route-b"), 0)
        con.execute(
            "UPDATE r2_canonical_daily_state SET component_qualified_as_of=true, qualified_event_risk_set_eligible=true WHERE state_version_id='state-a' AND trade_date='2024-01-03'"
        )
        self.assertEqual(_independent_daily_asof_mismatch(con, "state-a", "route-a"), 1)
        con.execute(
            "UPDATE r2_canonical_daily_state SET component_qualified_as_of=false, qualified_event_risk_set_eligible=false WHERE state_version_id='state-a' AND trade_date='2024-01-03'"
        )
        con.execute(
            "UPDATE r2_canonical_daily_state SET component_qualified_as_of=true, qualified_event_risk_set_eligible=true WHERE state_version_id='state-b' AND trade_date='2024-01-04'"
        )
        self.assertEqual(_independent_daily_asof_mismatch(con, "state-b", "route-b"), 1)
        con.execute(
            "UPDATE r2_canonical_daily_state SET component_qualified_as_of=false, qualified_event_risk_set_eligible=false WHERE state_version_id='state-b' AND trade_date='2024-01-04'"
        )
        con.execute(
            "UPDATE r2_canonical_daily_state SET active_event_id_as_of='event-b' WHERE state_version_id='state-a' AND trade_date='2024-01-04'"
        )
        self.assertEqual(_independent_daily_asof_mismatch(con, "state-a", "route-a"), 1)
        con.close()

    def test_canonical_serialization_is_sorted_and_compact(self) -> None:
        payload = _canonical_json({"b": 2, "a": 1})
        self.assertEqual(payload, b'{"a":1,"b":2}')
        self.assertNotIn(b" ", payload)


if __name__ == "__main__":
    unittest.main()
