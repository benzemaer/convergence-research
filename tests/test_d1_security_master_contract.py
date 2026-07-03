from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/d1_security_master_contract.schema.json"
CONFIG_PATH = ROOT / "configs/d1/security_master_contract.v1.json"
D0_CONTRACT_PATH = ROOT / "configs/d0/data_product_contracts.v1.json"

EXPECTED_FIELD_TYPES = {
    "data_version": "TEXT",
    "universe_id": "TEXT",
    "time_segment_id": "TEXT",
    "security_id": "TEXT",
    "ticker": "TEXT",
    "exchange": "TEXT",
    "security_name": "TEXT",
    "listing_date": "DATE",
    "delisting_date": "DATE",
    "security_type": "TEXT",
    "source_registry_id": "TEXT",
    "source_snapshot_id": "TEXT",
    "run_id": "TEXT",
}
EXPECTED_EXCHANGES = {"SSE", "SZSE"}
EXPECTED_SECURITY_TYPES = {"A_SHARE_COMMON"}
EXPECTED_IMPLEMENTATION_EXCLUSIONS = {
    "no_loader",
    "no_external_api_call",
    "no_real_data_import",
    "no_duckdb_entity_data",
    "no_committed_duckdb_file",
    "no_manifest",
}


def load(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def d0_security_master_contract() -> dict[str, object]:
    d0_contract = load(D0_CONTRACT_PATH)
    for table in d0_contract["tables"]:
        if table["table_name"] == "d1.security_master":
            return table
    raise AssertionError("missing d1.security_master in D0 data product contract")


class D1SecurityMasterContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )
        cls.d0_table = d0_security_master_contract()

    def validate(self, config: dict[str, object]) -> None:
        self.validator.validate(config)

    def test_security_master_contract_config_is_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validate(self.config)

    def test_field_semantics_match_d0_required_fields_exactly(self) -> None:
        d0_required_fields = set(self.d0_table["required_fields"])
        self.assertEqual(set(self.config["field_semantics"]), d0_required_fields)
        self.assertEqual(
            self.config["base_data_product_contract"]["contract_id"],
            "D0_DATA_PRODUCT_CONTRACTS_V1",
        )

    def test_field_semantics_nullable_matches_d0_contract(self) -> None:
        d0_required_fields = set(self.d0_table["required_fields"])
        d0_nullable_fields = set(self.d0_table["nullable_fields"])

        self.assertEqual(d0_nullable_fields, {"delisting_date"})
        for field_name, field_rule in self.config["field_semantics"].items():
            with self.subTest(field=field_name):
                self.assertIn(field_name, d0_required_fields)
                self.assertEqual(
                    field_rule["nullable"],
                    field_name in d0_nullable_fields,
                )

    def test_field_semantics_types_match_d1_duckdb_contract(self) -> None:
        self.assertEqual(
            set(EXPECTED_FIELD_TYPES), set(self.d0_table["required_fields"])
        )
        for field_name, expected_type in EXPECTED_FIELD_TYPES.items():
            with self.subTest(field=field_name):
                self.assertEqual(
                    self.config["field_semantics"][field_name]["type"],
                    expected_type,
                )

    def test_identifier_ticker_and_exchange_rules_are_explicit(self) -> None:
        identifier_policy = self.config["identifier_policy"]
        self.assertEqual(
            identifier_policy["security_id_format"],
            "CN.{exchange}.{ticker}",
        )
        self.assertEqual(
            identifier_policy["security_id_regex"],
            r"^CN\.(SSE|SZSE)\.[0-9]{6}$",
        )
        self.assertIn("internal identity key", identifier_policy["security_id_role"])
        self.assertEqual(
            set(self.config["exchange_policy"]["allowed_exchanges"]),
            EXPECTED_EXCHANGES,
        )
        self.assertEqual(self.config["ticker_policy"]["ticker_regex"], "^[0-9]{6}$")
        self.assertIn(
            "never parse as integer",
            self.config["ticker_policy"]["leading_zero_rule"],
        )

    def test_security_type_and_source_rules_remain_blocked_for_ingestion(self) -> None:
        self.assertEqual(
            set(self.config["security_type_policy"]["allowed_security_types"]),
            EXPECTED_SECURITY_TYPES,
        )

        source_requirements = self.config["source_registry_requirements"]
        self.assertEqual(
            source_requirements["allowed_source_registry_ids"],
            ["HITHINK_FINANCIAL_API"],
        )
        self.assertFalse(source_requirements["formal_ingestion_authorized"])
        self.assertIn(
            "CSINDEX_OFFICIAL",
            source_requirements["prohibited_source_registry_ids"],
        )
        self.assertIn(
            "A_STOCK_DATA_RECON",
            source_requirements["prohibited_source_registry_ids"],
        )
        self.assertIn(
            "BAOSTOCK",
            source_requirements["prohibited_source_registry_ids"],
        )
        self.assertIn("source terms", source_requirements["reason"])

    def test_source_symbol_mapping_boundary_is_traceable(self) -> None:
        source_symbol_policy = self.config["source_symbol_policy"]
        required_mapping_keys = set(source_symbol_policy["required_mapping_keys"])
        self.assertTrue(
            {
                "source_registry_id",
                "source_snapshot_id",
                "source_symbol",
                "security_id",
                "ticker",
                "exchange",
                "observed_at",
            }.issubset(required_mapping_keys)
        )
        prohibited_assumptions = "\n".join(
            source_symbol_policy["prohibited_assumptions"]
        )
        self.assertIn("supplier code", prohibited_assumptions)
        self.assertIn("wrapper-returned symbols", prohibited_assumptions)

    def test_no_data_artifact_loader_or_api_call_boundary_is_explicit(self) -> None:
        self.assertEqual(
            set(self.config["implementation_exclusions"]),
            EXPECTED_IMPLEMENTATION_EXCLUSIONS,
        )
        future_loader_requirements = "\n".join(
            self.config["future_loader_requirements"]
        )
        self.assertIn("never live APIs", future_loader_requirements)
        self.assertIn(
            "must not populate d1.security_master",
            future_loader_requirements,
        )

    def test_quality_checks_cover_future_loader_gates(self) -> None:
        quality_checks = set(self.config["quality_checks"])
        self.assertTrue(
            {
                "primary_key_unique",
                "security_id_matches_regex",
                "ticker_matches_regex",
                "exchange_allowed",
                "security_type_allowed",
                "ticker_exchange_mapping_unique_within_version",
                "listing_date_not_after_delisting_date",
                "source_registry_allowed",
                "source_snapshot_id_present",
                "no_unreviewed_source_symbol_mapping",
            }.issubset(quality_checks)
        )

    def test_authorizing_formal_ingestion_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["source_registry_requirements"]["formal_ingestion_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_allowing_csindex_as_security_master_source_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["source_registry_requirements"]["allowed_source_registry_ids"].append(
            "CSINDEX_OFFICIAL"
        )
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_removing_no_loader_boundary_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["implementation_exclusions"].remove("no_loader")
        with self.assertRaises(ValidationError):
            self.validate(changed)


if __name__ == "__main__":
    unittest.main()
