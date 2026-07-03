from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/d1_corporate_actions_adjustment_contract.schema.json"
CONFIG_PATH = ROOT / "configs/d1/corporate_actions_adjustment_contract.v1.json"
D0_CONTRACT_PATH = ROOT / "configs/d0/data_product_contracts.v1.json"

TARGET_TABLES = {"d1.corporate_actions", "d2.adjusted_market_prices"}
EXPECTED_IMPLEMENTATION_EXCLUSIONS = {
    "no_loader",
    "no_external_api_call",
    "no_real_data_import",
    "no_duckdb_entity_data",
    "no_committed_duckdb_file",
    "no_manifest",
}
EXPECTED_FIELD_TYPES = {
    "d1.corporate_actions": {
        "data_version": "TEXT",
        "universe_id": "TEXT",
        "time_segment_id": "TEXT",
        "security_id": "TEXT",
        "action_id": "TEXT",
        "action_type": "TEXT",
        "ex_date": "DATE",
        "record_date": "DATE",
        "pay_date": "DATE",
        "action_terms": "TEXT",
        "source_registry_id": "TEXT",
        "source_snapshot_id": "TEXT",
        "observed_at": "TIMESTAMP",
        "run_id": "TEXT",
    },
    "d2.adjusted_market_prices": {
        "data_version": "TEXT",
        "universe_id": "TEXT",
        "time_segment_id": "TEXT",
        "security_id": "TEXT",
        "trading_date": "DATE",
        "adj_open": "DOUBLE",
        "adj_high": "DOUBLE",
        "adj_low": "DOUBLE",
        "adj_close": "DOUBLE",
        "adjustment_factor": "DOUBLE",
        "adjustment_method": "TEXT",
        "factor_as_of_time": "TIMESTAMP",
        "corporate_action_flag": "BOOLEAN",
        "adjustment_revision": "TEXT",
        "source_registry_id": "TEXT",
        "source_snapshot_id": "TEXT",
        "run_id": "TEXT",
    },
}


def load(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def d0_table_contracts() -> dict[str, dict[str, object]]:
    d0_contract = load(D0_CONTRACT_PATH)
    tables = {
        table["table_name"]: table
        for table in d0_contract["tables"]
        if table["table_name"] in TARGET_TABLES
    }
    if set(tables) != TARGET_TABLES:
        raise AssertionError("missing D1-T03 target tables in D0 contract")
    return tables


class D1CorporateActionsAdjustmentContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )
        cls.d0_tables = d0_table_contracts()

    def validate(self, config: dict[str, object]) -> None:
        self.validator.validate(config)

    def table(self, table_name: str, config: dict[str, object] | None = None) -> dict:
        config = config or self.config
        for table in config["tables"]:
            if table["table_name"] == table_name:
                return table
        self.fail(f"missing table contract {table_name}")

    def test_corporate_actions_adjustment_contract_config_is_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validate(self.config)

    def test_contract_table_set_matches_d0_targets(self) -> None:
        self.assertEqual(
            {table["table_name"] for table in self.config["tables"]},
            TARGET_TABLES,
        )
        self.assertEqual(
            set(self.config["base_data_product_contract"]["required_tables"]),
            TARGET_TABLES,
        )

    def test_field_semantics_match_d0_required_fields_exactly(self) -> None:
        for table_name, d0_table in self.d0_tables.items():
            with self.subTest(table=table_name):
                self.assertEqual(
                    set(self.table(table_name)["field_semantics"]),
                    set(d0_table["required_fields"]),
                )

    def test_nullable_fields_match_d0_contract_exactly(self) -> None:
        expected_nullable = {
            "d1.corporate_actions": {"record_date", "pay_date"},
            "d2.adjusted_market_prices": set(),
        }
        for table_name, d0_table in self.d0_tables.items():
            table = self.table(table_name)
            d0_nullable_fields = set(d0_table["nullable_fields"])
            with self.subTest(table=table_name):
                self.assertEqual(d0_nullable_fields, expected_nullable[table_name])
                for field_name, field_rule in table["field_semantics"].items():
                    self.assertEqual(
                        field_rule["nullable"],
                        field_name in d0_nullable_fields,
                    )

    def test_field_types_match_d1_duckdb_contract(self) -> None:
        for table_name, expected_types in EXPECTED_FIELD_TYPES.items():
            table = self.table(table_name)
            with self.subTest(table=table_name):
                self.assertEqual(
                    set(expected_types),
                    set(self.d0_tables[table_name]["required_fields"]),
                )
                for field_name, expected_type in expected_types.items():
                    self.assertEqual(
                        table["field_semantics"][field_name]["type"],
                        expected_type,
                    )

    def test_primary_keys_match_d0_contract_exactly(self) -> None:
        for table_name, d0_table in self.d0_tables.items():
            with self.subTest(table=table_name):
                self.assertEqual(
                    self.table(table_name)["primary_key"],
                    d0_table["primary_key"],
                )

    def test_source_registry_boundaries_remain_blocked_for_ingestion(self) -> None:
        for table_name in TARGET_TABLES:
            requirements = self.table(table_name)["source_registry_requirements"]
            with self.subTest(table=table_name):
                self.assertFalse(requirements["formal_ingestion_authorized"])
                self.assertIn(
                    "HITHINK_FINANCIAL_API",
                    requirements["candidate_only_source_registry_ids"],
                )
                self.assertIn(
                    "CSINDEX_OFFICIAL",
                    requirements["prohibited_source_registry_ids"],
                )
                self.assertIn(
                    "A_STOCK_DATA_RECON",
                    requirements["prohibited_source_registry_ids"],
                )

        adjusted = self.table("d2.adjusted_market_prices")
        self.assertIn(
            "BAOSTOCK",
            adjusted["source_registry_requirements"][
                "candidate_only_source_registry_ids"
            ],
        )

    def test_controlled_vocabularies_cover_action_and_adjustment_boundaries(
        self,
    ) -> None:
        action_vocab = self.table("d1.corporate_actions")["controlled_vocabularies"]
        adjusted_vocab = self.table("d2.adjusted_market_prices")[
            "controlled_vocabularies"
        ]
        self.assertIn("cash_dividend", action_vocab["action_type"]["allowed_values"])
        self.assertIn("rights_issue", action_vocab["action_type"]["allowed_values"])
        self.assertIn(
            "forward_adjusted",
            adjusted_vocab["adjustment_method"]["allowed_values"],
        )
        self.assertIn("v1", adjusted_vocab["adjustment_revision"]["allowed_values"])

    def test_revision_and_factor_as_of_boundaries_are_explicit(self) -> None:
        shared = self.config["shared_boundary"]
        self.assertIn("D3", shared["d3_entry_rule"])
        self.assertIn("mechanical gaps", shared["mechanical_gap_rule"])
        self.assertIn("must not be interpreted directly", shared["mechanical_gap_rule"])
        self.assertIn("future corporate-action knowledge", shared["factor_as_of_rule"])
        self.assertIn("adjustment_revision", shared["factor_as_of_rule"])
        self.assertIn("source_snapshot_id", shared["revision_rule"])

    def test_no_data_artifact_loader_or_api_call_boundary_is_explicit(self) -> None:
        self.assertEqual(
            set(self.config["implementation_exclusions"]),
            EXPECTED_IMPLEMENTATION_EXCLUSIONS,
        )
        future_loader_requirements = "\n".join(
            self.config["future_loader_requirements"]
        )
        self.assertIn("never live APIs", future_loader_requirements)
        self.assertIn("must not populate", future_loader_requirements)

    def test_authorizing_formal_ingestion_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        self.table("d1.corporate_actions", changed)["source_registry_requirements"][
            "formal_ingestion_authorized"
        ] = True
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_allowing_csindex_as_formal_source_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        self.table("d1.corporate_actions", changed)["source_registry_requirements"][
            "allowed_source_registry_ids"
        ].append("CSINDEX_OFFICIAL")
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_allowing_a_stock_data_as_formal_source_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        self.table("d2.adjusted_market_prices", changed)[
            "source_registry_requirements"
        ]["allowed_source_registry_ids"].append("A_STOCK_DATA_RECON")
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_adding_baostock_to_corporate_action_source_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        requirements = self.table("d1.corporate_actions", changed)[
            "source_registry_requirements"
        ]
        requirements["allowed_source_registry_ids"].append("BAOSTOCK")
        requirements["candidate_only_source_registry_ids"].append("BAOSTOCK")
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_removing_no_loader_boundary_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["implementation_exclusions"].remove("no_loader")
        with self.assertRaises(ValidationError):
            self.validate(changed)


if __name__ == "__main__":
    unittest.main()
