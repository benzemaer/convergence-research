import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class AuthorDraftTest(unittest.TestCase):
    def test_author_cannot_open_t03(self):
        cfg = json.loads(
            (
                ROOT
                / "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v1.json"
            ).read_text()
        )
        gate = cfg["author_draft_gate_state"]
        self.assertFalse(gate["formal_task_completed"])
        self.assertFalse(gate["R2-T03_allowed_to_start"])
        self.assertEqual(gate["R2-T02_scientific_review_status"], "pending")

    def test_forbidden_fields_frozen(self):
        cfg = json.loads(
            (
                ROOT
                / "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v1.json"
            ).read_text()
        )
        self.assertIn("future_return", cfg["forbidden_output_fields"])
        self.assertIn("selected_d", cfg["forbidden_output_fields"])


if __name__ == "__main__":
    unittest.main()
