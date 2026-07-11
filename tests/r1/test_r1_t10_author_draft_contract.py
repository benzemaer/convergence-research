import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/generated/r1/r1_t10/R1-T10-20260711T2000Z"


class AuthorDraft(unittest.TestCase):
    def test_gate_closed(self):
        p = json.loads((OUT / "r1_t10_result_package.json").read_text())
        self.assertEqual(p["scientific_review_status"], "pending")
        self.assertFalse(p["formal_task_completed"])
        self.assertFalse(p["R2_allowed_to_start"])

    def test_validator_passes(self):
        v = json.loads(
            (OUT / "r1_t10_author_draft_package_validation_result.json").read_text()
        )
        self.assertEqual(v["status"], "passed")
