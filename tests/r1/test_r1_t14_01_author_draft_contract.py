# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.r1 import r1_t14_01_layer_q_response_diagnostic_validator as validator
from src.r1.r1_t14_01_layer_q_response_diagnostic_validator import (
    validate_r1_t14_01_layer_q_response_diagnostic,
)

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "data/generated/r1/r1_t14_01/R1-T14-01-20260710T2113Z"


def load_json(name: str) -> dict[str, object]:
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


class R1T1401FinalGateContractTests(unittest.TestCase):
    def test_final_package_opens_only_r0_t15_gate(self) -> None:
        package = load_json("r1_t14_01_result_package.json")
        self.assertEqual(package["status"], "completed")
        self.assertEqual(package["scientific_review_status"], "passed")
        self.assertEqual(package["reviewer_identity"], "benzemaer")
        self.assertTrue(package["independence_attestation"])
        self.assertTrue(package["formal_task_completed"])
        self.assertTrue(package["downstream_gate_allowed"])
        self.assertEqual(package["downstream_gate_scope"], "R0-T15_only")
        self.assertEqual(package["R0_q_vector_materialization_task_id"], "R0-T15")
        self.assertEqual(
            package["R0_q_vector_materialization_request_status"], "approved"
        )
        self.assertTrue(package["R0_q_vector_materialization_allowed_to_start"])
        self.assertFalse(package["R1-T14-02_allowed_to_start"])
        self.assertFalse(package["R1-T10_allowed_to_start"])
        self.assertFalse(package["R2_allowed_to_start"])
        self.assertTrue(package["selection_path_not_independently_confirmed"])
        gate = package["gate_status"]
        self.assertEqual(gate["engineering_validator_status"], "passed")
        self.assertEqual(gate["author_result_analysis_status"], "passed")
        self.assertEqual(gate["anomaly_resolution_status"], "passed")
        self.assertEqual(gate["goal_internal_continuation_gate_status"], "passed")
        self.assertTrue(gate["goal_internal_continuation_allowed"])
        self.assertEqual(gate["scientific_review_status"], "passed")
        self.assertEqual(gate["review_phase"], "independent_review_complete")
        self.assertEqual(gate["independent_review_status"], "completed")
        self.assertEqual(gate["repository_final_gate_status"], "passed")

    def test_review_record_binds_external_comment_and_author_bytes(self) -> None:
        package = load_json("r1_t14_01_result_package.json")
        review = load_json("r1_t14_01_scientific_review.json")
        summary_path = RUN_DIR / "r1_t14_01_diagnostic_summary.json"
        analysis_path = ROOT / package["result_analysis_path"]
        self.assertEqual(review["review_comment_id"], 4941866339)
        self.assertEqual(review["reviewer_identity"], "benzemaer")
        self.assertEqual(review["implementation_actor"], "codex")
        self.assertTrue(review["independence_attestation"])
        self.assertEqual(review["blocking_findings"], [])
        self.assertEqual(
            review["reviewed_summary_sha256"],
            hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            review["reviewed_analysis_sha256"],
            hashlib.sha256(analysis_path.read_bytes()).hexdigest(),
        )
        request = load_json("r1_t14_01_materialization_request.json")
        self.assertEqual(request["scientific_review_status"], "pending")
        self.assertEqual(request["reviewer_identity"], "unassigned")
        self.assertFalse(request["independence_attestation"])
        self.assertEqual(
            package["decision_sha256"],
            hashlib.sha256(
                (RUN_DIR / "r1_t14_01_materialization_request.json").read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(review["reviewed_decision_sha256"], package["decision_sha256"])

    def test_final_gate_validator_passes_and_rejects_downstream_overreach(self) -> None:
        result = load_json("r1_t14_01_final_gate_package_validation_result.json")
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["formal_task_completed"])
        self.assertEqual(result["downstream_gate_scope"], "R0-T15_only")
        self.assertTrue(result["R0_q_vector_materialization_allowed_to_start"])
        self.assertFalse(result["R1-T14-02_allowed_to_start"])
        self.assertFalse(result["R1-T10_allowed_to_start"])
        self.assertFalse(result["R2_allowed_to_start"])
        self.assertEqual(
            result["result_package_sha256"],
            hashlib.sha256(
                (RUN_DIR / "r1_t14_01_result_package.json").read_bytes()
            ).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / RUN_DIR.name
            shutil.copytree(RUN_DIR, copied)
            package_path = copied / "r1_t14_01_result_package.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["R1-T14-02_allowed_to_start"] = True
            package_path.write_text(
                json.dumps(package, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            invalid = validate_r1_t14_01_layer_q_response_diagnostic(
                run_dir=copied, require_final_package=True
            )
            self.assertEqual(invalid["status"], "failed")
            self.assertIn(
                "final_package_field_mismatch:R1-T14-02_allowed_to_start",
                invalid["errors"],
            )

    def test_final_gate_rehashes_analysis_and_current_readme_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            copied = temporary_root / RUN_DIR.relative_to(ROOT)
            shutil.copytree(RUN_DIR, copied)
            package = json.loads(
                (copied / "r1_t14_01_result_package.json").read_text(encoding="utf-8")
            )
            for key in (
                "result_analysis_path",
                "formal_evidence_path",
                "scientific_review_md_path",
                "readme_path",
                "config_path",
            ):
                source = ROOT / package[key]
                target = temporary_root / package[key]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            analysis_path = temporary_root / package["result_analysis_path"]
            analysis_path.write_text(
                analysis_path.read_text(encoding="utf-8") + "\nmutated\n",
                encoding="utf-8",
            )
            with mock.patch.object(validator, "ROOT", temporary_root):
                invalid_analysis = validate_r1_t14_01_layer_q_response_diagnostic(
                    run_dir=copied, require_final_package=True
                )
            self.assertIn("result_analysis_hash_mismatch", invalid_analysis["errors"])

            shutil.copy2(ROOT / package["result_analysis_path"], analysis_path)
            readme_path = temporary_root / package["readme_path"]
            readme_text = readme_path.read_text(encoding="utf-8")
            current, remainder = readme_text.split("## 命名与路径规则", 1)
            current = current.replace(
                "R1-T14-02_allowed_to_start: false",
                "R1-T14-02_allowed_to_start: true",
            )
            readme_path.write_text(
                current + "## 命名与路径规则" + remainder,
                encoding="utf-8",
            )
            package["readme_sha256"] = hashlib.sha256(
                readme_path.read_bytes()
            ).hexdigest()
            (copied / "r1_t14_01_result_package.json").write_text(
                json.dumps(package, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(validator, "ROOT", temporary_root):
                invalid_readme = validate_r1_t14_01_layer_q_response_diagnostic(
                    run_dir=copied, require_final_package=True
                )
            self.assertIn(
                "readme_final_gate_marker_missing:R1-T14-02_allowed_to_start: false",
                invalid_readme["errors"],
            )

            config_path = temporary_root / package["config_path"]
            config_path.write_text(
                config_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(validator, "ROOT", temporary_root):
                invalid_config = validate_r1_t14_01_layer_q_response_diagnostic(
                    run_dir=copied, require_final_package=True
                )
            self.assertIn("config_hash_mismatch", invalid_config["errors"])

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
