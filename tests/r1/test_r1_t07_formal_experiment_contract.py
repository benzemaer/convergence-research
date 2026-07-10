from __future__ import annotations

import unittest
from pathlib import Path


class R1T07FormalExperimentContractTest(unittest.TestCase):
    def test_readme_remains_on_r1_t07_author_draft_gate(self) -> None:
        text = Path("docs/tasks/README.md").read_text(encoding="utf-8")
        self.assertIn("current_task: R1-T07 P 首入锚定的固定滞后结构关系", text)
        self.assertIn(
            "next_planned_task: R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型", text
        )
        self.assertIn("R1-T07_allowed_to_start: true", text)
        self.assertIn("R1-T08_allowed_to_start: false", text)
        self.assertIn("R2_allowed_to_start: false", text)


if __name__ == "__main__":
    unittest.main()
