import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = (
    ROOT / "docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence.md"
)
README_PATH = ROOT / "docs/tasks/README.md"
TASK_PATH = ROOT / "docs/tasks/R0-T10-03_R0-T06_nested_state物化.md"


class R0T10NestedStateMaterializationEvidenceTest(unittest.TestCase):
    def test_evidence_records_real_nested_state_run_without_row_payload(self) -> None:
        text = EVIDENCE_PATH.read_text(encoding="utf-8")
        required = (
            "`task_id`: R0-T10-03",
            "`status`: completed",
            "`run_id`: R0-T10-03-20260707T1630Z",
            "`run_code_commit_argument`: 92dccee",
            "`pr_head_commit`: 92dcceefd710de40a65daa7d0e414bd7708f5353",
            "this historical run used the short SHA argument",
            "--code-commit 92dccee",
            "`input_indicator_score_duckdb_sha256`: "
            "`3061c07c0ab5074e54e1bbf83780c4fd3b2b065700314f1c1ca2f3524e83f944`",
            "`input_dimension_score_duckdb_sha256`: "
            "`8e371f1245933f763ea6328568a5d0025c0f17752d8c9f0c6c401f5ccc707942`",
            "`input_common_eligible_duckdb_sha256`: "
            "`47cafa631016b24830cd600ed53f6cf96818fec06641fb92621b1f23f6f56c88`",
            "`indicator_state_duckdb_sha256`: "
            "`102aa8f912e4d006d716e1bd8148ac0daf2823b467beabc262875d9afaab4904`",
            "`dimension_state_duckdb_sha256`: "
            "`9f3707e92e8410919609a356b8532a80d992f4078f9e966aaa358b44bbcafc52`",
            "`nested_daily_state_duckdb_sha256`: "
            "`1a5aa1375a46e5909f16d64353908dd7ad1d0754078079136b0aae06263be9d4`",
            "`manifest_sha256`: "
            "`214ff8e33432d7892e6d59b2a498893f772c6603a92ed71090d15ce8b7162f48`",
            "`summary_sha256`: "
            "`d9b32bb9d5f0d0bd1066b30e0d144a352a7d9253692466072a702760daeb1989`",
            "`indicator_state_row_count`: 124,615,368",
            "`dimension_state_row_count`: 62,307,684",
            "`nested_daily_state_row_count`: 15,576,921",
            "`security_count`: 800",
            "`date_min`: 20160104",
            "`date_max`: 20260630",
            "`W_coverage`: 120 / 250 / 500",
            "`q_coverage`: 0.10 / 0.20 / 0.30",
            "`weak_delta`: 0.10",
            "`max_workers`: 16",
            "`duckdb_threads`: 1",
            "`duckdb_memory_limit_per_worker`: 2GB",
            "`chunk_size_securities`: 1",
            "`process_pool_context`: spawn",
            "`validator_status`: passed",
            "`nested_recompute_sample_count`: 10",
            "`nested_recompute_mismatch_count`: 0",
            "`exclusive_layer_recompute_coverage`: NONE / UNKNOWN",
            "`exclusive_layer_non_none_sample_count`: 9",
            "`nested_invariant_check`: passed",
            "`exclusive_layer_uniqueness_check`: passed",
            "`forbidden_field_check`: passed",
            "`legacy_v1_check`: passed",
            "`confirmation_field_absence_check`: passed",
            "`K_absence_check`: passed",
            "`completed_chunk_count`: 800",
            "`failed_chunk_count`: 0",
            "`DONE_marker_count`: 800",
            "`FAILED_marker_count`: 0",
            "`downstream_gate_allowed`: true",
            "`R0-T07_allowed_to_start`: true",
        )
        for snippet in required:
            self.assertIn(snippet, text)

        forbidden_payload_markers = (
            '"indicator_state_results": [',
            '"dimension_state_results": [',
            '"nested_daily_state_results": [',
            "`indicator_state_results`:",
            "`dimension_state_results`:",
            "`nested_daily_state_results`:",
            "row_json",
        )
        for marker in forbidden_payload_markers:
            self.assertNotIn(marker, text)
        self.assertNotIn(
            "`code_commit`: 92dcceefd710de40a65daa7d0e414bd7708f5353", text
        )
        self.assertIn("does not embed row-level payloads", text)

    def test_task_and_readme_gate_semantics_match_completed_evidence(self) -> None:
        task_text = TASK_PATH.read_text(encoding="utf-8")
        readme_text = README_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "没有真实运行 evidence，不得把 R0-T10-03 标为 completed", task_text
        )
        self.assertIn(
            "只有 R0-T06 completed 且 validator passed 时，"
            "`R0-T07_allowed_to_start=true`",
            task_text,
        )
        self.assertIn(
            "current_task: R0-T10-04 R0-T07 confirmation / interval 物化",
            readme_text,
        )
        self.assertIn(
            "next_planned_task: R0-T10-05 authorized input manifest "
            "与 27 组 full-grid 执行",
            readme_text,
        )
        self.assertIn(
            "`R0-T10-03` R0-T06 nested state 物化：completed via PR #71",
            readme_text,
        )
        self.assertIn(
            "`R0-T10-04` R0-T07 confirmation / interval 物化：in_progress",
            readme_text,
        )


if __name__ == "__main__":
    unittest.main()
