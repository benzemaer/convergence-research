import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class R2T01FormalContract(unittest.TestCase):
    def test_config_freezes_role_mapping_and_scope(self):
        config = json.loads(
            (
                ROOT / "configs/r2/r2_t01_candidate_convergence_shortlist.v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(config["task_id"], "R2-T01")
        self.assertEqual(
            config["expected_role_counts"],
            {
                "primary": 4,
                "strict_core_reference": 4,
                "sensitivity": 2,
                "excluded": 2,
            },
        )
        self.assertFalse(config["author_draft_gate_state"]["R2-T02_allowed_to_start"])
        self.assertIn("selected_d", config["forbidden_output_fields"])

    def test_no_raw_or_future_source_access(self):
        text = (ROOT / "src/r2/r2_t01_candidate_convergence_shortlist.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("MarketDB", text)
        self.assertNotIn("data/raw", text)
        self.assertNotIn("future_return", text.replace('"future_return"', ""))


if __name__ == "__main__":
    unittest.main()
