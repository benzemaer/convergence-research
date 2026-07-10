from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class R1T05FormalExperimentContractTest(unittest.TestCase):
    def test_author_draft_gate_remains_pending(self) -> None:
        task = Path("docs/tasks/R1-T05_单指标诊断与层内互补性分析.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("scientific_review_status=pending", task)
        self.assertIn("downstream_gate_allowed=false", task)
        self.assertIn("R1-T06_allowed_to_start=false", task)
        self.assertNotIn("freeze_candidate = true", task)

    def test_readme_keeps_r1_t05_completed_after_later_final_gate(self) -> None:
        readme = Path("docs/tasks/README.md").read_text(encoding="utf-8")
        self.assertIn("R1-T05 completed via PR #81", readme)
        self.assertIn("R1-T05_allowed_to_start: true", readme)
        self.assertIn("R1-T06_allowed_to_start: true", readme)
        self.assertIn("R1-T07_allowed_to_start: true", readme)

    def test_required_implementation_files_exist(self) -> None:
        for path in (
            "src/r1/r1_t05_indicator_intralayer_diagnostics.py",
            "src/r1/r1_t05_indicator_intralayer_diagnostics_validator.py",
            "scripts/r1/run_r1_t05_indicator_intralayer_diagnostics.py",
            "scripts/r1/validate_r1_t05_indicator_intralayer_diagnostics.py",
        ):
            self.assertTrue(Path(path).exists(), path)

    def test_thin_wrappers_expose_help(self) -> None:
        for script in (
            "scripts/r1/run_r1_t05_indicator_intralayer_diagnostics.py",
            "scripts/r1/validate_r1_t05_indicator_intralayer_diagnostics.py",
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
