from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT / "schemas/d1_csi800_static_security_mapping_output_contract.schema.json"
)
CONFIG_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_security_mapping_output_contract.v1.json"
)
MEMBERSHIP_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"
)
FIELD_ALIAS_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_field_aliases.v1.json"
)
REFERENCE_CONTRACT_PATH = (
    ROOT
    / "configs/d1/csi800_static_2026_06_security_mapping_reference_contract.v1.json"
)

REQUIRED_OUTPUT_FIELDS = [
    "universe_id",
    "source_snapshot_id",
    "membership_effective_date",
    "source_symbol",
    "ticker",
    "exchange",
    "security_id",
    "security_id_mapping_reference",
    "mapping_method",
    "mapping_status",
]

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


class D1CSI800StaticSecurityMappingOutputContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.membership_contract = load(MEMBERSHIP_CONTRACT_PATH)
        cls.field_alias_contract = load(FIELD_ALIAS_CONTRACT_PATH)
        cls.reference_contract = load(REFERENCE_CONTRACT_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def validate(self, config: dict[str, object]) -> None:
        self.validator.validate(config)

    def test_security_mapping_output_schema_and_config_are_valid(self) -> None:
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

    def test_config_aligns_with_alias_and_reference_contracts(self) -> None:
        self.assertEqual(
            self.config["field_alias_contract_id"],
            self.field_alias_contract["contract_id"],
        )
        self.assertEqual(
            self.config["security_mapping_reference_contract_id"],
            self.reference_contract["contract_id"],
        )
        self.assertEqual(
            self.config["mapping_key_fields"],
            [
                *self.reference_contract["security_mapping_source"][
                    "mapping_key_fields"
                ],
                "membership_effective_date",
            ],
        )
        self.assertEqual(
            self.config["mapping_key_fields"][-1],
            "membership_effective_date",
        )
        self.assertEqual(
            self.reference_contract["security_mapping_source"]["effective_date"],
            "2026-06-12",
        )

    def test_output_row_schema_requires_security_mapping_fields(self) -> None:
        required_fields = self.config["output_row_schema"]["required_output_fields"]
        self.assertEqual(required_fields, REQUIRED_OUTPUT_FIELDS)
        self.assertIn("security_id", required_fields)
        self.assertIn("security_id_mapping_reference", required_fields)
        self.assertEqual(self.config["expected_row_count"], 800)
        self.assertEqual(self.config["allowed_mapping_status"], ["mapped"])
        self.assertEqual(
            self.config["required_mapping_method"],
            "ticker_exchange_effective_date_to_d1_security_master",
        )
        self.assertEqual(
            self.config["security_id_format_rule"],
            "CN.{exchange}.{ticker}",
        )

    def test_materialization_gate_and_failure_actions_block_outputs(self) -> None:
        gate = self.config["materialization_gate"]
        failure_actions = self.config["failure_actions"]
        self.assertTrue(gate["all_rows_must_map"])
        self.assertTrue(gate["no_unmapped_rows_allowed"])
        self.assertTrue(gate["no_duplicate_membership_key_allowed"])
        self.assertTrue(
            gate["no_duplicate_security_id_for_distinct_membership_key_allowed"]
        )
        self.assertEqual(
            failure_actions["inactive_or_delisted_ambiguity_action"],
            "block_materialization",
        )
        self.assertEqual(
            failure_actions["missing_match_action"],
            "block_materialization",
        )
        self.assertEqual(
            failure_actions["duplicate_match_action"],
            "block_materialization",
        )

    def test_no_artifact_or_materialization_flags_are_false(self) -> None:
        for field in (
            "output_artifact_allowed_in_this_pr",
            "output_rows_committed",
            "security_id_mapping_output_committed",
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

    def test_artifact_or_materialization_flags_true_are_rejected(self) -> None:
        for field in (
            "output_artifact_allowed_in_this_pr",
            "output_rows_committed",
            "security_id_mapping_output_committed",
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

    def test_invalid_output_contract_values_are_rejected(self) -> None:
        changes = (
            ("expected_row_count", 799),
            ("allowed_mapping_status", ["mapped", "unmapped"]),
            ("allowed_mapping_status", ["mapped", "ambiguous"]),
            ("allowed_mapping_status", ["mapped", "duplicate"]),
            ("mapping_key_fields", ["ticker", "membership_effective_date"]),
            ("mapping_key_fields", ["exchange", "membership_effective_date"]),
            ("mapping_key_fields", ["ticker", "exchange"]),
            ("security_id_format_rule", "CN.{ticker}.{exchange}"),
            (
                "downstream_decision",
                "evidence_validated_but_rows_not_materialized",
            ),
            ("downstream_decision", "ready_for_d2"),
        )
        for key, value in changes:
            changed = deepcopy(self.config)
            changed[key] = value
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_required_security_output_fields_cannot_be_removed(self) -> None:
        for field in ("security_id", "security_id_mapping_reference"):
            changed = deepcopy(self.config)
            changed["output_row_schema"]["required_output_fields"] = [
                item for item in REQUIRED_OUTPUT_FIELDS if item != field
            ]
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validate(changed)


if __name__ == "__main__":
    unittest.main()
