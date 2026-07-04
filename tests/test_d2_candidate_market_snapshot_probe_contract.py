from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d2/candidate_market_snapshot_probe_contract.v1.json"
CONTRACT_SCHEMA_PATH = (
    ROOT / "schemas/d2_candidate_market_snapshot_probe_contract.schema.json"
)
REPORT_PATH = ROOT / "configs/d2/candidate_market_snapshot_probe_report.v1.json"
REPORT_SCHEMA_PATH = (
    ROOT / "schemas/d2_candidate_market_snapshot_probe_report.schema.json"
)
README_PATH = ROOT / "docs/tasks/README.md"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2CandidateMarketSnapshotProbeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load(CONTRACT_PATH)
        cls.contract_schema = load(CONTRACT_SCHEMA_PATH)
        cls.report = load(REPORT_PATH)
        cls.report_schema = load(REPORT_SCHEMA_PATH)
        cls.contract_validator = Draft202012Validator(cls.contract_schema)
        cls.report_validator = Draft202012Validator(cls.report_schema)

    def test_contract_and_report_match_schemas(self) -> None:
        Draft202012Validator.check_schema(self.contract_schema)
        Draft202012Validator.check_schema(self.report_schema)
        self.contract_validator.validate(self.contract)
        self.report_validator.validate(self.report)

    def test_authorizations_and_report_flags_are_false(self) -> None:
        for key in [
            "external_api_call_authorized",
            "real_probe_execution_authorized",
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "official_dataset_materialization_authorized",
        ]:
            self.assertFalse(self.contract["authorization"][key])
        self.assertTrue(self.contract["authorization"]["synthetic_test_only"])

        for key in [
            "external_api_called",
            "real_probe_rows_generated",
            "raw_snapshot_read",
            "raw_snapshot_written",
            "data_external_read",
            "data_external_written",
            "duckdb_written",
            "official_dataset_materialized",
            "source_snapshot_manifest_created",
            "dataset_manifest_created",
            "run_manifest_created",
            "hithink_probe_authorized",
            "baostock_probe_authorized",
            "formal_ingestion_authorized",
        ]:
            self.assertFalse(self.report[key])
        self.assertTrue(self.report["d3_not_authorized_by_this_pr"])

    def test_schema_rejects_promoted_or_missing_core_gates(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["authorization"]["external_api_call_authorized"] = True
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["future_probe_output_required_fields"].remove("raw_response_sha256")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["prohibited_source_registry_ids"].remove("CSINDEX_OFFICIAL")
        with self.assertRaises(ValidationError):
            self.contract_validator.validate(changed)

    def test_readme_renumbers_d2_queue_without_advancing_d3(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        self.assertIn("current_stage: D2", readme)
        self.assertIn("D2-T06` 候选行情快照探针", readme)
        self.assertIn(
            "contract-only pending separately authorized probe execution", readme
        )
        self.assertIn("D2-T07` 跳空归因与价格质量标记：planned", readme)
        self.assertIn("D2-T08` D2 阶段验收与 D3 交接：planned", readme)


if __name__ == "__main__":
    unittest.main()
