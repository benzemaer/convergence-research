import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/generated/r1/r1_t10/R1-T10-20260711T2000Z"


class AuthorDraft(unittest.TestCase):
    def test_final_gate_completed_after_external_review(self):
        p = json.loads((OUT / "r1_t10_result_package.json").read_text())
        self.assertEqual(p["scientific_review_status"], "passed")
        self.assertEqual(p["independent_review_status"], "passed")
        self.assertTrue(p["formal_task_completed"])
        self.assertTrue(p["R2_allowed_to_start"])
        self.assertTrue(p["selection_path_not_independently_confirmed"])

    def test_author_draft_snapshot_validator_passed(self):
        v = json.loads(
            (OUT / "r1_t10_author_draft_package_validation_result.json").read_text()
        )
        self.assertEqual(v["status"], "passed")
