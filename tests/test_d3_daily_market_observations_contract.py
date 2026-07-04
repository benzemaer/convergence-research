from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d3/daily_market_observations_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d3_daily_market_observations_contract.schema.json"
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D3DailyMarketObservationsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)
        cls.schema = load_json(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)
        cls.readme = README_PATH.read_text(encoding="utf-8")

    def test_contract_schema_passes(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.contract)

    def test_contract_is_refs_only_canonical_entry(self) -> None:
        self.assertEqual(self.contract["target_table"], "d3.daily_market_observations")
        self.assertEqual(self.contract["canonical_table_mode"], "refs_only")
        self.assertFalse(self.contract["value_view_or_table_defined_by_this_pr"])
        self.assertFalse(
            self.contract["no_bypass_policy"][
                "value_fields_available_to_r0_in_this_contract"
            ]
        )

    def test_no_formal_or_research_generation_is_authorized(self) -> None:
        for key in [
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "real_data_materialization_authorized",
            "data_version_release_authorized",
            "pcvt_indicator_calculation_authorized",
            "r0_state_generation_authorized",
        ]:
            self.assertFalse(self.contract[key])
        self.assertTrue(self.contract["synthetic_test_only"])

    def test_required_fields_cover_d0_and_d2_t08_component_refs(self) -> None:
        required_fields = set(self.contract["required_fields"])
        component_refs = set(self.contract["component_refs"])
        expected_refs = {
            "raw_price_ref",
            "adjusted_price_ref",
            "trading_constraint_ref",
            "market_price_quality_ref",
            "mechanical_gap_ref",
            "pcvt_input_readiness_ref",
            "membership_ref",
            "calendar_ref",
            "source_snapshot_ref",
            "run_ref",
        }
        self.assertGreaterEqual(required_fields, expected_refs)
        self.assertGreaterEqual(component_refs, expected_refs)
        self.assertGreaterEqual(
            required_fields,
            {
                "data_version",
                "universe_id",
                "time_segment_id",
                "security_id",
                "trading_date",
                "observed_at",
                "revision_policy",
                "observed_at_rule",
                "history_revision_class",
                "research_use_tier",
                "source_registry_id",
                "source_snapshot_id",
                "run_id",
            },
        )

    def test_prohibited_fields_cover_future_labels_backtest_portfolio_payloads(
        self,
    ) -> None:
        prohibited = set(self.contract["prohibited_fields"])
        self.assertGreaterEqual(
            prohibited,
            {
                "future_return",
                "future_max_return",
                "label",
                "breakout_direction",
                "outcome",
                "target",
                "holding_period_return",
                "backtest_signal",
                "portfolio_return",
                "vendor_payload",
                "raw_vendor_payload",
            },
        )

    def test_raw_and_adjusted_ohlcv_values_are_not_in_refs_only_table(self) -> None:
        value_fields = {
            "raw_open",
            "raw_high",
            "raw_low",
            "raw_close",
            "adj_open",
            "adj_high",
            "adj_low",
            "adj_close",
            "volume",
            "amount",
            "turnover",
            "float_shares",
        }
        self.assertTrue(value_fields <= set(self.contract["prohibited_fields"]))
        self.assertTrue(value_fields.isdisjoint(set(self.contract["required_fields"])))

    def test_d3_t02_owns_value_view_or_table_contract(self) -> None:
        self.assertEqual(self.contract["future_value_view_or_table_task"], "D3-T02")
        self.assertFalse(self.contract["value_view_or_table_defined_by_this_pr"])

    def test_no_bypass_policy_is_enabled(self) -> None:
        policy = self.contract["no_bypass_policy"]
        self.assertTrue(policy["enabled"])
        self.assertTrue(policy["r0_must_read_d3_formal_entry_only"])
        self.assertTrue(policy["r0_must_not_read_d1_d2_directly"])
        self.assertIn("d3.daily_market_observations", policy["allowed_r0_entry_tables"])

    def test_readme_advances_to_d3_t02_and_keeps_d3_t01_completed(self) -> None:
        self.assertIn("current_stage: D3", self.readme)
        self.assertIn("current_task: D3-T03", self.readme)
        self.assertIn("next_planned_task: D3-T04", self.readme)
        self.assertIn(
            "D3-T01` `daily_market_observations` 语义与字段契约：completed via PR #35",
            self.readme,
        )
        self.assertIn(
            "D3-T07` 标准日频观测表正式生成与 candidate data_version 发布",
            self.readme,
        )
        self.assertIn("blocked pending D2 formal materialization", self.readme)
        self.assertIn("D3-T08` D3 阶段验收与 R0 交接契约", self.readme)

    def test_readme_preserves_d2_formal_blocking_semantics(self) -> None:
        self.assertIn(
            "formal ingestion and D1/D2/D3 materialization remain blocked",
            self.readme,
        )
        self.assertIn(
            "D3 contract work may proceed, but formal D3 generation remains blocked",
            self.readme,
        )

    def test_readme_does_not_mark_d3_generation_or_r0_unlocked(self) -> None:
        forbidden_phrases = [
            "D3 generation authorized",
            "D3 generation unlocked",
            "R0 unlocked",
            "R0：PCVT 候选观测量与候选状态定义\n\n状态：completed",
        ]
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, self.readme)
        self.assertIn("D3 generation", self.readme)
        self.assertIn("仍未授权", self.readme)
        self.assertIn("状态：blocked until D3 contract", self.readme)


if __name__ == "__main__":
    unittest.main()
