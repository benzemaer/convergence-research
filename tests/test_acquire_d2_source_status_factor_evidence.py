from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.acquire_d2_source_status_factor_evidence import (
    D2T11AcquisitionError,
    acquire_source_status_factor_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/acquire_d2_source_status_factor_evidence.py"
CONTRACT = (
    ROOT
    / "configs/d2/source_status_factor_evidence_acceptance_handoff_contract.v1.json"
)
SOURCE_REGISTRY = ROOT / "configs/d2/formal_source_registry_contract.v1.json"


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class AcquireD2SourceStatusFactorEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_json(CONTRACT)
        self.registry = load_json(SOURCE_REGISTRY)
        self.status_rows = [
            {
                "security_id": "S1",
                "trading_date": "2026-07-01",
                "status_source": "hithink_financial_api",
                "trading_status": "normal_trading",
                "price_limit_status": "unknown",
            },
            {
                "security_id": "S1",
                "trading_date": "2026-07-01",
                "status_source": "baostock",
                "trading_status": "suspended",
                "price_limit_status": "none",
                "suspension_status": "not_suspended",
            },
            {
                "security_id": "S1",
                "trading_date": "2026-07-01",
                "status_source": "tushare",
                "st_status": "not_st",
                "limit_up_price": 11,
                "limit_down_price": 9,
                "is_trading_day": True,
                "trading_calendar_status": "open",
            },
        ]
        self.factor_rows = [
            {
                "security_id": "S1",
                "trading_date": "2026-07-01",
                "factor_source": "baostock",
                "adjustment_factor": 1.2,
                "factor_as_of_time": None,
                "adjustment_revision": "candidate",
            },
            {
                "security_id": "S1",
                "trading_date": "2026-07-01",
                "factor_source": "tushare",
                "factor_as_of_time": "2026-07-04T00:00:00Z",
                "adjustment_factor_direction": "candidate_requires_review",
            },
        ]

    def _run(self, status_rows=None, factor_rows=None):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = acquire_source_status_factor_evidence(
                contract=self.contract,
                source_registry=self.registry,
                status_evidence_rows=self.status_rows
                if status_rows is None
                else status_rows,
                factor_evidence_rows=self.factor_rows
                if factor_rows is None
                else factor_rows,
                observed_at="2026-07-04T00:00:00Z",
                output_dir=Path(tmpdir) / "out",
            )
            report["status_rows_for_test"] = [
                json.loads(line)
                for line in Path(report["source_status_evidence_candidate"])
                .read_text()
                .splitlines()
            ]
            report["factor_rows_for_test"] = [
                json.loads(line)
                for line in Path(report["factor_evidence_candidate"])
                .read_text()
                .splitlines()
            ]
            return report

    def _candidate_universe(self) -> list[dict[str, object]]:
        return [
            {
                "security_id": "XSHE.000001",
                "trading_date": "2026-07-01",
                "universe_id": "CSI800_STATIC_2026_07",
                "time_segment_id": "RAW_10Y_TO_20260704",
            }
        ]

    def test_fallback_missing_only_and_conflict_report(self) -> None:
        report = self._run()
        rows = report["status_rows_for_test"]
        self.assertEqual(rows[0]["trading_status"], "normal_trading")
        self.assertEqual(rows[0]["price_limit_status"], "none")
        self.assertEqual(report["discrepancy_report"]["silent_override_count"], 0)
        self.assertGreater(report["discrepancy_report"]["conflict_count"], 0)

    def test_factor_missing_asof_blocks_point_in_time(self) -> None:
        report = self._run(factor_rows=[self.factor_rows[0]])
        row = report["factor_rows_for_test"][0]
        self.assertFalse(row["point_in_time_eligible"])
        self.assertNotEqual(row["factor_resolution_status"], "resolved")

    def test_a_stock_data_active_fails(self) -> None:
        rows = [dict(self.status_rows[0], status_source="a-stock-data")]
        with self.assertRaises(D2T11AcquisitionError):
            self._run(status_rows=rows)

    def test_no_env_remote_fetch_fails_and_cli_does_not_print_secret(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--enable-remote-fetch",
                "--source-observed-at",
                "2026-07-04T00:00:00Z",
                "--output-dir",
                "synthetic_out",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HITHINK_API_KEY", result.stderr)
        self.assertNotIn("fake-secret", result.stderr + result.stdout)

    def test_remote_fetch_requires_candidate_universe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env.local"
            env_file.write_text(
                "HITHINK_API_KEY=fake-h\nTUSHARE_TOKEN=fake-t\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(D2T11AcquisitionError, "candidate universe"):
                acquire_source_status_factor_evidence(
                    contract=self.contract,
                    source_registry=self.registry,
                    status_evidence_rows=[],
                    factor_evidence_rows=[],
                    observed_at="2026-07-04T00:00:00Z",
                    output_dir=Path(tmpdir) / "out",
                    enable_remote_fetch=True,
                    env_file=env_file,
                )

    def test_remote_fetch_provider_failure_keeps_evidence_unresolved(self) -> None:
        class FailingAdapter:
            provider_id = "hithink_financial_api"

            def probe(self, universe_rows, credentials):
                self.seen_credentials = credentials
                return (
                    [],
                    [],
                    {
                        "provider_id": self.provider_id,
                        "probe_status": "provider_probe_failed",
                        "probe_failure_reason": "fake_endpoint_unavailable",
                        "rows_requested": len(universe_rows),
                        "status_rows_returned": 0,
                        "factor_rows_returned": 0,
                    },
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env.local"
            env_file.write_text(
                "HITHINK_API_KEY=fake-h\nTUSHARE_TOKEN=fake-t\n",
                encoding="utf-8",
            )
            report = acquire_source_status_factor_evidence(
                contract=self.contract,
                source_registry=self.registry,
                status_evidence_rows=[],
                factor_evidence_rows=[],
                candidate_universe_rows=self._candidate_universe(),
                observed_at="2026-07-04T00:00:00Z",
                output_dir=Path(tmpdir) / "out",
                enable_remote_fetch=True,
                env_file=env_file,
                provider_adapters=[FailingAdapter()],
            )
            status_rows = [
                json.loads(line)
                for line in Path(report["source_status_evidence_candidate"])
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            factor_rows = [
                json.loads(line)
                for line in Path(report["factor_evidence_candidate"])
                .read_text(encoding="utf-8")
                .splitlines()
            ]
        self.assertEqual(status_rows[0]["status_resolution_status"], "unresolved")
        self.assertEqual(factor_rows[0]["factor_resolution_status"], "unresolved")
        self.assertTrue(report["discrepancy_report"]["blocking_flag"])
        self.assertIn(
            "provider_probe_failed", report["discrepancy_report"]["blocking_reasons"]
        )

    def test_remote_fetch_uses_candidate_universe_and_fallback_missing_only(
        self,
    ) -> None:
        class PrimaryAdapter:
            provider_id = "hithink_financial_api"

            def probe(self, universe_rows, credentials):
                row = universe_rows[0]
                return (
                    [
                        {
                            **row,
                            "status_source": self.provider_id,
                            "trading_status": "normal_trading",
                        }
                    ],
                    [],
                    {
                        "provider_id": self.provider_id,
                        "probe_status": "provider_probe_completed",
                        "rows_requested": len(universe_rows),
                        "status_rows_returned": 1,
                        "factor_rows_returned": 0,
                    },
                )

        class FallbackAdapter:
            provider_id = "baostock"

            def probe(self, universe_rows, credentials):
                row = universe_rows[0]
                return (
                    [
                        {
                            **row,
                            "status_source": self.provider_id,
                            "trading_status": "suspended",
                            "price_limit_status": "none",
                            "suspension_status": "not_suspended",
                            "st_status": "not_st",
                            "limit_up_price": 11,
                            "limit_down_price": 9,
                            "is_trading_day": True,
                            "trading_calendar_status": "open",
                        }
                    ],
                    [
                        {
                            **row,
                            "factor_source": self.provider_id,
                            "adjustment_factor": 1.0,
                            "factor_as_of_time": None,
                            "adjustment_revision": None,
                            "adjustment_factor_direction": "provider_schema_unresolved",
                            "point_in_time_eligible": False,
                        }
                    ],
                    {
                        "provider_id": self.provider_id,
                        "probe_status": "provider_probe_completed",
                        "rows_requested": len(universe_rows),
                        "status_rows_returned": 1,
                        "factor_rows_returned": 1,
                    },
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env.local"
            env_file.write_text(
                "HITHINK_API_KEY=fake-h\nTUSHARE_TOKEN=fake-t\n",
                encoding="utf-8",
            )
            report = acquire_source_status_factor_evidence(
                contract=self.contract,
                source_registry=self.registry,
                status_evidence_rows=[],
                factor_evidence_rows=[],
                candidate_universe_rows=self._candidate_universe(),
                observed_at="2026-07-04T00:00:00Z",
                output_dir=Path(tmpdir) / "out",
                enable_remote_fetch=True,
                env_file=env_file,
                provider_adapters=[PrimaryAdapter(), FallbackAdapter()],
            )
            status_rows = [
                json.loads(line)
                for line in Path(report["source_status_evidence_candidate"])
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            factor_rows = [
                json.loads(line)
                for line in Path(report["factor_evidence_candidate"])
                .read_text(encoding="utf-8")
                .splitlines()
            ]
        self.assertEqual(status_rows[0]["trading_status"], "normal_trading")
        self.assertEqual(status_rows[0]["price_limit_status"], "none")
        self.assertEqual(factor_rows[0]["factor_resolution_status"], "unresolved")
        self.assertGreater(report["discrepancy_report"]["conflict_count"], 0)

    def test_cli_synthetic_inputs_returns_zero_and_no_formal_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            status = tmp / "status.json"
            factor = tmp / "factor.json"
            write_json(status, self.status_rows)
            write_json(factor, self.factor_rows)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-status-evidence",
                    str(status),
                    "--factor-evidence",
                    str(factor),
                    "--source-observed-at",
                    "2026-07-04T00:00:00Z",
                    "--output-dir",
                    str(tmp / "out"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("source_status_evidence_candidate", result.stdout)
        self.assertNotIn("vendor_payload", result.stdout)

    def test_cli_remote_reads_candidate_universe_before_provider_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            env_file = tmp / ".env.local"
            env_file.write_text(
                "HITHINK_API_KEY=fake-h\nTUSHARE_TOKEN=fake-t\n",
                encoding="utf-8",
            )
            candidate = tmp / "candidate.json"
            write_json(candidate, self._candidate_universe())
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--enable-remote-fetch",
                    "--env-file",
                    str(env_file),
                    "--d2-t09-raw-candidate",
                    str(candidate),
                    "--source-observed-at",
                    "2026-07-04T00:00:00Z",
                    "--output-dir",
                    str(tmp / "out"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("provider_probe_diagnostics", result.stdout)
        self.assertNotIn("fake-h", result.stdout + result.stderr)
        self.assertNotIn("fake-t", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
