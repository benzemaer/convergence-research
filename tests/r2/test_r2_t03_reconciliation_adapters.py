# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from src.r2.r2_t02_protocol_freeze import (
    DailyInput,
    atomic_intervals,
    group_event_zones,
    replay_confirmation,
)
from src.r2.r2_t03_event_zone_scan import (
    R2T03Error,
    _materialize_authoritative_expected_keys,
    adapter_contract_status,
    build_expected_security_dates,
    reconcile_atomic_interval_rows,
    validate_source_readiness,
)
from src.r2.r2_t03_input_adapters import (
    R2T03AdapterError,
    assert_expected_completeness,
    build_base_expected_keys,
    derive_source_termination_reason,
    eod_available_time,
    expand_expected_route_keys,
    normalize_interval_row,
    normalize_termination_reason,
    reconcile_interval_multiset,
)


class R2T03ReconciliationAdapterTest(unittest.TestCase):
    def test_expected_keys_use_authoritative_calendar_and_applicability(self) -> None:
        actual = build_expected_security_dates(
            ["S1", "S2"],
            ["2026-01-01", "2026-01-02"],
            [("S1", "2026-01-01"), ("S1", "2026-01-02"), ("S2", "2026-01-02")],
        )
        self.assertEqual(actual["S1"], ["2026-01-01", "2026-01-02"])
        self.assertEqual(actual["S2"], ["2026-01-02"])
        with self.assertRaisesRegex(R2T03Error, "outside_authoritative_domain"):
            build_expected_security_dates(
                ["S1"], ["2026-01-01"], [("S2", "2026-01-01")]
            )

    def test_interval_reconciliation_is_row_level_and_exact(self) -> None:
        row = {
            "route_id": "r1",
            "security_id": "S1",
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
            "confirmed_day_count": 3,
            "termination_reason": "natural_state_exit",
        }
        self.assertEqual(
            reconcile_atomic_interval_rows([row], [dict(row)])["status"], "passed"
        )
        mutated = {**row, "termination_reason": "quality_interruption"}
        failed = reconcile_atomic_interval_rows([row], [mutated])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["rebuilt_row_count"], 1)
        self.assertEqual(failed["upstream_row_count"], 1)
        duplicate = reconcile_atomic_interval_rows([row, row], [row])
        self.assertEqual(duplicate["status"], "failed")
        self.assertEqual(duplicate["unexpected_multiset_row_count"], 1)

    def test_interval_reconciliation_missing_field_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            R2T03Error, "interval_reconciliation_missing_field"
        ):
            reconcile_atomic_interval_rows([{"route_id": "r1"}], [])

    def test_current_adapters_are_explicitly_unresolved(self) -> None:
        config = {
            "inputs": {},
            "semantics": {
                "availability_adapter_status": "unresolved_upstream_contract",
                "availability_upstream_contract_path": "",
                "expected_key_adapter_status": "unresolved_upstream_contract",
                "expected_key_upstream_contract_path": "",
                "interval_reconciliation_adapter_status": "unresolved_upstream_contract",
                "interval_reconciliation_upstream_contract_path": "",
            },
        }
        actual = adapter_contract_status(config)
        self.assertEqual(
            actual["availability_adapter_status"], "unresolved_upstream_contract"
        )
        self.assertEqual(
            actual["expected_key_adapter_status"], "unresolved_upstream_contract"
        )
        self.assertEqual(
            actual["interval_reconciliation_adapter_status"],
            "unresolved_upstream_contract",
        )
        with self.assertRaisesRegex(
            R2T03Error, "availability_adapter_status:unresolved_upstream_contract"
        ):
            validate_source_readiness(config, [], root=Path("."))

    def test_config_claim_without_contract_file_is_not_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "inputs": {},
                "semantics": {
                    "availability_adapter_status": "resolved_research_policy",
                    "expected_key_adapter_status": "resolved_upstream_adapter",
                    "interval_reconciliation_adapter_status": "resolved_upstream_adapter",
                },
                "availability_policy_contract_path": "missing.json",
                "expected_key_adapter_contract_path": "missing.json",
                "expected_key_adapter_validation_path": "missing-validation.json",
                "interval_adapter_contract_path": "missing.json",
                "interval_adapter_validation_path": "missing-validation.json",
            }
            actual = adapter_contract_status(config, root=root)
            self.assertEqual(
                actual["availability_adapter_status"], "unresolved_upstream_contract"
            )
            self.assertEqual(
                actual["expected_key_adapter_status"], "unresolved_upstream_contract"
            )

    def test_expected_adapter_rechecks_actual_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            database = root / "source.duckdb"
            manifest.write_bytes(b"manifest\n")
            database.write_bytes(b"source-v2")
            old_database_sha = hashlib.sha256(b"source-v1").hexdigest()
            contract = {
                "source_manifest_path": "manifest.json",
                "source_manifest_sha256": hashlib.sha256(b"manifest\n").hexdigest(),
                "source_duckdb_path": "source.duckdb",
                "source_duckdb_sha256": old_database_sha,
            }
            validation = {
                "status": "passed",
                "source_manifest_sha256": contract["source_manifest_sha256"],
                "source_duckdb_sha256": old_database_sha,
            }
            (root / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
            (root / "validation.json").write_text(
                json.dumps(validation), encoding="utf-8"
            )
            actual = adapter_contract_status(
                {
                    "semantics": {
                        "expected_key_adapter_status": "resolved_upstream_adapter"
                    },
                    "expected_key_adapter_contract_path": "contract.json",
                    "expected_key_adapter_validation_path": "validation.json",
                },
                root=root,
            )
            self.assertEqual(
                actual["expected_key_adapter_status"], "unresolved_upstream_contract"
            )

    def test_v2_committed_contracts_resolve_only_when_actual_sources_exist(
        self,
    ) -> None:
        config = json.loads(
            Path("configs/r2/r2_t03_four_route_event_zone_scan.v2.json").read_text(
                encoding="utf-8"
            )
        )
        actual = adapter_contract_status(config)
        self.assertEqual(
            actual["availability_adapter_status"], "resolved_research_policy"
        )
        expected_contract = json.loads(
            Path(config["expected_key_adapter_contract_path"]).read_text(
                encoding="utf-8"
            )
        )
        interval_contract = json.loads(
            Path(config["interval_adapter_contract_path"]).read_text(encoding="utf-8")
        )
        source_bytes_present = Path(expected_contract["source_duckdb_path"]).is_file()
        interval_bytes_present = all(
            Path(row["interval_path"]).is_file()
            for row in interval_contract["route_mappings"]
        )
        self.assertEqual(
            actual["expected_key_adapter_status"],
            "resolved_upstream_adapter"
            if source_bytes_present
            else "unresolved_upstream_contract",
        )
        self.assertEqual(
            actual["interval_reconciliation_adapter_status"],
            "resolved_upstream_adapter"
            if interval_bytes_present
            else "unresolved_upstream_contract",
        )

    def test_v2_config_and_adapter_contracts_validate_against_schemas(self) -> None:
        pairs = [
            (
                "schemas/r2/r2_t03_eod_availability_policy.schema.json",
                "configs/r2/r2_t03_eod_availability_policy.v1.json",
            ),
            (
                "schemas/r2/r2_t03_expected_key_adapter.schema.json",
                "configs/r2/r2_t03_expected_key_adapter.v1.json",
            ),
            (
                "schemas/r2/r2_t03_interval_adapter.schema.json",
                "configs/r2/r2_t03_interval_adapter.v1.json",
            ),
            (
                "schemas/r2/r2_t03_four_route_event_zone_scan_config.v2.schema.json",
                "configs/r2/r2_t03_four_route_event_zone_scan.v2.json",
            ),
        ]
        for schema_path, config_path in pairs:
            schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(
                json.loads(Path(config_path).read_text(encoding="utf-8"))
            )

    def test_eod_availability_exact_offset_and_no_rollover(self) -> None:
        self.assertEqual(eod_available_time("20260102"), "2026-01-02T15:00:00+08:00")
        self.assertEqual(eod_available_time("20260103"), "2026-01-03T15:00:00+08:00")
        self.assertNotEqual(
            eod_available_time("20260102"), eod_available_time("20260103")
        )

    def test_confirmation_qualification_finalization_and_bridge_times(self) -> None:
        raw = [True, True, True, False, True, True, True, False, False]
        daily = [
            DailyInput(
                "S",
                f"2026-01-{i:02d}",
                eod_available_time(f"202601{i:02d}"),
                True,
                "valid",
                value,
            )
            for i, value in enumerate(raw, 1)
        ]
        timeline, _ = replay_confirmation(daily, [row.trade_date for row in daily])
        self.assertEqual(timeline[2]["confirmation_time"], "2026-01-03T15:00:00+08:00")
        components, zones, _ = group_event_zones(
            timeline, atomic_intervals(timeline), 1, 1, candidate_cell_id="c"
        )
        self.assertEqual(
            components[0]["event_qualification_time"], "2026-01-03T15:00:00+08:00"
        )
        self.assertEqual(
            zones[0]["zone_finalization_time"], "2026-01-09T15:00:00+08:00"
        )
        bridge = next(
            row for row in zones[0]["membership_rows"] if row["is_raw_false_bridge"]
        )
        self.assertGreaterEqual(
            bridge["membership_available_time"],
            components[1]["event_qualification_time"],
        )
        self.assertNotEqual(
            bridge["membership_available_time"],
            components[0]["event_qualification_time"],
        )

    def test_expected_formula_keeps_nonvalid_and_missing_observation_dates(
        self,
    ) -> None:
        calendar = [
            {"trade_date": "20260101", "is_open": 0},
            {"trade_date": "20260102", "is_open": 1},
            {"trade_date": "20260103", "is_open": 1},
            {"trade_date": "20260104", "is_open": 1},
        ]
        lifecycle = [
            {"security_id": "S1", "list_date": "20260102", "delist_date": "20260103"},
            {"security_id": "S2", "list_date": "20260103", "delist_date": ""},
        ]
        base = build_base_expected_keys(
            ["S1", "S2"], calendar, lifecycle, date_min="20260101", date_max="20260104"
        )
        self.assertEqual(
            base,
            [
                ("S1", "20260102"),
                ("S1", "20260103"),
                ("S2", "20260103"),
                ("S2", "20260104"),
            ],
        )
        routes = [f"r{i}" for i in range(8)]
        expanded = expand_expected_route_keys(base, routes)
        self.assertEqual(len(expanded), len(base) * 8)
        self.assertEqual(len({route for route, _, _ in expanded}), 8)
        with self.assertRaisesRegex(
            R2T03AdapterError, "observed_row_outside_expected_keys"
        ):
            assert_expected_completeness(
                expanded, expanded + [("r0", "S0", "20260102")]
            )
        with self.assertRaisesRegex(
            R2T03AdapterError, "expected_row_absent_from_observed"
        ):
            assert_expected_completeness(expanded, expanded[:-1])
        with self.assertRaisesRegex(R2T03AdapterError, "duplicate_expected_route_key"):
            assert_expected_completeness(expanded + [expanded[0]], expanded)

    def test_interval_reason_mapping_geometry_and_multiset(self) -> None:
        expected = {
            "raw_state_false": "natural_state_exit",
            "end_of_input_open": "sample_end_censoring",
            "raw_state_blocked": "quality_interruption",
            "raw_state_diagnostic_required": "quality_interruption",
            "raw_state_unknown": "quality_interruption",
        }
        self.assertEqual(
            {key: normalize_termination_reason(key) for key in expected}, expected
        )
        with self.assertRaisesRegex(R2T03AdapterError, "unregistered_source"):
            normalize_termination_reason("legacy_unknown")
        base = {
            "route_id": "r",
            "security_id": "S",
            "source_interval_id": "i",
            "confirmed_start_date": "20260102",
            "confirmation_date": "20260102",
            "interval_end_date": "20260104",
            "last_observed_date": "20260105",
            "confirmed_duration_observations": 3,
            "source_kind": "r0",
            "source_artifact_sha256": "a" * 64,
        }
        closed = normalize_interval_row(
            {
                **base,
                "source_termination_reason": "raw_state_false",
                "is_open_interval": False,
            }
        )
        self.assertEqual(
            (closed["end_date"], closed["termination_reason"]),
            ("20260104", "natural_state_exit"),
        )
        opened = normalize_interval_row(
            {
                **base,
                "source_termination_reason": "end_of_input_open",
                "is_open_interval": True,
            }
        )
        self.assertEqual(
            (opened["end_date"], opened["termination_reason"]),
            ("20260105", "sample_end_censoring"),
        )
        self.assertEqual(
            derive_source_termination_reason(
                {"quality_state": "blocked", "raw_state": None}
            ),
            "raw_state_blocked",
        )
        self.assertEqual(
            derive_source_termination_reason(None, is_open_interval=True),
            "end_of_input_open",
        )
        with self.assertRaisesRegex(
            R2T03AdapterError, "closed_interval_terminal_decision_missing"
        ):
            derive_source_termination_reason(None, is_open_interval=False)
        result = reconcile_interval_multiset([closed, closed], [closed])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["unexpected_multiset_row_count"], 1)

    def test_t15_closed_interval_uses_last_observed_decision_row_semantics(
        self,
    ) -> None:
        self.assertEqual(
            derive_source_termination_reason(
                {"quality_state": "valid", "raw_state": False},
                is_open_interval=False,
            ),
            "raw_state_false",
        )
        for quality, expected in [
            ("blocked", "raw_state_blocked"),
            ("diagnostic_required", "raw_state_diagnostic_required"),
        ]:
            with self.subTest(quality=quality):
                self.assertEqual(
                    derive_source_termination_reason(
                        {"quality_state": quality, "raw_state": None},
                        is_open_interval=False,
                    ),
                    expected,
                )

    def test_dense_expected_surface_materializes_expected_empty_hard_break(
        self,
    ) -> None:
        import duckdb

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "expected.duckdb"
            with duckdb.connect(str(source)) as source_con:
                source_con.execute(
                    "CREATE TABLE d2_expected_security_dates(ts_code VARCHAR,trade_date VARCHAR)"
                )
                source_con.execute(
                    "CREATE TABLE d2_source_status(ts_code VARCHAR,trade_date VARCHAR,trading_status VARCHAR)"
                )
                source_con.execute(
                    "INSERT INTO d2_expected_security_dates VALUES ('S1','20260102'),('S1','20260103')"
                )
                source_con.execute(
                    "INSERT INTO d2_source_status VALUES ('S1','20260103','suspended')"
                )
            contract = {
                "expected_skeleton_source": {
                    "source_duckdb_path": "expected.duckdb",
                    "table": "d2_expected_security_dates",
                    "security_id_field": "ts_code",
                    "trade_date_field": "trade_date",
                },
                "date_min": "20260102",
                "date_max": "20260103",
            }
            (root / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
            con = duckdb.connect()
            con.execute("CREATE TABLE cell_registry(route_id VARCHAR)")
            con.execute("INSERT INTO cell_registry VALUES ('r1')")
            con.execute(
                """CREATE TABLE route_source_daily(route_id VARCHAR,security_id VARCHAR,
                trade_date DATE,available_time VARCHAR,eligible BOOLEAN,quality_state VARCHAR,
                raw_state BOOLEAN,confirmed_state BOOLEAN,confirmed_start_date DATE,
                confirmation_time VARCHAR,state_risk_set_eligible BOOLEAN,
                expected_empty_reason VARCHAR,source_row_present BOOLEAN)"""
            )
            con.execute(
                "INSERT INTO route_source_daily VALUES ('r1','S1',DATE '2026-01-02','2026-01-02T15:00:00+08:00',true,'valid',true,false,NULL,NULL,false,NULL,true)"
            )
            _materialize_authoritative_expected_keys(
                con, {"expected_key_adapter_contract_path": "contract.json"}, root
            )
            self.assertEqual(
                con.execute(
                    "SELECT eligible,quality_state,raw_state FROM route_source_daily WHERE trade_date=DATE '2026-01-03'"
                ).fetchone(),
                (False, "expected_empty", None),
            )
            self.assertEqual(
                con.execute("SELECT count(*) FROM route_source_daily").fetchone()[0], 2
            )
            con.close()


if __name__ == "__main__":
    unittest.main()
