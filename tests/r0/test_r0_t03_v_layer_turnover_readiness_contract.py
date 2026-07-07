from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r0/r0_t03_v_layer_turnover_readiness_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/r0/r0_t03_v_layer_turnover_readiness_contract.schema.json"
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class R0T03VLayerTurnoverReadinessContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.config = load_json(CONFIG_PATH)

    def test_config_passes_schema_validation(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema, format_checker=FormatChecker()).validate(
            self.config
        )

    def test_baseline_v_indicators_are_turnover_shrink_and_amount_level(self) -> None:
        by_id = {
            indicator["indicator_id"]: indicator
            for indicator in self.config["baseline_v_indicators"]
        }
        self.assertEqual(set(by_id), {"V1_TurnoverShrink20_60", "V2_AmountLevel20Pct"})
        self.assertEqual(
            by_id["V1_TurnoverShrink20_60"]["input_field"], "turnover_float"
        )
        self.assertEqual(
            by_id["V1_TurnoverShrink20_60"]["denominator_field"],
            "float_share_shares",
        )
        self.assertEqual(by_id["V2_AmountLevel20Pct"]["input_field"], "amount_yuan")

    def test_alternative_turnover_metrics_are_not_baseline(self) -> None:
        alternatives = set(self.config["alternative_v_indicators"])
        self.assertEqual(
            alternatives,
            {
                "FreeTurnoverShrink20_60",
                "TurnoverLevel20Pct",
                "FreeTurnoverLevel20Pct",
            },
        )
        baseline_names = {
            indicator["raw_metric_name"]
            for indicator in self.config["baseline_v_indicators"]
        }
        self.assertTrue(alternatives.isdisjoint(baseline_names))

    def test_turnover_gate_requires_d3_t11_quality_and_comparability_fields(
        self,
    ) -> None:
        required = set(self.config["turnover_shrink_gate"]["required_fields"])
        self.assertTrue(
            {
                "turnover_float",
                "turnover_field_status",
                "share_field_status",
                "provider_turnover_crosscheck_status",
                "float_share_shares",
                "common_share_basis_policy",
                "volume_comparability_policy",
            }.issubset(required)
        )

    def test_amount_level_forbids_repeated_percentile(self) -> None:
        amount_gate = self.config["amount_level_gate"]
        self.assertTrue(amount_gate["no_repeated_percentile"])
        self.assertIn(
            "amount_level_repeated_percentile_forbidden",
            amount_gate["unknown_or_blocked_rules"],
        )

    def test_no_real_output_or_downstream_generation_is_authorized(self) -> None:
        for key in (
            "real_data_read_authorized",
            "formal_data_version_authorized",
            "pcvt_metric_calculation_authorized",
            "pcvt_percentile_generation_authorized",
            "pcvt_score_generation_authorized",
            "pcvt_state_generation_authorized",
            "state_interval_generation_authorized",
            "future_label_generation_authorized",
            "returns_generation_authorized",
            "backtest_generation_authorized",
            "portfolio_generation_authorized",
        ):
            self.assertFalse(self.config[key])
        prohibited = set(self.config["prohibited_outputs"])
        self.assertIn("readiness_audit_real_output_file", prohibited)
        self.assertIn("pcvt_raw_values", prohibited)

    def test_d3_t12_is_completed_and_r0_t03_is_current_task(self) -> None:
        text = README_PATH.read_text(encoding="utf-8")
        self.assertIn("current_stage: R0", text)
        self.assertIn(
            "current_task: R0-T08 主网格 candidate 状态日表与 manifest",
            text,
        )
        self.assertIn(
            "next_planned_task: R0-T09 R0 审计报告与 R1 交接",
            text,
        )
        self.assertIn(
            "`D3-T12` 开放候选层门禁与下游消费审计解耦：completed via PR #60",
            text,
        )
        self.assertIn(
            "`R0-T03` V层 turnover 替代指标可行性、口径决策与输入门禁"
            "：completed via PR #61",
            text,
        )


if __name__ == "__main__":
    unittest.main()
