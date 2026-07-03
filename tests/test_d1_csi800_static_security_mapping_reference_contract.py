from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT / "schemas/d1_csi800_static_security_mapping_reference_contract.schema.json"
)
CONFIG_PATH = (
    ROOT
    / "configs/d1/csi800_static_2026_06_security_mapping_reference_contract.v1.json"
)
MEMBERSHIP_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"
)
FIELD_ALIAS_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_field_aliases.v1.json"
)

ROW_LEVEL_FIELDS = (
    "member_rows",
    "members",
    "constituents",
    "rows",
    "tickers",
    "source_symbols",
    "security_ids",
)


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D1CSI800StaticSecurityMappingReferenceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.membership_contract = load(MEMBERSHIP_CONTRACT_PATH)
        cls.field_alias_contract = load(FIELD_ALIAS_CONTRACT_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def validate(self, config: dict[str, object]) -> None:
        self.validator.validate(config)

    def test_security_mapping_reference_schema_and_config_are_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validate(self.config)

    def test_config_aligns_with_membership_contract(self) -> None:
        universe = self.membership_contract["universe"]
        evidence = self.membership_contract["source_evidence"]
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

    def test_config_aligns_with_field_alias_contract(self) -> None:
        self.assertEqual(
            self.config["field_alias_contract_id"],
            self.field_alias_contract["contract_id"],
        )
        self.assertEqual(
            self.config["field_alias_contract_version"],
            self.field_alias_contract["contract_version"],
        )

    def test_security_mapping_source_rules_are_strict(self) -> None:
        source = self.config["security_mapping_source"]
        shortcuts = self.config["prohibited_mapping_shortcuts"]
        self.assertEqual(source["source_domain"], "D1_SECURITY_MASTER")
        self.assertEqual(source["mapping_key_fields"], ["ticker", "exchange"])
        self.assertEqual(source["effective_date"], "2026-06-12")
        self.assertFalse(shortcuts["using_csindex_raw_evidence_as_security_id_source"])
        self.assertFalse(shortcuts["fabricate_security_id_mapping_reference"])
        self.assertFalse(shortcuts["ticker_only_mapping_allowed"])
        self.assertFalse(shortcuts["exchange_agnostic_mapping_allowed"])

    def test_unresolved_mapping_policy_blocks_materialization(self) -> None:
        policy = self.config["unresolved_mapping_policy"]
        gate = self.config["materialization_gate"]
        self.assertEqual(policy["missing_match_action"], "block_materialization")
        self.assertEqual(policy["duplicate_match_action"], "block_materialization")
        self.assertEqual(
            policy["inactive_or_delisted_ambiguity_action"],
            "block_materialization",
        )
        self.assertTrue(
            gate["security_id_mapping_reference_required_before_membership_rows"]
        )
        self.assertTrue(gate["all_800_rows_must_map"])
        self.assertTrue(gate["no_unmapped_rows_allowed"])
        self.assertTrue(gate["no_duplicate_security_id_for_same_membership_row"])

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

    def test_prohibited_mapping_source_or_shortcuts_are_rejected(self) -> None:
        changes = (
            ("security_mapping_source", "source_domain", "CSINDEX_OFFICIAL"),
            (
                "prohibited_mapping_shortcuts",
                "using_csindex_raw_evidence_as_security_id_source",
                True,
            ),
            (
                "prohibited_mapping_shortcuts",
                "fabricate_security_id_mapping_reference",
                True,
            ),
            ("prohibited_mapping_shortcuts", "ticker_only_mapping_allowed", True),
            (
                "prohibited_mapping_shortcuts",
                "exchange_agnostic_mapping_allowed",
                True,
            ),
        )
        for section, key, value in changes:
            changed = deepcopy(self.config)
            changed[section][key] = value
            with self.subTest(section=section, key=key):
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


if __name__ == "__main__":
    unittest.main()
