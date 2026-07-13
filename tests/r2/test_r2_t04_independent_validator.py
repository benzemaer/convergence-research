import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.r2.r2_t04_independent_validator import (
    validate_independently,
    validate_phase_b,
)

ROOT = Path(__file__).resolve().parents[2]
REAL_OUTPUT = ROOT / "data/generated/r2/r2_t04/R2-T04-20260713T120000Z"
PHASE_B_READY = REAL_OUTPUT / "r2_t04_user_decision_input.json"


class R2T04IndependentValidatorTest(unittest.TestCase):
    def test_validator_is_callable(self):
        self.assertTrue(callable(validate_independently))

    @unittest.skipUnless(
        PHASE_B_READY.exists(), "Phase B output is generated in the PR"
    )
    def test_phase_b_rejects_gate_status_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / REAL_OUTPUT.name
            shutil.copytree(REAL_OUTPUT, target)
            path = target / "r2_t04_selected_cell_gate_revalidation.csv"
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(",passed,False,False,", ",failed,False,False,", 1),
                encoding="utf-8",
            )
            result = validate_phase_b(target)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(
                any("gate_revalidation" in error for error in result["errors"])
            )

    @unittest.skipUnless(
        PHASE_B_READY.exists(), "Phase B output is generated in the PR"
    )
    def test_phase_b_rejects_W250_plan_and_hash_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / REAL_OUTPUT.name
            shutil.copytree(REAL_OUTPUT, target)
            path = target / "r2_t04_freeze_plan_manifest.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["planned_versions"][0]["W"] = 250
            path.write_text(json.dumps(value), encoding="utf-8")
            result = validate_phase_b(target)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(
                any("hash" in error or "W250" in error for error in result["errors"])
            )


if __name__ == "__main__":
    unittest.main()
