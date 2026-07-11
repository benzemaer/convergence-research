import json
import unittest
from pathlib import Path

from src.r2.r2_t02_event_rule_contract import (
    evaluate_hard_gate_cell,
    hard_gate_registry,
)

ROOT = Path(__file__).resolve().parents[2]


class HardGateTest(unittest.TestCase):
    def test_thresholds_are_state_line_not_window_specific(self):
        cfg = json.loads(
            (
                ROOT
                / "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v2.json"
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
                / "configs/r2/r2_t02_event_rule_hard_gate_risk_set_contract.v2.json"
            ).read_text()
        )
        self.assertEqual(cfg["event_rule"]["d_grid"], [1, 2, 3])
        self.assertEqual(cfg["event_rule"]["g_grid"], [0, 1, 2])
        self.assertEqual(cfg["candidate_boundary"]["primary_route_count"], 4)

    def test_empty_cell_fails_closed_with_reasons(self):
        metrics = {
            "qualified_event_count": 0,
            "unique_securities_with_qualified_event": 0,
            "qualified_confirmed_day_count": 0,
            "short_interval_drop_rate": None,
            "bridged_day_ratio": None,
            "merge_ratio": None,
            "open_event_ratio": None,
            "nonzero_years": 0,
            "max_year_share": None,
            "duration_q95": None,
        }
        upstream = {
            "upstream_confirmed_interval_count": 0,
            "upstream_unique_securities": 0,
            "upstream_confirmed_state_days": 0,
            "upstream_interval_duration_q95": 0,
        }
        result = evaluate_hard_gate_cell(metrics, "S_PCT", upstream)
        self.assertEqual(result["status"], "failed")
        self.assertIn("qualified_confirmed_day_retention", result["null_reasons"])
        self.assertIn("duration_inflation", result["null_reasons"])


if __name__ == "__main__":
    unittest.main()
