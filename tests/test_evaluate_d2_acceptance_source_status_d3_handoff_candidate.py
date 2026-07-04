from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_d2_acceptance_source_status_d3_handoff_candidate import (
    evaluate_d2_acceptance_source_status_d3_handoff_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/evaluate_d2_acceptance_source_status_d3_handoff_candidate.py"
CONTRACT = (
    ROOT
    / "configs/d2/source_status_factor_evidence_acceptance_handoff_contract.v1.json"
)


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class EvaluateD2AcceptanceSourceStatusD3HandoffCandidateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_json(CONTRACT)
        self.status_resolved = [
            {
                "security_id": "S1",
                "trading_date": "2026-07-01",
                "trading_status": "normal_trading",
                "price_limit_status": "none",
                "suspension_status": "not_suspended",
                "st_status": "not_st",
                "limit_up_price": 11,
                "limit_down_price": 9,
                "status_resolution_status": "resolved",
            }
        ]
        self.factor_resolved = [
            {
                "security_id": "S1",
                "trading_date": "2026-07-01",
                "adjustment_factor": 1.0,
                "factor_as_of_time": "2026-07-04T00:00:00Z",
                "adjustment_revision": "candidate",
                "point_in_time_eligible": True,
                "factor_resolution_status": "resolved",
            }
        ]
        self.no_conflict = {"conflict_count": 0}

    def _run(self, status_rows, factor_rows, discrepancy=None):
        with tempfile.TemporaryDirectory() as tmpdir:
            return evaluate_d2_acceptance_source_status_d3_handoff_candidate(
                contract=self.contract,
                source_status_rows=status_rows,
                factor_rows=factor_rows,
                discrepancy_report=discrepancy or self.no_conflict,
                output_dir=Path(tmpdir) / "out",
            )

    def test_blocked_without_supplemental_evidence(self) -> None:
        report = self._run([], [])
        self.assertFalse(report["d3_candidate_generation_allowed"])
        self.assertEqual(report["r0_handoff_decision"], "r0_blocked")

    def test_source_resolved_factor_unresolved_blocks(self) -> None:
        report = self._run(self.status_resolved, [])
        self.assertEqual(
            report["d2_acceptance_decision"],
            "blocked_pending_adjustment_factor_resolution",
        )

    def test_factor_resolved_source_unresolved_blocks(self) -> None:
        report = self._run([], self.factor_resolved)
        self.assertEqual(
            report["d2_acceptance_decision"],
            "blocked_pending_source_status_resolution",
        )

    def test_all_resolved_allows_d3_candidate_but_not_generation(self) -> None:
        report = self._run(self.status_resolved, self.factor_resolved)
        self.assertTrue(report["d3_candidate_generation_allowed"])
        self.assertFalse(report["d3_generation_authorized"])
        self.assertFalse(report["r0_state_generation_authorized"])

    def test_conflict_blocks_and_cli_returns_zero(self) -> None:
        report = self._run(
            self.status_resolved,
            self.factor_resolved,
            {"conflict_count": 1},
        )
        self.assertFalse(report["d3_candidate_generation_allowed"])
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            status = tmp / "status.json"
            factor = tmp / "factor.json"
            discrepancy = tmp / "disc.json"
            write_json(status, self.status_resolved)
            write_json(factor, self.factor_resolved)
            write_json(discrepancy, {"conflict_count": 0})
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-status-evidence",
                    str(status),
                    "--factor-evidence",
                    str(factor),
                    "--discrepancy-report",
                    str(discrepancy),
                    "--output-dir",
                    str(tmp / "out"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("row_level_prices", result.stdout)

    def test_forbidden_path_guard(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--source-status-evidence",
                "data/raw/status.json",
                "--factor-evidence",
                "factor.json",
                "--discrepancy-report",
                "disc.json",
                "--output-dir",
                "out",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
