import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.r2.r2_t02_premerge_full_evidence import (
    R2T02PremergeEvidenceError,
    build_premerge_full_evidence,
    collection_sha256,
)


class R2T02PremergeFullEvidenceTest(unittest.TestCase):
    def _runner(self, path: Path, ids: list[str]) -> None:
        path.write_text(
            json.dumps(
                {
                    "profile": "full",
                    "status": "passed",
                    "test_count": len(ids),
                    "collected_test_count": len(ids),
                    "unique_test_count": len(ids),
                    "failure_count": 0,
                    "error_count": 0,
                    "skipped_count": 0,
                    "elapsed_seconds": 1.25,
                    "test_ids": ids,
                    "test_collection_sha256": collection_sha256(ids),
                }
            ),
            encoding="utf-8",
        )

    @patch(
        "src.r2.r2_t02_premerge_full_evidence.formal_surface_sha256",
        return_value="a" * 64,
    )
    @patch("src.r2.r2_t02_premerge_full_evidence.profile_test_ids")
    def test_evidence_binds_exact_full_and_heavy_collections(self, profiles, _surface):
        profiles.side_effect = (
            lambda name: ["test.a", "test.b"] if name == "full" else ["test.b"]
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = root / "runner.json"
            self._runner(runner, ["test.a", "test.b"])
            evidence = build_premerge_full_evidence(
                runner_result_path=runner,
                output_path=root / "evidence.json",
                tested_head="b" * 40,
                workflow_run_id="123",
                workflow_run_attempt="2",
            )
            self.assertEqual(evidence["test_count"], 2)
            self.assertEqual(evidence["heavy_test_count"], 1)
            self.assertTrue(
                evidence["collection_conservation"]["heavy_is_subset_of_full"]
            )

    @patch(
        "src.r2.r2_t02_premerge_full_evidence.profile_test_ids",
        return_value=["test.a", "test.b"],
    )
    def test_collection_mismatch_fails_closed(self, _profiles):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = root / "runner.json"
            self._runner(runner, ["test.a"])
            with self.assertRaisesRegex(
                R2T02PremergeEvidenceError, "full_collection_mismatch"
            ):
                build_premerge_full_evidence(
                    runner_result_path=runner,
                    output_path=root / "evidence.json",
                    tested_head="b" * 40,
                    workflow_run_id="123",
                    workflow_run_attempt="1",
                )


if __name__ == "__main__":
    unittest.main()
