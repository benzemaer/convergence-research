from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "configs/d2/source_status_factor_evidence_acceptance_handoff_contract.v1.json"
)
SCHEMA = (
    ROOT
    / "schemas/d2_source_status_factor_evidence_acceptance_handoff_contract.schema.json"
)


class D2SourceStatusFactorEvidenceAcceptanceHandoffContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def test_contract_json_passes_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema).validate(self.contract)
        self.assertEqual(self.contract["task_id"], "D2-T11")

    def test_authorization_boundary_and_sources(self) -> None:
        for key in [
            "formal_source_acceptance_authorized",
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "real_data_materialization_authorized",
            "manifest_creation_authorized",
            "data_version_release_authorized",
            "d3_generation_authorized",
            "r0_state_generation_authorized",
        ]:
            self.assertIs(self.contract[key], False)
        self.assertIs(self.contract["local_candidate_artifact_write_authorized"], True)
        self.assertIs(self.contract["local_candidate_report_write_authorized"], True)
        self.assertEqual(self.contract["primary_source"], "hithink_financial_api")
        self.assertEqual(self.contract["fallback_sources"][0]["source_id"], "baostock")
        self.assertEqual(self.contract["fallback_sources"][0]["priority"], 1)
        self.assertEqual(self.contract["fallback_sources"][1]["source_id"], "tushare")
        self.assertEqual(self.contract["fallback_sources"][1]["priority"], 2)
        self.assertIs(
            self.contract["active_source_policy"]["a_stock_data_active_allowed"], False
        )

    def test_depends_on_and_decision_enums_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["depends_on"]),
            {
                "D2_FORMAL_SOURCE_REGISTRY_CONTRACT_V1",
                "D2_HITHINK_RAW_OHLCV_PROBE_CONTRACT_V1",
                "D2_HITHINK_RAW_MARKET_PRICES_CANDIDATE_MATERIALIZATION_CONTRACT_V1",
                "D2_HITHINK_RAW_MARKET_PRICES_CANDIDATE_ARTIFACT_CONTRACT_V1",
                "D2_ADJUSTED_PRICE_QUALITY_GAP_CANDIDATE_CONTRACT_V1",
                "D2_ACCEPTANCE_D3_HANDOFF_CONTRACT_V1",
                "D2_MARKET_QUALITY_PCVT_DEPENDENCY_CONTRACT_V1",
                "D3_DATA_VERSION_QUALITY_MANIFEST_GATE_CONTRACT_V1",
            },
        )
        self.assertIn(
            "accepted_for_d3_candidate_generation",
            self.contract["d2_acceptance_decision_enum"],
        )
        self.assertIn(
            "d3_candidate_generation_allowed",
            self.contract["d3_handoff_decision_enum"],
        )


if __name__ == "__main__":
    unittest.main()
