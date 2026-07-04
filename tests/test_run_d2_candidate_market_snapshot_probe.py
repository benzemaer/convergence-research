from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.run_d2_candidate_market_snapshot_probe import (
    DEFAULT_MEMBERSHIP_PATH,
    DEFAULT_PLAN_PATH,
    ProbeExecutionError,
    build_redacted_report_from_synthetic_responses,
    main,
    security_id_to_baostock_code,
    sha256_text,
    validate_sample_security_ids,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/run_d2_candidate_market_snapshot_probe.py"


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class RunD2CandidateMarketSnapshotProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = load(DEFAULT_PLAN_PATH)
        self.membership = load(DEFAULT_MEMBERSHIP_PATH)

    def test_security_id_to_baostock_code(self) -> None:
        self.assertEqual(security_id_to_baostock_code("CN.SSE.600000"), "sh.600000")
        self.assertEqual(security_id_to_baostock_code("CN.SZSE.000001"), "sz.000001")
        with self.assertRaises(ProbeExecutionError):
            security_id_to_baostock_code("CN.BSE.830000")

    def test_dry_run_does_not_require_external_execution(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--plan", str(DEFAULT_PLAN_PATH), "--dry-run"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["execution_status"], "not_executed_environment_blocked")
        self.assertFalse(report["duckdb_written"])
        self.assertFalse(report["d1_raw_market_prices_generated"])

    def test_execute_without_authorization_fails_before_api_call(self) -> None:
        with patch.dict(os.environ, {"D2_PROBE_ALLOW_EXTERNAL_API": ""}, clear=False):
            with self.assertRaises(ProbeExecutionError):
                main(
                    [
                        "--plan",
                        str(DEFAULT_PLAN_PATH),
                        "--execute",
                        "--source",
                        "BAOSTOCK",
                    ]
                )

    def test_non_member_sample_security_fails(self) -> None:
        changed = copy.deepcopy(self.plan)
        changed["sample_security_ids"] = ["CN.SSE.999999"]
        with self.assertRaises(ProbeExecutionError):
            validate_sample_security_ids(changed, self.membership)

    def test_synthetic_responses_build_redacted_report(self) -> None:
        responses = {
            "raw": [
                {
                    "security_id": "CN.SSE.600519",
                    "trading_date": "2024-12-16",
                    "raw_close": 100.0,
                }
            ],
            "qfq": [
                {
                    "security_id": "CN.SSE.600519",
                    "trading_date": "2024-12-16",
                    "qfq_close": 90.0,
                    "implied_qfq_factor": 0.9,
                }
            ],
            "hfq": [
                {
                    "security_id": "CN.SSE.600519",
                    "trading_date": "2024-12-16",
                    "hfq_close": 110.0,
                    "implied_hfq_factor": 1.1,
                }
            ],
        }
        report = build_redacted_report_from_synthetic_responses(
            self.plan, "BAOSTOCK", responses, ["2026-07-04T00:00:00+00:00"]
        )
        self.assertEqual(report["execution_status"], "executed_small_sample")
        self.assertTrue(report["raw_snapshot_written_local"])
        self.assertFalse(report["raw_snapshot_committed"])
        self.assertEqual(report["implied_qfq_factor_check"]["status"], "pass")
        self.assertNotIn("raw", report)
        self.assertNotIn("qfq", report)
        self.assertNotIn("hfq", report)

    def test_synthetic_implied_factor_mismatch_is_reported(self) -> None:
        responses = {
            "raw": [
                {
                    "security_id": "CN.SSE.600519",
                    "trading_date": "2024-12-16",
                    "raw_close": 100.0,
                }
            ],
            "qfq": [
                {
                    "security_id": "CN.SSE.600519",
                    "trading_date": "2024-12-16",
                    "qfq_close": 90.0,
                    "implied_qfq_factor": 0.8,
                }
            ],
            "hfq": [],
        }
        report = build_redacted_report_from_synthetic_responses(
            self.plan, "BAOSTOCK", responses
        )
        self.assertEqual(report["implied_qfq_factor_check"]["status"], "fail")
        self.assertEqual(report["implied_qfq_factor_check"]["mismatch_count"], 1)

    def test_sha256_text_returns_hex_digest(self) -> None:
        digest = sha256_text("synthetic response")
        self.assertEqual(len(digest), 64)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_script_does_not_hardcode_credentials_or_data_access(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("marketdb", source)
        self.assertNotIn(".day", source)
        self.assertNotIn("data/external", source)
        self.assertNotIn("import duckdb", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("urllib", source)
        credential_patterns = [
            "api_key =",
            "apikey =",
            "access_token =",
            "password =",
            "secret =",
        ]
        for pattern in credential_patterns:
            self.assertNotIn(pattern, source)

    def test_temp_plan_can_be_loaded_without_writing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = Path(tmpdir) / "plan.json"
            plan_path.write_text(
                json.dumps(self.plan, ensure_ascii=False), encoding="utf-8"
            )
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--plan", str(plan_path), "--dry-run"]), 0)
            self.assertEqual(list(Path(tmpdir).iterdir()), [plan_path])


if __name__ == "__main__":
    unittest.main()
