from __future__ import annotations

# ruff: noqa: E501
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/r1/r1_t14_02_formal_structural_revalidation.v2.json"
SCHEMA = ROOT / "schemas/r1/r1_t14_02_formal_structural_revalidation.schema.json"


class R1T1402FormalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_config_validates_and_binds_merged_r0_t15_final_gate(self) -> None:
        Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(
            self.config
        )
        binding = self.config["upstream_binding"]
        self.assertEqual(binding["draft_pr_number"], 88)
        self.assertEqual(
            binding["exact_head_commit"], "faea7a957b84b0bd0e327d1af945c00c967f6ecb"
        )
        self.assertEqual(
            binding["merge_commit"], "09fb86510dc021f031c5f646777c5202013f2e86"
        )
        self.assertTrue(binding["goal_internal_t14_02_authorized"])
        self.assertTrue(binding["repository_t14_02_gate_passed"])
        self.assertTrue(binding["stale_dependency"])
        self.assertTrue(binding["current_dependency_verified"])

    def test_old_run_is_explicitly_superseded(self) -> None:
        superseded = self.config["superseded_run"]
        self.assertEqual(superseded["run_id"], "R1-T14-02-20260710T2340Z")
        record = json.loads(
            (ROOT / superseded["supersession_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(record["status"], "superseded")
        self.assertTrue(record["stale_dependency"])
        self.assertEqual(record["review_comment_id"], 4941877464)

    def test_formal_null_and_family_correction_are_frozen(self) -> None:
        null = self.config["null_model"]
        self.assertEqual(null["N_perm"], 10000)
        self.assertAlmostEqual(null["p_floor"], 1 / 10001)
        self.assertEqual(len(null["families"]), 5)
        self.assertEqual(null["null_sd_zero_policy"], "blocking_anomaly")
        self.assertFalse(null["reuse_prior_null"])

    def test_science_revision_inputs_are_hash_bound(self) -> None:
        inputs = self.config["diagnostic_reconciliation_inputs"]
        self.assertEqual(
            set(inputs),
            {
                "t14_01_robust_envelope",
                "t14_01_interlayer_profile",
                "r1_t06_layer_step_profile",
            },
        )
        self.assertFalse(self.config["robust_envelope_policy"]["fallback_allowed"])

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
