import json
import unittest
from pathlib import Path

from src.r2.r2_t02_event_rule_contract import hard_gate_registry

ROOT = Path(__file__).resolve().parents[2]


class HardGateTest(unittest.TestCase):
    def test_thresholds_are_state_line_not_window_specific(self):
        cfg = json.loads(
            (
                ROOT
                / "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v1.json"
            ).read_text()
        )
        self.assertEqual(
            set(cfg["hard_gates"]), {"global_zero_tolerance", "S_PCT", "S_PCVT"}
        )
        self.assertGreaterEqual(len(hard_gate_registry()), 30)

    def test_grid_and_candidate_boundary(self):
        cfg = json.loads(
            (
                ROOT
                / "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v1.json"
            ).read_text()
        )
        self.assertEqual(cfg["event_rule"]["d_grid"], [1, 2, 3])
        self.assertEqual(cfg["event_rule"]["g_grid"], [0, 1, 2])
        self.assertEqual(cfg["candidate_boundary"]["primary_route_count"], 4)


if __name__ == "__main__":
    unittest.main()
