from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r0/r0_t05_strict_past_percentile_score_contract.v1.json"
SCHEMA_PATH = (
    ROOT / "schemas/r0/r0_t05_strict_past_percentile_score_contract.schema.json"
)
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class R0T05StrictPastPercentileScoreContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.config = load_json(CONFIG_PATH)

    def test_config_passes_schema_validation(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema, format_checker=FormatChecker()).validate(
            self.config
        )

    def test_contract_authorizes_only_synthetic_percentiles_and_scores(self) -> None:
        self.assertEqual(
            self.config["strict_past_percentile_generation_authorized"],
            "synthetic_only",
        )
        self.assertEqual(self.config["score_generation_authorized"], "synthetic_only")
        for key in (
            "real_data_read_authorized",
            "duckdb_write_authorized",
            "formal_data_version_authorized",
            "pcvt_state_generation_authorized",
            "state_interval_generation_authorized",
            "future_label_generation_authorized",
            "returns_generation_authorized",
            "backtest_generation_authorized",
            "portfolio_generation_authorized",
            "q_thresholds_applied_by_this_task",
            "states_generated_by_this_task",
        ):
            self.assertFalse(self.config[key])

    def test_windows_tie_method_and_v2_mapping_are_fixed(self) -> None:
        self.assertEqual(self.config["percentile_windows_W"], [120, 250, 500])
        self.assertEqual(self.config["tie_method"], "midrank")
        self.assertFalse(self.config["current_value_in_reference_set"])
        self.assertFalse(self.config["cross_sectional_percentile"])
        self.assertTrue(self.config["AmountLevel20Pct_generated_by_this_task"])
        self.assertEqual(
            self.config["AmountLevel20Pct_source_base"], "V2_LogAmount20_base"
        )
        self.assertTrue(self.config["AmountLevel20Pct_repeated_percentile_forbidden"])

    def test_active_indicator_ids_use_amount_level_not_log_amount_base(self) -> None:
        active = set(self.config["active_indicator_ids"])
        self.assertIn("V2_AmountLevel20Pct", active)
        self.assertNotIn("V2_LogAmount20_base", active)
        self.assertIn("V2_LogAmount20_base", self.config["input_raw_metric_ids"])

    def test_forbidden_outputs_exclude_state_and_future_work(self) -> None:
        prohibited = set(self.config["prohibited_outputs"])
        for forbidden in (
            "indicator_active",
            "dimension_active",
            "pcvt_state",
            "state_interval",
            "S_PCT",
            "S_PCVT",
            "q_threshold",
            "future_returns",
            "backtest",
            "portfolio",
        ):
            self.assertIn(forbidden, prohibited)

    def test_prohibited_direct_sources_include_generated_data(self) -> None:
        prohibited = set(self.config["prohibited_direct_sources"])
        self.assertIn("data/generated", prohibited)

    def test_readme_advances_to_r0_t06_after_r0_t05_completion(self) -> None:
        text = README_PATH.read_text(encoding="utf-8")
        self.assertIn("current_stage: R0", text)
        self.assertIn(
            "current_task: R0-T10-01 真实数据源与 R0-T04 raw metrics 物化",
            text,
        )
        self.assertIn(
            "next_planned_task: R0-T10-02 R0-T05 strict-past score 物化",
            text,
        )
        self.assertRegex(
            text,
            r"`R0-T05` 严格过去分位、eligible 样本与 Score 体系：completed via PR #\d+",
        )


if __name__ == "__main__":
    unittest.main()
