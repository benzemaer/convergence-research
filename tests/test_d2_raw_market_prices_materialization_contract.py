from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d2/raw_market_prices_materialization_contract.v1.json"
CONTRACT_SCHEMA_PATH = (
    ROOT / "schemas/d2_raw_market_prices_materialization_contract.schema.json"
)
REPORT_PATH = (
    ROOT / "configs/d2/raw_market_prices_materialization_blocking_report.v1.json"
)
REPORT_SCHEMA_PATH = (
    ROOT / "schemas/d2_raw_market_prices_materialization_blocking_report.schema.json"
)
README_PATH = ROOT / "docs/tasks/README.md"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2RawMarketPricesMaterializationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load(CONTRACT_PATH)
        cls.contract_schema = load(CONTRACT_SCHEMA_PATH)
        cls.report = load(REPORT_PATH)
        cls.report_schema = load(REPORT_SCHEMA_PATH)
        cls.contract_validator = Draft202012Validator(cls.contract_schema)
        cls.report_validator = Draft202012Validator(cls.report_schema)

    def test_contract_and_blocking_report_match_schemas(self) -> None:
        Draft202012Validator.check_schema(self.contract_schema)
        Draft202012Validator.check_schema(self.report_schema)
        self.contract_validator.validate(self.contract)
        self.report_validator.validate(self.report)

    def test_contract_keeps_materialization_blocked(self) -> None:
        auth = self.contract["authorization"]
        self.assertFalse(auth["materialization_authorized"])
        self.assertFalse(auth["formal_ingestion_authorized"])
        self.assertFalse(auth["full_market_collection_authorized"])
        self.assertFalse(auth["duckdb_write_authorized"])
        self.assertFalse(auth["real_market_data_artifact_authorized"])
        self.assertTrue(auth["synthetic_test_only"])

    def test_candidate_source_boundaries_are_blocked(self) -> None:
        boundary = self.contract["candidate_source_boundary"]
        self.assertEqual(
            set(boundary["allowed_candidate_source_registry_ids"]),
            {"HITHINK_FINANCIAL_API", "BAOSTOCK"},
        )
        self.assertIn("CSINDEX_OFFICIAL", boundary["prohibited_source_registry_ids"])
        self.assertIn("A_STOCK_DATA_RECON", boundary["prohibited_source_registry_ids"])
        self.assertFalse(boundary["a_stock_data_recon_formal_source_allowed"])
        self.assertFalse(boundary["baostock_adjusted_price_formal_source_allowed"])

    def test_report_records_no_real_data_actions(self) -> None:
        for key in [
            "formal_ingestion_authorized",
            "full_market_collection_authorized",
            "duckdb_written",
            "real_market_data_rows_generated",
            "real_market_data_artifact_committed",
            "run_manifest_created",
            "dataset_manifest_created",
            "source_snapshot_manifest_created",
            "raw_snapshot_read",
            "data_external_read",
            "external_api_called",
            "marketdb_read",
            "tdx_day_file_read",
        ]:
            self.assertFalse(self.report[key])
        self.assertEqual(
            self.report["materialization_status"],
            "blocked_pending_source_authorization",
        )
        self.assertTrue(self.report["membership_alignment_available"])
        self.assertEqual(self.report["membership_alignment_row_count"], 800)

    def test_schema_rejects_authorization_or_completed_report(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["authorization"]["duckdb_write_authorized"] = True
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

        changed_report = copy.deepcopy(self.report)
        changed_report["materialization_status"] = "completed"
        with self.assertRaises(ValidationError):
            self.report_validator.validate(changed_report)

    def test_schema_requires_exact_raw_market_price_fields(self) -> None:
        for field in ["raw_close", "observed_at"]:
            changed = copy.deepcopy(self.contract)
            changed["required_fields"].remove(field)
            with self.assertRaises(ValidationError):
                self.contract_validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["required_fields"].append("ticker")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

    def test_schema_requires_exact_primary_key_fields(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["primary_key"].remove("source_snapshot_id")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

    def test_schema_requires_core_blocking_conditions(self) -> None:
        for blocker in ["adjusted_price_used_as_raw_price", "duckdb_write_attempted"]:
            changed = copy.deepcopy(self.contract)
            changed["blocking_conditions"].remove(blocker)
            with self.assertRaises(ValidationError):
                self.contract_validator.validate(changed)

    def test_schema_requires_core_prohibited_row_fields(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["prohibited_row_fields"].remove("adj_close")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

    def test_readme_does_not_advance_to_d2_t04(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        self.assertIn("current_task: D3-T01", readme)
        self.assertIn("next_planned_task: D3-T02", readme)
        self.assertIn(
            "D2-T03` 原始行情价格落账：blocked pending source authorization",
            readme,
        )
        self.assertIn("D2-T04` 复权因子与 `factor_as_of_time` 契约：planned", readme)


if __name__ == "__main__":
    unittest.main()
