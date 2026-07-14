from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class GovT02SimpleResearchWorkflowTest(unittest.TestCase):
    def test_quality_is_basic_only(self) -> None:
        quality = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
        self.assertIn("basic-quality:", quality)
        self.assertNotIn("run_unittest_profile.py", quality)
        self.assertNotIn("premerge-full", quality)
        self.assertNotIn("SCIENTIFIC PASS", quality)
        self.assertNotIn("final gate", quality.lower())
        self.assertNotIn("\n  governance:", quality)
        self.assertNotIn("canonical-text-cross-platform:", quality)
        self.assertEqual(quality.count("\n  basic-quality:"), 1)

    def test_template_and_task_describe_two_review_stages(self) -> None:
        template = (ROOT / ".github/PULL_REQUEST_TEMPLATE/research-task.md").read_text(
            encoding="utf-8"
        )
        task = (
            ROOT / "docs/tasks/GOV-T02_先审实现后运行的两阶段研究流程.md"
        ).read_text(encoding="utf-8")
        for marker in (
            "reviewed_implementation_sha",
            "formal_run_allowed",
            "formal_execution_sha",
            "result_review_status",
        ):
            self.assertIn(marker, template)
        self.assertIn("同一 PR 分两次提交是默认模式", task)
        self.assertIn("两个 PR 也是合法模式", task)
        self.assertIn("formal run 必须晚于用户实现审阅", task)

    def test_history_remains_legacy_evidence(self) -> None:
        for path in (
            "docs/evidence/governance/GOV-T01_R1-R6_formal实验结果与科学审阅治理_evidence.md",
            "src/r2/r2_t02_premerge_full_evidence.py",
            "schemas/r2/r2_t02_premerge_full_evidence.schema.json",
        ):
            self.assertTrue((ROOT / path).exists(), path)


if __name__ == "__main__":
    unittest.main()
