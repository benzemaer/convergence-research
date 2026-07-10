# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "data/generated/r1/r1_t14_01/R1-T14-01-20260710T2113Z"


def load_json(name: str) -> dict[str, object]:
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


class R1T1401AuthorDraftContractTests(unittest.TestCase):
    def test_author_package_passes_internal_gate_only(self) -> None:
        package = load_json("r1_t14_01_result_package.json")
        self.assertEqual(package["status"], "author_draft_complete")
        self.assertEqual(package["scientific_review_status"], "pending")
        self.assertEqual(package["reviewer_identity"], "unassigned")
        self.assertFalse(package["independence_attestation"])
        self.assertFalse(package["formal_task_completed"])
        self.assertFalse(package["downstream_gate_allowed"])
        self.assertFalse(package["R0_q_vector_materialization_allowed_to_start"])
        self.assertFalse(package["R1-T14-02_allowed_to_start"])
        self.assertFalse(package["R1-T10_allowed_to_start"])
        self.assertFalse(package["R2_allowed_to_start"])
        gate = package["gate_status"]
        self.assertEqual(gate["engineering_validator_status"], "passed")
        self.assertEqual(gate["author_result_analysis_status"], "passed")
        self.assertEqual(gate["anomaly_resolution_status"], "passed")
        self.assertEqual(gate["goal_internal_continuation_gate_status"], "passed")
        self.assertTrue(gate["goal_internal_continuation_allowed"])
        self.assertEqual(gate["repository_final_gate_status"], "pending")

    def test_frozen_request_has_exact_centers_and_neighbors(self) -> None:
        request = load_json("r1_t14_01_materialization_request.json")
        self.assertEqual(request["decision"], "q_vector_materialization_request")
        self.assertEqual(request["center_count"], 4)
        self.assertEqual(request["nonbaseline_formal_vector_count"], 8)
        self.assertEqual(
            {
                row["candidate_q_vector_id"]
                for row in request["frozen_registry"]
                if row["request_role"] == "center"
            },
            {
                "W120_K3_P20_C20_T25_V20",
                "W120_K3_P20_C20_T20_V30",
                "W250_K3_P20_C20_T25_V20",
                "W250_K3_P20_C20_T20_V30",
            },
        )
        self.assertEqual(
            {
                row["candidate_q_vector_id"]
                for row in request["frozen_registry"]
                if row["request_role"] == "immediate_neighbor"
            },
            {
                "W120_K3_P20_C20_T30_V20",
                "W120_K3_P20_C20_T20_V25",
                "W250_K3_P20_C20_T30_V20",
                "W250_K3_P20_C20_T20_V25",
            },
        )
        for row in request["frozen_registry"]:
            self.assertTrue(row["diagnostic_metrics"])
            self.assertIn("state_line_role", row)
            self.assertIn("same_parameter_parent_id", row)
            self.assertIn("warnings", row)

    def test_anomaly_and_reconciliation_are_clean(self) -> None:
        anomaly = load_json("r1_t14_01_anomaly_scan.json")
        self.assertEqual(anomaly["status"], "passed")
        self.assertEqual(anomaly["blocking_findings"], [])
        self.assertEqual(anomaly["unresolved_questions"], [])
        with (RUN_DIR / "r1_t14_01_upstream_reconciliation.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 32)
        self.assertEqual(sum(int(row["mismatch_count"]) for row in rows), 0)

    def test_result_package_hashes_final_artifact_bytes(self) -> None:
        package = load_json("r1_t14_01_result_package.json")
        artifacts = (
            package["primary_result_artifacts"] + package["diagnostic_artifacts"]
        )
        for artifact in artifacts:
            path = ROOT / artifact["path"]
            self.assertTrue(path.is_file(), path)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"], path
            )

    def test_analysis_keeps_scientific_claim_boundary(self) -> None:
        text = (
            ROOT
            / "docs/experiments/r1/R1-T14-01_层级q单变量响应诊断与候选提名_result_analysis.md"
        ).read_text(encoding="utf-8")
        for marker in (
            "author-side scientific analysis",
            "scientific_review_status=pending",
            "selection_path_not_independently_confirmed=true",
            "不能替代 R0-T15 formal materialization",
            "不说明它们是最优 q",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
