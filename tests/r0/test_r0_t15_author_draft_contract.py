# ruff: noqa: E501
from __future__ import annotations

import csv
import hashlib
import json
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


def load_json(name: str) -> dict[str, object]:
    return json.loads((RUN_DIR / name).read_text(encoding="utf-8"))


class R0T15AuthorRevisionContractTests(unittest.TestCase):
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

    def test_author_revision_keeps_every_downstream_gate_closed(self) -> None:
        package = load_json("r0_t15_result_package.json")
        self.assertEqual(package["status"], "author_revision_complete")
        self.assertEqual(
            package["R0_q_vector_materialization_status"],
            "author_revision_complete_pending_rereview",
        )
        self.assertEqual(package["independent_review_status"], "pending_rereview")
        self.assertEqual(package["repository_final_gate_status"], "pending")
        self.assertFalse(package["R1-T14-02_allowed_to_start"])
        self.assertFalse(package["R1-T10_allowed_to_start"])
        self.assertFalse(package["R2_allowed_to_start"])
        self.assertFalse(package["formal_task_completed"])
        self.assertTrue(package["selection_path_not_independently_confirmed"])
        self.assertFalse(package["external_direct_duckdb_byte_review_performed"])
        gate = package["gate_status"]
        self.assertEqual(
            gate["goal_internal_continuation_gate_status"],
            "closed_pending_external_rereview",
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
        paths = [artifact["path"] for artifact in package["committed_artifacts"]]
        self.assertEqual(len(paths), len(set(paths)))
        for artifact in package["committed_artifacts"]:
            path = ROOT / artifact["path"]
            self.assertTrue(path.is_file(), path)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"], path
            )

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

    def test_revision_validator_result_binds_current_package(self) -> None:
        result = load_json("r0_t15_author_revision_package_validation_result.json")
        package_path = RUN_DIR / "r0_t15_result_package.json"
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(
            result["result_package_sha256"],
            hashlib.sha256(package_path.read_bytes()).hexdigest(),
        )
        self.assertFalse(result["goal_internal_continuation_allowed"])
        self.assertFalse(result["R1-T14-02_allowed_to_start"])

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

    def test_analysis_preserves_rereview_and_byte_access_boundaries(self) -> None:
        text = (
            ROOT
            / "docs/experiments/r0/R0-T15_层级q向量正式物化与R1-T14-02交接_result_analysis.md"
        ).read_text(encoding="utf-8")
        for marker in (
            "independent_review_status=pending_rereview",
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
