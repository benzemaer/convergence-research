from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class R1T1401FormalContractTests(unittest.TestCase):
    def test_config_preserves_author_review_boundary(self) -> None:
        config = json.loads(
            (
                ROOT / "configs/r1/r1_t14_01_layer_q_response_diagnostic.v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(config["grid"]["expected_vector_W_count"], 34)
        self.assertFalse(config["authoritative"])
        self.assertFalse(config["formal_candidate_state"])
        governance = config["governance"]
        self.assertEqual(governance["scientific_review_status"], "pending")
        self.assertEqual(governance["independent_review_status"], "not_started")
        self.assertFalse(governance["downstream_gate_allowed"])
        self.assertFalse(governance["R0_q_vector_materialization_allowed_to_start"])
        self.assertFalse(governance["R1-T14-02_allowed_to_start"])
        self.assertFalse(governance["formal_task_completed"])

    def test_future_outcomes_are_forbidden_selection_inputs(self) -> None:
        config = json.loads(
            (
                ROOT / "configs/r1/r1_t14_01_layer_q_response_diagnostic.v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(config["forbidden_inputs"]),
            {
                "future_return",
                "future_volatility",
                "future_direction",
                "future_path",
                "backtest",
                "trading_result",
            },
        )

    def test_formal_runner_emits_vector_heartbeat(self) -> None:
        source = (ROOT / "src/r1/r1_t14_01_layer_q_response_diagnostic.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("phase=vector_start", source)
        self.assertIn("phase=vector_complete", source)
        self.assertIn("flush=True", source)

    def test_layer_classification_and_request_lineage_are_explicit(self) -> None:
        source = (ROOT / "src/r1/r1_t14_01_layer_q_response_diagnostic.py").read_text(
            encoding="utf-8"
        )
        for marker in (
            "dominant_bottleneck",
            "low_material_impact",
            "structural_dilution_risk",
            '"state_line_role"',
            '"diagnostic_metrics"',
            '"rejected_alternatives"',
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
