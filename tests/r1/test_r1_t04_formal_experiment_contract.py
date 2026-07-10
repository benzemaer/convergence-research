from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class R1T04FormalExperimentContractTest(unittest.TestCase):
    def test_author_draft_gate_remains_pending(self) -> None:
        task = Path("docs/tasks/R1-T04_S_PCT与S_PCVT分线状态画像.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("scientific_review_status=pending", task)
        self.assertIn("downstream_gate_allowed=false", task)
        self.assertNotIn("freeze_candidate", task)

    def test_required_implementation_files_exist(self) -> None:
        for path in (
            "src/r1/r1_t04_state_line_profiles.py",
            "src/r1/r1_t04_state_line_profiles_validator.py",
            "scripts/r1/run_r1_t04_state_line_profiles.py",
            "scripts/r1/validate_r1_t04_state_line_profiles.py",
        ):
            self.assertTrue(Path(path).exists(), path)

    def test_thin_wrappers_expose_help(self) -> None:
        for script in (
            "scripts/r1/run_r1_t04_state_line_profiles.py",
            "scripts/r1/validate_r1_t04_state_line_profiles.py",
        ):
            completed = subprocess.run(
                ["python", script, "--help"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
