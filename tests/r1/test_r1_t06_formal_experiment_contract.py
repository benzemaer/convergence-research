from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class R1T06FormalExperimentContractTest(unittest.TestCase):
    def test_readme_records_r1_t06_completion_after_later_final_gates(self) -> None:
        readme = Path("docs/tasks/README.md").read_text(encoding="utf-8")
        self.assertIn(
            "current_task: R1-T10 R1 验收门禁与 R2 交接矩阵",
            readme,
        )
        self.assertIn(
            "next_planned_task: R2-T01 参数候选收敛",
            readme,
        )
        self.assertIn("R1-T06 completed via PR #82", readme)
        self.assertIn("R1-T06_allowed_to_start: true", readme)
        self.assertIn("R1-T07_allowed_to_start: true", readme)
        self.assertIn("R1-T08_allowed_to_start: true", readme)
        self.assertIn("R1-T09_allowed_to_start: true", readme)
        self.assertIn("R1-T10_allowed_to_start: true", readme)
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
