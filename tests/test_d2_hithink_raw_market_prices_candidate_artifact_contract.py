from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT / "configs/d2/hithink_raw_market_prices_candidate_artifact_contract.v1.json"
)
SCHEMA_PATH = (
    ROOT
    / "schemas/d2_hithink_raw_market_prices_candidate_artifact_contract.schema.json"
)


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D2HiThinkRawMarketPricesCandidateArtifactContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)
        cls.schema = load_json(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def test_contract_json_passes_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.contract)
        self.assertFalse(self.schema["additionalProperties"])

    def test_stage_target_and_authorizations_are_exact(self) -> None:
        self.assertEqual(self.contract["stage"], "stage_3")
        self.assertEqual(self.contract["target_table"], "d1.raw_market_prices")
        self.assertEqual(self.contract["primary_source"], "hithink_financial_api")
        self.assertTrue(self.contract["local_candidate_artifact_write_authorized"])
        for key in [
            "formal_source_acceptance_authorized",
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "real_data_materialization_authorized",
            "manifest_creation_authorized",
            "data_version_release_authorized",
            "d3_generation_authorized",
            "r0_state_generation_authorized",
        ]:
            self.assertFalse(self.contract[key])

    def test_candidate_row_schema_has_exact_17_fields(self) -> None:
        self.assertEqual(
            set(self.contract["candidate_row_schema"]),
            {
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
            },
        )
        self.assertEqual(len(self.contract["candidate_row_schema"]), 17)

    def test_prohibited_fields_quality_fields_blocking_rules_and_depends_on(
        self,
    ) -> None:
        self.assertGreaterEqual(
            set(self.contract["prohibited_row_fields"]),
            {
                "source_symbol",
                "thscode",
                "vendor_payload",
                "raw_rows",
                "qfq_rows",
                "hfq_rows",
                "future_return",
                "label",
                "pcvt_value",
                "backtest_signal",
                "portfolio_return",
            },
        )
        self.assertGreaterEqual(
            set(self.contract["quality_summary_fields"]),
            {
                "row_count_input",
                "row_count_output",
                "dropped_unmapped_security_count",
                "security_count_output",
                "trading_date_min",
                "trading_date_max",
                "null_ohlc_count",
                "nonpositive_ohlc_count",
                "ohlc_order_violation_count",
                "null_volume_count",
                "null_amount_count",
                "negative_volume_count",
                "negative_amount_count",
                "unknown_trading_status_count",
                "unknown_price_limit_status_count",
                "duplicate_key_count",
                "candidate_blocking_flag",
                "candidate_blocking_reasons",
            },
        )
        self.assertIn(
            "duplicate_key_blocks_candidate_acceptance",
            self.contract["blocking_rules"],
        )
        self.assertIn(
            "null_volume_blocks_candidate_acceptance",
            self.contract["blocking_rules"],
        )
        self.assertIn(
            "null_amount_blocks_candidate_acceptance",
            self.contract["blocking_rules"],
        )
        self.assertGreaterEqual(
            set(self.contract["depends_on"]),
            {
                "D2_FORMAL_SOURCE_REGISTRY_CONTRACT_V1",
                "D2_HITHINK_RAW_OHLCV_PROBE_CONTRACT_V1",
                "D2_HITHINK_RAW_MARKET_PRICES_CANDIDATE_MATERIALIZATION_CONTRACT_V1",
                "D2_ACCEPTANCE_D3_HANDOFF_CONTRACT_V1",
                "D3_DATA_VERSION_QUALITY_MANIFEST_GATE_CONTRACT_V1",
            },
        )

    def test_schema_rejects_missing_row_field_or_enabled_formal_gate(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["candidate_row_schema"].remove("observed_at")
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)

        changed = copy.deepcopy(self.contract)
        changed["formal_ingestion_authorized"] = True
        with self.assertRaises(ValidationError):
            self.validator.validate(changed)


if __name__ == "__main__":
    unittest.main()
