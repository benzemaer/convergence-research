from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator

from src.r2 import r2_t02_repository_final_gate_handoff as handoff

ROOT = Path(__file__).resolve().parents[2]


class R2T02RepositoryFinalGateHandoffTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(
            (ROOT / handoff.EVIDENCE_PATH).read_text(encoding="utf-8")
        )
        cls.reviews = json.loads(
            (ROOT / handoff.ARTIFACT_DIR / "review_pages.json").read_text(
                encoding="utf-8"
            )
        )

    def test_workflow_artifacts_are_exact_expected_set(self) -> None:
        names = {path.name for path in (ROOT / handoff.ARTIFACT_DIR).iterdir()}
        self.assertEqual(
            names,
            {
                "full_profile_result.json",
                "review_pages.json",
                "r2_t02_premerge_full_evidence.json",
            },
        )

    def test_downloaded_evidence_and_review_identity_reconcile(self) -> None:
        handoff._validate_evidence_identity(self.evidence, self.reviews)
        self.assertEqual(self.evidence["workflow_run_id"], handoff.WORKFLOW_RUN_ID)
        self.assertEqual(
            self.evidence["github_scientific_review_id"],
            handoff.SCIENTIFIC_REVIEW_ID,
        )

    def test_evidence_mutations_fail_closed(self) -> None:
        for key, value in {
            "workflow_run_id": 1,
            "tested_head_sha": "0" * 40,
            "reviewed_head_sha": "0" * 40,
            "github_scientific_review_id": 1,
        }.items():
            with self.subTest(key=key):
                mutated = copy.deepcopy(self.evidence)
                mutated[key] = value
                with self.assertRaisesRegex(
                    handoff.R2T02HandoffError,
                    f"workflow_evidence_identity_mismatch:{key}",
                ):
                    handoff._validate_evidence_identity(mutated, self.reviews)

    def test_review_snapshot_mutations_fail_closed(self) -> None:
        mutated = copy.deepcopy(self.reviews)
        target = next(
            row
            for row in mutated
            if int(row.get("id", 0)) == handoff.SCIENTIFIC_REVIEW_ID
        )
        target["body"] = "scientific result omitted"
        with self.assertRaisesRegex(
            handoff.R2T02HandoffError, "scientific_review_snapshot_mismatch"
        ):
            handoff._validate_evidence_identity(self.evidence, mutated)

    def test_author_package_must_remain_immutable_author_stage(self) -> None:
        author = json.loads(
            (ROOT / handoff.RUN_DIR / "r2_t02_result_package.json").read_text(
                encoding="utf-8"
            )
        )
        handoff._validate_immutable_author_package(author)
        for key, value in {
            "scientific_review_status": "passed",
            "repository_final_gate_status": "passed",
            "formal_task_completed": True,
            "R2-T03_allowed_to_start": True,
        }.items():
            with self.subTest(key=key):
                mutated = copy.deepcopy(author)
                mutated[key] = value
                with self.assertRaisesRegex(
                    handoff.R2T02HandoffError,
                    f"author_package_lifecycle_mutated:{key}",
                ):
                    handoff._validate_immutable_author_package(mutated)

    def test_exact_reviewed_head_is_direct_merge_parent(self) -> None:
        parents = handoff._validate_merge_ancestry("HEAD", ROOT)
        self.assertIn(handoff.REVIEWED_HEAD, parents)

    def test_remote_artifact_digest_and_job_must_match(self) -> None:
        artifact = {
            "id": handoff.ARTIFACT_ID,
            "name": handoff.ARTIFACT_NAME,
            "digest": handoff.ARTIFACT_DIGEST,
            "expired": False,
            "workflow_run": {
                "id": handoff.WORKFLOW_RUN_ID,
                "head_sha": handoff.REVIEWED_HEAD,
            },
        }
        job = {
            "id": handoff.PREMERGE_JOB_ID,
            "run_id": handoff.WORKFLOW_RUN_ID,
            "head_sha": handoff.REVIEWED_HEAD,
            "name": "premerge-full",
            "conclusion": "success",
        }
        with mock.patch.object(handoff, "_gh_json", side_effect=[artifact, job]):
            self.assertEqual(
                handoff._validate_remote_metadata(ROOT), {"expired": False}
            )
        mutated = copy.deepcopy(artifact)
        mutated["digest"] = "sha256:" + "0" * 64
        with mock.patch.object(handoff, "_gh_json", side_effect=[mutated, job]):
            with self.assertRaisesRegex(
                handoff.R2T02HandoffError,
                "remote_metadata_mismatch:artifact.digest",
            ):
                handoff._validate_remote_metadata(ROOT)

    def test_handoff_schemas_are_strict(self) -> None:
        for schema_path in [handoff.HANDOFF_SCHEMA, handoff.VALIDATION_SCHEMA]:
            schema = json.loads((ROOT / schema_path).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self.assertFalse(schema["additionalProperties"])

    def test_handoff_semantics_reject_downstream_overreach(self) -> None:
        payload = {
            "task_id": "R2-T02",
            "run_id": handoff.RUN_ID,
            "author_package_lifecycle": "immutable_author_stage",
            "scientific_review_status": "passed",
            "repository_final_gate_status": "passed",
            "formal_task_completed": True,
            "R2-T03_allowed_to_start": True,
            "R2-T04_allowed_to_start": True,
            "R3_allowed_to_start": False,
            "selection_path_not_independently_confirmed": True,
            "repository": handoff.REPOSITORY,
            "pull_request_number": handoff.PR_NUMBER,
            "workflow_name": handoff.WORKFLOW_NAME,
            "workflow_run_id": handoff.WORKFLOW_RUN_ID,
            "premerge_job_id": handoff.PREMERGE_JOB_ID,
            "reviewed_head_sha": handoff.REVIEWED_HEAD,
            "merge_commit": handoff.MERGE_COMMIT,
            "scientific_review_id": handoff.SCIENTIFIC_REVIEW_ID,
            "workflow_artifact": {},
        }
        with self.assertRaisesRegex(
            handoff.R2T02HandoffError,
            "handoff_semantic_mismatch:R2-T04_allowed_to_start",
        ):
            handoff._validate_handoff_semantics(payload)

    def test_committed_handoff_and_validation_pass(self) -> None:
        run_dir = ROOT / handoff.RUN_DIR
        payload = json.loads(
            (run_dir / handoff.HANDOFF_NAME).read_text(encoding="utf-8")
        )
        result = json.loads(
            (run_dir / handoff.VALIDATION_NAME).read_text(encoding="utf-8")
        )
        handoff._validate_schema(payload, ROOT / handoff.HANDOFF_SCHEMA)
        handoff._validate_schema(result, ROOT / handoff.VALIDATION_SCHEMA)
        replay = handoff.validate_handoff(
            run_dir / handoff.HANDOFF_NAME,
            handoff_commit=result["handoff_commit"],
            root=ROOT,
            verify_remote=False,
        )
        self.assertEqual(replay["status"], "passed")
        self.assertTrue(replay["R2-T03_allowed_to_start"])
        self.assertFalse(replay["R2-T04_allowed_to_start"])


if __name__ == "__main__":
    unittest.main()
