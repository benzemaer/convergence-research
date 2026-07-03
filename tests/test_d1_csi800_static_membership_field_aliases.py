from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/d1_csi800_static_membership_field_aliases.schema.json"
CONFIG_PATH = ROOT / "configs/d1/csi800_static_2026_06_membership_field_aliases.v1.json"
CONTRACT_PATH = ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"
DIAGNOSTICS_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_field_diagnostics.v1.json"
)

ROW_LEVEL_FIELDS = (
    "member_rows",
    "members",
    "constituents",
    "rows",
    "tickers",
    "source_symbols",
)


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D1CSI800StaticMembershipFieldAliasesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.contract = load(CONTRACT_PATH)
        cls.diagnostics = load(DIAGNOSTICS_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def validate(self, config: dict[str, object]) -> None:
        self.validator.validate(config)

    def test_field_alias_schema_and_config_are_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validate(self.config)

    def test_alias_contract_aligns_with_contract_and_diagnostics(self) -> None:
        universe = self.contract["universe"]
        evidence = self.contract["source_evidence"]
        self.assertEqual(self.config["universe_id"], universe["universe_id"])
        self.assertEqual(self.config["index_code"], universe["index_code"])
        self.assertEqual(
            self.config["source_snapshot_id"],
            evidence["source_snapshot_id"],
        )
        self.assertEqual(
            self.config["raw_evidence_sha256_expected"],
            evidence["raw_evidence_sha256"],
        )
        self.assertEqual(
            self.config["observed_columns_hash"],
            self.diagnostics["observed_columns_hash"],
        )
        self.assertEqual(
            self.config["observed_column_count"],
            self.diagnostics["observed_column_count"],
        )

    def test_aliases_are_approved_diagnostics_candidates(self) -> None:
        aliases = self.config["canonical_field_aliases"]
        candidates = self.diagnostics["candidate_aliases_by_required_field"]
        self.assertEqual(
            aliases["source_symbol"]["source_columns"],
            ["成份券代码Constituent Code"],
        )
        self.assertEqual(
            aliases["ticker"]["source_columns"],
            ["成份券代码Constituent Code"],
        )
        self.assertIn(
            aliases["source_symbol"]["source_columns"][0],
            candidates["source_symbol"],
        )
        self.assertIn(aliases["ticker"]["source_columns"][0], candidates["ticker"])
        self.assertIn(
            aliases["exchange"]["primary_source_column"],
            candidates["exchange"],
        )
        for column in aliases["exchange"]["fallback_source_columns"]:
            self.assertIn(column, candidates["exchange"])

    def test_security_id_mapping_reference_remains_deferred(self) -> None:
        mapping_alias = self.config["canonical_field_aliases"][
            "security_id_mapping_reference"
        ]
        self.assertEqual(mapping_alias["source_columns"], [])
        self.assertTrue(mapping_alias["cannot_be_sourced_from_csindex"])
        self.assertTrue(mapping_alias["deferred_to_d1_security_master_mapping"])
        self.assertTrue(mapping_alias["required_before_materialization"])
        self.assertEqual(
            mapping_alias["status"],
            "deferred_to_d1_security_master_mapping",
        )

    def test_no_artifact_or_materialization_flags_are_false(self) -> None:
        for field in (
            "row_level_detail_included",
            "raw_bytes_committed",
            "member_rows_committed",
            "duckdb_written",
            "run_manifest_created",
            "dataset_manifest_created",
            "materialization_authorized",
            "member_rows_materialized",
        ):
            with self.subTest(field=field):
                self.assertFalse(self.config[field])
        self.assertEqual(
            self.config["downstream_decision"],
            "materialization_remains_blocked",
        )

    def test_row_level_fields_are_rejected(self) -> None:
        for field in ROW_LEVEL_FIELDS:
            changed = deepcopy(self.config)
            changed[field] = []
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_raw_security_mapping_source_column_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["canonical_field_aliases"]["security_id_mapping_reference"][
            "source_columns"
        ] = ["成份券代码Constituent Code"]
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_artifact_or_materialization_flags_true_are_rejected(self) -> None:
        for field in (
            "row_level_detail_included",
            "raw_bytes_committed",
            "member_rows_committed",
            "duckdb_written",
            "run_manifest_created",
            "dataset_manifest_created",
            "materialization_authorized",
            "member_rows_materialized",
        ):
            changed = deepcopy(self.config)
            changed[field] = True
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_alias_column_absent_from_diagnostics_is_rejected(self) -> None:
        changes = (
            ("source_symbol", "source_columns", ["absent column"]),
            ("ticker", "source_columns", ["absent column"]),
            ("exchange", "primary_source_column", "absent column"),
            ("exchange", "fallback_source_columns", ["absent column"]),
        )
        for field, key, value in changes:
            changed = deepcopy(self.config)
            changed["canonical_field_aliases"][field][key] = value
            with self.subTest(field=field, key=key):
                with self.assertRaises(ValidationError):
                    self.validate(changed)


if __name__ == "__main__":
    unittest.main()
