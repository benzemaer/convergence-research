from __future__ import annotations

# ruff: noqa: E501
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/r1/r1_t14_02_formal_structural_revalidation.v1.json"
SCHEMA = ROOT / "schemas/r1/r1_t14_02_formal_structural_revalidation.schema.json"


class R1T1402FormalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_config_validates_and_binds_exact_r0_t15_head(self) -> None:
        Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(
            self.config
        )
        binding = self.config["upstream_binding"]
        self.assertEqual(binding["draft_pr_number"], 88)
        self.assertEqual(
            binding["exact_head_commit"], "35a01fa9ba2e7b20455d7fc5f75d25217892c471"
        )
        self.assertTrue(binding["goal_internal_t14_02_authorized"])
        self.assertFalse(binding["repository_t14_02_gate_passed"])

    def test_formal_null_and_family_correction_are_frozen(self) -> None:
        null = self.config["null_model"]
        self.assertEqual(null["N_perm"], 10000)
        self.assertAlmostEqual(null["p_floor"], 1 / 10001)
        self.assertEqual(len(null["families"]), 5)
        self.assertEqual(null["null_sd_zero_policy"], "blocking_anomaly")

    def test_same_sample_and_external_review_boundaries_are_permanent(self) -> None:
        self.assertTrue(self.config["selection_path_not_independently_confirmed"])
        governance = self.config["governance"]
        self.assertEqual(governance["scientific_review_status"], "pending")
        self.assertEqual(governance["independent_review_status"], "not_started")
        self.assertFalse(governance["downstream_gate_allowed"])
        self.assertFalse(governance["R1-T10_allowed_to_start"])
        self.assertFalse(governance["formal_task_completed"])

    def test_future_outcomes_are_forbidden_inputs(self) -> None:
        forbidden = set(self.config["forbidden_inputs"])
        self.assertTrue(
            {
                "future_return",
                "future_volatility",
                "future_direction",
                "future_path",
                "backtest",
                "trading_result",
            }.issubset(forbidden)
        )


if __name__ == "__main__":
    unittest.main()
