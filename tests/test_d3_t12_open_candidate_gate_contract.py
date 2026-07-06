from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d3/d3_t12_open_candidate_gate_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d3_t12_open_candidate_gate_contract.schema.json"


class D3T12OpenCandidateGateContractTest(unittest.TestCase):
    def test_contract_json_passes_schema(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(contract)

    def test_contract_freezes_open_candidate_generation_semantics(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

        self.assertTrue(contract["d3_candidate_generation_is_research_agnostic"])
        self.assertTrue(
            contract["downstream_consumer_readiness_evaluated_by_consumer_task"]
        )
        self.assertTrue(contract["formal_release_gate_separate"])
        self.assertTrue(contract["r_stage_specific_readiness_not_hardcoded_in_d3"])
        self.assertFalse(contract["formal_data_version_authorized"])
        self.assertFalse(contract["pcvt_metric_calculation_authorized"])
        self.assertFalse(contract["future_label_generation_authorized"])
        self.assertFalse(contract["returns_generation_authorized"])
        self.assertFalse(contract["backtest_generation_authorized"])
        self.assertFalse(contract["portfolio_generation_authorized"])


if __name__ == "__main__":
    unittest.main()
