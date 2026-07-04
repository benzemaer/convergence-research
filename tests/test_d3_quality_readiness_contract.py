from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d3/quality_readiness_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d3_quality_readiness_contract.schema.json"
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D3QualityReadinessContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)
        cls.schema = load_json(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)
        cls.readme = README_PATH.read_text(encoding="utf-8")

    def test_contract_schema_passes(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.contract)

    def test_contract_binds_prior_d3_and_d2_dependencies(self) -> None:
        self.assertEqual(
            self.contract["canonical_ref_table"], "d3.daily_market_observations"
        )
        self.assertEqual(
            self.contract["value_layer_object"], "d3.daily_market_observation_values"
        )
        self.assertEqual(
            self.contract["component_lineage_contract"],
            "D3_COMPONENT_LINEAGE_NO_BYPASS_CONTRACT_V1",
        )
        self.assertEqual(
            self.contract["pcvt_dependency_source_contract"],
            "D2_MARKET_QUALITY_PCVT_DEPENDENCY_CONTRACT_V1",
        )

    def test_no_formal_generation_or_research_calculation_authorized(self) -> None:
        for key in [
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "ddl_authorized",
            "real_data_materialization_authorized",
            "data_version_release_authorized",
            "pcvt_indicator_calculation_authorized",
            "r0_state_generation_authorized",
        ]:
            self.assertFalse(self.contract[key])
        self.assertTrue(self.contract["synthetic_test_only"])

    def test_quality_domains_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["quality_domains"]),
            {
                "raw_ohlcv_integrity",
                "continuous_ohlc_integrity",
                "raw_vs_continuous_reconciliation",
                "amount_volume_unit_validation",
                "daily_vwap_range_validation",
                "trading_constraint_diagnostics",
                "mechanical_gap_attribution",
                "window_validity",
                "pcvt_input_readiness",
            },
        )

    def test_quality_summary_fields_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["quality_summary_fields"]),
            {
                "raw_ohlcv_integrity_status",
                "continuous_ohlc_integrity_status",
                "raw_vs_continuous_reconciliation_status",
                "amount_volume_unit_status",
                "daily_vwap_range_status",
                "trading_constraint_status",
                "mechanical_gap_attribution",
                "window_validity_status",
                "quality_severity_max",
                "quality_blocking_flag",
                "quality_blocking_reasons",
            },
        )

    def test_raw_ohlcv_rules_cover_price_order_units_and_unknown_policy(self) -> None:
        rules = "\n".join(self.contract["raw_ohlcv_quality_rules"])
        for phrase in [
            "raw_high >= max",
            "raw_low <= min",
            "volume >= 0",
            "amount >= 0",
            "unknown to normal",
            "unknown to none",
            "suspended rows",
            "zero_volume rows",
        ]:
            self.assertIn(phrase, rules)

    def test_continuous_price_rules_cover_factor_revision_and_vendor_boundaries(
        self,
    ) -> None:
        rules = "\n".join(self.contract["continuous_price_quality_rules"])
        for phrase in [
            "must be positive",
            "factor_as_of_time must be present",
            "adjustment_revision must be present",
            "unverified revision semantics",
            "qfq/hfq vendor rows",
            "implied factors",
        ]:
            self.assertIn(phrase, rules)

    def test_reconciliation_rules_cover_identity_multiplicative_reverse_and_gap(
        self,
    ) -> None:
        section = self.contract["raw_vs_continuous_reconciliation_rules"]
        rules = "\n".join(section["rules"])
        for phrase in [
            "identity_no_adjustment",
            "multiplicative_adjustment",
            "reverse_check",
            "mechanical_gap_attribution",
            "unknown corporate action evidence",
        ]:
            self.assertIn(phrase, rules)
        self.assertIn("price_reconciliation_abs_tolerance", section)
        self.assertIn("price_reconciliation_rel_tolerance", section)

    def test_amount_volume_and_daily_vwap_readiness(self) -> None:
        section = self.contract["amount_volume_daily_vwap_readiness"]
        self.assertGreaterEqual(
            set(section["amount_unit_allowed_values"]),
            {"yuan", "thousand_yuan", "ten_thousand_yuan", "unknown"},
        )
        self.assertGreaterEqual(
            set(section["volume_unit_allowed_values"]), {"share", "lot", "unknown"}
        )
        rules = "\n".join(section["rules"])
        self.assertIn("unknown amount_unit or volume_unit blocks", rules)
        self.assertIn("daily_vwap = amount_yuan / volume_shares", rules)
        self.assertIn("within raw_low/raw_high", rules)
        self.assertFalse(section["daily_vwap_calculated_by_this_pr"])

    def test_trading_constraint_and_mechanical_gap_vocabularies_are_complete(
        self,
    ) -> None:
        self.assertGreaterEqual(
            set(self.contract["trading_constraint_vocabulary"]),
            {
                "normal_trading",
                "suspended",
                "zero_volume",
                "limit_up",
                "limit_down",
                "one_price_limit_up",
                "one_price_limit_down",
                "reopen_after_suspension",
                "unknown",
            },
        )
        self.assertGreaterEqual(
            set(self.contract["mechanical_gap_vocabulary"]),
            {
                "none",
                "market_gap",
                "corporate_action_mechanical_gap",
                "suspension_reopen_gap",
                "limit_constraint_gap",
                "code_mapping_gap",
                "unknown",
                "diagnostic_required",
            },
        )

    def test_window_validity_policy_covers_required_cases(self) -> None:
        policy = self.contract["window_validity_policy"]
        self.assertGreaterEqual(
            set(policy["fields"]),
            {
                "valid_observation_for_price_window",
                "valid_observation_for_participation_window",
                "valid_observation_for_trend_window",
                "valid_observation_for_vwap_window",
                "window_blocking_reasons",
            },
        )
        rules = "\n".join(policy["rules"])
        for phrase in [
            "suspended rows",
            "zero_volume rows",
            "nonpositive price",
            "missing previous close",
            "window_not_full",
            "unknown trading constraint",
        ]:
            self.assertIn(phrase, rules)

    def test_pcvt_input_readiness_matrix_contains_eight_indicators(self) -> None:
        matrix = self.contract["pcvt_input_readiness_matrix"]
        self.assertEqual(
            {entry["indicator_id"] for entry in matrix},
            {
                "P1_NATR14",
                "P2_LogRange20",
                "C1_LogMASpread_5_60",
                "C2_AdjVWAPSpread_5_60",
                "T1_ER20",
                "T2_AbsTrendT20",
                "V1_VolShrink20_60",
                "V2_AmountLevel20Pct",
            },
        )
        self.assertEqual(len(matrix), 8)

    def test_pcvt_readiness_entries_are_not_values_scores_or_states(self) -> None:
        forbidden = {"pcvt_value", "pcvt_score", "state"}
        for entry in self.contract["pcvt_input_readiness_matrix"]:
            self.assertTrue(forbidden.isdisjoint(entry))
        policy = self.contract["pcvt_readiness_policy"]
        self.assertTrue(policy["readiness_fields_are_not_pcvt_values"])
        self.assertTrue(policy["readiness_fields_are_not_pcvt_scores"])
        self.assertTrue(policy["readiness_fields_are_not_state_labels"])
        self.assertTrue(policy["d3_t04_does_not_define_q"])
        self.assertTrue(policy["d3_t04_does_not_define_thresholds"])
        self.assertTrue(policy["d3_t04_does_not_define_state_machine"])

    def test_prohibited_fields_cover_outcome_payload_and_pcvt_state(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["prohibited_fields"]),
            {
                "future_return",
                "label",
                "backtest_signal",
                "portfolio_return",
                "vendor_payload",
                "raw_vendor_payload",
                "raw_rows",
                "qfq_rows",
                "hfq_rows",
                "pcvt_value",
                "pcvt_score",
                "pcvt_state",
                "state",
            },
        )

    def test_readme_advances_to_d3_t04_and_preserves_stage_boundaries(self) -> None:
        self.assertIn("current_stage: D3", self.readme)
        self.assertIn("current_task: D3-T04", self.readme)
        self.assertIn("next_planned_task: D3-T05", self.readme)
        self.assertIn("completed via PR #35", self.readme)
        self.assertIn("completed via PR #36", self.readme)
        self.assertIn("completed via PR #37", self.readme)
        self.assertIn("blocked pending D2 formal materialization", self.readme)
        self.assertIn("D3-T08` D3 阶段验收与 R0 交接契约：planned", self.readme)


if __name__ == "__main__":
    unittest.main()
