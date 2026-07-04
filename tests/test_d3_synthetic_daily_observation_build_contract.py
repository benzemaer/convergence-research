from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/d3/synthetic_daily_observation_build_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/d3_synthetic_daily_observation_build_contract.schema.json"
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D3SyntheticDailyObservationBuildContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json(CONTRACT_PATH)
        cls.schema = load_json(SCHEMA_PATH)
        cls.readme = README_PATH.read_text(encoding="utf-8")

    def test_contract_schema_passes(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema).validate(self.contract)

    def test_contract_binds_prior_d3_contracts(self) -> None:
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
            self.contract["quality_readiness_contract"],
            "D3_QUALITY_READINESS_CONTRACT_V1",
        )

    def test_no_formal_generation_authorized(self) -> None:
        for key in [
            "formal_ingestion_authorized",
            "duckdb_write_authorized",
            "ddl_authorized",
            "real_data_materialization_authorized",
            "manifest_creation_authorized",
            "data_version_release_authorized",
            "pcvt_indicator_calculation_authorized",
            "r0_state_generation_authorized",
        ]:
            self.assertFalse(self.contract[key])
        self.assertTrue(self.contract["synthetic_test_only"])

    def test_synthetic_input_field_groups_are_complete(self) -> None:
        groups = self.contract["synthetic_input_field_groups"]
        self.assertGreaterEqual(
            set(groups),
            {
                "identity_fields",
                "component_ref_fields",
                "lineage_fields",
                "raw_trading_value_fields",
                "continuous_research_price_fields",
                "participation_value_fields",
                "trading_constraint_fields",
                "quality_status_fields",
                "pcvt_input_readiness_fields",
            },
        )
        self.assertGreaterEqual(
            set(groups["component_ref_fields"]),
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
        self.assertIn("daily_vwap", groups["raw_trading_value_fields"])
        self.assertIn("factor_as_of_time", groups["continuous_research_price_fields"])
        self.assertIn("quality_blocking_reasons", groups["quality_status_fields"])
        self.assertIn("pcvt_blocking_reasons", groups["pcvt_input_readiness_fields"])

    def test_build_output_sections_are_complete(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["build_output_sections"]),
            {
                "canonical_observation",
                "value_observation",
                "quality_readiness_summary",
                "lineage_validation_errors",
                "build_diagnostics",
            },
        )
        self.assertTrue(self.contract["canonical_output_policy"]["refs_only"])
        self.assertFalse(
            self.contract["canonical_output_policy"]["value_fields_allowed"]
        )
        self.assertTrue(
            self.contract["value_output_policy"]["canonical_observation_ref_required"]
        )

    def test_prohibited_fields_cover_research_outcome_and_payload_fields(self) -> None:
        self.assertGreaterEqual(
            set(self.contract["prohibited_fields"]),
            {
                "pcvt_value",
                "pcvt_state",
                "future_return",
                "label",
                "backtest_signal",
                "portfolio_return",
                "vendor_payload",
                "raw_vendor_payload",
                "raw_rows",
                "qfq_rows",
                "hfq_rows",
            },
        )

    def test_forbidden_path_policy_is_explicit(self) -> None:
        policy = self.contract["forbidden_path_policy"]
        self.assertTrue(policy["reject_payload_path_before_open"])
        self.assertTrue(policy["reject_payload_content_paths"])
        self.assertGreaterEqual(
            set(policy["forbidden_patterns"]),
            {"data/raw", "data/external", "marketdb", ".day", ".duckdb"},
        )

    def test_readme_advances_to_d3_t05_and_preserves_stage_boundaries(self) -> None:
        self.assertIn("current_stage: D3", self.readme)
        self.assertIn("current_task: D3-T05", self.readme)
        self.assertIn("next_planned_task: D3-T06", self.readme)
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
            "D3-T04` 基础质量指标与 PCVT input readiness 契约：completed via PR #38",
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
