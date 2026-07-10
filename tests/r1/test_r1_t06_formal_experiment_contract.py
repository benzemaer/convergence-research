from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class R1T06FormalExperimentContractTest(unittest.TestCase):
    def test_readme_is_author_draft_position_for_r1_t06(self) -> None:
        readme = Path("docs/tasks/README.md").read_text(encoding="utf-8")
        self.assertIn("current_task: R1-T06 层间同期留存、关联 Lift 与嵌套增量", readme)
        self.assertIn("next_planned_task: R1-T07 P 首入锚定的固定滞后结构关系", readme)
        self.assertIn("R1-T06_allowed_to_start: true", readme)
        self.assertIn("R1-T07_allowed_to_start: false", readme)
        self.assertIn("R1-T08_allowed_to_start: false", readme)
        self.assertIn("R2_allowed_to_start: false", readme)

    def test_required_implementation_files_exist(self) -> None:
        for path in (
            "configs/r1/r1_t06_contemporaneous_retention_lift.v1.json",
            "schemas/r1/r1_t06_contemporaneous_retention_lift.schema.json",
            "src/r1/r1_t06_contemporaneous_retention_lift.py",
            "src/r1/r1_t06_contemporaneous_retention_lift_cli.py",
            "src/r1/r1_t06_contemporaneous_retention_lift_validator.py",
            "src/r1/r1_t06_contemporaneous_retention_lift_validator_cli.py",
            "scripts/r1/run_r1_t06_contemporaneous_retention_lift.py",
            "scripts/r1/validate_r1_t06_contemporaneous_retention_lift.py",
        ):
            self.assertTrue(Path(path).exists(), path)

    def test_thin_wrappers_expose_help(self) -> None:
        for script in (
            "scripts/r1/run_r1_t06_contemporaneous_retention_lift.py",
            "scripts/r1/validate_r1_t06_contemporaneous_retention_lift.py",
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
