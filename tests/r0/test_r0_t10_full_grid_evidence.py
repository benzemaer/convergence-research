from __future__ import annotations

import re
import unittest
from pathlib import Path

EVIDENCE = Path(
    "docs/evidence/r0/R0-T10-05_authorized_input_manifest_full_grid_evidence.md"
)
README = Path("docs/tasks/README.md")


class R0T10FullGridEvidenceTest(unittest.TestCase):
    def test_evidence_records_completed_full_grid_without_row_payload(self) -> None:
        text = EVIDENCE.read_text(encoding="utf-8")
        self.assertIn("`task_id`: R0-T10-05", text)
        self.assertIn("`status`: completed", text)
        self.assertRegex(text, r"`code_commit`: [0-9a-f]{40}")
        self.assertIn("`authorized_r0_input`: true", text)
        self.assertIn("`selected_config_count`: 27", text)
        self.assertIn("`completed_config_count`: 27", text)
        self.assertIn("`failed_config_count`: 0", text)
        self.assertIn("`confirmed_interval_row_count_total`: 0", text)
        self.assertIn("`daily_confirmed_true_count_total`: 0", text)
        self.assertIn(
            "`zero_interval_reason_if_any`: no_confirmed_segments_in_r0_t07_input",
            text,
        )
        self.assertIn("`manifest_contains_row_payload`: false", text)
        self.assertIn("`summary_contains_row_payload`: false", text)
        self.assertIn("`R0-T11_allowed_to_start`: true", text)
        self.assertNotIn("r0_t09_full_grid_payload.json", text)

    def test_evidence_hash_fields_are_sha256_like(self) -> None:
        text = EVIDENCE.read_text(encoding="utf-8")
        hash_values = re.findall(r"`[^`]*(?:sha256|hash)[^`]*`: `([0-9a-f]{64})`", text)
        self.assertGreaterEqual(len(hash_values), 10)
        self.assertEqual(len(hash_values), len(set(hash_values)))

    def test_readme_advances_only_after_completed_evidence(self) -> None:
        evidence_text = EVIDENCE.read_text(encoding="utf-8")
        readme_text = README.read_text(encoding="utf-8")
        self.assertIn("`status`: completed", evidence_text)
        self.assertIn("`validator_status`: passed", evidence_text)
        completed_status = (
            "R0-T10-05` authorized input manifest 与 27 组 full-grid 执行："
            "completed via PR #73"
        )
        self.assertIn(
            completed_status,
            readme_text,
        )


if __name__ == "__main__":
    unittest.main()
