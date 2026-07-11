from __future__ import annotations

import unittest
from pathlib import Path

README = Path("docs/tasks/README.md")


class TaskIndexCurrentTest(unittest.TestCase):
    def test_current_task_pointer_is_centralized(self) -> None:
        text = README.read_text(encoding="utf-8")
        current = text.split("## 当前阶段", 1)[1].split("## 命名与路径规则", 1)[0]
        self.assertIn("current_stage: R1", current)
        self.assertIn("current_task: R1-T10 R1 验收门禁与 R2 交接矩阵", current)
        self.assertIn("next_planned_task: R2-T01 参数候选收敛", current)
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
        self.assertIn(
            "`R1-T08` S_PCT/S_PCVT 同步性与嵌套增量零模型：completed via PR #84",
            text,
        )
        self.assertIn(
            "`R1-T09` 年份稳定性与状态集中度检查：completed via PR #85",
            text,
        )
        self.assertIn(
            "R1-T14-01_decision_status: q_vector_materialization_request", current
        )
        self.assertIn("R1-T14-02_status: completed", current)
        self.assertIn("R1-T14-02_scientific_review_status: passed", current)
        self.assertIn("R1-T14-02_independent_review_status: passed", current)
        self.assertIn("R0_q_vector_materialization_request_status: fulfilled", current)
        self.assertIn("R0_q_vector_materialization_task_id: R0-T15", current)
        self.assertIn("R0_q_vector_materialization_allowed_to_start: false", current)
        self.assertIn(
            "R0_q_vector_materialization_status: completed",
            current,
        )
        self.assertIn("R1-T09_allowed_to_start: true", text)
        self.assertIn("R1-T14-01_allowed_to_start: true", text)
        self.assertIn("R1-T14-02_allowed_to_start: false", current)
        self.assertIn("R1-T10_allowed_to_start: true", current)
        self.assertIn("R1-T10_status: completed", current)
        self.assertIn("R1-T10_scientific_review_status: passed", current)
        self.assertIn("R1-T10_independent_review_status: passed", current)
        self.assertIn("R1-T11_allowed_to_start: false", current)
        self.assertIn("R1-T12_allowed_to_start: false", current)
        self.assertIn("R1-T13_allowed_to_start: false", current)
        self.assertIn("R2_allowed_to_start: true", current)
        self.assertIn("## R2：参数、事件规则与状态版本冻结", text)
        self.assertIn("状态：ready after R1-T10 final gate", text)


if __name__ == "__main__":
    unittest.main()
