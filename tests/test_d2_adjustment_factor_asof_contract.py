from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d2/adjustment_factor_asof_contract.v1.json"
CONTRACT_SCHEMA_PATH = ROOT / "schemas/d2_adjustment_factor_asof_contract.schema.json"
REPORT_PATH = ROOT / "configs/d2/adjustment_factor_asof_blocking_report.v1.json"
REPORT_SCHEMA_PATH = (
    ROOT / "schemas/d2_adjustment_factor_asof_blocking_report.schema.json"
)
README_PATH = ROOT / "docs/tasks/README.md"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2AdjustmentFactorAsOfContractTest(unittest.TestCase):
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

    def test_contract_keeps_adjustment_materialization_blocked(self) -> None:
        auth = self.contract["authorization"]
        for key in [
            "adjustment_factor_materialization_authorized",
            "adjusted_price_generation_authorized",
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "real_factor_artifact_authorized",
            "real_adjusted_price_artifact_authorized",
        ]:
            self.assertFalse(auth[key])
        self.assertTrue(auth["synthetic_test_only"])

    def test_report_records_no_real_data_actions(self) -> None:
        for key in [
            "formal_ingestion_authorized",
            "adjustment_factor_materialization_authorized",
            "adjusted_price_generation_authorized",
            "duckdb_written",
            "real_factor_rows_generated",
            "real_adjusted_price_rows_generated",
            "real_factor_artifact_committed",
            "real_adjusted_price_artifact_committed",
            "run_manifest_created",
            "dataset_manifest_created",
            "source_snapshot_manifest_created",
            "raw_snapshot_read",
            "data_external_read",
            "external_api_called",
            "marketdb_read",
            "tdx_day_file_read",
            "raw_price_materialization_available",
        ]:
            self.assertFalse(self.report[key])
        self.assertEqual(
            self.report["materialization_status"],
            "blocked_pending_factor_source_authorization",
        )
        self.assertTrue(self.report["membership_alignment_available"])
        self.assertEqual(self.report["membership_alignment_row_count"], 800)
        self.assertTrue(self.report["d2_t05_not_authorized_by_this_pr"])

    def test_candidate_source_boundaries_are_blocked(self) -> None:
        boundary = self.contract["candidate_source_boundary"]
        self.assertEqual(
            set(boundary["allowed_candidate_source_registry_ids"]),
            {"HITHINK_FINANCIAL_API", "BAOSTOCK"},
        )
        self.assertEqual(
            set(boundary["candidate_only_source_registry_ids"]),
            {"HITHINK_FINANCIAL_API", "BAOSTOCK"},
        )
        self.assertIn("CSINDEX_OFFICIAL", boundary["prohibited_source_registry_ids"])
        self.assertIn("A_STOCK_DATA_RECON", boundary["prohibited_source_registry_ids"])
        self.assertTrue(boundary["hithink_candidate_only"])
        self.assertFalse(boundary["baostock_formal_adjusted_price_source_allowed"])
        self.assertTrue(boundary["csindex_membership_only"])

    def test_schema_rejects_authorization_or_completed_report(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["authorization"]["adjusted_price_generation_authorized"] = True
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

        changed_report = copy.deepcopy(self.report)
        changed_report["materialization_status"] = "completed"
        with self.assertRaises(ValidationError):
            self.report_validator.validate(changed_report)

    def test_schema_requires_exact_adjusted_market_price_fields(self) -> None:
        for field in ["adjustment_factor", "factor_as_of_time"]:
            changed = copy.deepcopy(self.contract)
            changed["required_fields"].remove(field)
            with self.assertRaises(ValidationError):
                self.contract_validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["required_fields"].append("raw_close")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

    def test_schema_requires_core_blockers_and_prohibited_fields(self) -> None:
        for blocker in [
            "future_corporate_action_knowledge_used",
            "duckdb_write_attempted",
            "real_adjusted_price_artifact_generated",
        ]:
            changed = copy.deepcopy(self.contract)
            changed["blocking_conditions"].remove(blocker)
            with self.assertRaises(ValidationError):
                self.contract_validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["prohibited_row_fields"].remove("vendor_payload")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

    def test_readme_keeps_d2_t04_blocked_without_advancing(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        self.assertIn("current_task: D3-T01", readme)
        self.assertIn("next_planned_task: D3-T02", readme)
        self.assertIn("D2-T04` 复权因子与 `factor_as_of_time` 契约", readme)
        self.assertIn("blocked pending factor source authorization", readme)
        self.assertIn("D2-T05` 连续研究价格构建与反推校验：planned", readme)


if __name__ == "__main__":
    unittest.main()
