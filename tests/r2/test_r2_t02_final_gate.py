import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.r0.upstream_artifact_io import sha256_file
from src.r2.r2_t02_final_gate import (
    R2T02FinalGateError,
    finalize_r2_t02_reviewed_package,
)
from src.r2.r2_t02_premerge_full_evidence import collection_sha256

ROOT = Path(__file__).resolve().parents[2]


class R2T02FinalGateTest(unittest.TestCase):
    def _fixtures(self, root: Path, *, evidence_head: str) -> dict[str, Path | str]:
        head = "a" * 40
        output = root / "R2-T02-test"
        output.mkdir()
        package_path = output / "r2_t02_result_package.json"
        package_path.write_text(
            json.dumps({"committed_artifacts": []}), encoding="utf-8"
        )
        (output / "r2_t02_contract_validation_result.json").write_text(
            json.dumps({"status": "passed", "all_synthetic_cases_passed": True}),
            encoding="utf-8",
        )
        review = root / "review.json"
        review.write_text(
            json.dumps(
                {
                    "task_id": "R2-T02",
                    "scientific_review_status": "passed",
                    "independent_review_status": "passed",
                    "independence_attestation": True,
                    "blocking_findings": [],
                    "downstream_gate_recommendation": True,
                    "downstream_gate_scope": "R2-T03_only",
                    "reviewed_pr_head_commit": head,
                    "reviewed_author_package_sha256": sha256_file(package_path),
                }
            ),
            encoding="utf-8",
        )
        index = root / "README.md"
        index.write_text(
            "R2-T02_scientific_review_status: pending\n"
            "R2-T03_allowed_to_start: false\n",
            encoding="utf-8",
        )
        evidence = root / "premerge.json"
        evidence.write_text(
            json.dumps(
                {
                    "task_id": "R2-T02",
                    "profile": "full",
                    "status": "passed",
                    "tested_head": evidence_head,
                    "workflow_run_id": "123",
                    "workflow_run_attempt": "1",
                    "test_count": 2,
                    "unique_test_count": 2,
                    "failure_count": 0,
                    "error_count": 0,
                    "test_collection_sha256": collection_sha256(["a", "b"]),
                    "heavy_profile": "r0-heavy-premerge",
                    "heavy_test_count": 1,
                    "heavy_test_collection_sha256": collection_sha256(["b"]),
                    "heavy_test_ids": ["b"],
                    "formal_surface_sha256": "f" * 64,
                    "collection_conservation": {
                        "full_equals_current_collection": True,
                        "heavy_is_subset_of_full": True,
                        "executed_equals_collected": True,
                    },
                }
            ),
            encoding="utf-8",
        )
        return {
            "head": head,
            "output": output,
            "review": review,
            "index": index,
            "evidence": evidence,
        }

    @patch("src.r2.r2_t02_final_gate.formal_surface_sha256", return_value="f" * 64)
    @patch("src.r2.r2_t02_final_gate.profile_test_ids")
    @patch("src.r2.r2_t02_final_gate.subprocess.run")
    def test_exact_premerge_evidence_is_required(self, git_run, profiles, _surface):
        git_run.return_value.returncode = 0
        profiles.side_effect = lambda name: ["a", "b"] if name == "full" else ["b"]
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            fixture = self._fixtures(Path(temporary), evidence_head="a" * 40)
            result = finalize_r2_t02_reviewed_package(
                output_dir=fixture["output"],
                review_record_path=fixture["review"],
                reviewed_head=fixture["head"],
                task_index_path=fixture["index"],
                premerge_full_evidence_path=fixture["evidence"],
            )
            self.assertEqual(result["repository_final_gate_status"], "passed")

    @patch("src.r2.r2_t02_final_gate.formal_surface_sha256", return_value="f" * 64)
    @patch("src.r2.r2_t02_final_gate.profile_test_ids")
    @patch("src.r2.r2_t02_final_gate.subprocess.run")
    def test_stale_tested_head_fails_closed(self, git_run, profiles, _surface):
        git_run.return_value.returncode = 0
        profiles.side_effect = lambda name: ["a", "b"] if name == "full" else ["b"]
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            fixture = self._fixtures(Path(temporary), evidence_head="c" * 40)
            with self.assertRaisesRegex(R2T02FinalGateError, "tested_head"):
                finalize_r2_t02_reviewed_package(
                    output_dir=fixture["output"],
                    review_record_path=fixture["review"],
                    reviewed_head=fixture["head"],
                    task_index_path=fixture["index"],
                    premerge_full_evidence_path=fixture["evidence"],
                )


if __name__ == "__main__":
    unittest.main()
