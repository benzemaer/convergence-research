from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_tnskhdata_full_candidate import (
    acceptance_decision,
    build_candidate_outputs,
    build_fetch_plan,
    build_quality_report,
    materialize_full_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (
        ROOT / "configs/d2/tnskhdata_full_materialization_acceptance_contract.v1.json"
    ).read_text(encoding="utf-8")
)


class FakeFrame:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []

    @property
    def empty(self) -> bool:
        return not self.rows

    def to_dict(self, orient: str):
        return self.rows


class CompleteFakeClient:
    def stock_basic(self, **kwargs):
        return FakeFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "list_status": kwargs["list_status"],
                    "list_date": "20100101",
                }
            ]
        )

    def trade_cal(self, **kwargs):
        return FakeFrame(
            [{"cal_date": "20260630", "is_open": 1, "pretrade_date": "20260629"}]
        )

    def daily(self, **kwargs):
        return FakeFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": kwargs["trade_date"],
                    "open": 10,
                    "high": 10.5,
                    "low": 9.5,
                    "close": 10,
                    "pre_close": 9.8,
                    "vol": 100,
                    "amount": 200,
                }
            ]
        )

    def stk_limit(self, **kwargs):
        return FakeFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": kwargs["trade_date"],
                    "up_limit": 11,
                    "down_limit": 9,
                }
            ]
        )

    def adj_factor(self, **kwargs):
        return FakeFrame(
            [{"ts_code": "000001.SZ", "trade_date": "20260630", "adj_factor": 1.2}]
        )

    def stock_st(self, **kwargs):
        return FakeFrame([])

    def suspend_d(self, **kwargs):
        return FakeFrame([])

    def pro_bar(self, **kwargs):
        return FakeFrame([])


class ProBarFailingFakeClient(CompleteFakeClient):
    def pro_bar(self, **kwargs):
        raise RuntimeError("No such method: pro_bar")


class D2T13TnskhdataAcceptanceGateTest(unittest.TestCase):
    def _candidate_path(self, tmp: Path, rows=None) -> Path:
        path = tmp / "candidate.json"
        path.write_text(
            json.dumps(
                rows
                or [
                    {
                        "security_id": "XSHE.000001",
                        "trading_date": "20260630",
                        "universe_id": "u",
                        "time_segment_id": "t",
                    }
                ]
            ),
            encoding="utf-8",
        )
        return path

    def test_complete_fake_coverage_is_accepted_without_d3_or_duckdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            result = materialize_full_candidate(
                contract=CONTRACT,
                candidate_universe=self._candidate_path(tmp),
                output_dir=tmp / "generated",
                start_date="20160101",
                end_date="20260630",
                enable_remote_fetch=False,
                client=CompleteFakeClient(),
                full=True,
            )
            self.assertEqual(
                result["d2_acceptance_decision"], "accepted_for_d3_candidate_generation"
            )
            self.assertEqual(
                result["d3_handoff_decision"], "d3_candidate_generation_allowed"
            )
            self.assertFalse(result["duckdb_written"])
            self.assertFalse(result["d3_rows_generated"])
            self.assertFalse(result["r0_state_generated"])
            self.assertEqual(
                result["quality_report"]["pro_bar_reconciliation_status"],
                "passed_or_not_requested",
            )

    def test_pro_bar_failure_is_non_blocking_for_d2_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            result = materialize_full_candidate(
                contract=CONTRACT,
                candidate_universe=self._candidate_path(tmp),
                output_dir=tmp / "generated",
                start_date="20160101",
                end_date="20260630",
                enable_remote_fetch=False,
                client=ProBarFailingFakeClient(),
                full=True,
            )
            self.assertEqual(
                result["d2_acceptance_decision"], "accepted_for_d3_candidate_generation"
            )
            self.assertEqual(
                result["quality_report"]["primary_provider_error_count"], 0
            )
            self.assertEqual(
                result["quality_report"]["reconciliation_provider_error_count"], 1
            )
            self.assertEqual(
                result["quality_report"]["pro_bar_reconciliation_status"],
                "failed_non_blocking",
            )
            self.assertGreater(
                result["quality_report"]["pro_bar_reconciliation_warning_count"], 0
            )

    def test_missing_adj_factor_blocks_provider_coverage(self) -> None:
        plan = build_fetch_plan(
            [
                {
                    "security_id": "XSHE.000001",
                    "trading_date": "20260630",
                    "universe_id": "u",
                    "time_segment_id": "t",
                }
            ],
            full=True,
            sample_securities=None,
            sample_dates_per_security=None,
        )
        evidence = {
            "stock_basic": [{"ts_code": "000001.SZ", "list_date": "20100101"}],
            "trade_cal": [{"cal_date": "20260630", "is_open": 1}],
            "daily": [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260630",
                    "open": 10,
                    "high": 10,
                    "low": 9,
                    "close": 10,
                    "vol": 1,
                    "amount": 1,
                }
            ],
            "stk_limit": [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260630",
                    "up_limit": 11,
                    "down_limit": 9,
                }
            ],
            "adj_factor": [],
            "stock_st": [],
            "suspend_d": [],
            "_metrics": [
                {
                    "primary_provider_error_count": 0,
                    "reconciliation_provider_error_count": 0,
                    "rate_limit_count": 0,
                }
            ],
        }
        outputs = build_candidate_outputs(
            plan, evidence, source_snapshot_id="s", artifact_sha256="h"
        )
        quality = build_quality_report(plan, outputs, evidence)
        self.assertEqual(
            acceptance_decision(quality), "blocked_pending_provider_coverage"
        )

    def test_duplicate_key_or_unit_unknown_blocks_quality(self) -> None:
        rows = [
            {
                "security_id": "XSHE.000001",
                "trading_date": "20260630",
                "universe_id": "u",
                "time_segment_id": "t",
            },
            {
                "security_id": "XSHE.000001",
                "trading_date": "20260630",
                "universe_id": "u",
                "time_segment_id": "t",
            },
        ]
        plan = build_fetch_plan(
            rows, full=True, sample_securities=None, sample_dates_per_security=None
        )
        evidence = {
            "stock_basic": [{"ts_code": "000001.SZ", "list_date": "20100101"}],
            "trade_cal": [{"cal_date": "20260630", "is_open": 1}],
            "daily": [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260630",
                    "open": 10,
                    "high": 10,
                    "low": 9,
                    "close": 10,
                    "vol": None,
                    "amount": 1,
                }
            ],
            "stk_limit": [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260630",
                    "up_limit": 11,
                    "down_limit": 9,
                }
            ],
            "adj_factor": [
                {"ts_code": "000001.SZ", "trade_date": "20260630", "adj_factor": 1}
            ],
            "stock_st": [],
            "suspend_d": [],
            "_metrics": [
                {
                    "primary_provider_error_count": 0,
                    "reconciliation_provider_error_count": 0,
                    "rate_limit_count": 0,
                }
            ],
        }
        outputs = build_candidate_outputs(
            plan, copy.deepcopy(evidence), source_snapshot_id="s", artifact_sha256="h"
        )
        quality = build_quality_report(plan, outputs, evidence)
        self.assertEqual(quality["volume_unit_status"], "unknown")
        self.assertEqual(
            acceptance_decision(quality), "blocked_pending_quality_resolution"
        )


if __name__ == "__main__":
    unittest.main()
