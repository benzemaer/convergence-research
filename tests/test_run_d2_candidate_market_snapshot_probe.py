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
    attach_implied_factors,
    build_redacted_report_from_synthetic_responses,
    main,
    normalize_baostock_rows,
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

    def test_normalize_baostock_rows_for_raw_qfq_hfq(self) -> None:
        raw_shape = [{"date": "2024-12-16", "code": "sh.600519", "close": "100.0"}]

        raw_rows = normalize_baostock_rows("raw", "CN.SSE.600519", raw_shape)
        self.assertEqual(raw_rows[0]["security_id"], "CN.SSE.600519")
        self.assertEqual(raw_rows[0]["trading_date"], "2024-12-16")
        self.assertEqual(raw_rows[0]["raw_close"], 100.0)

        qfq_rows = normalize_baostock_rows("qfq", "CN.SSE.600519", raw_shape)
        self.assertEqual(qfq_rows[0]["qfq_close"], 100.0)

        hfq_rows = normalize_baostock_rows("hfq", "CN.SSE.600519", raw_shape)
        self.assertEqual(hfq_rows[0]["hfq_close"], 100.0)

    def test_attach_implied_factors_from_normalized_baostock_rows(self) -> None:
        raw_rows = normalize_baostock_rows(
            "raw",
            "CN.SSE.600519",
            [{"date": "2024-12-16", "code": "sh.600519", "close": "100.0"}],
        )
        qfq_rows = normalize_baostock_rows(
            "qfq",
            "CN.SSE.600519",
            [{"date": "2024-12-16", "code": "sh.600519", "close": "90.0"}],
        )
        hfq_rows = normalize_baostock_rows(
            "hfq",
            "CN.SSE.600519",
            [{"date": "2024-12-16", "code": "sh.600519", "close": "110.0"}],
        )
        responses = attach_implied_factors(raw_rows, qfq_rows, hfq_rows)

        self.assertEqual(responses["qfq"][0]["implied_qfq_factor"], 0.9)
        self.assertEqual(responses["hfq"][0]["implied_hfq_factor"], 1.1)
        report = build_redacted_report_from_synthetic_responses(
            self.plan, "BAOSTOCK", responses
        )
        self.assertEqual(report["implied_qfq_factor_check"]["status"], "pass")
        self.assertGreater(report["implied_qfq_factor_check"]["checked_count"], 0)
        self.assertEqual(report["implied_hfq_factor_check"]["status"], "pass")
        self.assertGreater(report["implied_hfq_factor_check"]["checked_count"], 0)

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

    def test_factor_check_fails_when_adjusted_rows_exist_but_no_join_keys(
        self,
    ) -> None:
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
                    "trading_date": "2024-12-17",
                    "qfq_close": 90.0,
                    "implied_qfq_factor": 0.9,
                }
            ],
            "hfq": [],
        }
        report = build_redacted_report_from_synthetic_responses(
            self.plan, "BAOSTOCK", responses
        )
        self.assertEqual(report["implied_qfq_factor_check"]["status"], "fail")
        self.assertEqual(report["implied_qfq_factor_check"]["checked_count"], 0)
        self.assertGreater(report["implied_qfq_factor_check"]["mismatch_count"], 0)

    def test_factor_check_fails_when_adjusted_rows_empty_in_executed_path(
        self,
    ) -> None:
        responses = {
            "raw": [
                {
                    "security_id": "CN.SSE.600519",
                    "trading_date": "2024-12-16",
                    "raw_close": 100.0,
                }
            ],
            "qfq": [],
            "hfq": [],
        }
        report = build_redacted_report_from_synthetic_responses(
            self.plan, "BAOSTOCK", responses
        )
        self.assertEqual(report["qfq_coverage"], "fail")
        self.assertEqual(report["hfq_coverage"], "fail")
        self.assertEqual(report["implied_qfq_factor_check"]["status"], "fail")
        self.assertEqual(report["implied_hfq_factor_check"]["status"], "fail")

    def test_baostock_normalization_rejects_bad_close(self) -> None:
        for row in [
            {"date": "2024-12-16", "code": "sh.600519"},
            {"date": "2024-12-16", "code": "sh.600519", "close": ""},
            {"date": "2024-12-16", "code": "sh.600519", "close": "bad"},
        ]:
            with self.assertRaises(ProbeExecutionError):
                normalize_baostock_rows("raw", "CN.SSE.600519", [row])

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
