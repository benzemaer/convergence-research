from __future__ import annotations

import json
import unittest
from pathlib import Path

import duckdb

from src.r2.r2_t05_canonical_materialization import _canonical_json, _create_output_schema, _event_identity


ROOT = Path(__file__).resolve().parents[2]


class R2T05CanonicalMaterializationContractTest(unittest.TestCase):
    def test_config_freezes_two_selected_versions_and_exclusions(self) -> None:
        config = json.loads((ROOT / "configs/r2/r2_t05_canonical_state_event_zone_materialization.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(len(config["selected_versions"]), 2)
        self.assertEqual({row["W"] for row in config["selected_versions"]}, {120})
        self.assertEqual({row["d"] for row in config["selected_versions"]}, {2})
        self.assertEqual({row["g"] for row in config["selected_versions"]}, {1})
        self.assertEqual(config["exclusions"]["W250_materialized_version_count"], 0)
        self.assertEqual(config["exclusions"]["shared_q_independent_state_version_count"], 0)
        self.assertEqual(config["exclusions"]["PCT_parent_product_count"], 0)

    def test_event_identity_is_independent_of_revision_and_later_components(self) -> None:
        config = {"contract_version": "r2_t02_confirmed_event_zone_state_machine_contract.v8"}
        version = {"state_version_id": "state-a"}
        first = ("cell-a", "scan-a", "000001.SZ", "component_001", "2020-01-02", "2020-01-03T15:00:00+08:00")
        event_id, payload, _ = _event_identity(config, version, first)
        revised_id, revised_payload, _ = _event_identity(config, version, first)
        self.assertEqual(event_id, revised_id)
        self.assertEqual(payload, revised_payload)
        self.assertNotIn("zone_revision", payload)
        self.assertNotIn("component_002", payload)

    def test_event_identity_separates_state_version_and_security(self) -> None:
        config = {"contract_version": "r2_t02_confirmed_event_zone_state_machine_contract.v8"}
        first = ("cell-a", "scan-a", "000001.SZ", "component_001", "2020-01-02", "2020-01-03T15:00:00+08:00")
        base = _event_identity(config, {"state_version_id": "state-a"}, first)[0]
        other_state = _event_identity(config, {"state_version_id": "state-b"}, first)[0]
        other_security = _event_identity(config, {"state_version_id": "state-a"}, (*first[:2], "000002.SZ", *first[3:]))[0]
        self.assertNotEqual(base, other_state)
        self.assertNotEqual(base, other_security)

    def test_public_schema_has_closed_primary_keys(self) -> None:
        con = duckdb.connect(":memory:")
        _create_output_schema(con)
        for table in ("r2_canonical_daily_state", "r2_canonical_event_zone", "r2_canonical_event_membership"):
            columns = {row[0] for row in con.execute(f'DESCRIBE "{table}"').fetchall()}
            self.assertGreater(len(columns), 10)
        constraints = con.execute("SELECT table_name,constraint_type FROM duckdb_constraints() WHERE table_name LIKE 'r2_canonical_%'").fetchall()
        self.assertGreaterEqual(sum(row[1] == "PRIMARY KEY" for row in constraints), 3)
        con.close()

    def test_canonical_serialization_is_sorted_and_compact(self) -> None:
        payload = _canonical_json({"b": 2, "a": 1})
        self.assertEqual(payload, b'{"a":1,"b":2}')
        self.assertNotIn(b" ", payload)


if __name__ == "__main__":
    unittest.main()
