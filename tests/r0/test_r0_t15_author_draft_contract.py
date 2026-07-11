# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import unittest
from copy import deepcopy
from pathlib import Path

from src.r0.r0_t15_layer_q_vector_materialization_validator import (
    _validate_attestation,
    _validate_execution_binding,
    _validate_revision_record,
)

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "data/generated/r0/r0_t15/R0-T15-20260710T2136Z"
README = ROOT / "docs/tasks/README.md"


def load_json(name: str) -> dict[str, object]:
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


class R0T15FinalGateContractTests(unittest.TestCase):
    def test_original_author_draft_bytes_are_archived(self) -> None:
        expected = {
            "r0_t15_result_package.author_draft_v1.json": (
                "43aa859dc938f6a9796f68297107d978e9a3b1a36b1ea12fec8c10e5aee27f8b"
            ),
            "r0_t15_authorized_handoff_manifest.author_draft_v1.json": (
                "fa589db97a19c8e4ba5baee272d5250c0a666e476532d316de2f1225feac879d"
            ),
            "r0_t15_result_analysis.author_draft_v1.md": (
                "0ce1ccc4c3c13f39c5447c0c0b74a3d433254bc11bbf11d65a2dc7268b072418"
            ),
            "r0_t15_evidence.author_draft_v1.md": (
                "a9bdbbe581753e22eb7f19731c8871b3057121389e10212948d42ce8ead38a5a"
            ),
        }
        for name, expected_sha256 in expected.items():
            path = RUN_DIR / name
            self.assertTrue(path.is_file(), path)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(), expected_sha256, path
            )
        old_package = load_json("r0_t15_result_package.author_draft_v1.json")
        self.assertEqual(old_package["status"], "author_draft_complete")
        self.assertEqual(old_package["independent_review_status"], "not_started")

    def test_final_gate_passes_but_keeps_every_downstream_gate_closed(self) -> None:
        package = load_json("r0_t15_result_package.json")
        self.assertEqual(
            package["status"], "review_passed_final_gate_passed_pending_merge"
        )
        self.assertEqual(
            package["R0_q_vector_materialization_status"],
            "final_gate_passed_pending_merge",
        )
        self.assertEqual(package["independent_review_status"], "passed")
        self.assertEqual(package["repository_final_gate_status"], "passed")
        self.assertEqual(package["repository_merge_status"], "pending")
        self.assertFalse(package["R1-T14-02_allowed_to_start"])
        self.assertFalse(package["R1-T10_allowed_to_start"])
        self.assertFalse(package["R2_allowed_to_start"])
        self.assertFalse(package["formal_task_completed"])
        self.assertTrue(package["selection_path_not_independently_confirmed"])
        self.assertFalse(package["external_direct_duckdb_byte_review_performed"])
        gate = package["gate_status"]
        self.assertEqual(
            gate["goal_internal_continuation_gate_status"],
            "closed_pending_repository_merge",
        )
        self.assertFalse(gate["goal_internal_continuation_allowed"])
        self.assertFalse(gate["goal_internal_t14_02_authorized"])
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

    def test_handoff_and_package_bind_current_lf_bytes(self) -> None:
        package = load_json("r0_t15_result_package.json")
        handoff = load_json("r0_t15_authorized_handoff_manifest.json")
        manifest_sha = hashlib.sha256(
            (RUN_DIR / "r0_t15_artifact_manifest.json").read_bytes()
        ).hexdigest()
        registry_sha = hashlib.sha256(
            (RUN_DIR / "r0_t15_candidate_registry.csv").read_bytes()
        ).hexdigest()
        handoff_sha = hashlib.sha256(
            (RUN_DIR / "r0_t15_authorized_handoff_manifest.json").read_bytes()
        ).hexdigest()
        self.assertEqual(
            manifest_sha,
            "664b6d4558978806db80912aa5e544e0c81824b188a5ea71fece8e20507a8c51",
        )
        self.assertEqual(
            registry_sha,
            "02fdaf1b94780ef42115a9109ae9f1fd6b90a6e019925a5067ad1bac96d4944f",
        )
        self.assertEqual(handoff["artifact_manifest_sha256"], manifest_sha)
        self.assertEqual(handoff["candidate_registry_sha256"], registry_sha)
        self.assertEqual(package["artifact_manifest_sha256"], manifest_sha)
        self.assertEqual(package["candidate_registry_sha256"], registry_sha)
        self.assertEqual(package["handoff_manifest_sha256"], handoff_sha)

    def test_committed_artifact_hashes_are_current_and_unique(self) -> None:
        package = load_json("r0_t15_result_package.json")
        transition = load_json("r0_t15_repository_merge_transition.json")
        paths = [artifact["path"] for artifact in package["committed_artifacts"]]
        self.assertEqual(len(paths), len(set(paths)))
        for artifact in package["committed_artifacts"]:
            path = ROOT / artifact["path"]
            self.assertTrue(path.is_file(), path)
            current_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if artifact["path"] != "docs/tasks/README.md":
                self.assertEqual(current_sha, artifact["sha256"], path)
                continue
            self.assertEqual(
                artifact["sha256"],
                transition["historical_final_gate_readme_sha256"],
            )
            historical = subprocess.run(
                [
                    "git",
                    "show",
                    f"{transition['final_head_commit']}:{artifact['path']}",
                ],
                cwd=ROOT,
                capture_output=True,
                check=True,
            ).stdout
            self.assertEqual(hashlib.sha256(historical).hexdigest(), artifact["sha256"])
            if current_sha != transition["current_readme_sha256"]:
                t14_final = json.loads(
                    (
                        ROOT / "data/generated/r1/r1_t14_02/"
                        "R1-T14-02-20260711T1100Z/"
                        "r1_t14_02_final_gate_package.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(t14_final["status"], "completed")
                if current_sha != t14_final["task_index_sha256"]:
                    t10_author = json.loads(
                        (
                            ROOT / "data/generated/r1/r1_t10/"
                            "R1-T10-20260711T2000Z/"
                            "r1_t10_result_package.json"
                        ).read_text(encoding="utf-8")
                    )
                    self.assertEqual(t10_author["status"], "completed")
                    self.assertEqual(t10_author["scientific_review_status"], "passed")
                    self.assertTrue(t10_author["formal_task_completed"])
                    self.assertTrue(t10_author["R2_allowed_to_start"])
                    readme_text = README.read_text(encoding="utf-8")
                    if (
                        "R2-T01_status: author_analysis_complete_pending_independent_review"
                        in readme_text
                    ):
                        self.assertIn("R2-T02_allowed_to_start: false", readme_text)
                        self.assertIn("R3_allowed_to_start: false", readme_text)
                    else:
                        self.assertEqual(current_sha, t10_author["task_index_sha256"])

    def test_repository_merge_transition_authorizes_only_t14_02(self) -> None:
        transition = load_json("r0_t15_repository_merge_transition.json")
        self.assertEqual(transition["status"], "passed")
        self.assertEqual(transition["repository_merge_status"], "merged")
        self.assertEqual(
            transition["merge_commit"], "09fb86510dc021f031c5f646777c5202013f2e86"
        )
        self.assertTrue(transition["R1-T14-02_allowed_to_start"])
        self.assertFalse(transition["R1-T10_allowed_to_start"])
        self.assertFalse(transition["R2_allowed_to_start"])

    def test_local_attestation_is_author_local_not_independent_review(self) -> None:
        attestation = load_json("r0_t15_local_duckdb_attestation.json")
        self.assertEqual(attestation["status"], "passed")
        self.assertTrue(attestation["local_duckdb_byte_access"])
        self.assertFalse(attestation["external_direct_duckdb_byte_review_performed"])
        self.assertEqual(
            attestation["independent_byte_validation_status"], "not_performed"
        )
        self.assertEqual(attestation["failures"], [])
        self.assertTrue(all(attestation["checks"].values()))
        self.assertEqual(
            sum(item["file_size_bytes"] for item in attestation["outputs"].values()),
            1_820_639_232,
        )
        self.assertTrue(
            all(
                item["primary_key_duplicate_count"] == 0
                for item in attestation["outputs"].values()
            )
        )

    def test_revision_validator_result_binds_reviewed_package_archive(self) -> None:
        result = load_json("r0_t15_author_revision_package_validation_result.json")
        package_path = RUN_DIR / "r0_t15_result_package.reviewed_rev1.json"
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(
            result["result_package_sha256"],
            hashlib.sha256(package_path.read_bytes()).hexdigest(),
        )
        self.assertFalse(result["goal_internal_continuation_allowed"])
        self.assertFalse(result["R1-T14-02_allowed_to_start"])

    def test_external_review_and_final_validator_bind_reviewed_head(self) -> None:
        review = load_json("r0_t15_external_review.json")
        final = load_json("r0_t15_final_gate_validation_result.json")
        package = load_json("r0_t15_result_package.json")
        self.assertEqual(review["external_review_status"], "passed")
        self.assertEqual(review["review_comment_id"], 4943245857)
        self.assertEqual(
            review["reviewed_pr_head_commit"],
            "3210c35a6a5a5679792bfd455969e78664fc5e13",
        )
        self.assertFalse(review["external_direct_duckdb_byte_review_performed"])
        self.assertEqual(review["independent_byte_validation_status"], "not_performed")
        self.assertEqual(review["blocking_findings"], [])
        self.assertEqual(final["status"], "passed")
        self.assertEqual(final["validation_mode"], "final_package")
        self.assertEqual(final["error_count"], 0)
        self.assertEqual(
            final["result_package_sha256"],
            hashlib.sha256(
                (RUN_DIR / "r0_t15_result_package.json").read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(
            package["reviewed_author_revision_package_sha256"],
            "078cb456c21ef995bcb8e052191ef948d5ea5129e82f7549eef5ed4b3ab917b0",
        )
        self.assertEqual(
            package["handoff_manifest_sha256"],
            "438d2f09ee7a853547a037521ba4ca133bd18bf1fa5dfef91f97db5f670393c3",
        )

    def test_mutated_revision_lineage_and_attestation_fail_closed(self) -> None:
        package = load_json("r0_t15_result_package.json")
        handoff = load_json("r0_t15_authorized_handoff_manifest.json")
        revision = load_json("r0_t15_author_revision.json")
        bad_handoff = deepcopy(handoff)
        bad_handoff["goal_internal_continuation_allowed"] = True
        errors: list[str] = []
        _validate_revision_record(RUN_DIR, package, bad_handoff, revision, errors)
        self.assertIn(
            "handoff_revision_governance_field_mismatch:goal_internal_continuation_allowed",
            errors,
        )

        bad_package = deepcopy(package)
        bad_package["execution_upstream_binding"] = {}
        errors = []
        _validate_execution_binding(bad_package, handoff, revision, errors)
        self.assertIn("package_execution_upstream_binding_mismatch", errors)

        attestation = load_json("r0_t15_local_duckdb_attestation.json")
        bad_attestation = deepcopy(attestation)
        bad_attestation["run_id"] = "wrong"
        errors = []
        _validate_attestation(
            RUN_DIR,
            package,
            bad_attestation,
            errors,
            verify_local_duckdb=False,
        )
        self.assertIn("local_duckdb_attestation_semantics_invalid", errors)

    def test_analysis_preserves_final_gate_and_byte_access_boundaries(self) -> None:
        text = (
            ROOT
            / "docs/experiments/r0/R0-T15_层级q向量正式物化与R1-T14-02交接_result_analysis.md"
        ).read_text(encoding="utf-8")
        for marker in (
            "independent_review_status=passed",
            "repository_final_gate_status=passed",
            "external_direct_duckdb_byte_review_performed=false",
            "goal_internal_continuation_allowed=false",
            "R1-T14-02_allowed_to_start=false",
            "selection_path_not_independently_confirmed=true",
            "formal_task_completed=false",
            "不是独立 reviewer 的直接字节复核",
        ):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
