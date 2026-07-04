from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_d2_hithink_raw_market_prices_candidate import (
    CandidateArtifactMaterializationError,
    materialize_hithink_raw_market_prices_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/materialize_d2_hithink_raw_market_prices_candidate.py"
ARTIFACT_CONTRACT_PATH = (
    ROOT / "configs/d2/hithink_raw_market_prices_candidate_artifact_contract.v1.json"
)
SOURCE_REGISTRY_PATH = ROOT / "configs/d2/formal_source_registry_contract.v1.json"
PROBE_CONTRACT_PATH = ROOT / "configs/d2/hithink_raw_ohlcv_probe_contract.v1.json"
PLAN_CONTRACT_PATH = (
    ROOT
    / "configs/d2/hithink_raw_market_prices_candidate_materialization_contract.v1.json"
)
TARGET_FIELDS = [
    "data_version",
    "universe_id",
    "time_segment_id",
    "security_id",
    "trading_date",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "volume",
    "amount",
    "trading_status",
    "price_limit_status",
    "source_registry_id",
    "source_snapshot_id",
    "observed_at",
    "run_id",
]


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def read_artifact(path: Path) -> list[dict[str, object]]:
    if path.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    import pandas as pd

    return pd.read_parquet(path).to_dict(orient="records")


class MaterializeD2HiThinkRawMarketPricesCandidateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contracts = {
            "artifact_contract": load_json(ARTIFACT_CONTRACT_PATH),
            "source_registry": load_json(SOURCE_REGISTRY_PATH),
            "probe_contract": load_json(PROBE_CONTRACT_PATH),
            "plan_contract": load_json(PLAN_CONTRACT_PATH),
        }
        self.probe_report = {
            "raw_k_schema_report": {
                "status": "passed",
                "resolved_fields": {
                    "security_code_or_thscode": "thscode",
                    "trading_date": "trade_date",
                    "raw_open": "open",
                    "raw_high": "high",
                    "raw_low": "low",
                    "raw_close": "close",
                    "volume": "vol",
                    "amount": "turnover_amount",
                },
            }
        }
        self.mapping = {
            "rows": [
                {
                    "source_symbol": "600000.SH",
                    "security_id": "SHSE.600000",
                    "mapping_status": "accepted",
                },
                {
                    "source_symbol": "600001.SH",
                    "security_id": "SHSE.600001",
                    "mapping_status": "pending",
                },
            ]
        }
        self.raw_rows = [
            {
                "thscode": "600000.SH",
                "trade_date": "20260701",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "vol": 1000,
                "turnover_amount": 10500,
            },
            {
                "thscode": "600001.SH",
                "trade_date": "20260701",
                "open": 20,
                "high": 21,
                "low": 19,
                "close": 20.5,
                "vol": 2000,
                "turnover_amount": 41000,
            },
        ]

    def _run(
        self, raw_rows: list[dict[str, object]] | None = None
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_path = tmp / "raw.json"
            write_json(raw_path, raw_rows or self.raw_rows)
            output_dir = tmp / "generated"
            report = materialize_hithink_raw_market_prices_candidate(
                raw_k_path=raw_path,
                probe_report=self.probe_report,
                security_mapping=self.mapping,
                contracts=self.contracts,
                params={
                    "universe_id": "CSI800_STATIC_2026_07",
                    "time_segment_id": "RAW_10Y_TO_20260704",
                    "source_observed_at": "2026-07-04T00:00:00Z",
                    "output_dir": output_dir,
                },
            )
            artifact_rows = read_artifact(
                Path(report["candidate_raw_market_prices_artifact"])
            )
            report["artifact_rows_for_test"] = artifact_rows
            return report

    def test_synthetic_input_generates_candidate_artifact_with_17_fields(self) -> None:
        report = self._run()
        rows = report["artifact_rows_for_test"]
        self.assertEqual(report["status"], "candidate_blocked")
        self.assertEqual(len(rows), 1)
        self.assertEqual(list(rows[0]), TARGET_FIELDS)
        self.assertEqual(set(rows[0]), set(TARGET_FIELDS))
        self.assertNotIn("source_symbol", rows[0])
        self.assertNotIn("thscode", rows[0])
        self.assertNotIn("vendor_payload", rows[0])
        self.assertNotIn("raw_rows", rows[0])

    def test_raw_fields_and_security_mapping_are_applied(self) -> None:
        row = self._run()["artifact_rows_for_test"][0]
        self.assertEqual(row["security_id"], "SHSE.600000")
        self.assertEqual(row["trading_date"], "2026-07-01")
        self.assertEqual(row["raw_open"], 10.0)
        self.assertEqual(row["raw_close"], 10.5)
        self.assertEqual(row["volume"], 1000.0)
        self.assertEqual(row["amount"], 10500.0)
        self.assertEqual(row["source_registry_id"], "hithink_financial_api")
        self.assertEqual(row["observed_at"], "2026-07-04T00:00:00Z")

    def test_unmapped_symbol_is_dropped_and_counted(self) -> None:
        quality = self._run()["quality_summary"]
        self.assertEqual(quality["row_count_input"], 2)
        self.assertEqual(quality["row_count_output"], 1)
        self.assertEqual(quality["dropped_unmapped_security_count"], 1)

    def test_missing_status_fields_default_to_unknown_and_are_counted(self) -> None:
        report = self._run()
        row = report["artifact_rows_for_test"][0]
        quality = report["quality_summary"]
        self.assertEqual(row["trading_status"], "unknown")
        self.assertEqual(row["price_limit_status"], "unknown")
        self.assertEqual(quality["unknown_trading_status_count"], 1)
        self.assertEqual(quality["unknown_price_limit_status_count"], 1)

    def test_quality_blockers_for_prices_volume_amount_and_duplicates(self) -> None:
        raw_rows = [
            {
                "thscode": "600000.SH",
                "trade_date": "20260701",
                "open": 0,
                "high": 8,
                "low": 9,
                "close": 10,
                "vol": -1,
                "turnover_amount": -2,
            },
            {
                "thscode": "600000.SH",
                "trade_date": "20260701",
                "open": 0,
                "high": 8,
                "low": 9,
                "close": 10,
                "vol": -1,
                "turnover_amount": -2,
            },
        ]
        quality = self._run(raw_rows)["quality_summary"]
        self.assertTrue(quality["candidate_blocking_flag"])
        self.assertGreater(quality["nonpositive_ohlc_count"], 0)
        self.assertGreater(quality["ohlc_order_violation_count"], 0)
        self.assertGreater(quality["negative_volume_count"], 0)
        self.assertGreater(quality["negative_amount_count"], 0)
        self.assertGreater(quality["duplicate_key_count"], 0)

    def test_null_volume_and_amount_trigger_candidate_blocking_flag(self) -> None:
        raw_rows = [
            {
                "thscode": "600000.SH",
                "trade_date": "20260701",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "vol": None,
                "turnover_amount": None,
            }
        ]
        quality = self._run(raw_rows)["quality_summary"]
        self.assertTrue(quality["candidate_blocking_flag"])
        self.assertEqual(quality["null_volume_count"], 1)
        self.assertEqual(quality["null_amount_count"], 1)
        self.assertIn("null_volume", quality["candidate_blocking_reasons"])
        self.assertIn("null_amount", quality["candidate_blocking_reasons"])

    def test_missing_or_unparseable_observed_at_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "raw.json"
            write_json(raw_path, self.raw_rows)
            for observed_at in ["", "20260704"]:
                with self.subTest(observed_at=observed_at):
                    with self.assertRaises(CandidateArtifactMaterializationError):
                        materialize_hithink_raw_market_prices_candidate(
                            raw_k_path=raw_path,
                            probe_report=self.probe_report,
                            security_mapping=self.mapping,
                            contracts=self.contracts,
                            params={
                                "universe_id": "CSI800_STATIC_2026_07",
                                "time_segment_id": "RAW_10Y_TO_20260704",
                                "source_observed_at": observed_at,
                                "output_dir": Path(tmpdir) / "generated",
                            },
                        )

    def test_report_contains_no_row_level_payload_and_no_formal_outputs(self) -> None:
        report = self._run()
        for key in [
            "raw_rows",
            "row_level_prices",
            "vendor_payload",
            "d3_rows",
        ]:
            self.assertNotIn(key, report)
        self.assertFalse(report["duckdb_written"])
        self.assertFalse(report["accepted_manifest_created"])
        self.assertFalse(report["data_version_published"])
        self.assertFalse(report["d3_artifact_generated"])
        self.assertFalse(report["r0_state_generated"])

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
            raw_path = tmp / "raw.parquet"
            try:
                pd.DataFrame(self.raw_rows).to_parquet(raw_path, index=False)
            except Exception as exc:  # pragma: no cover - depends on optional engine
                self.skipTest(f"parquet engine unavailable: {exc}")
            report = materialize_hithink_raw_market_prices_candidate(
                raw_k_path=raw_path,
                probe_report=self.probe_report,
                security_mapping=self.mapping,
                contracts=self.contracts,
                params={
                    "universe_id": "CSI800_STATIC_2026_07",
                    "time_segment_id": "RAW_10Y_TO_20260704",
                    "source_observed_at": "2026-07-04T00:00:00Z",
                    "output_dir": tmp / "generated",
                },
            )
            artifact_path = Path(report["candidate_raw_market_prices_artifact"])
            self.assertEqual(artifact_path.suffix, ".parquet")
            rows = read_artifact(artifact_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(set(rows[0]), set(TARGET_FIELDS))
            self.assertFalse(report["duckdb_written"])

    def test_cli_explicit_synthetic_input_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            raw_path = tmp / "raw.json"
            probe_path = tmp / "probe_report.json"
            mapping_path = tmp / "security_mapping.json"
            output_dir = tmp / "generated"
            write_json(raw_path, self.raw_rows)
            write_json(probe_path, self.probe_report)
            write_json(mapping_path, self.mapping)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--raw-k-path",
                    str(raw_path),
                    "--probe-report",
                    str(probe_path),
                    "--security-mapping",
                    str(mapping_path),
                    "--universe-id",
                    "CSI800_STATIC_2026_07",
                    "--time-segment-id",
                    "RAW_10Y_TO_20260704",
                    "--source-observed-at",
                    "2026-07-04T00:00:00Z",
                    "--output-dir",
                    str(output_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("candidate_raw_market_prices_artifact", result.stdout)
        self.assertNotIn('"raw_rows":', result.stdout)

    def test_cli_missing_observed_at_returns_nonzero(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_cli_path_guards(self) -> None:
        forbidden_metadata_paths = [
            ROOT / "data/raw/probe_report.json",
            ROOT / "data/external/security_mapping.json",
            ROOT / "MarketDB/security_mapping.json",
            ROOT / "probe_report.parquet",
            ROOT / "probe_report.duckdb",
            ROOT / "SH000001.day",
        ]
        for path in forbidden_metadata_paths:
            with self.subTest(path=path):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT_PATH),
                        "--raw-k-path",
                        str(ROOT / "data/raw/allowed_raw.parquet"),
                        "--probe-report",
                        str(path),
                        "--security-mapping",
                        str(ROOT / "synthetic_security_mapping.json"),
                        "--universe-id",
                        "CSI800_STATIC_2026_07",
                        "--time-segment-id",
                        "RAW_10Y_TO_20260704",
                        "--source-observed-at",
                        "2026-07-04T00:00:00Z",
                        "--output-dir",
                        str(
                            ROOT
                            / "data/generated/d2/d2_t09_candidate_raw_market_prices"
                        ),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("forbidden", result.stderr.lower())

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "raw.json"
            probe_path = Path(tmpdir) / "probe_report.json"
            mapping_path = Path(tmpdir) / "security_mapping.json"
            write_json(raw_path, self.raw_rows)
            write_json(probe_path, self.probe_report)
            write_json(mapping_path, self.mapping)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--raw-k-path",
                    str(raw_path),
                    "--probe-report",
                    str(probe_path),
                    "--security-mapping",
                    str(mapping_path),
                    "--universe-id",
                    "CSI800_STATIC_2026_07",
                    "--time-segment-id",
                    "RAW_10Y_TO_20260704",
                    "--source-observed-at",
                    "2026-07-04T00:00:00Z",
                    "--output-dir",
                    str(ROOT / "data/raw/forbidden_output"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("forbidden", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
