from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class R0T15FormalContractTests(unittest.TestCase):
    def test_upstream_commit_and_hashes_are_immutable(self) -> None:
        config = json.loads(
            (
                ROOT / "configs/r0/r0_t15_layer_q_vector_materialization.v1.json"
            ).read_text(encoding="utf-8")
        )
        binding = config["upstream_binding"]
        self.assertEqual(binding["upstream_pr_number"], 87)
        self.assertEqual(
            binding["upstream_head_commit"], "2e2cc2931a4c3ff1ab427966bc78f79a0f69c151"
        )
        self.assertEqual(
            binding["upstream_internal_continuation_gate_status"], "passed"
        )
        self.assertTrue(binding["goal_internal_r0_materialization_authorized"])
        self.assertFalse(binding["repository_r0_materialization_gate_passed"])
        self.assertFalse(binding["stale_dependency"])
        for key in (
            "upstream_result_package_sha256",
            "upstream_author_analysis_sha256",
            "materialization_request_sha256",
        ):
            self.assertRegex(binding[key], r"^[0-9a-f]{64}$")

    def test_repository_gates_remain_closed(self) -> None:
        config = json.loads(
            (
                ROOT / "configs/r0/r0_t15_layer_q_vector_materialization.v1.json"
            ).read_text(encoding="utf-8")
        )
        governance = config["governance"]
        self.assertEqual(governance["independent_review_status"], "not_started")
        self.assertEqual(governance["repository_final_gate_status"], "pending")
        self.assertFalse(governance["R1-T14-02_allowed_to_start"])
        self.assertFalse(governance["R1-T10_allowed_to_start"])
        self.assertFalse(governance["R2_allowed_to_start"])
        self.assertFalse(governance["formal_task_completed"])


if __name__ == "__main__":
    unittest.main()
