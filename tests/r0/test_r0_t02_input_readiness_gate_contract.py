from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r0/r0_t02_input_readiness_gate_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/r0/r0_t02_input_readiness_gate_contract.schema.json"

REQUIRED_REASONS = {
    "ready_no_blocker",
    "missing_required_field",
    "amount_unit_unknown",
    "volume_unit_unknown",
    "amount_volume_unit_status_fail",
    "daily_vwap_range_unknown",
    "daily_vwap_range_fail",
    "adjusted_vwap_policy_missing",
    "corporate_action_window_without_common_basis",
    "volume_comparability_policy_missing",
    "corporate_action_volume_comparability_policy_missing",
    "suspension_in_window",
    "zero_volume_in_window",
    "window_not_full",
    "listing_age_insufficient",
    "d3_lineage_missing",
    "direct_d1_d2_bypass_detected",
    "unknown_not_false_guard",
}
REQUIRED_PROHIBITED_OUTPUTS = {
    "pcvt_values",
    "pcvt_percentiles",
    "pcvt_scores",
    "pcvt_states",
    "future_labels",
    "future_returns",
    "backtest",
    "portfolio",
    "formal_data_version",
}


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class R0T02InputReadinessGateContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.config = load_json(CONFIG_PATH)

    def test_config_passes_schema_validation(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema, format_checker=FormatChecker()).validate(
            self.config
        )

    def test_readiness_status_vocabulary_is_complete(self) -> None:
        self.assertEqual(
            set(self.config["readiness_status_vocabulary"]),
            {"ready", "unknown", "diagnostic_required", "blocked", "not_applicable"},
        )

    def test_reason_code_vocabulary_is_complete(self) -> None:
        self.assertTrue(
            REQUIRED_REASONS.issubset(set(self.config["reason_code_vocabulary"]))
        )

    def test_c2_required_fields_include_core_inputs(self) -> None:
        required_fields = set(self.config["c2_gate"]["required_fields"])
        self.assertTrue(
            {
                "amount",
                "volume",
                "amount_unit",
                "volume_unit",
                "daily_vwap_range_status",
                "adjusted_vwap_policy",
            }.issubset(required_fields)
        )

    def test_v1_required_fields_include_core_inputs(self) -> None:
        required_fields = set(self.config["v1_gate"]["required_fields"])
        self.assertTrue(
            {
                "volume",
                "volume_unit",
                "trading_status",
                "corporate_action_flag",
                "suspension_flag",
            }.issubset(required_fields)
        )

    def test_prohibited_outputs_cover_all_required_non_goals(self) -> None:
        prohibited = set(self.config["prohibited_outputs"])
        self.assertTrue(REQUIRED_PROHIBITED_OUTPUTS.issubset(prohibited))


if __name__ == "__main__":
    unittest.main()
