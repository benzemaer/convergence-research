from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/d0_data_product_contracts.schema.json"
CONFIG_PATH = ROOT / "configs/d0/data_product_contracts.v1.json"

CORE_TABLES = {
    "d1.security_master",
    "d1.trading_calendar",
    "d1.raw_market_prices",
    "d1.corporate_actions",
    "d1.trading_constraints",
    "d2.adjusted_market_prices",
    "d2.market_price_quality_flags",
    "d2.membership_alignment",
    "d3.daily_market_observations",
}
GLOBAL_FIELDS = {
    "data_version",
    "universe_id",
    "time_segment_id",
    "source_registry_id",
    "source_snapshot_id",
    "run_id",
}
D3_REQUIRED_SOURCE_FIELDS = {
    "price_fact_source",
    "corporate_action_source",
    "membership_source",
    "calendar_source",
    "revision_policy",
    "observed_at_rule",
}


def load(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D0DataProductContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )

    def table(self, table_name: str, config: dict[str, object] | None = None) -> dict:
        config = config or self.config
        for table in config["tables"]:
            if table["table_name"] == table_name:
                return table
        self.fail(f"missing table contract {table_name}")

    def validate(self, config: dict[str, object]) -> None:
        self.validator.validate(config)
        self.assert_contract_invariants(config)

    def assert_contract_invariants(self, config: dict[str, object]) -> None:
        table_names = {table["table_name"] for table in config["tables"]}
        self.assertEqual(table_names, CORE_TABLES)
        for table in config["tables"]:
            required_fields = set(table["required_fields"])
            primary_key = set(table["primary_key"])
            self.assertTrue(GLOBAL_FIELDS.issubset(required_fields))
            self.assertTrue(primary_key.issubset(required_fields))
            self.assertTrue(table["grain"])
            self.assertTrue(table["source_registry_requirements"])
            self.assertTrue(table["quality_checks"])
            self.assertTrue(table["blocking_conditions"])
            self.assertTrue(
                table["source_snapshot_requirements"]["raw_snapshot_required"]
            )
            self.assertTrue(table["source_snapshot_requirements"]["sha256_required"])
            self.assertTrue(
                table["manifest_requirements"]["source_snapshot_manifest_required"]
            )
            self.assertTrue(table["manifest_requirements"]["input_hashes_required"])

    def test_data_product_contract_config_is_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validate(self.config)

    def test_d3_is_r0_unique_formal_daily_entry(self) -> None:
        d3 = self.table("d3.daily_market_observations")
        self.assertEqual(d3["downstream_allowed_uses"], ["R0_formal_daily_entry"])
        self.assertTrue(d3["research_entry_contract"]["r0_unique_formal_daily_entry"])
        self.assertTrue(d3["research_entry_contract"]["bypass_d1_d2_for_r0_prohibited"])
        self.assertTrue(D3_REQUIRED_SOURCE_FIELDS.issubset(d3["required_fields"]))

    def test_a_stock_data_recon_is_never_formal_table_source(self) -> None:
        for table in self.config["tables"]:
            with self.subTest(table=table["table_name"]):
                requirements = table["source_registry_requirements"]
                self.assertNotIn(
                    "A_STOCK_DATA_RECON",
                    requirements["allowed_source_registry_ids"],
                )
                self.assertIn(
                    "A_STOCK_DATA_RECON",
                    requirements["prohibited_source_registry_ids"],
                )

    def test_csindex_is_not_a_market_fact_source(self) -> None:
        market_tables = {
            "d1.raw_market_prices",
            "d1.corporate_actions",
            "d1.trading_constraints",
            "d2.adjusted_market_prices",
            "d2.market_price_quality_flags",
        }
        for table_name in market_tables:
            requirements = self.table(table_name)["source_registry_requirements"]
            self.assertNotIn(
                "CSINDEX_OFFICIAL",
                requirements["allowed_source_registry_ids"],
            )
            self.assertIn(
                "CSINDEX_OFFICIAL",
                requirements["prohibited_source_registry_ids"],
            )

    def test_hithink_is_not_formal_ingestion_source_yet(self) -> None:
        for table in self.config["tables"]:
            requirements = table["source_registry_requirements"]
            if "HITHINK_FINANCIAL_API" in requirements["allowed_source_registry_ids"]:
                with self.subTest(table=table["table_name"]):
                    self.assertFalse(requirements["formal_ingestion_authorized"])
                    self.assertTrue(requirements["reason"])

    def test_baostock_is_not_sole_formal_primary_source(self) -> None:
        for table in self.config["tables"]:
            requirements = table["source_registry_requirements"]
            if "BAOSTOCK" in requirements["allowed_source_registry_ids"]:
                with self.subTest(table=table["table_name"]):
                    self.assertFalse(requirements["sole_primary_source_allowed"])

    def test_deleting_core_table_fails_invariants(self) -> None:
        changed = deepcopy(self.config)
        changed["tables"] = [
            table
            for table in changed["tables"]
            if table["table_name"] != "d1.security_master"
        ]
        with self.assertRaises((AssertionError, ValidationError)):
            self.validate(changed)

    def test_deleting_primary_key_field_fails_invariants(self) -> None:
        changed = deepcopy(self.config)
        table = self.table("d1.raw_market_prices", changed)
        table["required_fields"].remove("source_snapshot_id")
        with self.assertRaises(AssertionError):
            self.validate(changed)

    def test_deleting_raw_snapshot_requirement_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        table = self.table("d1.raw_market_prices", changed)
        del table["source_snapshot_requirements"]["raw_snapshot_required"]
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_deleting_hash_requirement_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        table = self.table("d1.raw_market_prices", changed)
        table["source_snapshot_requirements"]["sha256_required"] = False
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_deleting_manifest_requirement_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        table = self.table("d1.raw_market_prices", changed)
        del table["manifest_requirements"]["source_snapshot_manifest_required"]
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

    def test_authorizing_hithink_formal_ingestion_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        table = self.table("d1.raw_market_prices", changed)
        table["source_registry_requirements"]["formal_ingestion_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)


if __name__ == "__main__":
    unittest.main()
