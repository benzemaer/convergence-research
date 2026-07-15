from __future__ import annotations

import unittest
from pathlib import Path

README = Path("docs/tasks/README.md")


class TaskIndexCurrentTest(unittest.TestCase):
    def test_current_task_pointer_is_centralized(self) -> None:
        text = README.read_text(encoding="utf-8")
        current = text.split("## 当前阶段", 1)[1].split("## 命名与路径规则", 1)[0]
        self.assertIn("current_stage: R3", current)
        self.assertIn(
            "current_task: R3-T02 对照路径、标准化与经验边界契约",
            current,
        )
        self.assertIn(
            "previous_completed_task: R3-T01 研究协议、T0 与分析单位冻结",
            current,
        )
        self.assertIn(
            "next_planned_task: R3-T03 五类未来路径与技术状态标签契约",
            current,
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
        self.assertIn("R2-T01_allowed_to_start: true", current)
        self.assertIn("R2-T01_status: completed", current)
        self.assertIn("R2-T01_scientific_review_status: passed", current)
        self.assertIn("R2-T01_independent_review_status: passed", current)
        self.assertIn(
            "R2-T02_status: completed",
            current,
        )
        self.assertIn("R2-T02_scientific_review_status: passed", current)
        self.assertIn("R2-T02_independent_review_status: passed", current)
        self.assertIn("R2-T02_repository_final_gate_status: passed", current)
        self.assertIn("R2-T02_formal_task_completed: true", current)
        self.assertIn("R2-T02_allowed_to_start: false", current)
        self.assertIn("R2-T03_allowed_to_start: false", current)
        self.assertIn("R2-T03_status: completed", current)
        self.assertIn("R2-T03_formal_task_completed: true", current)
        self.assertIn("R2-T03_repository_final_gate_status: passed", current)
        self.assertIn(
            "R2-T03_repository_final_gate_binding: "
            "r2_t03_repository_final_gate_handoff.json",
            current,
        )
        self.assertIn("R2-T04_allowed_to_start: true", current)
        self.assertIn(
            "R2-T04_status: completed",
            current,
        )
        self.assertIn("R2-T04_scientific_review_status: passed", current)
        self.assertIn("R2-T04_repository_final_gate_status: passed", current)
        self.assertIn("R2-T04_formal_task_completed: true", current)
        self.assertIn("R2-T05_allowed_to_start: true", current)
        self.assertIn(
            "R2-T05_status: completed_via_PR_97_merged_pr_direct_binding",
            current,
        )
        self.assertIn(
            "R2-T05_startup_status: passed",
            current,
        )
        self.assertIn("R2-T05_scientific_review_status: passed", current)
        self.assertIn("R2-T05_repository_final_gate_status: passed", current)
        self.assertIn("R2-T05_formal_run_executed: true", current)
        self.assertIn("R2-T05_formal_task_completed: true", current)
        self.assertIn(
            "R2-T06_status: completed_via_PR_98_merged_pr_direct_binding", current
        )
        self.assertIn("R2-T06_scientific_review_status: passed", current)
        self.assertIn("R2-T06_formal_task_completed: true", current)
        self.assertIn("R2-T07_allowed_to_start: true", current)
        self.assertIn(
            "R2-T07_status: completed_via_PR_99_merged_pr_direct_binding",
            current,
        )
        self.assertIn(
            "R2-T07_scientific_review_status: passed",
            current,
        )
        self.assertIn("R2-T07_formal_run_executed: true", current)
        self.assertIn("R2-T07_formal_task_completed: true", current)
        self.assertIn(
            "R2-T08_status: completed_via_PR_100_merged_pr_direct_binding",
            current,
        )
        self.assertIn("R2-T08_scientific_review_status: passed", current)
        self.assertIn(
            "R2-T08_reviewed_head: 90b3b25a5294a8cf9cab622de1f96c99ff3f29f6",
            current,
        )
        self.assertIn(
            "R2-T08_merge_commit: 0cebf836302b3e89d5d8059c6992e154eea46610",
            current,
        )
        self.assertIn("R2-T08_formal_run_executed: true", current)
        self.assertIn("R2-T08_formal_task_completed: true", current)
        self.assertIn("R3_allowed_to_start: true", current)
        self.assertIn("R3-T01_allowed_to_start: true", current)
        self.assertIn("R3-T01_status: completed_via_PR_103_accepted", current)
        self.assertIn("R3-T01_implementation_review_status: approved", current)
        self.assertIn(
            "R3-T01_reviewed_implementation_sha: "
            "460728eb42fb4464b781a34595f3ad544677c113",
            current,
        )
        self.assertIn("R3-T01_formal_run_allowed: true", current)
        self.assertIn("R3-T01_formal_run_status: completed", current)
        self.assertIn("R3-T01_formal_result_status: accepted", current)
        self.assertIn("R3-T01_result_review_status: passed", current)
        self.assertIn("R3-T01_scientific_review_status: passed", current)
        self.assertIn("R3-T01_formal_run_executed: true", current)
        self.assertIn("R3-T01_next_task_allowed: true", current)
        self.assertIn("R3-T01_readme_advanced: true", current)
        self.assertIn("R3-T02_allowed_to_start: true", current)
        self.assertIn("R3-T08_allowed_to_start: false", current)
        self.assertIn("R4_allowed_to_start: false", current)
        self.assertIn("## R3：收敛区间脱离、经验路径边界与未来路径标签", text)
        self.assertIn("`R3-T08` R3 阶段验收与 R4 交接：blocked pending R3-T07", text)
        self.assertIn("## R2：参数、事件规则与状态版本冻结", text)
        self.assertIn(
            "immutable post-merge handoff 持久绑定",
            text,
        )


if __name__ == "__main__":
    unittest.main()
