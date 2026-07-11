import json
import unittest
from pathlib import Path

from src.r2.r2_t01_final_gate import AUTHOR_PACKAGE_SHA256, REVIEWED_HEAD

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "data/generated/r2/r2_t01/R2-T01-20260712T0020Z"


class R2T01FinalGateTests(unittest.TestCase):
    def test_final_gate_validation_passes(self):
        result = json.loads(
            (RUN / "r2_t01_final_gate_validation_result.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["R2-T02_allowed_to_start"])
        self.assertFalse(result["R3_allowed_to_start"])

    def test_final_gate_binds_reviewed_head_and_package(self):
        package = json.loads(
            (RUN / "r2_t01_final_gate_package.json").read_text(encoding="utf-8")
        )
        self.assertEqual(package["reviewed_pr_head_commit"], REVIEWED_HEAD)
        self.assertEqual(
            package["reviewed_author_package_sha256"], AUTHOR_PACKAGE_SHA256
        )
        self.assertEqual(package["downstream_gate_scope"], "R2-T02_only")

    def test_completed_package_opens_only_r2_t02(self):
        package = json.loads(
            (RUN / "r2_t01_result_package.json").read_text(encoding="utf-8")
        )
        self.assertTrue(package["formal_task_completed"])
        self.assertTrue(package["R2-T02_allowed_to_start"])
        self.assertFalse(package["R3_allowed_to_start"])
        self.assertTrue(package["selection_path_not_independently_confirmed"])


if __name__ == "__main__":
    unittest.main()
