from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d2/hithink_raw_ohlcv_probe_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d2_hithink_raw_ohlcv_probe_contract.schema.json"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2HiThinkRawOhlcvProbeContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)
        cls.schema = load_json(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def test_contract_json_passes_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.contract)
        self.assertFalse(self.schema["additionalProperties"])

    def test_expected_local_snapshot_patterns_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["expected_local_snapshot_patterns"]),
            {
                "data/raw/a_share_daily_k_1d_none_10y_*.parquet",
                "data/raw/a_share_adjustment_factors_event_none_all_*.parquet",
            },
        )

    def test_raw_and_adjustment_semantic_fields_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["raw_ohlcv_required_semantic_fields"]),
            {
                "security_code_or_thscode",
                "trading_date",
                "raw_open",
                "raw_high",
                "raw_low",
                "raw_close",
                "volume",
                "amount",
            },
        )
        self.assertGreaterEqual(
            set(self.contract["adjustment_event_expected_semantic_fields"]),
            {
                "security_code_or_thscode",
                "event_date",
                "ex_date",
                "record_date",
                "announcement_date",
                "cash_dividend",
                "share_bonus",
                "share_transfer",
                "rights_issue",
                "rights_price",
                "adjustment_factor",
                "factor_as_of_time",
                "adjustment_revision",
            },
        )

    def test_probe_output_sections_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["probe_output_sections"]),
            {
                "raw_k_schema_report",
                "adjustment_event_schema_report",
                "coverage_report",
                "unit_inference_report",
                "time_semantics_report",
                "missing_field_report",
                "fallback_readiness_report",
                "a_stock_data_removal_report",
                "probe_diagnostics",
            },
        )

    def test_stage_1_decisions_remain_blocked(self) -> None:
        decisions = self.contract["stage_1_release_decisions"]
        self.assertEqual(
            decisions["formal_source_acceptance_decision"],
            "formal_source_acceptance_blocked_pending_probe_review",
        )
        self.assertEqual(
            decisions["raw_materialization_decision"],
            "raw_materialization_not_authorized_in_stage_1",
        )
        self.assertEqual(decisions["d3_generation_decision"], "d3_generation_blocked")
        self.assertEqual(decisions["r0_handoff_decision"], "r0_handoff_blocked")

    def test_depends_on_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["depends_on"]),
            {
                "D2_ACCEPTANCE_D3_HANDOFF_CONTRACT_V1",
                "D2_MARKET_QUALITY_PCVT_DEPENDENCY_CONTRACT_V1",
                "D0_DATA_PRODUCT_CONTRACTS_V1",
                "D3_DATA_VERSION_QUALITY_MANIFEST_GATE_CONTRACT_V1",
            },
        )

    def test_schema_rejects_authorization_and_missing_pattern(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["formal_ingestion_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["expected_local_snapshot_patterns"] = changed[
            "expected_local_snapshot_patterns"
        ][:-1]
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)


if __name__ == "__main__":
    unittest.main()
