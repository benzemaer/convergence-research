import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from src.r2.r2_t02_event_rule_contract import build_contract_artifacts
from src.r2.r2_t02_event_rule_contract_validator import validate_contract

ROOT = Path(__file__).resolve().parents[2]


class R2T02V2ContractTest(unittest.TestCase):
    def test_dual_state_machine_and_exact_t03_boundary_are_committed(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = build_contract_artifacts(output)
            validation = validate_contract(output)
            self.assertEqual(result["artifact_count"], 12)
            self.assertEqual(result["synthetic_case_count"], 53)
            self.assertEqual(validation["deterministic_output_check"], "passed")
            cells = (
                (output / "r2_t02_t03_cell_registry.csv")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            self.assertEqual(len(cells) - 1, 72)
            self.assertTrue(
                all("not_executed_contract_only" in row for row in cells[1:])
            )

    def test_v2_event_and_risk_outputs_use_strict_schemas(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            build_contract_artifacts(output)
            for artifact, schema in (
                (
                    "r2_t02_event_rule_contract.json",
                    "r2_t02_event_rule_contract.v2.schema.json",
                ),
                (
                    "r2_t02_r3_risk_set_contract.json",
                    "r2_t02_risk_set_contract.v2.schema.json",
                ),
            ):
                instance = json.loads((output / artifact).read_text(encoding="utf-8"))
                contract = json.loads(
                    (ROOT / "schemas/r2" / schema).read_text(encoding="utf-8")
                )
                jsonschema.validate(instance, contract)
                instance["undeclared"] = True
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(instance, contract)


if __name__ == "__main__":
    unittest.main()
