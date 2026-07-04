from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d3/component_lineage_no_bypass_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d3_component_lineage_no_bypass_contract.schema.json"
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D3ComponentLineageNoBypassContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)
        cls.schema = load_json(SCHEMA_PATH)
        cls.validator = Draft202012Validator(cls.schema)
        cls.readme = README_PATH.read_text(encoding="utf-8")

    def test_contract_schema_passes(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validator.validate(self.contract)

    def test_contract_binds_d3_t01_and_d3_t02_layers(self) -> None:
        self.assertEqual(
            self.contract["canonical_ref_table"], "d3.daily_market_observations"
        )
        self.assertEqual(
            self.contract["value_layer_object"], "d3.daily_market_observation_values"
        )
        self.assertEqual(
            self.contract["canonical_ref_contract"],
            "D3_DAILY_MARKET_OBSERVATIONS_CONTRACT_V1",
        )
        self.assertEqual(
            self.contract["value_layer_contract"],
            "D3_DAILY_MARKET_OBSERVATION_VALUES_CONTRACT_V1",
        )

    def test_no_formal_generation_or_storage_authorized(self) -> None:
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

    def test_component_refs_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["component_refs"]),
            {
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
            },
        )

    def test_lineage_inheritance_fields_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["lineage_inheritance_fields"]),
            {
                "data_version",
                "universe_id",
                "time_segment_id",
                "security_id",
                "trading_date",
                "observation_revision",
                "canonical_observation_ref",
                "observed_at",
                "observed_at_rule",
                "revision_policy",
                "history_revision_class",
                "research_use_tier",
                "source_registry_id",
                "source_snapshot_id",
                "run_id",
                "source_snapshot_ref",
                "run_ref",
            },
        )

    def test_no_bypass_policy_blocks_d1_d2_direct_reads(self) -> None:
        policy = self.contract["no_bypass_policy"]
        self.assertIn("d3.daily_market_observations", policy["allowed_r0_sources"])
        self.assertIn(
            "d3.daily_market_observation_values", policy["allowed_r0_sources"]
        )
        self.assertGreaterEqual(
            set(policy["prohibited_r0_sources"]),
            {
                "d1.raw_market_prices",
                "d1.corporate_actions",
                "d1.trading_constraints",
                "d2.adjusted_market_prices",
                "d2.market_price_quality_flags",
                "d2.membership_alignment",
                "D1/D2 raw component tables directly",
                "vendor payloads",
                "raw/qfq/hfq row payloads",
            },
        )
        self.assertTrue(policy["d1_d2_direct_read_prohibited"])

    def test_prohibited_fields_cover_research_outcome_payload_and_pcvt_state(
        self,
    ) -> None:
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
                "pcvt_state",
                "state_machine_version",
            },
        )

    def test_validator_behavior_is_synthetic_only(self) -> None:
        behavior = self.contract["validator_behavior"]
        self.assertTrue(behavior["accept_synthetic_payload_only"])
        self.assertFalse(behavior["real_data_read_authorized"])
        self.assertFalse(behavior["duckdb_connection_authorized"])
        self.assertFalse(behavior["external_api_call_authorized"])
        self.assertFalse(behavior["manifest_creation_authorized"])

    def test_readme_advances_to_d3_t03_and_preserves_later_blocks(self) -> None:
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
            "D3-T03` 组件引用、source lineage 与 no-bypass 校验器："
            "completed via PR #37",
            self.readme,
        )
        self.assertIn(
            "D3-T07` 标准日频观测表正式生成与 candidate data_version 发布："
            "blocked pending D2 formal materialization",
            self.readme,
        )
        self.assertIn("D3-T08` D3 阶段验收与 R0 交接契约：planned", self.readme)


if __name__ == "__main__":
    unittest.main()
