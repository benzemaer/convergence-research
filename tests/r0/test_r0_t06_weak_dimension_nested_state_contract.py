from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r0/r0_t06_weak_dimension_nested_state_contract.v1.json"
SCHEMA_PATH = (
    ROOT / "schemas/r0/r0_t06_weak_dimension_nested_state_contract.schema.json"
)
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class R0T06WeakDimensionNestedStateContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.config = load_json(CONFIG_PATH)

    def test_config_passes_schema_validation(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema, format_checker=FormatChecker()).validate(
            self.config
        )

    def test_contract_authorizes_only_synthetic_state_generation(self) -> None:
        self.assertEqual(self.config["state_generation_authorized"], "synthetic_only")
        for key in (
            "real_data_read_authorized",
            "duckdb_write_authorized",
            "formal_data_version_authorized",
            "confirmation_generation_authorized",
            "state_interval_generation_authorized",
            "future_label_generation_authorized",
            "returns_generation_authorized",
            "backtest_generation_authorized",
            "portfolio_generation_authorized",
            "strict_rule_generated_by_this_task",
            "confirmed_state_generated_by_this_task",
            "streak_generated_by_this_task",
            "interval_generated_by_this_task",
        ):
            self.assertFalse(self.config[key])

    def test_q_weak_delta_and_weak_rule_are_fixed(self) -> None:
        self.assertEqual(self.config["q_values"], [0.10, 0.20, 0.30])
        self.assertEqual(self.config["baseline_q"], 0.20)
        self.assertEqual(self.config["weak_delta"], 0.10)
        self.assertEqual(self.config["dimension_rule"], "weak")
        self.assertEqual(self.config["indicator_threshold_formula"], "1 - q")
        self.assertEqual(
            self.config["dimension_min_threshold_formula"], "1 - q - weak_delta"
        )

    def test_generated_outputs_stop_before_r0_t07(self) -> None:
        self.assertTrue(self.config["indicator_active_generated_by_this_task"])
        self.assertTrue(self.config["dimension_active_generated_by_this_task"])
        self.assertTrue(self.config["nested_raw_state_generated_by_this_task"])
        self.assertTrue(self.config["exclusive_state_layer_generated_by_this_task"])
        prohibited = set(self.config["prohibited_outputs"])
        for forbidden in (
            "confirmation",
            "confirmed_state",
            "streak",
            "state_interval",
            "future_return",
            "backtest",
            "portfolio",
            "formal_data_version",
        ):
            self.assertIn(forbidden, prohibited)

    def test_lineage_and_q_selection_guards_are_declared(self) -> None:
        self.assertIn(
            "synthetic_in_memory_scores", self.config["allowed_logical_input_sources"]
        )
        self.assertIn("data/generated", self.config["prohibited_direct_sources"])
        self.assertIn("data/raw", self.config["prohibited_direct_sources"])
        self.assertIn("MarketDB", self.config["prohibited_direct_sources"])
        self.assertIn(".day", self.config["prohibited_direct_sources"])
        for prohibited in ("future_labels", "returns", "backtest", "future_outcomes"):
            self.assertIn(prohibited, self.config["q_selection_prohibited_by"])

    def test_readme_advances_to_r0_t07_after_r0_t06_completion(self) -> None:
        text = README_PATH.read_text(encoding="utf-8")
        self.assertIn("current_stage: R0", text)
        self.assertIn(
            "current_task: R0-T09 R0 审计报告与 R1 交接",
            text,
        )
        self.assertIn(
            "next_planned_task: R0-T10 替代指标口径敏感性骨架",
            text,
        )
        self.assertRegex(
            text,
            r"`R0-T06` weak 维度规则、嵌套状态与互斥分层：completed via PR #\d+",
        )


if __name__ == "__main__":
    unittest.main()
