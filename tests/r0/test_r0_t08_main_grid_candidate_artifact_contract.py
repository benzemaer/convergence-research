from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r0/r0_t08_main_grid_candidate_artifact_contract.v1.json"
SCHEMA_PATH = (
    ROOT / "schemas/r0/r0_t08_main_grid_candidate_artifact_contract.schema.json"
)
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class R0T08MainGridCandidateArtifactContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.config = load_json(CONFIG_PATH)

    def test_config_passes_schema_validation(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema, format_checker=FormatChecker()).validate(
            self.config
        )

    def test_contract_authorizes_only_synthetic_artifact_assembly(self) -> None:
        self.assertTrue(self.config["candidate_config_generation_authorized"])
        self.assertTrue(self.config["candidate_daily_state_assembly_authorized"])
        self.assertTrue(self.config["confirmed_interval_assembly_authorized"])
        self.assertTrue(self.config["manifest_generation_authorized"])
        for key in (
            "real_data_read_authorized",
            "provider_call_authorized",
            "duckdb_read_authorized",
            "duckdb_write_authorized",
            "formal_data_version_authorized",
            "generated_artifact_commit_authorized",
            "future_label_generation_authorized",
            "returns_generation_authorized",
            "backtest_generation_authorized",
            "portfolio_generation_authorized",
            "release_event_generation_authorized",
            "gap_merge_generated_by_this_task",
            "cooldown_generated_by_this_task",
            "raw_metric_recalculation_authorized",
            "score_recalculation_authorized",
            "raw_daily_state_recalculation_authorized",
            "confirmation_recalculation_authorized",
        ):
            self.assertFalse(self.config[key])

    def test_grid_and_baseline_are_fixed(self) -> None:
        self.assertEqual(self.config["percentile_window_W_values"], [120, 250, 500])
        self.assertEqual(self.config["low_quantile_q_values"], [0.10, 0.20, 0.30])
        self.assertEqual(self.config["confirmation_days_K_values"], [2, 3, 5])
        self.assertNotIn(1, self.config["confirmation_days_K_values"])
        self.assertEqual(self.config["baseline_percentile_window_W"], 250)
        self.assertEqual(self.config["baseline_low_quantile_q"], 0.20)
        self.assertEqual(self.config["baseline_confirmation_days_K"], 3)
        self.assertEqual(self.config["dimension_rule"], "weak")
        self.assertEqual(self.config["weak_delta"], 0.10)
        self.assertEqual(self.config["main_grid_config_count"], 27)
        self.assertTrue(self.config["K1_confirmation_forbidden"])
        self.assertTrue(self.config["raw_daily_state_reference_from_R0_T06"])

    def test_active_v1_turnover_fields_and_legacy_forbidden_names_are_fixed(
        self,
    ) -> None:
        self.assertEqual(self.config["active_v1_raw_field"], "TurnoverShrink20_60_raw")
        self.assertEqual(
            self.config["active_v1_indicator_id"], "V1_TurnoverShrink20_60"
        )
        self.assertEqual(
            self.config["legacy_v1_field_names_forbidden"],
            [
                "VolShrink20_60_raw",
                "V1_VolShrink20_60",
                "VolShrink20_60",
                "volume_shrink_20_60",
            ],
        )

    def test_dependencies_lineage_and_forbidden_outputs_are_declared(self) -> None:
        for dependency in (
            "R0_T04_RAW_METRIC_ENGINE_CONTRACT_V1",
            "R0_T05_STRICT_PAST_PERCENTILE_SCORE_CONTRACT_V1",
            "R0_T06_WEAK_DIMENSION_NESTED_STATE_CONTRACT_V1",
            "R0_T07_CONFIRMATION_STREAK_INTERVAL_CONTRACT_V1",
        ):
            self.assertIn(dependency, self.config["depends_on"])
        self.assertIn(
            "synthetic_in_memory_r0_grid_inputs",
            self.config["allowed_logical_input_sources"],
        )
        for source in (
            "data/raw",
            "data/external",
            "data/generated",
            "MarketDB",
            ".day",
        ):
            self.assertIn(source, self.config["prohibited_direct_sources"])
        for forbidden in (
            "future_label",
            "future_return",
            "future_volatility",
            "breakout_direction",
            "release_direction",
            "win_rate",
            "pnl",
            "return",
            "backtest",
            "portfolio",
            "trade_signal",
            "buy_signal",
            "sell_signal",
        ):
            self.assertIn(forbidden, self.config["forbidden_outputs"])

    def test_artifact_schema_fields_are_declared(self) -> None:
        self.assertIn(
            "TurnoverShrink20_60_raw",
            self.config["candidate_daily_state_required_fields"],
        )
        self.assertIn(
            "AmountLevel20Pct", self.config["candidate_daily_state_required_fields"]
        )
        self.assertNotIn(
            "AmountLevel20Pct_raw", self.config["candidate_daily_state_required_fields"]
        )
        for legacy_name in self.config["legacy_v1_field_names_forbidden"]:
            self.assertNotIn(
                legacy_name, self.config["candidate_daily_state_required_fields"]
            )
        self.assertIn(
            "confirmation_time", self.config["confirmed_interval_required_fields"]
        )
        self.assertIn("quality_summary", self.config["manifest_required_fields"])
        self.assertIn("field_availability", self.config["manifest_required_fields"])

    def test_readme_advances_to_r0_t09_after_r0_t08_completion(self) -> None:
        text = README_PATH.read_text(encoding="utf-8")
        self.assertIn("current_stage: R0", text)
        self.assertIn(
            "current_task: R0-T09 正式 input manifest 与全量参数网格物化", text
        )
        self.assertIn("next_planned_task: R0-T10 R0 审计报告与 R1 交接", text)
        self.assertRegex(
            text,
            r"`R0-T08` 主网格 candidate 状态日表与 manifest：completed via PR #\d+",
        )


if __name__ == "__main__":
    unittest.main()
