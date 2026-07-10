from __future__ import annotations

import json
import unittest
from hashlib import sha256
from pathlib import Path


class R1T07FormalExperimentContractTest(unittest.TestCase):
    def test_readme_advances_to_r1_t08_after_final_gate(self) -> None:
        text = Path("docs/tasks/README.md").read_text(encoding="utf-8")
        self.assertIn("current_task: R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型", text)
        self.assertIn("next_planned_task: R1-T09 年份稳定性检查", text)
        self.assertIn("R1-T07 completed via PR #83", text)
        self.assertIn("R1-T07_allowed_to_start: true", text)
        self.assertIn("R1-T08_allowed_to_start: true", text)
        self.assertIn("R1-T09_allowed_to_start: false", text)
        self.assertIn("R2_allowed_to_start: false", text)

    def test_independent_scientific_review_is_bound_to_final_gate(
        self,
    ) -> None:
        root = Path.cwd()
        package_path = (
            root
            / "data/generated/r1/r1_t07/R1-T07-20260710T1915Z"
            / "r1_t07_result_package.json"
        )
        review_path = package_path.with_name("r1_t07_scientific_review.json")
        package = json.loads(package_path.read_text(encoding="utf-8"))
        review = json.loads(review_path.read_text(encoding="utf-8"))
        gate = package["gate_status"]
        self.assertEqual(review["scientific_review_status"], "passed")
        self.assertTrue(review["independence_attestation"])
        self.assertEqual(review["implementation_actor"], "codex")
        self.assertEqual(review["reviewer_identity"], "benzemaer")
        self.assertEqual(review["reviewer_role"], "independent_scientific_reviewer")
        self.assertEqual(review["blocking_findings"], [])
        self.assertTrue(review["downstream_gate_recommendation"])
        self.assertEqual(
            review["reviewed_code_commit"],
            "100fb7a5a4f8107a22efcfbe38509fc5342ccc9e",
        )
        self.assertEqual(gate["scientific_review_status"], "passed")
        self.assertEqual(gate["review_phase"], "independent_review_complete")
        self.assertTrue(gate["anomaly_resolution_status"] == "passed")
        self.assertTrue(package["downstream_gate_allowed"])
        self.assertTrue(gate["readme_gate_updated"])
        self.assertEqual(package["status"], "completed")
        self.assertEqual(
            package["scientific_review_record_sha256"], _sha256(review_path)
        )
        self.assertEqual(
            review["reviewed_summary_sha256"], package["experiment_summary_sha256"]
        )
        self.assertEqual(
            review["reviewed_analysis_sha256"], package["result_analysis_sha256"]
        )


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
