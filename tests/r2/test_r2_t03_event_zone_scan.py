# ruff: noqa: E501

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.r2.r2_t02_protocol_freeze import (
    DailyInput,
    atomic_intervals,
    group_event_zones,
    replay_confirmation,
)
from src.r2.r2_t03_event_zone_scan import (
    R2T03Error,
    RouteSpec,
    _bind_zone_terminal_reasons,
    _component_lineage_rows,
    _entity_transition_rows,
    load_config,
)
from src.r2.r2_t03_independent_validator import _equal
from src.r2.r2_t03_runtime_gates import (
    R2T03GateError,
    _compare,
    _threshold,
    _transition_closure_checks,
    _transition_registry_check,
    validate_runtime_gates,
)


class R2T03FailurePathTest(unittest.TestCase):
    def test_component_lineage_uses_exact_source_interval_id(self) -> None:
        route = RouteSpec(
            "r",
            "primary",
            "S_PCT",
            120,
            3,
            0.2,
            0.2,
            0.2,
            0.2,
            "r0",
            "source",
            "d",
            "i",
        )
        component = {
            "component_id": "c1",
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
            "confirmed_day_count": 3,
            "termination_reason": "natural_state_exit",
        }
        interval = {
            **component,
            "upstream_source_interval_id": "actual_r0_interval_42",
        }
        rows = _component_lineage_rows(route, "cell", "S1", [component], [interval])
        self.assertEqual(rows[0][3], "actual_r0_interval_42")

    def test_load_config_fails_closed_on_wrong_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"task_id": "R2-T02"}), encoding="utf-8")
            with self.assertRaisesRegex(R2T03Error, "config_task_id_mismatch"):
                load_config(path)

    def test_frozen_gate_comparison_fails_closed(self) -> None:
        self.assertTrue(_compare(3, ">=", 3))
        self.assertFalse(_compare(3, "<=", 2))
        self.assertFalse(_compare(None, ">=", 0))

    def test_dynamic_thresholds_use_upstream_denominators(self) -> None:
        self.assertEqual(
            _threshold(
                "s_pct_qualified_event_count",
                "qualified_event_count",
                (6000, 0),
                900,
            ),
            300,
        )
        self.assertEqual(
            _threshold("s_pcvt_unique_securities", "unique_securities", (0, 0), 1000),
            150,
        )

    def test_independent_numeric_comparison(self) -> None:
        self.assertTrue(_equal(0.3, 0.1 + 0.2))
        self.assertFalse(_equal(1, 2))
        self.assertFalse(_equal(None, 0))

    def test_runtime_validator_rejects_missing_contract_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "broken.duckdb"
            with duckdb.connect(str(database)) as con:
                con.execute("CREATE TABLE cell_registry(candidate_cell_id VARCHAR)")
            registry = root / "gates.csv"
            registry.write_text("implementation_stage\n", encoding="utf-8")
            with self.assertRaises(duckdb.Error):
                validate_runtime_gates(database, root, registry)

    def test_runtime_error_type_is_dedicated(self) -> None:
        self.assertTrue(issubclass(R2T03GateError, RuntimeError))

    def test_entity_ledger_closes_d1_component_event_bridge_and_reentry(self) -> None:
        components = [
            {
                "component_id": "component_001",
                "qualified": True,
                "termination_reason": "natural_state_exit",
            },
            {
                "component_id": "component_002",
                "qualified": False,
                "termination_reason": "natural_state_exit",
            },
        ]
        zones = [
            {
                "scan_event_id": "event_001",
                "status": "FINALIZED",
                "zone_finalization_time": "2026-01-10T15:00:00+08:00",
            }
        ]
        bridge = (
            "cell",
            "route",
            "S1",
            "event_001",
            "bridge_001",
            1,
            "component_001",
            "component_003",
            "2026-01-04",
            "2026-01-04",
            3,
            1,
            1,
            1,
            2,
            3,
            True,
            "bridge_accepted",
            "",
            "",
        )
        reentry = (
            "cell",
            "route",
            "S1",
            "event_001",
            "reentry_001",
            "component_002",
            "2026-01-05",
            "2026-01-06",
            "natural_state_exit",
            "unqualified_reentry",
        )
        rows = _entity_transition_rows(
            "cell", "S1", [], components, zones, [bridge], [reentry]
        )
        qualified = [
            row
            for row in rows
            if row[3] == "component" and row[6] == "QUALIFIED_ACTIVE"
        ]
        unqualified = [
            row
            for row in rows
            if row[3] == "component" and row[6] == "UNQUALIFIED_CLOSED"
        ]
        event_created = [
            row
            for row in rows
            if row[3] == "event_zone"
            and row[5] == "COMPONENT_FORMING"
            and row[6] == "QUALIFIED_ACTIVE"
            and row[7] == "d_qualification"
        ]
        event_terminal = [
            row for row in rows if row[3] == "event_zone" and row[6] == "FINALIZED"
        ]
        bridge_path = [row for row in rows if row[4] == "bridge_001"]
        reentry_path = [row for row in rows if row[4] == "reentry_001"]
        self.assertEqual(len(qualified), 1)
        self.assertEqual(len(unqualified), 1)
        self.assertEqual(len(event_created), 1)
        self.assertEqual(len(event_terminal), 1)
        self.assertEqual(len(bridge_path), 3)
        self.assertEqual(len(reentry_path), 3)

    def test_zone_terminal_binding_excludes_prequalification_censor(self) -> None:
        zones = [{"scan_event_id": "e1", "status": "FINALIZED"}]
        ledger = [
            {
                "scan_event_id": "component-only",
                "from_state": "COMPONENT_FORMING",
                "to_state": "RIGHT_CENSORED",
                "reason_code": "prequalification_right_censored",
            },
            {
                "scan_event_id": "e1",
                "from_state": "GAP_PENDING",
                "to_state": "FINALIZED",
                "reason_code": "raw_false_gap_exceeds_g",
            },
        ]
        _bind_zone_terminal_reasons(zones, ledger)
        self.assertEqual(zones[0]["terminal_reason_code"], "raw_false_gap_exceeds_g")

    def test_zone_terminal_binding_fails_on_unclosed_ledger(self) -> None:
        with self.assertRaisesRegex(R2T03Error, "zone_terminal_ledger_not_closed"):
            _bind_zone_terminal_reasons(
                [{"scan_event_id": "e1", "status": "RIGHT_CENSORED"}], []
            )

    def test_zone_terminal_binding_rejects_order_only_cross_event_match(self) -> None:
        zones = [
            {"scan_event_id": "e1", "status": "FINALIZED"},
            {"scan_event_id": "e2", "status": "RIGHT_CENSORED"},
        ]
        swapped = [
            {
                "scan_event_id": "e2",
                "from_state": "GAP_PENDING",
                "to_state": "FINALIZED",
                "reason_code": "raw_false_gap_exceeds_g",
            },
            {
                "scan_event_id": "e1",
                "from_state": "GAP_PENDING",
                "to_state": "RIGHT_CENSORED",
                "reason_code": "sample_end_open_zone",
            },
        ]
        with self.assertRaisesRegex(R2T03Error, "zone_terminal_state_mismatch"):
            _bind_zone_terminal_reasons(zones, swapped)

    def test_reference_timelines_bind_every_event_terminal_reason(self) -> None:
        cases = [
            ([True, True, True, False], 1, 0),
            ([True, True, True, True, False], 2, 0),
            ([True, True, True, True], 3, 0),
            ([True, True, True, False, True, True, True, False], 1, 0),
            ([True, True, True, False, True, True, True, False], 1, 1),
            ([True, True, True, False, False, True, True, True, False], 1, 2),
            ([True, True, True, False, False, True, True, True, False], 1, 1),
        ]
        for raw, d, g in cases:
            inputs = [
                DailyInput(
                    security_id="S1",
                    trade_date=f"2026-01-{index:02d}",
                    available_time=f"2026-01-{index:02d}T15:00:00+08:00",
                    eligible=True,
                    quality_state="valid",
                    raw_state=value,
                )
                for index, value in enumerate(raw, start=1)
            ]
            timeline, _ = replay_confirmation(
                inputs, [row.trade_date for row in inputs]
            )
            _, zones, ledger = group_event_zones(
                timeline, atomic_intervals(timeline), d, g
            )
            for zone, terminal in zip(
                zones,
                [
                    row
                    for row in ledger
                    if row["to_state"]
                    in {"FINALIZED", "FINALIZED_WITH_QUALITY_BREAK", "RIGHT_CENSORED"}
                    and row["from_state"]
                    in {"GAP_PENDING", "REENTRY_PENDING_QUALIFICATION"}
                ],
            ):
                terminal["scan_event_id"] = zone["scan_event_id"]
            _bind_zone_terminal_reasons(zones, ledger)
            self.assertTrue(all(zone.get("terminal_reason_code") for zone in zones))

    def test_runtime_transition_closure_detects_path_mutation(self) -> None:
        con = duckdb.connect(":memory:")
        try:
            con.execute(_TRANSITION_FIXTURE_SQL)
            checks = _transition_closure_checks(con)
            self.assertTrue(all(row["status"] == "passed" for row in checks))
            con.execute(
                """DELETE FROM transition_entity_ledger
                WHERE entity_kind='bridge' AND to_state='QUALIFIED_ACTIVE'"""
            )
            mutated = _transition_closure_checks(con)
            bridge = next(
                row
                for row in mutated
                if row["check_id"] == "accepted_bridge_transition_closure"
            )
            self.assertEqual(bridge["status"], "failed")
            con.execute(
                "INSERT INTO transition_entity_ledger VALUES ('c','S1',4,'event_zone','e1','FINALIZED','QUALIFIED_ACTIVE','illegal_reason')"
            )
            continuity = _transition_closure_checks(con)
            self.assertEqual(
                next(
                    row
                    for row in continuity
                    if row["check_id"] == "event_entity_no_transition_after_terminal"
                )["status"],
                "failed",
            )
            registry = _transition_registry_check(
                con,
                Path(
                    "data/generated/r2/r2_t02/R2-T02-20260712T1700Z/r2_t02_transition_registry.csv"
                ),
            )
            self.assertEqual(registry["status"], "failed")
        finally:
            con.close()


_TRANSITION_FIXTURE_SQL = """
CREATE TABLE qualified_component(candidate_cell_id VARCHAR,security_id VARCHAR,component_id VARCHAR,qualified BOOLEAN);
INSERT INTO qualified_component VALUES ('c','S1','q1',true),('c','S1','q2',false);
CREATE TABLE component_source_lineage(candidate_cell_id VARCHAR,security_id VARCHAR,component_id VARCHAR,normally_ended BOOLEAN);
INSERT INTO component_source_lineage VALUES ('c','S1','q1',true),('c','S1','q2',true);
CREATE TABLE event_zone(candidate_cell_id VARCHAR,security_id VARCHAR,scan_event_id VARCHAR);
INSERT INTO event_zone VALUES ('c','S1','e1');
CREATE TABLE event_zone_bridge_segment(candidate_cell_id VARCHAR,security_id VARCHAR,bridge_segment_id VARCHAR,merge_accepted BOOLEAN,decision_reason VARCHAR);
INSERT INTO event_zone_bridge_segment VALUES ('c','S1','b1',true,'bridge_accepted');
CREATE TABLE reentry_attempt(candidate_cell_id VARCHAR,security_id VARCHAR,reentry_attempt_id VARCHAR);
INSERT INTO reentry_attempt VALUES ('c','S1','r1');
CREATE TABLE transition_entity_ledger(candidate_cell_id VARCHAR,security_id VARCHAR,transition_ordinal INTEGER,entity_kind VARCHAR,entity_id VARCHAR,from_state VARCHAR,to_state VARCHAR,reason_code VARCHAR);
INSERT INTO transition_entity_ledger VALUES
('c','S1',1,'component','q1','COMPONENT_FORMING','QUALIFIED_ACTIVE','d_qualification'),
('c','S1',1,'component','q2','COMPONENT_FORMING','UNQUALIFIED_CLOSED','normal_short_interval_drop'),
('c','S1',1,'event_zone','e1','COMPONENT_FORMING','QUALIFIED_ACTIVE','d_qualification'),
('c','S1',2,'event_zone','e1','QUALIFIED_ACTIVE','GAP_PENDING','gap_pending'),
('c','S1',3,'event_zone','e1','GAP_PENDING','FINALIZED','raw_false_gap_exceeds_g'),
('c','S1',1,'bridge','b1','QUALIFIED_ACTIVE','GAP_PENDING','gap_pending'),
('c','S1',2,'bridge','b1','GAP_PENDING','REENTRY_PENDING_QUALIFICATION','reentry_pending'),
('c','S1',3,'bridge','b1','REENTRY_PENDING_QUALIFICATION','QUALIFIED_ACTIVE','reentry_reaches_d_merge'),
('c','S1',1,'reentry','r1','QUALIFIED_ACTIVE','GAP_PENDING','gap_pending'),
('c','S1',2,'reentry','r1','GAP_PENDING','REENTRY_PENDING_QUALIFICATION','unqualified_reentry_observed'),
('c','S1',3,'reentry','r1','REENTRY_PENDING_QUALIFICATION','FINALIZED','unqualified_reentry_blocks_merge');
"""


if __name__ == "__main__":
    unittest.main()
