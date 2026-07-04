from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_adjusted_price_quality_gap_candidate import (
    AdjustedPriceQualityGapMaterializationError,
    materialize_adjusted_price_quality_gap_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/materialize_d2_adjusted_price_quality_gap_candidate.py"
CONTRACT_PATH = (
    ROOT / "configs/d2/adjusted_price_quality_gap_candidate_contract.v1.json"
)
SOURCE_REGISTRY_PATH = ROOT / "configs/d2/formal_source_registry_contract.v1.json"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def read_rows(path: Path) -> list[dict[str, object]]:
    if path.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    import pandas as pd

    frame = pd.read_parquet(path)
    return list(frame.to_dict(orient="records"))


class MaterializeD2AdjustedPriceQualityGapCandidateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contracts = {
            "contract": load_json(CONTRACT_PATH),
            "source_registry": load_json(SOURCE_REGISTRY_PATH),
        }
        self.raw_rows = [
            {
                "data_version": "D2_T09_SYNTHETIC",
                "universe_id": "CSI800_STATIC_2026_07",
                "time_segment_id": "RAW_10Y_TO_20260704",
                "security_id": "CN.SSE.600000",
                "trading_date": "2026-07-01",
                "raw_open": 10.0,
                "raw_high": 11.0,
                "raw_low": 9.0,
                "raw_close": 10.0,
                "volume": 1000.0,
                "amount": 10000.0,
                "trading_status": "normal_trading",
                "price_limit_status": "none",
                "source_registry_id": "hithink_financial_api",
                "source_snapshot_id": "snapshot_1",
                "observed_at": "2026-07-04T00:00:00Z",
                "run_id": "d2_t09_candidate_test",
            },
            {
                "data_version": "D2_T09_SYNTHETIC",
                "universe_id": "CSI800_STATIC_2026_07",
                "time_segment_id": "RAW_10Y_TO_20260704",
                "security_id": "CN.SSE.600000",
                "trading_date": "2026-07-02",
                "raw_open": 12.0,
                "raw_high": 13.0,
                "raw_low": 11.0,
                "raw_close": 12.0,
                "volume": 1100.0,
                "amount": 13200.0,
                "trading_status": "unknown",
                "price_limit_status": "unknown",
                "source_registry_id": "hithink_financial_api",
                "source_snapshot_id": "snapshot_1",
                "observed_at": "2026-07-04T00:00:00Z",
                "run_id": "d2_t09_candidate_test",
            },
        ]
        self.adjustment_rows = [
            {
                "security_id": "CN.SSE.600000",
                "trading_date": "2026-07-01",
                "adjustment_factor": 1.0,
                "factor_as_of_time": "2026-07-04T00:00:00Z",
                "adjustment_revision": "candidate",
            },
            {
                "security_id": "CN.SSE.600000",
                "trading_date": "2026-07-02",
                "adjustment_factor": 0.85,
            },
        ]
        self.quality_summary = {"candidate_blocking_flag": True}
        self.probe_report = {"status": "passed"}

    def _run(
        self,
        raw_rows: list[dict[str, object]] | None = None,
        adjustment_rows: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_path = tmp / "raw_candidate.json"
            adjustment_path = tmp / "adjustments.json"
            write_json(raw_path, self.raw_rows if raw_rows is None else raw_rows)
            write_json(
                adjustment_path,
                self.adjustment_rows if adjustment_rows is None else adjustment_rows,
            )
            report = materialize_adjusted_price_quality_gap_candidate(
                raw_candidate_artifact=raw_path,
                raw_candidate_quality_summary=self.quality_summary,
                adjustment_events_path=adjustment_path,
                probe_report=self.probe_report,
                contracts=self.contracts,
                params={
                    "source_observed_at": "2026-07-04T00:00:00Z",
                    "output_dir": tmp / "generated",
                },
            )
            report["adjusted_rows_for_test"] = read_rows(
                Path(report["adjusted_market_prices_candidate"])
            )
            report["quality_rows_for_test"] = read_rows(
                Path(report["market_price_quality_flags_candidate"])
            )
            report["gap_rows_for_test"] = read_rows(
                Path(report["mechanical_gap_attribution_candidate"])
            )
            return report

    def test_synthetic_inputs_generate_adjusted_candidate_artifacts(self) -> None:
        report = self._run()
        self.assertEqual(report["status"], "candidate_blocked")
        self.assertEqual(len(report["adjusted_rows_for_test"]), 2)
        self.assertEqual(len(report["quality_rows_for_test"]), 2)
        self.assertEqual(len(report["gap_rows_for_test"]), 2)
        self.assertFalse(report["duckdb_written"])
        self.assertFalse(report["data_version_published"])
        self.assertFalse(report["d3_artifact_generated"])
        self.assertFalse(report["pcvt_values_generated"])

    def test_adjusted_artifact_has_only_allowed_fields_and_factor_math(self) -> None:
        row = self._run()["adjusted_rows_for_test"][1]
        for field in [
            "source_symbol",
            "vendor_payload",
            "future_return",
            "pcvt_value",
            "label",
        ]:
            self.assertNotIn(field, row)
        self.assertAlmostEqual(row["adj_open"], 10.2)
        self.assertAlmostEqual(row["adj_high"], 11.05)
        self.assertAlmostEqual(row["adj_low"], 9.35)
        self.assertAlmostEqual(row["adj_close"], 10.2)

    def test_missing_factor_asof_and_revision_block_point_in_time_readiness(
        self,
    ) -> None:
        report = self._run()
        reconciliation = report["reconciliation_summary"]
        self.assertGreater(reconciliation["factor_as_of_time_missing_count"], 0)
        self.assertGreater(reconciliation["adjustment_revision_missing_count"], 0)
        self.assertIn(
            "adjustment_revision_missing",
            reconciliation["candidate_blocking_reasons"],
        )

    def test_raw_and_adjusted_ohlc_volume_amount_violations_block(self) -> None:
        bad_rows = [
            dict(
                self.raw_rows[0],
                raw_open=0,
                raw_high=8,
                raw_low=9,
                volume=None,
                amount=-1,
            )
        ]
        report = self._run(raw_rows=bad_rows, adjustment_rows=[])
        reasons = report["adjusted_rows_for_test"][0]["quality_blocking_reasons"]
        self.assertIn("raw_ohlc_null_or_nonpositive", reasons)
        self.assertIn("adjusted_ohlc_null_or_nonpositive", reasons)
        self.assertIn("raw_ohlc_order_violation", reasons)
        self.assertIn("null_volume", reasons)
        self.assertIn("negative_amount", reasons)

    def test_unknown_trading_and_limit_status_readiness_block(self) -> None:
        readiness = self._run()["trading_constraint_readiness"]
        self.assertEqual(readiness["trading_status_unknown_count"], 1)
        self.assertEqual(readiness["price_limit_status_unknown_count"], 1)
        self.assertTrue(readiness["readiness_blocking_flag"])

    def test_mechanical_gap_candidate_and_unknown_gap_are_reported(self) -> None:
        report = self._run()
        gap_rows = report["gap_rows_for_test"]
        self.assertTrue(gap_rows[1]["mechanical_gap_candidate_flag"])
        self.assertEqual(
            gap_rows[1]["gap_attribution_status"], "candidate_mechanical_gap"
        )
        no_event_report = self._run(adjustment_rows=[])
        no_event_gap = no_event_report["gap_rows_for_test"][1]
        self.assertEqual(
            no_event_gap["gap_attribution_status"], "unknown_or_unverified"
        )

    def test_output_report_contains_no_row_level_payload(self) -> None:
        report = self._run()
        for key in [
            "raw_rows",
            "row_level_prices",
            "vendor_payload",
            "d3_rows",
            "pcvt_values",
        ]:
            self.assertNotIn(key, report)

    def test_raw_candidate_with_prohibited_field_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_path = tmp / "raw_candidate.json"
            adjustment_path = tmp / "adjustments.json"
            write_json(raw_path, [dict(self.raw_rows[0], future_return=0.1)])
            write_json(adjustment_path, self.adjustment_rows)
            with self.assertRaises(AdjustedPriceQualityGapMaterializationError):
                materialize_adjusted_price_quality_gap_candidate(
                    raw_candidate_artifact=raw_path,
                    raw_candidate_quality_summary=self.quality_summary,
                    adjustment_events_path=adjustment_path,
                    probe_report=self.probe_report,
                    contracts=self.contracts,
                    params={
                        "source_observed_at": "2026-07-04T00:00:00Z",
                        "output_dir": tmp / "generated",
                    },
                )

    def test_cli_explicit_synthetic_inputs_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_path = tmp / "raw_candidate.json"
            quality_path = tmp / "quality.json"
            adjustment_path = tmp / "adjustments.json"
            probe_path = tmp / "probe.json"
            write_json(raw_path, self.raw_rows)
            write_json(quality_path, self.quality_summary)
            write_json(adjustment_path, self.adjustment_rows)
            write_json(probe_path, self.probe_report)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--raw-candidate-artifact",
                    str(raw_path),
                    "--raw-candidate-quality-summary",
                    str(quality_path),
                    "--adjustment-events-path",
                    str(adjustment_path),
                    "--probe-report",
                    str(probe_path),
                    "--source-observed-at",
                    "2026-07-04T00:00:00Z",
                    "--output-dir",
                    str(tmp / "generated"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("adjusted_market_prices_candidate", result.stdout)
        self.assertNotIn('"raw_rows":', result.stdout)

    def test_cli_forbidden_path_guards(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--raw-candidate-artifact",
                str(ROOT / "data/generated/raw_candidate.parquet"),
                "--raw-candidate-quality-summary",
                str(ROOT / "data/raw/quality.json"),
                "--adjustment-events-path",
                str(ROOT / "MarketDB/adjustments.json"),
                "--probe-report",
                str(ROOT / "probe.json"),
                "--source-observed-at",
                "2026-07-04T00:00:00Z",
                "--output-dir",
                str(ROOT / "data/generated/d2/d2_t10_adjusted_price_quality_gap"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden", result.stderr.lower())

    def test_materializer_source_does_not_convert_real_parquet_to_dict_rows(
        self,
    ) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertNotIn('.to_dict(orient="records")', source)
        self.assertNotIn(".to_dict(orient='records')", source)

    def test_small_parquet_input_uses_dataframe_branch_when_available(self) -> None:
        try:
            import pandas as pd
        except ImportError:
            self.skipTest("pandas is unavailable")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_path = tmp / "raw_candidate.parquet"
            adjustment_path = tmp / "adjustments.parquet"
            try:
                pd.DataFrame(self.raw_rows).to_parquet(raw_path, index=False)
                pd.DataFrame(self.adjustment_rows).to_parquet(
                    adjustment_path, index=False
                )
            except Exception as exc:  # pragma: no cover
                self.skipTest(f"parquet engine unavailable: {exc}")
            report = materialize_adjusted_price_quality_gap_candidate(
                raw_candidate_artifact=raw_path,
                raw_candidate_quality_summary=self.quality_summary,
                adjustment_events_path=adjustment_path,
                probe_report=self.probe_report,
                contracts=self.contracts,
                params={
                    "source_observed_at": "2026-07-04T00:00:00Z",
                    "output_dir": tmp / "generated",
                },
            )
            self.assertEqual(
                Path(report["adjusted_market_prices_candidate"]).suffix, ".parquet"
            )


if __name__ == "__main__":
    unittest.main()
