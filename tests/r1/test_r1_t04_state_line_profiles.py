from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.r1.r1_t04_state_line_profiles import _comparison_status, _quantile_ordered


class R1T04StateLineProfilesTest(unittest.TestCase):
    def test_registry_is_exact_and_q_is_fixed(self) -> None:
        config = json.loads(Path("configs/r1/r1_t04_state_line_profiles.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(config["q"], 0.2)
        self.assertEqual(len(config["profiles"]), 7)
        self.assertEqual(len({(row["state_line"], row["candidate_config_id"]) for row in config["profiles"]}), 7)

    def test_description_status_never_selects_a_winner(self) -> None:
        self.assertEqual(_comparison_status("reference_vs_fast_challenger", 0.1, 0.2, 0.8), "sensitivity_coherence_tradeoff")
        self.assertNotIn("best", _comparison_status("reference_vs_long_window", -0.1, -0.1, 1.2))

    def test_duration_quantile_order(self) -> None:
        self.assertTrue(_quantile_ordered({"min": 1, "q10": 1, "q25": 2, "q50": 3, "q75": 3, "q90": 4, "q95": 4, "q99": 5, "max": 6}))
        self.assertFalse(_quantile_ordered({"min": 2, "q10": 1, "q25": 2, "q50": 3, "q75": 3, "q90": 4, "q95": 4, "q99": 5, "max": 6}))


if __name__ == "__main__":
    unittest.main()
