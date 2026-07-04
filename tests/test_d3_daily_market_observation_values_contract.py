from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d3/daily_market_observation_values_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d3_daily_market_observation_values_contract.schema.json"
CANONICAL_CONTRACT_PATH = ROOT / "configs/d3/daily_market_observations_contract.v1.json"
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D3DailyMarketObservationValuesContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)
        cls.schema = load_json(SCHEMA_PATH)
        cls.canonical_contract = load_json(CANONICAL_CONTRACT_PATH)
        cls.validator = Draft202012Validator(cls.schema)
        cls.readme = README_PATH.read_text(encoding="utf-8")

    def test_contract_schema_passes(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.contract)

    def test_contract_binds_canonical_refs_table(self) -> None:
        self.assertEqual(
            self.contract["canonical_ref_table"],
            self.canonical_contract["target_table"],
        )
        self.assertEqual(
            self.contract["canonical_ref_contract"],
            self.canonical_contract["contract_id"],
        )
        self.assertEqual(
            self.contract["target_object"], "d3.daily_market_observation_values"
        )

    def test_no_formal_ddl_or_research_generation_is_authorized(self) -> None:
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

    def test_primary_key_aligns_with_d3_t01_canonical_table(self) -> None:
        self.assertEqual(
            set(self.contract["primary_key"]),
            set(self.canonical_contract["primary_key"]),
        )
        self.assertEqual(
            set(self.contract["grain"]["fields"]),
            set(self.canonical_contract["grain"]["fields"]),
        )

    def test_value_fields_include_r0_bottom_layer_inputs(self) -> None:
        groups = self.contract["value_field_groups"]
        self.assertGreaterEqual(
            set(groups["raw_trading_value_fields"]),
            {
                "raw_open",
                "raw_high",
                "raw_low",
                "raw_close",
                "volume",
                "amount",
                "daily_vwap",
            },
        )
        self.assertGreaterEqual(
            set(groups["continuous_research_price_fields"]),
            {"adj_open", "adj_high", "adj_low", "adj_close", "factor_as_of_time"},
        )
        self.assertGreaterEqual(
            set(groups["participation_value_fields"]),
            {"volume", "amount", "amount_unit", "volume_unit"},
        )

    def test_daily_vwap_is_derived_and_readiness_gated(self) -> None:
        daily_vwap = self.contract["derived_candidate_fields"]["daily_vwap"]
        self.assertEqual(daily_vwap["formula"], "amount_yuan / volume_shares")
        self.assertFalse(daily_vwap["calculated_by_this_pr"])
        self.assertGreaterEqual(
            set(daily_vwap["formal_readiness_requires"]),
            {"amount_volume_unit_status_valid", "daily_vwap_range_status_valid"},
        )

    def test_pcvt_input_readiness_fields_exist_but_are_not_pcvt_values(self) -> None:
        readiness_fields = set(
            self.contract["value_field_groups"]["pcvt_input_readiness_fields"]
        )
        self.assertGreaterEqual(
            readiness_fields,
            {
                "pcvt_input_readiness_status",
                "p_layer_input_ready",
                "c_layer_input_ready",
                "t_layer_input_ready",
                "v_layer_input_ready",
                "pcvt_blocking_reasons",
            },
        )
        semantics = self.contract["pcvt_readiness_semantics"]
        self.assertTrue(semantics["readiness_fields_are_pcvt_inputs_only"])
        self.assertTrue(semantics["not_pcvt_values"])
        self.assertTrue(semantics["not_pcvt_score"])
        self.assertTrue(semantics["not_state_machine_result"])

    def test_pcvt_future_label_backtest_portfolio_payload_fields_are_prohibited(
        self,
    ) -> None:
        prohibited = set(self.contract["prohibited_fields"])
        self.assertGreaterEqual(
            prohibited,
            {
                "pcvt_value",
                "pcvt_score",
                "pcvt_state",
                "state",
                "q_threshold",
                "future_return",
                "label",
                "breakout_direction",
                "backtest_signal",
                "portfolio_return",
                "vendor_payload",
                "raw_vendor_payload",
            },
        )

    def test_r0_source_policy_allows_d3_and_blocks_d1_d2_direct_tables(self) -> None:
        policy = self.contract["r0_source_policy"]
        self.assertTrue(policy["future_policy_only_r0_currently_blocked"])
        self.assertIn("d3.daily_market_observations", policy["allowed_sources"])
        self.assertIn("d3.daily_market_observation_values", policy["allowed_sources"])
        self.assertGreaterEqual(
            set(policy["prohibited_direct_sources"]),
            {
                "d1.raw_market_prices",
                "d2.adjusted_market_prices",
                "d2.market_price_quality_flags",
                "d2.membership_alignment",
                "D1/D2 raw component tables directly",
            },
        )
        self.assertTrue(policy["d1_d2_direct_read_prohibited"])

    def test_readme_advances_to_d3_t02_and_preserves_later_blocks(self) -> None:
        self.assertIn("current_stage: D3", self.readme)
        self.assertIn("current_task: D3-T04", self.readme)
        self.assertIn("next_planned_task: D3-T05", self.readme)
        self.assertIn(
            "D3-T01` `daily_market_observations` 语义与字段契约：completed via PR #35",
            self.readme,
        )
        self.assertIn(
            "D3-T02` D3 标准数值观测 view/table 契约：completed via PR #36",
            self.readme,
        )
        self.assertIn(
            "D3-T07` 标准日频观测表正式生成与 candidate data_version 发布："
            "blocked pending D2 formal materialization",
            self.readme,
        )
        self.assertIn("D3-T08` D3 阶段验收与 R0 交接契约：planned", self.readme)
        self.assertIn(
            "状态：blocked until D3 contract and later D3 data_version gates "
            "are accepted",
            self.readme,
        )

    def test_turnover_and_float_shares_are_future_or_blocked_not_current_required(
        self,
    ) -> None:
        all_current_group_fields = set()
        for fields in self.contract["value_field_groups"].values():
            all_current_group_fields.update(fields)
        self.assertNotIn("turnover", all_current_group_fields)
        self.assertNotIn("float_shares", all_current_group_fields)
        self.assertIn("turnover", self.contract["future_or_blocked_fields"])
        self.assertIn("float_shares", self.contract["future_or_blocked_fields"])
        self.assertEqual(
            self.contract["future_or_blocked_fields"]["turnover"],
            "blocked_pending_source_contract",
        )
        self.assertEqual(
            self.contract["future_or_blocked_fields"]["float_shares"],
            "blocked_pending_source_contract",
        )


if __name__ == "__main__":
    unittest.main()
