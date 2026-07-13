from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.r2.r2_t03_cli import (
    _normalized_json_sha,
    _post_comparison_fingerprint,
)


class R2T03PostFingerprintTest(unittest.TestCase):
    def test_run_specific_metadata_is_excluded_from_comparison(self) -> None:
        payload = {
            "execution_commit": "a" * 40,
            "config_sha256": "b" * 64,
            "database_fingerprint": {"route_daily": {"row_count": 2}},
            "runtime_gate_results_sha256": "c" * 64,
        }
        baseline = {
            "run_id": "R2-T03-baseline",
            "comparison_fingerprint": _post_comparison_fingerprint(payload),
        }
        formal = {
            "run_id": "R2-T03-formal",
            "comparison_fingerprint": _post_comparison_fingerprint(payload),
        }
        self.assertNotEqual(baseline["run_id"], formal["run_id"])
        self.assertEqual(
            baseline["comparison_fingerprint"], formal["comparison_fingerprint"]
        )

    def test_validation_json_path_does_not_change_canonical_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            left = Path(directory) / "left.json"
            right = Path(directory) / "right.json"
            left.write_text(
                json.dumps({"status": "passed", "database_path": "baseline/db"}),
                encoding="utf-8",
            )
            right.write_text(
                json.dumps({"status": "passed", "database_path": "formal/db"}),
                encoding="utf-8",
            )
            self.assertEqual(_normalized_json_sha(left), _normalized_json_sha(right))


if __name__ == "__main__":
    unittest.main()
