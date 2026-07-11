from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.r1.r1_t14_02_final_gate import (
    AUTHOR_PACKAGE_SHA256,
    REVIEWED_HEAD,
    validate_r1_t14_02_final_gate,
)

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "data/generated/r1/r1_t14_02/R1-T14-02-20260711T1100Z"


class R1T1402FinalGateTests(unittest.TestCase):
    def test_final_gate_package_is_valid(self) -> None:
        result = validate_r1_t14_02_final_gate(run_dir=RUN_DIR)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["formal_task_completed"])
        self.assertTrue(result["R1-T10_allowed_to_start"])
        self.assertFalse(result["R2_allowed_to_start"])
        self.assertTrue(result["selection_path_not_independently_confirmed"])

    def test_final_gate_preserves_reviewed_author_package(self) -> None:
        package = json.loads(
            (RUN_DIR / "r1_t14_02_final_gate_package.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            package["reviewed_author_package_sha256"], AUTHOR_PACKAGE_SHA256
        )
        self.assertEqual(package["reviewed_pr_head_commit"], REVIEWED_HEAD)
        self.assertEqual(package["downstream_gate_scope"], "R1-T10_only")


if __name__ == "__main__":
    unittest.main()
