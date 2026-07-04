from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.build_d2_hithink_candidate_materialization_plan import (
    CandidateMaterializationPlanError,
    build_candidate_materialization_plan,
)

ROOT = Path(__file__).resolve().parents[1]
MATERIALIZATION_CONTRACT_PATH = (
    ROOT
    / "configs/d2/hithink_raw_market_prices_candidate_materialization_contract.v1.json"
)
SOURCE_REGISTRY_PATH = ROOT / "configs/d2/formal_source_registry_contract.v1.json"
PROBE_CONTRACT_PATH = ROOT / "configs/d2/hithink_raw_ohlcv_probe_contract.v1.json"
SCRIPT_PATH = ROOT / "scripts/build_d2_hithink_candidate_materialization_plan.py"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class BuildD2HiThinkCandidateMaterializationPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.materialization_contract = load_json(MATERIALIZATION_CONTRACT_PATH)
        self.source_registry = load_json(SOURCE_REGISTRY_PATH)
        self.probe_contract = load_json(PROBE_CONTRACT_PATH)
        self.probe_report = {
            "raw_k_schema_report": {
                "status": "passed",
                "row_count": 2,
                "columns": [
                    "thscode",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "vol",
                    "turnover_amount",
                ],
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
                "missing_semantic_fields": [],
            },
            "adjustment_event_schema_report": {
                "status": "warning",
                "resolved_fields": {},
                "missing_semantic_fields": ["factor_as_of_time"],
            },
            "coverage_report": {
                "status": "passed",
                "row_count": 2,
                "security_count": 2,
                "trading_date_min": "2026-07-01",
                "trading_date_max": "2026-07-02",
            },
            "unit_inference_report": {
                "status": "warning",
                "amount_present": True,
                "volume_present": True,
                "amount_source_column": "turnover_amount",
                "volume_source_column": "vol",
            },
            "missing_field_report": {"status": "passed", "missing_fields": []},
            "fallback_readiness_report": {
                "status": "passed",
                "fallback_sources": [
                    {"source_id": "baostock", "priority": 1},
                    {"source_id": "tushare", "priority": 2},
                ],
            },
            "probe_diagnostics": {
                "default_scan_data_raw": False,
                "duckdb_written": False,
                "manifest_created": False,
                "data_version_published": False,
                "raw_rows_emitted": False,
            },
        }

    def _build(self) -> dict[str, object]:
        return build_candidate_materialization_plan(
            probe_report=self.probe_report,
            materialization_contract=self.materialization_contract,
            source_registry=self.source_registry,
            probe_contract=self.probe_contract,
        )

    def test_builds_candidate_plan_without_formal_materialization(self) -> None:
        plan = self._build()
        self.assertEqual(plan["contract_readiness_report"]["status"], "blocked")
        self.assertFalse(
            plan["contract_readiness_report"]["real_data_materialization_authorized"]
        )
        self.assertEqual(
            plan["raw_field_mapping_report"]["resolved_price_fields"]["raw_close"],
            "close",
        )
        self.assertEqual(
            plan["raw_field_mapping_report"]["resolved_price_fields"]["amount"],
            "turnover_amount",
        )
        diagnostics = plan["candidate_plan_diagnostics"]
        self.assertFalse(diagnostics["duckdb_written"])
        self.assertFalse(diagnostics["manifest_created"])
        self.assertFalse(diagnostics["row_level_prices_emitted"])
        self.assertNotIn("raw_rows", plan)

    def test_target_fields_stay_blocked_without_manifests_and_mapping(self) -> None:
        plan = self._build()
        field_status = {
            item["target_field"]: item
            for item in plan["target_field_readiness_report"]["field_status"]
        }
        self.assertEqual(
            field_status["raw_close"]["status"], "mapped_from_primary_candidate"
        )
        self.assertEqual(field_status["security_id"]["status"], "blocked")
        self.assertEqual(field_status["observed_at"]["status"], "blocked")
        self.assertEqual(field_status["source_snapshot_id"]["status"], "blocked")

    def test_missing_raw_field_enters_fallback_repair_probe_plan(self) -> None:
        changed = copy.deepcopy(self.probe_report)
        changed["raw_k_schema_report"]["status"] = "warning"
        changed["raw_k_schema_report"]["resolved_fields"].pop("raw_close")
        changed["raw_k_schema_report"]["missing_semantic_fields"] = ["raw_close"]
        changed["missing_field_report"]["status"] = "warning"
        changed["missing_field_report"]["missing_fields"] = [
            {"section": "raw_k", "semantic_field": "raw_close"}
        ]
        plan = build_candidate_materialization_plan(
            probe_report=changed,
            materialization_contract=self.materialization_contract,
            source_registry=self.source_registry,
            probe_contract=self.probe_contract,
        )
        self.assertIn(
            {"section": "raw_k", "semantic_field": "raw_close"},
            plan["fallback_repair_probe_plan"]["missing_semantic_fields_to_probe"],
        )
        self.assertIn(
            "primary_candidate_missing_required_semantic_fields",
            plan["blocking_report"]["active_blocking_conditions"],
        )

    def test_authorization_or_active_a_stock_data_fails(self) -> None:
        changed_contract = copy.deepcopy(self.materialization_contract)
        changed_contract["duckdb_write_authorized"] = True
        with self.assertRaises(CandidateMaterializationPlanError):
            build_candidate_materialization_plan(
                self.probe_report,
                changed_contract,
                self.source_registry,
                self.probe_contract,
            )

        changed_registry = copy.deepcopy(self.source_registry)
        changed_registry["source_hierarchy"]["fallback_sources"][0]["source_id"] = (
            "a-stock-data"
        )
        with self.assertRaises(CandidateMaterializationPlanError):
            build_candidate_materialization_plan(
                self.probe_report,
                self.materialization_contract,
                changed_registry,
                self.probe_contract,
            )

    def test_probe_report_with_raw_rows_or_manifest_fails(self) -> None:
        changed = copy.deepcopy(self.probe_report)
        changed["probe_diagnostics"]["raw_rows_emitted"] = True
        with self.assertRaises(CandidateMaterializationPlanError):
            build_candidate_materialization_plan(
                changed,
                self.materialization_contract,
                self.source_registry,
                self.probe_contract,
            )

        changed = copy.deepcopy(self.probe_report)
        changed["probe_diagnostics"]["manifest_created"] = True
        with self.assertRaises(CandidateMaterializationPlanError):
            build_candidate_materialization_plan(
                changed,
                self.materialization_contract,
                self.source_registry,
                self.probe_contract,
            )

        changed = copy.deepcopy(self.probe_report)
        changed["probe_diagnostics"]["data_version_published"] = True
        with self.assertRaises(CandidateMaterializationPlanError):
            build_candidate_materialization_plan(
                changed,
                self.materialization_contract,
                self.source_registry,
                self.probe_contract,
            )

        changed = copy.deepcopy(self.probe_report)
        changed["probe_diagnostics"]["default_scan_data_raw"] = True
        with self.assertRaises(CandidateMaterializationPlanError):
            build_candidate_materialization_plan(
                changed,
                self.materialization_contract,
                self.source_registry,
                self.probe_contract,
            )

    def test_probe_report_with_prohibited_nested_payload_fields_fails(self) -> None:
        for field in [
            "raw_rows",
            "vendor_payload",
            "qfq_rows",
            "future_return",
            "row_level_prices",
            "raw_vendor_payload",
            "hfq_rows",
            "label",
            "pcvt_value",
            "backtest_signal",
            "portfolio_return",
        ]:
            changed = copy.deepcopy(self.probe_report)
            changed["nested"] = {"payload": [{field: []}]}
            with self.subTest(field=field):
                with self.assertRaises(CandidateMaterializationPlanError):
                    build_candidate_materialization_plan(
                        changed,
                        self.materialization_contract,
                        self.source_registry,
                        self.probe_contract,
                    )

    def test_adjustment_event_missing_fields_are_deferred_not_raw_fallback(
        self,
    ) -> None:
        changed = copy.deepcopy(self.probe_report)
        changed["missing_field_report"]["status"] = "warning"
        changed["missing_field_report"]["missing_fields"] = [
            {"section": "adjustment_events", "semantic_field": "factor_as_of_time"},
            {"section": "adjustment_events", "semantic_field": "adjustment_revision"},
        ]
        plan = build_candidate_materialization_plan(
            probe_report=changed,
            materialization_contract=self.materialization_contract,
            source_registry=self.source_registry,
            probe_contract=self.probe_contract,
        )
        self.assertEqual(
            plan["fallback_repair_probe_plan"]["missing_semantic_fields_to_probe"],
            [],
        )
        self.assertEqual(
            {
                item["semantic_field"]
                for item in plan["adjustment_event_readiness_report"][
                    "missing_semantic_fields"
                ]
            },
            {"factor_as_of_time", "adjustment_revision"},
        )
        self.assertIn(
            "adjustment_event_readiness_deferred_to_d2_t10",
            plan["blocking_report"]["active_blocking_conditions"],
        )

    def test_cli_reads_explicit_probe_report_and_outputs_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            probe_report_path = Path(tmpdir) / "probe_report.json"
            probe_report_path.write_text(
                json.dumps(self.probe_report), encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--probe-report",
                    str(probe_report_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fallback_repair_probe_plan", result.stdout)
        self.assertNotIn('"raw_rows":', result.stdout)

    def test_cli_forbidden_probe_report_path_fails_before_opening(self) -> None:
        forbidden_paths = [
            ROOT / "data/raw/missing_probe_report.json",
            ROOT / "data/external/missing_probe_report.json",
            ROOT / "MarketDB/missing_probe_report.json",
            ROOT / "synthetic_probe_report.parquet",
            ROOT / "synthetic_probe_report.duckdb",
            ROOT / "SH000001.day",
        ]
        for path in forbidden_paths:
            with self.subTest(path=path):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT_PATH),
                        "--probe-report",
                        str(path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("forbidden", result.stderr.lower())
                self.assertNotIn("no such file", result.stderr.lower())

    def test_script_does_not_scan_data_raw_or_use_forbidden_storage(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8").lower()
        for token in [
            "import duckdb",
            "duckdb.connect",
            "glob(",
            "requests.",
        ]:
            self.assertNotIn(token, source)
        self.assertIn("prohibited_probe_report_path_tokens", source)


if __name__ == "__main__":
    unittest.main()
