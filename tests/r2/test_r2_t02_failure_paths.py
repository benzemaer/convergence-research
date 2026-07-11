import csv
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

    def test_synthetic_execution_ledger_mutation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            build_contract_artifacts(out)
            validate_contract(out)
            path = out / "r2_t02_synthetic_case_results.csv"
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["assertion_ledger"] = "[]"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=list(rows[0]), lineterminator="\n"
                )
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(
                R2T02ValidationError, "synthetic_ledger_hash:S01"
            ):
                validate_contract(out)

    def test_synthetic_cases_have_real_execution_ledgers(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            build_contract_artifacts(out)
            with (out / "r2_t02_synthetic_case_results.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 37)
            self.assertTrue(all(int(row["assertion_count"]) > 0 for row in rows))
            self.assertTrue(all(row["assertion_ledger"] != "[]" for row in rows))
            self.assertTrue(all(row["status"] == "passed" for row in rows))


if __name__ == "__main__":
    unittest.main()
