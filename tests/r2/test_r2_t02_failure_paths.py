import json
import tempfile
import unittest
from pathlib import Path

from src.r2.r2_t02_event_rule_contract import build_contract_artifacts
from src.r2.r2_t02_event_rule_contract_validator import (
    R2T02ValidationError,
    validate_contract,
)


class FailurePathTest(unittest.TestCase):
    def test_sidecar_mutation_fails_with_specific_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            build_contract_artifacts(out)
            validate_contract(out)
            path = out / "r2_t02_event_rule_contract.json"
            value = json.loads(path.read_text())
            value["K"] = 4
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(
                R2T02ValidationError,
                "committed_artifact_mismatch:r2_t02_event_rule_contract.json",
            ):
                validate_contract(out)

    def test_validator_does_not_import_builder(self):
        text = (
            Path(__file__).resolve().parents[2]
            / "src/r2/r2_t02_event_rule_contract_validator.py"
        ).read_text()
        self.assertNotIn("from src.r2.r2_t02_event_rule_contract import", text)


if __name__ == "__main__":
    unittest.main()
