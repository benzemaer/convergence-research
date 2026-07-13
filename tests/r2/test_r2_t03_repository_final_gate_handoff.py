from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator

from src.r2 import r2_t03_repository_final_gate_handoff as handoff

ROOT = Path(__file__).resolve().parents[2]


class R2T03RepositoryFinalGateHandoffTest(unittest.TestCase):
    def test_author_package_is_immutable(self) -> None:
        package = json.loads(
            (ROOT / handoff.RUN_DIR / "r2_t03_result_package.json").read_text(
                encoding="utf-8"
            )
        )
        handoff._validate_immutable_author(package)
        mutated = copy.deepcopy(package)
        mutated["formal_task_completed"] = True
        with self.assertRaisesRegex(
            handoff.R2T03HandoffError,
            "author_package_lifecycle_mutated:formal_task_completed",
        ):
            handoff._validate_immutable_author(mutated)

    def test_handoff_semantics_reject_t02_consumer_as_passed(self) -> None:
        payload = {
            "task_id": "R2-T03",
            "promoted_run_id": handoff.RUN_ID,
            "scientific_review_status": "passed",
            "repository_final_gate_status": "passed",
            "formal_task_completed": True,
            "R2-T04_allowed_to_start": True,
            "R2-T05_allowed_to_start": False,
            "R3_allowed_to_start": False,
            "reviewed_head_sha": handoff.REVIEWED_HEAD,
            "merge_commit": handoff.MERGE_COMMIT,
            "scientific_review_id": handoff.SCIENTIFIC_REVIEW_ID,
            "ready_workflow_run_id": handoff.READY_WORKFLOW_RUN_ID,
            "premerge_job_id": handoff.PREMERGE_JOB_ID,
            "ready_workflow_overall_conclusion": "failure",
            "full_profile_status": "passed",
            "t02_evidence_build_status": "passed",
            "t02_evidence_consumer_status": "passed",
            "t02_evidence_consumer_error": (
                "formal_surface_changed_after_artifact_commit"
            ),
            "t02_consumer_applicability_to_r2_t03": "not_applicable",
            "administrator_merge": True,
            "administrator_exception_recorded": True,
        }
        with self.assertRaisesRegex(
            handoff.R2T03HandoffError,
            "handoff_semantic_mismatch:t02_evidence_consumer_status",
        ):
            handoff._validate_handoff_semantics(payload)

    def test_remote_facts_reconcile_from_github_api_shape(self) -> None:
        run = {
            "id": handoff.READY_WORKFLOW_RUN_ID,
            "head_sha": handoff.REVIEWED_HEAD,
            "conclusion": "failure",
        }
        job = {
            "id": handoff.PREMERGE_JOB_ID,
            "head_sha": handoff.REVIEWED_HEAD,
            "name": "premerge-full",
            "steps": [
                {"name": n, "conclusion": c}
                for n, c in [
                    ("Run full profile on reviewed head", "success"),
                    ("Fetch authenticated GitHub scientific reviews", "success"),
                    ("Build R2-T02 premerge full evidence", "success"),
                    ("Consume R2-T02 premerge full evidence final gate", "failure"),
                ]
            ],
        }
        pr = {
            "merge_commit_sha": handoff.MERGE_COMMIT,
            "head": {"sha": handoff.REVIEWED_HEAD},
        }
        review = {
            "id": handoff.SCIENTIFIC_REVIEW_ID,
            "commit_id": handoff.REVIEWED_HEAD,
            "state": "COMMENTED",
            "body": "[R2-T02 scientific PASS]\nscientific_review_status=passed",
        }
        with (
            mock.patch.object(handoff, "_gh_json", side_effect=[run, job, pr]),
            mock.patch.object(handoff, "_gh_json_list", return_value=[review]),
        ):
            facts = handoff._validate_remote_facts(ROOT)
        self.assertEqual(facts["review"]["id"], handoff.SCIENTIFIC_REVIEW_ID)

    def test_schemas_are_strict(self) -> None:
        for path in (handoff.HANDOFF_SCHEMA, handoff.VALIDATION_SCHEMA):
            schema = json.loads((ROOT / path).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
