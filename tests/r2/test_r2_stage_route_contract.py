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
            "`R2-T02` K/d/g、事件指标、hard gate 与 R3 risk-set 契约",
            "`R2-T03` 四路线 d×g 事件区间几何扫描",
            "`R2-T04` Hard gate、Pareto 推荐、用户决策与 freeze plan",
            "`R2-T05` canonical 日度状态与事件区间物化",
            "`R2-T06` canonical 状态机无前视回放与一致性验收",
            "`R2-T07` 状态版本登记册与最终 freeze manifest",
            "`R2-T08` R2 阶段验收与 R3 交接",
        ):
            self.assertIn(task, text)

    def test_only_t01_is_implemented_and_t02_is_authorized(self):
        for task in range(2, 9):
            self.assertFalse(list((ROOT / "src/r2").glob(f"r2_t{task:02d}*")))
            self.assertFalse((ROOT / f"data/generated/r2/r2_t{task:02d}").exists())
        current = (
            (ROOT / "docs/tasks/README.md")
            .read_text(encoding="utf-8")
            .split("## 当前阶段", 1)[1]
            .split("## 命名与路径规则", 1)[0]
        )
        self.assertIn("R2-T02_allowed_to_start: true", current)
        self.assertIn("R3_allowed_to_start: false", current)


if __name__ == "__main__":
    unittest.main()
