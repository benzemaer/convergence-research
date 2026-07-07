import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = (
    ROOT / "docs/evidence/r0/R0-T10-01_r0_t04_raw_metrics_materialization_evidence.md"
)
README_PATH = ROOT / "docs/tasks/README.md"
TASK_PATH = ROOT / "docs/tasks/R0-T10-01_真实数据源与R0-T04_raw_metrics物化.md"


class R0T10MaterializationEvidenceTest(unittest.TestCase):
    def test_evidence_records_real_run_summary_without_row_payload(self) -> None:
        text = EVIDENCE_PATH.read_text(encoding="utf-8")
        required = (
            "`task_id`: R0-T10-01",
            "`status`: completed",
            "`run_id`: R0-T10-01-20260707T1345Z",
            "`code_commit`: 7ea2e649f0c9f0d04614cbbe7240747b98adec39",
            "`input_source`: `data/generated/d3/"
            "d3_t11_volume_amount_share_turnover_candidate/"
            "d3_t11_volume_amount_share_turnover_candidate.duckdb`",
            "`input_artifact_hash`: "
            "`57707f6ed5e821bd837029e3f0a8f42c1e1a0ecc432002df959a71064177f103`",
            "`output_duckdb_sha256`: "
            "`100f515de8e337c82e86e3f3760648df4229860dd83c16ac767065c4f2e16fc7`",
            "`manifest_sha256`: "
            "`820c741ba69a7b4d2657f8a79c94fa22c45e78f599be5466c05c40acd67cce65`",
            "`summary_sha256`: "
            "`2dd20ac270a012e8c8ceb5e9bb4ced7ce335d1e3fe9a4f0c61ab7a330ef4cf36`",
            "`row_count`: 13,846,152",
            "`security_count`: 800",
            "`date_min`: 20160104",
            "`date_max`: 20260630",
            "`shard_count`: 800",
            "`max_workers`: 6",
            "`duckdb_threads`: 1",
            "`duckdb_memory_limit_per_worker`: 2GB",
            "`chunk_size_securities`: 1",
            "`forbidden_field_check`: passed",
            "`legacy_v1_check`: passed",
            "`R0-T05_allowed_to_start`: true",
        )
        for snippet in required:
            self.assertIn(snippet, text)

        self.assertNotIn('"raw_metric_results": [', text)
        self.assertNotIn("`raw_metric_results`:", text)
        self.assertNotIn("row_json", text)
        self.assertIn("does not embed row-level payloads", text)

    def test_task_policy_requires_evidence_before_completion(self) -> None:
        text = TASK_PATH.read_text(encoding="utf-8")
        self.assertIn("大的 generated data artifacts 不提交到 git", text)
        self.assertIn(
            "每个 formal materialization PR 必须提交小型 evidence record", text
        )
        self.assertIn("没有真实运行 evidence record，不得把 task 标为 completed", text)

    def test_readme_advances_after_evidence_completion(self) -> None:
        text = README_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "current_task: R0-T10-05 authorized input manifest 与 27 组 full-grid 执行",
            text,
        )
        self.assertIn(
            "next_planned_task: R0-T11 R0 审计报告与 R1 交接",
            text,
        )
        self.assertIn(
            "`R0-T10-01` 真实数据源与 R0-T04 raw metrics 物化：completed via PR #69",
            text,
        )
        self.assertIn(
            "`R0-T10-02` R0-T05 strict-past score 物化：completed via PR #70", text
        )
        self.assertIn(
            "`R0-T10-03` R0-T06 nested state 物化：completed via PR #71",
            text,
        )


if __name__ == "__main__":
    unittest.main()
