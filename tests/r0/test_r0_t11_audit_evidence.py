from __future__ import annotations

import re
import unittest
from pathlib import Path

EVIDENCE = Path("docs/evidence/r0/R0-T11_r0_audit_report_r1_handoff_evidence.md")
README = Path("docs/tasks/README.md")


class R0T11AuditEvidenceTest(unittest.TestCase):
    def test_evidence_records_completed_audit_handoff(self) -> None:
        text = EVIDENCE.read_text(encoding="utf-8")
        required = (
            "`task_id`: R0-T11",
            "`status`: completed",
            "`validator_status`: passed",
            "`R0_status`: completed",
            "`R1_allowed_to_start`: true",
            "`R1_starting_task`: R1-T01",
            "`zero_interval_acknowledged`: true",
            "`r_stage_formal_run_standard_updated`: true",
            "`r_stage_formal_run_standard_check`: passed",
            "`r1_formal_run_standard_gate`: passed",
            "`README_updated_to_R1`: true",
            "`downstream_gate_allowed`: true",
        )
        for snippet in required:
            self.assertIn(snippet, text)

    def test_source_evidence_and_report_hashes_are_present(self) -> None:
        text = EVIDENCE.read_text(encoding="utf-8")
        self.assertIn("`source_evidence_files`:", text)
        self.assertIn(
            "`engineering_standard_path`: `docs/03_可复现研究工程标准.md`",
            text,
        )
        hash_values = re.findall(r"`[^`]*(?:sha256|hash)[^`]*`: `([0-9a-f]{64})`", text)
        self.assertGreaterEqual(len(hash_values), 10)
        for value in hash_values:
            self.assertRegex(value, r"^[0-9a-f]{64}$")

    def test_readme_advances_to_r1(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("current_stage: R1", text)
        self.assertIn("current_task: R1-T01 状态存在性与频率轮廓", text)
        self.assertIn("next_planned_task: R1-T02 结构关系与协同约束检验", text)
        self.assertIn("`R0-T11` R0 审计报告与 R1 交接：completed via PR #74", text)

    def test_evidence_has_no_row_payload(self) -> None:
        text = EVIDENCE.read_text(encoding="utf-8")
        forbidden = ('"rows": [', "`rows`:", "row_payload_json", "row_json")
        for marker in forbidden:
            self.assertNotIn(marker, text)

    def test_no_generated_row_artifacts_are_committed(self) -> None:
        forbidden_suffixes = (".duckdb", ".parquet", ".csv.gz", ".jsonl", ".jsonl.gz")
        tracked = Path(".git").exists()
        self.assertTrue(tracked)
        for path in Path("docs").rglob("*"):
            self.assertFalse(path.name.endswith(forbidden_suffixes), path)


if __name__ == "__main__":
    unittest.main()
