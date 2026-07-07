import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = ROOT / (
    "docs/evidence/r0/"
    "R0-T10-04_r0_t07_confirmation_interval_materialization_evidence.md"
)
README_PATH = ROOT / "docs/tasks/README.md"
TASK_PATH = ROOT / "docs/tasks/R0-T10-04_R0-T07_confirmation_interval物化.md"


class R0T10ConfirmationIntervalMaterializationEvidenceTest(unittest.TestCase):
    def test_evidence_records_real_confirmation_run_without_row_payload(self) -> None:
        text = EVIDENCE_PATH.read_text(encoding="utf-8")
        code_commit = "99a914d59b6563b5bd685d09ee5e7804a325c397"
        self.assertRegex(code_commit, r"^[0-9a-f]{40}$")
        required = (
            "`task_id`: R0-T10-04",
            "`status`: completed",
            "`run_id`: R0-T10-04-20260707T1711Z",
            f"`code_commit`: {code_commit}",
            f"--code-commit {code_commit}",
            "`input_nested_daily_state_duckdb_sha256`: "
            "`1a5aa1375a46e5909f16d64353908dd7ad1d0754078079136b0aae06263be9d4`",
            "`daily_confirmation_duckdb_sha256`: "
            "`643b988359823d89ca5d38b58716f6c5880aa0b45e0c81fe21bfe9faa991ae29`",
            "`confirmed_interval_duckdb_sha256`: "
            "`f6d662e7be4a8adb009aeee6c23edc849fc2dec9b7babbec004546dd108e81ea`",
            "`manifest_sha256`: "
            "`21d75966acc084ade48ebe2d6435f0da2e4f79422501016b7bfe1c4cd89a69bd`",
            "`summary_sha256`: "
            "`5aa95a4586bb7662460946261e5a736bd8a9031bf9e5dc7d42caabe7fc82421b`",
            "`daily_confirmation_row_count`: 186,923,052",
            "`confirmed_interval_row_count`: 0",
            "`security_count`: 800",
            "`date_min`: 20160104",
            "`date_max`: 20260630",
            "`W_coverage`: 120 / 250 / 500",
            "`q_coverage`: 0.10 / 0.20 / 0.30",
            "`K_coverage`: 2 / 3 / 5",
            "`state_name_coverage`: S_P / S_PC / S_PCT / S_PCVT",
            "`confirmed_true_sample_status`: skipped; confirmed_true_absent",
            "`interval_recompute_skipped_reasons`: open_interval_absent",
            "`daily_recompute_sample_count`: 111",
            "`daily_recompute_mismatch_count`: 0",
            "`interval_recompute_sample_count`: 0",
            "`interval_recompute_mismatch_count`: 0",
            "`confirmed_nested_invariant_check`: passed",
            "`no_backfill_check`: passed",
            "`forbidden_field_check`: passed",
            "`legacy_v1_check`: passed",
            "`future_return_absence_check`: passed",
            "`full_code_commit_check`: passed",
            "`completed_chunk_count`: 800",
            "`failed_chunk_count`: 0",
            "`DONE_marker_count`: 800",
            "`FAILED_marker_count`: 0",
            "`downstream_gate_allowed`: true",
            "`R0-T10-05_allowed_to_start`: true",
        )
        for snippet in required:
            self.assertIn(snippet, text)

        command_match = re.search(r"`materialization_command`: `([^`]+)`", text)
        self.assertIsNotNone(command_match)
        self.assertIn(f"--code-commit {code_commit}", command_match.group(1))
        self.assertNotRegex(
            command_match.group(1), r"--code-commit\s+[0-9a-f]{7}(?:\s|$)"
        )

        forbidden_payload_markers = (
            '"daily_confirmation_results": [',
            '"confirmed_interval_results": [',
            "`daily_confirmation_results`:",
            "`confirmed_interval_results`:",
            "row_json",
        )
        for marker in forbidden_payload_markers:
            self.assertNotIn(marker, text)
        self.assertIn("does not embed row-level payloads", text)

    def test_task_and_readme_gate_semantics_match_completed_evidence(self) -> None:
        task_text = TASK_PATH.read_text(encoding="utf-8")
        readme_text = README_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "没有真实运行 evidence，不得把 R0-T10-04 标为 completed", task_text
        )
        self.assertIn("`--code-commit` 必须为 40 位完整 Git SHA", task_text)
        self.assertIn(
            "current_task: R0-T11 R0 审计报告与 R1 交接",
            readme_text,
        )
        self.assertIn(
            "next_planned_task: R1-T01 状态存在性与频率轮廓",
            readme_text,
        )
        self.assertIn(
            "`R0-T10-04` R0-T07 confirmation / interval 物化：completed via PR #72",
            readme_text,
        )


if __name__ == "__main__":
    unittest.main()
