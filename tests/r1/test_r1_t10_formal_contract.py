import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Contract(unittest.TestCase):
    def test_config_freezes_scope(self):
        c = json.loads(
            (ROOT / "configs/r1/r1_t10_r1_gate_r2_decision_matrix.v1.json").read_text()
        )
        self.assertEqual(c["expected_matrix_row_count"], 12)
        self.assertFalse(c["author_draft_gate"]["R2_allowed_to_start"])

    def test_no_raw_source_access(self):
        text = (ROOT / "src/r1/r1_t10_r1_gate_r2_decision_matrix.py").read_text()
        self.assertNotIn("MarketDB", text)
        self.assertNotIn("data/raw", text)
