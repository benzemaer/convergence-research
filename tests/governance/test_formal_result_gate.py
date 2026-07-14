from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from src.governance.formal_result_gate import validate_formal_result_gate

ROOT = Path(__file__).resolve().parents[2]


class FormalResultGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.directory.name)
        git(self.repo, "init", "-q", "--initial-branch=main")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "formal-result-test")
        write(self.repo / "README.md", "base\n")
        self.base = commit(self.repo, "base")
        write(self.repo / "src/r3/r3_t01.py", "IMPLEMENTATION = 1\n")
        self.implementation = commit(self.repo, "implementation")
        write(
            self.repo / "data/generated/r3/r3_t01/example/result_package.json",
            json.dumps({"task_id": "R3-T01", "run_id": "R3-T01-run"}) + "\n",
        )
        write(
            self.repo / "docs/experiments/r3/r3_t01/example/result_analysis.md",
            "analysis\n",
        )
        write(
            self.repo / "data/generated/r3/r3_t01/example/input_manifest.json",
            '{"input": true}\n',
        )
        self.artifact = commit(self.repo, "artifact")
        self._write_manifest()
        write(self.repo / "docs/tasks/README.md", "governance metadata\n")
        self.current = commit(self.repo, "post review metadata")
        self._write_full_profile()
        self._write_reviews()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _write_manifest(self, **overrides: object) -> None:
        result_path = "data/generated/r3/r3_t01/example/result_package.json"
        analysis_path = "docs/experiments/r3/r3_t01/example/result_analysis.md"
        input_path = "data/generated/r3/r3_t01/example/input_manifest.json"
        payload = {
            "schema_version": 1,
            "pr_type": "formal-result",
            "task_id": "R3-T01",
            "run_id": "R3-T01-run",
            "implementation_actor": "codex",
            "implementation_merge_sha": self.implementation,
            "formal_execution_sha": self.implementation,
            "artifact_commit_sha": self.artifact,
            "result_package": {
                "path": result_path,
                "sha256": file_sha(self.repo / result_path),
            },
            "result_analysis": {
                "path": analysis_path,
                "sha256": file_sha(self.repo / analysis_path),
            },
            "input_manifest": {
                "path": input_path,
                "sha256": file_sha(self.repo / input_path),
            },
            "implementation_protected_paths": ["src/r3/r3_t01.py"],
            "scientific_review_protected_paths": [
                "src/r3/r3_t01.py",
                result_path,
                analysis_path,
                input_path,
            ],
            "allowed_post_review_paths": [
                "formal_submission.json",
                "docs/tasks/README.md",
            ],
            "downstream_gate_scope": "R3-T02_only",
        }
        payload.update(overrides)
        write(
            self.repo / "formal_submission.json", json.dumps(payload, indent=2) + "\n"
        )

    def _write_full_profile(self, **overrides: object) -> None:
        payload = {
            "profile": "full",
            "status": "passed",
            "test_count": 10,
            "failure_count": 0,
            "error_count": 0,
            "tested_head_sha": self.current,
        }
        payload.update(overrides)
        write(self.repo / "full.json", json.dumps(payload) + "\n")

    def _write_reviews(self, **overrides: object) -> None:
        marker = self._marker()
        review = {
            "id": 7,
            "state": "COMMENTED",
            "body": marker,
            "commit_id": self.artifact,
            "submitted_at": "2026-07-14T00:00:00Z",
            "user": {"login": "independent-reviewer"},
        }
        review.update(overrides)
        write(self.repo / "reviews.json", json.dumps([review]) + "\n")

    def _marker(
        self,
        *,
        task_id: str = "R3-T01",
        run_id: str = "R3-T01-run",
        artifact_commit: str | None = None,
    ) -> str:
        result_hash = json.loads((self.repo / "formal_submission.json").read_text())[
            "result_package"
        ]["sha256"]
        return (
            f"[SCIENTIFIC PASS] task_id={task_id} run_id={run_id} "
            f"artifact_commit={artifact_commit or self.artifact} "
            f"result_package_sha256={result_hash} independence_attestation=true"
        )

    def _run(self, **kwargs: object) -> dict:
        manifest = json.loads((self.repo / "formal_submission.json").read_text())
        result = validate_formal_result_gate(
            submission_manifest=self.repo / "formal_submission.json",
            github_reviews_json=self.repo / "reviews.json",
            full_profile_result=self.repo / "full.json",
            current_head_sha=kwargs.pop("current_head_sha", self.current),
            pull_request_number=100,
            repository="benzemaer/convergence-research",
            root=self.repo,
        )
        self.assertEqual(result["task_id"], manifest.get("task_id"))
        return result

    def test_valid_fixture_passes_and_review_need_not_equal_current_head(self) -> None:
        result = self._run()
        self.assertEqual(result["status"], "passed")
        self.assertNotEqual(self.artifact, self.current)
        self.assertTrue(result["downstream_gate_allowed"])

    def test_manifest_schema_and_static_workflow_contract(self) -> None:
        schema = json.loads(
            (
                ROOT / "schemas/governance/formal_result_submission.schema.json"
            ).read_text()
        )
        example = json.loads(
            (
                ROOT / "configs/governance/formal_result_submission.example.json"
            ).read_text()
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(example)
        quality = (ROOT / ".github/workflows/quality.yml").read_text()
        formal = (ROOT / ".github/workflows/formal-result-gate.yml").read_text()
        self.assertNotIn("premerge-full", quality)
        self.assertNotIn("R2-T02", quality)
        self.assertNotIn("scientific PASS", quality)
        self.assertIn("workflow_dispatch", formal)
        self.assertNotRegex(formal, re.compile(r"R[0-9]-T[0-9]"))
        self.assertNotRegex(formal, re.compile(r"data/generated/r[0-9]"))
        self.assertNotRegex(
            (ROOT / "src/governance/formal_result_gate.py").read_text(),
            re.compile(r"R[0-9]-T[0-9]"),
        )

    def test_history_is_present_and_unchanged_surface_is_not_migrated(self) -> None:
        for path in [
            "configs/governance/r_formal_experiment_governance.v1.json",
            "docs/evidence/governance/GOV-T01_R1-R6_formal实验结果与科学审阅治理_evidence.md",
            "src/r2/r2_t02_premerge_full_evidence.py",
            "schemas/r2/r2_t02_premerge_full_evidence.schema.json",
        ]:
            self.assertTrue((ROOT / path).exists(), path)

    def test_ancestor_and_protected_path_failures_are_fail_closed(self) -> None:
        self._write_manifest(implementation_merge_sha="9" * 40)
        result = self._run()
        self.assertIn(
            "implementation_merge_not_ancestor_of_formal_execution", result["errors"]
        )

        self._write_manifest()
        write(self.repo / "src/r3/r3_t01.py", "FORMAL_RESULT_CHANGED = 1\n")
        commit(self.repo, "illegal implementation change")
        self.current = git(self.repo, "rev-parse", "HEAD")
        self._write_full_profile(tested_head_sha=self.current)
        result = self._run()
        self.assertIn(
            "scientific_review_protected_surface_changed:src/r3/r3_t01.py",
            result["errors"],
        )

        self._write_manifest(
            implementation_merge_sha=self.base,
            formal_execution_sha=self.current,
            artifact_commit_sha=self.current,
        )
        self._write_reviews()
        result = self._run()
        self.assertIn(
            "implementation_changed_requires_new_implementation_pr:src/r3/r3_t01.py",
            result["errors"],
        )

    def test_artifact_hash_and_result_identity_failures(self) -> None:
        self._write_manifest(
            result_package={
                "path": "data/generated/r3/r3_t01/example/result_package.json",
                "sha256": "f" * 64,
            }
        )
        result = self._run()
        self.assertIn("result_package_hash_mismatch", result["errors"])

        self._write_manifest()
        package = self.repo / "data/generated/r3/r3_t01/example/result_package.json"
        package.write_text(
            json.dumps({"task_id": "OTHER", "run_id": "R3-T01-run"}) + "\n"
        )
        result = self._run()
        self.assertIn("result_package_task_id_mismatch", result["errors"])

    def test_scientific_marker_mismatches_and_reviewer_identity_fail(self) -> None:
        cases = [
            ("task_id", "scientific_pass_task_id_mismatch"),
            ("run_id", "scientific_pass_run_id_mismatch"),
            ("commit_id", "scientific_pass_review_commit_not_ancestor"),
        ]
        for field, error in cases:
            with self.subTest(field=field):
                self._write_manifest()
                if field == "commit_id":
                    self._write_reviews(commit_id="8" * 40)
                elif field == "task_id":
                    self._write_reviews(body=self._marker(task_id="wrong"))
                else:
                    self._write_reviews(body=self._marker(run_id="wrong"))
                result = self._run()
                self.assertIn(error, result["errors"])

        self._write_manifest()
        self._write_reviews(user={"login": "codex"})
        result = self._run()
        self.assertIn(
            "scientific_pass_reviewer_is_implementation_actor", result["errors"]
        )

    def test_post_review_governance_change_is_allowed_but_protected_result_is_not(
        self,
    ) -> None:
        self.assertEqual(self._run()["status"], "passed")
        write(self.repo / "docs/tasks/README.md", "updated governance metadata\n")
        self.assertEqual(self._run()["status"], "passed")

        write(
            self.repo / "docs/experiments/r3/r3_t01/example/result_analysis.md",
            "changed analysis\n",
        )
        result = self._run()
        self.assertIn(
            "scientific_review_protected_surface_changed:docs/experiments/r3/r3_t01/example/result_analysis.md",
            result["errors"],
        )

    def test_full_profile_is_bound_to_current_head(self) -> None:
        for mutation, error in [
            ({"status": "failed"}, "full_profile_failed"),
            ({"tested_head_sha": "0" * 40}, "full_profile_current_head_mismatch"),
        ]:
            with self.subTest(error=error):
                self._write_full_profile(**mutation)
                result = self._run()
                self.assertIn(error, result["errors"])


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def commit(cwd: Path, message: str) -> str:
    git(cwd, "add", ".")
    git(cwd, "commit", "-q", "-m", message)
    return git(cwd, "rev-parse", "HEAD")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
