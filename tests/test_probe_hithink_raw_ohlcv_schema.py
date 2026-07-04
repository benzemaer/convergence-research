from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.probe_hithink_raw_ohlcv_schema import (
    HiThinkProbeError,
    probe_hithink_raw_ohlcv_schema,
)

ROOT = Path(__file__).resolve().parents[1]
PROBE_CONTRACT_PATH = ROOT / "configs/d2/hithink_raw_ohlcv_probe_contract.v1.json"
SOURCE_REGISTRY_PATH = ROOT / "configs/d2/formal_source_registry_contract.v1.json"
SCRIPT_PATH = ROOT / "scripts/probe_hithink_raw_ohlcv_schema.py"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(rows), encoding="utf-8")


class ProbeHiThinkRawOhlcvSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contracts = {
            "probe_contract": load_json(PROBE_CONTRACT_PATH),
            "source_registry": load_json(SOURCE_REGISTRY_PATH),
        }

    def _run_probe(
        self,
        raw_rows: list[dict[str, object]] | None = None,
        adjustment_rows: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        raw_rows = raw_rows or [
            {
                "thscode": "600000.SH",
                "trade_date": "2026-07-01",
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 1000,
                "amount": 10500,
                "trading_status": "normal_trading",
                "price_limit_status": "none",
            },
            {
                "thscode": "600001.SH",
                "trade_date": "2026-07-02",
                "open": 20.0,
                "high": 21.0,
                "low": 19.5,
                "close": 20.5,
                "volume": 2000,
                "amount": 41000,
                "trading_status": "normal_trading",
                "price_limit_status": "none",
            },
        ]
        adjustment_rows = adjustment_rows or [
            {
                "thscode": "600000.SH",
                "event_date": "2026-06-30",
                "ex_date": "2026-07-01",
                "record_date": "2026-06-29",
                "announcement_date": "2026-06-20",
                "cash_dividend": 0.1,
                "share_bonus": 0.0,
                "share_transfer": 0.0,
                "rights_issue": 0.0,
                "rights_price": 0.0,
                "adjustment_factor": 1.0,
                "factor_as_of_time": "2026-07-01T00:00:00Z",
                "adjustment_revision": "v1",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "synthetic_raw.parquet"
            adjustment_path = Path(tmpdir) / "synthetic_adjustment.parquet"
            write_json_rows(raw_path, raw_rows)
            write_json_rows(adjustment_path, adjustment_rows)
            return probe_hithink_raw_ohlcv_schema(
                raw_path, adjustment_path, self.contracts
            )

    def test_synthetic_parquet_paths_generate_probe_report(self) -> None:
        report = self._run_probe()
        self.assertIn("raw_k_schema_report", report)
        self.assertIn("adjustment_event_schema_report", report)
        self.assertEqual(report["coverage_report"]["row_count"], 2)
        self.assertEqual(report["coverage_report"]["security_count"], 2)
        self.assertEqual(report["coverage_report"]["trading_date_min"], "2026-07-01")
        self.assertEqual(report["coverage_report"]["trading_date_max"], "2026-07-02")
        self.assertEqual(report["raw_k_schema_report"]["status"], "passed")

    def test_missing_raw_close_or_amount_enters_missing_field_report(self) -> None:
        report = self._run_probe(
            raw_rows=[
                {
                    "thscode": "600000.SH",
                    "trade_date": "2026-07-01",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "volume": 1000,
                }
            ]
        )
        missing = {
            item["semantic_field"]
            for item in report["missing_field_report"]["missing_fields"]
            if item["section"] == "raw_k"
        }
        self.assertGreaterEqual(missing, {"raw_close", "amount"})

    def test_missing_adjustment_time_fields_enters_reports(self) -> None:
        report = self._run_probe(
            adjustment_rows=[
                {
                    "thscode": "600000.SH",
                    "event_date": "2026-06-30",
                    "ex_date": "2026-07-01",
                    "record_date": "2026-06-29",
                    "announcement_date": "2026-06-20",
                    "cash_dividend": 0.1,
                    "share_bonus": 0.0,
                    "share_transfer": 0.0,
                    "rights_issue": 0.0,
                    "rights_price": 0.0,
                    "adjustment_factor": 1.0,
                }
            ]
        )
        missing = {
            item["semantic_field"]
            for item in report["missing_field_report"]["missing_fields"]
            if item["section"] == "adjustment_events"
        }
        self.assertGreaterEqual(missing, {"factor_as_of_time", "adjustment_revision"})
        self.assertGreaterEqual(
            set(report["time_semantics_report"]["missing_time_semantic_fields"]),
            {"factor_as_of_time", "adjustment_revision"},
        )

    def test_missing_optional_status_fields_warn_without_defaults(self) -> None:
        report = self._run_probe(
            raw_rows=[
                {
                    "thscode": "600000.SH",
                    "trade_date": "2026-07-01",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "volume": 1000,
                    "amount": 10500,
                }
            ]
        )
        optional = report["probe_diagnostics"]["optional_field_report"]
        self.assertEqual(optional["status"], "warning")
        self.assertIn("trading_status", optional["missing_optional_fields"])
        self.assertIn("price_limit_status", optional["missing_optional_fields"])
        self.assertTrue(optional["missing_fields_are_not_defaulted"])

    def test_active_a_stock_data_fails(self) -> None:
        changed = copy.deepcopy(self.contracts)
        changed["source_registry"] = copy.deepcopy(self.contracts["source_registry"])
        changed["source_registry"]["source_hierarchy"]["fallback_sources"][0][
            "source_id"
        ] = "a-stock-data"
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "raw.parquet"
            adjustment_path = Path(tmpdir) / "adjustment.parquet"
            write_json_rows(raw_path, [{"thscode": "600000.SH"}])
            write_json_rows(adjustment_path, [{"thscode": "600000.SH"}])
            with self.assertRaises(HiThinkProbeError):
                probe_hithink_raw_ohlcv_schema(raw_path, adjustment_path, changed)

    def test_fallback_readiness_priorities(self) -> None:
        report = self._run_probe()
        fallback = {
            item["source_id"]: item["priority"]
            for item in report["fallback_readiness_report"]["fallback_sources"]
        }
        self.assertEqual(fallback["baostock"], 1)
        self.assertEqual(fallback["tushare"], 2)

    def test_probe_does_not_write_artifacts_or_raw_rows(self) -> None:
        report = self._run_probe()
        diagnostics = report["probe_diagnostics"]
        self.assertFalse(diagnostics["duckdb_written"])
        self.assertFalse(diagnostics["manifest_created"])
        self.assertFalse(diagnostics["data_version_published"])
        self.assertFalse(diagnostics["raw_rows_emitted"])
        self.assertNotIn("raw_rows", report)

    def test_cli_explicit_synthetic_paths_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "raw.parquet"
            adjustment_path = Path(tmpdir) / "adjustment.parquet"
            write_json_rows(
                raw_path,
                [
                    {
                        "thscode": "600000.SH",
                        "trade_date": "2026-07-01",
                        "open": 1,
                        "high": 2,
                        "low": 1,
                        "close": 2,
                        "volume": 1,
                        "amount": 2,
                    }
                ],
            )
            write_json_rows(adjustment_path, [{"thscode": "600000.SH"}])
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--contract",
                    str(PROBE_CONTRACT_PATH),
                    "--source-registry",
                    str(SOURCE_REGISTRY_PATH),
                    "--raw-k-path",
                    str(raw_path),
                    "--adjustment-events-path",
                    str(adjustment_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("raw_k_schema_report", result.stdout)

    def test_cli_missing_paths_returns_nonzero(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_script_does_not_default_scan_data_raw_or_use_forbidden_storage(
        self,
    ) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8").lower()
        for token in [
            "import duckdb",
            ".duckdb",
            "duckdb.connect",
            "manifest_created = true",
            "data/raw",
            "data\\raw",
        ]:
            self.assertNotIn(token, source)
        self.assertIn("raw_k_path", source)
        self.assertIn("adjustment_events_path", source)


if __name__ == "__main__":
    unittest.main()
