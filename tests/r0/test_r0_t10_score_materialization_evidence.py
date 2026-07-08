import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = (
    ROOT / "docs/evidence/r0/"
    "R0-T10-02_r0_t05_strict_past_score_materialization_evidence.md"
)
README_PATH = ROOT / "docs/tasks/README.md"
TASK_PATH = ROOT / "docs/tasks/R0-T10-02_R0-T05_strict-past_score物化.md"


class R0T10ScoreMaterializationEvidenceTest(unittest.TestCase):
    def test_evidence_records_real_score_run_without_row_payload(self) -> None:
        text = EVIDENCE_PATH.read_text(encoding="utf-8")
        required = (
            "`task_id`: R0-T10-02",
            "`status`: completed",
            "`run_id`: R0-T10-02-20260707T1500Z",
            "`code_commit`: bc0920f811bf683ecffbb81a5ce9119cb4858256",
            "`input_artifact_hash`: "
            "`100f515de8e337c82e86e3f3760648df4229860dd83c16ac767065c4f2e16fc7`",
            "`input_row_count`: 13,846,152",
            "`input_security_count`: 800",
            "`indicator_score_duckdb_sha256`: "
            "`3061c07c0ab5074e54e1bbf83780c4fd3b2b065700314f1c1ca2f3524e83f944`",
            "`dimension_score_duckdb_sha256`: "
            "`8e371f1245933f763ea6328568a5d0025c0f17752d8c9f0c6c401f5ccc707942`",
            "`common_eligible_duckdb_sha256`: "
            "`47cafa631016b24830cd600ed53f6cf96818fec06641fb92621b1f23f6f56c88`",
            "`manifest_sha256`: "
            "`8dcbbd1a5fce9ad4e4ec6b71631065aadf14ae7820fbf766889b7c75c0dca4ec`",
            "`summary_sha256`: "
            "`fb7f9ebd0bd2bf83b5b8cd678658a008861608cdd0d106ef3e1f58655140a15d`",
            "`indicator_score_row_count`: 41,538,456",
            "`dimension_score_row_count`: 20,769,228",
            "`common_eligible_row_count`: 1,730,769",
            "`security_count`: 800",
            "`date_min`: 20160104",
            "`date_max`: 20260630",
            "`shard_count`: 800",
            "`max_workers`: 16",
            "`duckdb_threads`: 1",
            "`duckdb_memory_limit_per_worker`: 2GB",
            "`chunk_size_securities`: 1",
            "`validator_status`: passed",
            "`strict_past_validator_status`: passed",
            "`future_leakage_check`: passed",
            "`forbidden_field_check`: passed",
            "`legacy_v1_check`: passed",
            "`R0-T06_allowed_to_start`: true",
        )
        for snippet in required:
            self.assertIn(snippet, text)

        forbidden_payload_markers = (
            '"indicator_score": [',
            '"dimension_score": [',
            '"common_eligible": [',
            "`indicator_score_results`:",
            "`dimension_score_results`:",
            "row_json",
        )
        for marker in forbidden_payload_markers:
            self.assertNotIn(marker, text)
        self.assertIn("does not embed row-level payloads", text)

    def test_task_and_readme_gate_semantics_match_completed_evidence(self) -> None:
        task_text = TASK_PATH.read_text(encoding="utf-8")
        readme_text = README_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "没有真实运行 evidence，不得把 R0-T10-02 标为 completed", task_text
        )
        self.assertIn(
            "只有 R0-T05 completed 且 validator passed 时，"
            "`R0-T06_allowed_to_start=true`",
            task_text,
        )
        self.assertIn(
            "current_task: R1-T02 R0 产物接收、lineage 与无前视复检",
            readme_text,
        )
        self.assertIn(
            "next_planned_task: R1-T03 27 组 W/q/K 全量轻量结构扫描",
            readme_text,
        )
        self.assertIn(
            "`R0-T10-02` R0-T05 strict-past score 物化：completed via PR #70",
            readme_text,
        )
        self.assertIn(
            "`R0-T10-03` R0-T06 nested state 物化：completed via PR #71",
            readme_text,
        )


if __name__ == "__main__":
    unittest.main()
