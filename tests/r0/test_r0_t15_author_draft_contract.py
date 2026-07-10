# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "data/generated/r0/r0_t15/R0-T15-20260710T2136Z"


def load_json(name: str) -> dict[str, object]:
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


class R0T15AuthorDraftContractTests(unittest.TestCase):
    def test_author_package_opens_only_internal_t14_02_gate(self) -> None:
        package = load_json("r0_t15_result_package.json")
        self.assertEqual(
            package["R0_q_vector_materialization_status"], "author_draft_complete"
        )
        self.assertEqual(
            package["R0_q_vector_materialization_request_status"],
            "pending_external_review",
        )
        self.assertEqual(package["independent_review_status"], "not_started")
        self.assertEqual(package["repository_final_gate_status"], "pending")
        self.assertFalse(package["R1-T14-02_allowed_to_start"])
        self.assertFalse(package["R1-T10_allowed_to_start"])
        self.assertFalse(package["R2_allowed_to_start"])
        self.assertFalse(package["formal_task_completed"])
        gate = package["gate_status"]
        self.assertEqual(gate["engineering_validator_status"], "passed")
        self.assertEqual(gate["author_result_analysis_status"], "passed")
        self.assertEqual(gate["anomaly_resolution_status"], "passed")
        self.assertEqual(gate["goal_internal_continuation_gate_status"], "passed")
        self.assertTrue(gate["goal_internal_t14_02_authorized"])
        self.assertFalse(gate["repository_t14_02_gate_passed"])

    def test_registry_and_reconciliation_are_exact(self) -> None:
        with (RUN_DIR / "r0_t15_candidate_registry.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            registry = list(csv.DictReader(handle))
        self.assertEqual(len(registry), 10)
        self.assertEqual(sum(row["materialize"] == "true" for row in registry), 8)
        self.assertEqual(sum(row["baseline_reuse"] == "true" for row in registry), 2)
        self.assertEqual(len({row["formal_vector_id"] for row in registry}), 10)
        with (RUN_DIR / "r0_t15_upstream_reconciliation.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            reconciliation = list(csv.DictReader(handle))
        self.assertEqual(len(reconciliation), 32)
        self.assertEqual(sum(int(row["mismatch_count"]) for row in reconciliation), 0)

    def test_anomaly_and_output_manifest_are_clean(self) -> None:
        anomaly = load_json("r0_t15_anomaly_scan.json")
        self.assertEqual(anomaly["status"], "passed")
        self.assertEqual(anomaly["blocking_findings"], [])
        self.assertEqual(anomaly["unresolved_questions"], [])
        self.assertTrue(all(anomaly["checks"].values()))
        manifest = load_json("r0_t15_artifact_manifest.json")
        expected = {
            "dimension_state": 55384608,
            "nested_daily_state": 13846152,
            "daily_confirmation": 55384608,
            "confirmed_interval": 340625,
        }
        for key, count in expected.items():
            output = manifest["outputs"][key]
            self.assertEqual(output["row_count"], count)
            self.assertEqual(output["vector_count"], 8)
            self.assertFalse(output["committed_to_repo"])
            self.assertRegex(output["sha256"], r"^[0-9a-f]{64}$")

    def test_committed_artifact_hashes_are_current(self) -> None:
        package = load_json("r0_t15_result_package.json")
        for artifact in package["committed_artifacts"]:
            path = ROOT / artifact["path"]
            self.assertTrue(path.is_file(), path)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"], path
            )

    def test_analysis_preserves_external_review_boundary(self) -> None:
        text = (
            ROOT
            / "docs/experiments/r0/R0-T15_层级q向量正式物化与R1-T14-02交接_result_analysis.md"
        ).read_text(encoding="utf-8")
        for marker in (
            "不表示独立审阅",
            "repository_final_gate_status=pending",
            "R1-T14-02_allowed_to_start=false",
            "不能据此声称",
            "stale_dependency=true",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
