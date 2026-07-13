import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class R2StageRouteContract(unittest.TestCase):
    def test_r2_stage_document_and_task_route_exist(self):
        self.assertTrue(
            (ROOT / "docs/stages/R2_参数、事件规则与状态版本冻结.md").is_file()
        )
        text = (ROOT / "docs/tasks/README.md").read_text(encoding="utf-8")
        for task in (
            "`R2-T01` 参数候选收敛与 shortlist registry",
            "`R2-T02` confirmed-state 与 event-zone 双层状态机契约",
            "`R2-T03` 四路线 d×g event-zone 状态机扫描与区间几何审计",
            "`R2-T04` Hard gate、Pareto 推荐、用户决策与 freeze plan",
            "`R2-T05` canonical daily state、event zone 与 membership 物化",
            "`R2-T06` canonical 状态机无前视回放与一致性验收",
            "`R2-T07` 状态版本登记册与最终 freeze manifest",
            "`R2-T08` R2 阶段验收与 R3 交接",
        ):
            self.assertIn(task, text)

    def test_t03_is_implemented_and_t05_startup_gate_is_passed(self):
        self.assertTrue(list((ROOT / "src/r2").glob("r2_t02*")))
        self.assertTrue(list((ROOT / "src/r2").glob("r2_t03*")))
        self.assertTrue(list((ROOT / "src/r2").glob("r2_t04*")))
        self.assertTrue((ROOT / "data/generated/r2/r2_t04").exists())
        self.assertTrue(list((ROOT / "src/r2").glob("r2_t05*")))
        self.assertTrue(
            (
                ROOT
                / "configs/r2/r2_t05_canonical_state_event_zone_materialization.v1.json"
            ).is_file()
        )
        for task in range(6, 9):
            self.assertFalse(list((ROOT / "src/r2").glob(f"r2_t{task:02d}*")))
            self.assertFalse((ROOT / f"data/generated/r2/r2_t{task:02d}").exists())
        current = (
            (ROOT / "docs/tasks/README.md")
            .read_text(encoding="utf-8")
            .split("## 当前阶段", 1)[1]
            .split("## 命名与路径规则", 1)[0]
        )
        self.assertIn("R2-T02_formal_task_completed: true", current)
        self.assertIn("R2-T03_allowed_to_start: false", current)
        self.assertIn("R2-T03_formal_task_completed: true", current)
        self.assertIn("R2-T04_allowed_to_start: true", current)
        self.assertIn("R2-T04_status: completed", current)
        self.assertIn("R2-T04_formal_task_completed: true", current)
        self.assertIn("R2-T05_allowed_to_start: true", current)
        self.assertIn(
            "R2-T05_status: successor_author_package_complete_pending_independent_scientific_review",
            current,
        )
        self.assertIn(
            "R2-T05_startup_status: passed",
            current,
        )
        self.assertIn("R2-T05_scientific_review_status: needs_revision", current)
        self.assertIn("R2-T05_formal_run_executed: true", current)
        self.assertIn("R2-T05_formal_task_completed: false", current)
        self.assertIn("R3_allowed_to_start: false", current)


if __name__ == "__main__":
    unittest.main()
