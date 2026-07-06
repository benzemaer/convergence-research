from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d2/continuous_price_construction_contract.v1.json"
CONTRACT_SCHEMA_PATH = (
    ROOT / "schemas/d2_continuous_price_construction_contract.schema.json"
)
REPORT_PATH = ROOT / "configs/d2/continuous_price_construction_blocking_report.v1.json"
REPORT_SCHEMA_PATH = (
    ROOT / "schemas/d2_continuous_price_construction_blocking_report.schema.json"
)
README_PATH = ROOT / "docs/tasks/README.md"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2ContinuousPriceConstructionContractTest(unittest.TestCase):
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

    def test_contract_keeps_continuous_price_construction_blocked(self) -> None:
        auth = self.contract["authorization"]
        for key in [
            "continuous_price_construction_authorized",
            "adjusted_price_generation_authorized",
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "real_continuous_price_artifact_authorized",
        ]:
            self.assertFalse(auth[key])
        self.assertTrue(auth["synthetic_test_only"])

    def test_report_records_no_real_data_actions(self) -> None:
        for key in [
            "continuous_price_construction_authorized",
            "adjusted_price_generation_authorized",
            "formal_ingestion_authorized",
            "duckdb_written",
            "real_continuous_price_rows_generated",
            "real_continuous_price_artifact_committed",
            "run_manifest_created",
            "dataset_manifest_created",
            "source_snapshot_manifest_created",
            "raw_snapshot_read",
            "data_external_read",
            "external_api_called",
            "marketdb_read",
            "tdx_day_file_read",
            "raw_price_materialization_available",
            "adjustment_factor_materialization_available",
        ]:
            self.assertFalse(self.report[key])
        self.assertEqual(
            self.report["materialization_status"],
            "blocked_pending_raw_and_factor_authorization",
        )
        self.assertTrue(self.report["membership_alignment_available"])
        self.assertEqual(self.report["membership_alignment_row_count"], 800)
        self.assertTrue(self.report["d2_t06_not_authorized_by_this_pr"])

    def test_schema_rejects_authorization_or_completed_report(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["authorization"]["continuous_price_construction_authorized"] = True
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

        changed_report = copy.deepcopy(self.report)
        changed_report["materialization_status"] = "completed"
        with self.assertRaises(ValidationError):
            self.report_validator.validate(changed_report)

    def test_schema_requires_core_fields_blockers_and_prohibited_fields(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["required_fields"].remove("adj_close")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["synthetic_input_raw_fields"].remove("raw_close")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["blocking_conditions"].remove("reverse_check_failed")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["prohibited_row_fields"].remove("future_return")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

    def test_schema_requires_controlled_vocabularies(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["controlled_vocabularies"]["adjustment_method"][
            "allowed_values"
        ].remove("forward_adjusted")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["controlled_vocabularies"]["adjustment_revision"][
            "allowed_values"
        ].remove("candidate")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

    def test_schema_requires_candidate_source_boundary(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["candidate_source_boundary"]["prohibited_source_registry_ids"].remove(
            "CSINDEX_OFFICIAL"
        )
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["candidate_source_boundary"][
            "baostock_formal_adjusted_price_source_allowed"
        ] = True
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

    def test_readme_keeps_d2_t05_blocked_without_advancing(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "current_task: D3-T07 candidate daily observation from D2-T20", readme
        )
        self.assertIn(
            "next_planned_task: D3-T08 PCVT input readiness and "
            "feature-base quality checks",
            readme,
        )
        self.assertIn("D2-T05` 连续研究价格构建与反推校验", readme)
        self.assertIn("blocked pending raw and factor authorization", readme)
        self.assertIn("D2-T06` 跳空归因与价格质量标记：planned", readme)


if __name__ == "__main__":
    unittest.main()
