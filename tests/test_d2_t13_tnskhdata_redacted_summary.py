from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = (
    ROOT
    / "docs/research"
    / "D2_T13_tnskhdata_full_materialization_acceptance_redacted_summary.md"
)


class D2T13TnskhdataRedactedSummaryTest(unittest.TestCase):
    def test_summary_contains_gate_decision_and_no_forbidden_payload(self) -> None:
        text = SUMMARY.read_text(encoding="utf-8")
        self.assertIn("20160101", text)
        self.assertIn("20260630", text)
        self.assertIn("d2_acceptance_decision", text)
        self.assertIn("d3_handoff_decision", text)
        for forbidden in [
            "vendor_payload:",
            "raw provider response:",
            "API tokens:",
            "row-level prices:",
        ]:
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
