from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r0/r0_t07_confirmation_streak_interval_contract.v1.json"
SCHEMA_PATH = (
    ROOT / "schemas/r0/r0_t07_confirmation_streak_interval_contract.schema.json"
)
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class R0T07ConfirmationStreakIntervalContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.config = load_json(CONFIG_PATH)

    def test_config_passes_schema_validation(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema, format_checker=FormatChecker()).validate(
            self.config
        )

    def test_contract_authorizes_only_synthetic_confirmation_outputs(self) -> None:
        self.assertEqual(
            self.config["confirmation_generation_authorized"], "synthetic_only"
        )
        self.assertEqual(self.config["streak_generation_authorized"], "synthetic_only")
        self.assertEqual(
            self.config["interval_generation_authorized"], "synthetic_only"
        )
        for key in (
            "real_data_read_authorized",
            "duckdb_write_authorized",
            "formal_data_version_authorized",
            "future_label_generation_authorized",
            "returns_generation_authorized",
            "backtest_generation_authorized",
            "portfolio_generation_authorized",
            "manifest_generation_authorized",
            "gap_merge_generated_by_this_task",
            "confirmed_state_backfill_allowed",
            "future_data_used",
        ):
            self.assertFalse(self.config[key])
        self.assertTrue(self.config["current_and_past_only"])

    def test_k_values_and_state_names_are_fixed(self) -> None:
        self.assertEqual(self.config["confirmation_k_values"], [2, 3, 5])
        self.assertEqual(self.config["baseline_confirmation_k"], 3)
        self.assertEqual(
            self.config["confirmed_state_names"], ["S_P", "S_PC", "S_PCT", "S_PCVT"]
        )
        self.assertEqual(
            self.config["input_raw_state_fields"],
            ["S_P_raw", "S_PC_raw", "S_PCT_raw", "S_PCVT_raw"],
        )

    def test_forbidden_outputs_and_lineage_are_declared(self) -> None:
        prohibited = set(self.config["prohibited_outputs"])
        for forbidden in (
            "future_label",
            "future_return",
            "breakout_direction",
            "backtest",
            "portfolio",
            "formal_data_version",
        ):
            self.assertIn(forbidden, prohibited)

        self.assertIn(
            "synthetic_in_memory_daily_states",
            self.config["allowed_logical_input_sources"],
        )
        for source in ("data/generated", "data/raw", "MarketDB", ".day"):
            self.assertIn(source, self.config["prohibited_direct_sources"])

    def test_readme_advances_to_r0_t08_after_r0_t07_completion(self) -> None:
        text = README_PATH.read_text(encoding="utf-8")
        self.assertIn("current_stage: R0", text)
        self.assertIn(
            "current_task: R0-T10 R0 审计报告与 R1 交接",
            text,
        )
        self.assertIn(
            "next_planned_task: R0-T11 替代指标口径敏感性骨架",
            text,
        )
        self.assertRegex(
            text,
            r"`R0-T07` 联合确认层、streak 与确认区间表：completed via PR #\d+",
        )


if __name__ == "__main__":
    unittest.main()
