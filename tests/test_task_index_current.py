from __future__ import annotations

import unittest
from pathlib import Path

README = Path("docs/tasks/README.md")


class TaskIndexCurrentTest(unittest.TestCase):
    def test_current_task_pointer_is_centralized(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("current_stage: R1", text)
        self.assertIn(
            "current_task: R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型",
            text,
        )
        self.assertIn(
            "next_planned_task: R1-T09 年份稳定性检查",
            text,
        )
        self.assertIn(
            "`R1-T01` 验证协议、状态线假设与 manifest 锁定：completed via PR #75",
            text,
        )
        self.assertIn(
            "`R1-T04` S_PCT 与 S_PCVT 分线状态画像：completed via PR #80",
            text,
        )
        self.assertIn(
            "`R1-T05` 单指标诊断与层内互补性分析：completed via PR #81",
            text,
        )
        self.assertIn(
            "`R1-T06` 层间同期留存、关联 Lift 与嵌套增量：completed via PR #82",
            text,
        )
        self.assertIn(
            "`R1-T07` P 首入锚定的固定滞后结构关系：completed via PR #83",
            text,
        )
        self.assertIn("## R2：参数、事件规则与状态版本冻结", text)
        self.assertIn("状态：blocked until R1", text)


if __name__ == "__main__":
    unittest.main()
