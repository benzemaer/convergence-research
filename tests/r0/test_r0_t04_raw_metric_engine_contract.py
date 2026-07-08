from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r0/r0_t04_raw_metric_engine_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/r0/r0_t04_raw_metric_engine_contract.schema.json"
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class R0T04RawMetricEngineContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.config = load_json(CONFIG_PATH)

    def test_config_passes_schema_validation(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema, format_checker=FormatChecker()).validate(
            self.config
        )

    def test_active_metrics_are_raw_or_base_metrics_only(self) -> None:
        by_id = {
            metric["indicator_id"]: metric
            for metric in self.config["active_raw_metrics"]
        }
        self.assertEqual(
            set(by_id),
            {
                "P1_NATR14",
                "P2_LogRange20",
                "C1_LogMASpread_5_60",
                "C2_AdjVWAPSpread_5_60",
                "T1_ER20",
                "T2_AbsTrendT20",
                "V1_TurnoverShrink20_60",
                "V2_LogAmount20_base",
            },
        )
        self.assertNotIn("V1_VolShrink20_60", by_id)
        self.assertNotIn("V2_AmountLevel20Pct", by_id)
        self.assertEqual(by_id["V2_LogAmount20_base"]["raw_metric_name"], "LogAmount20")
        self.assertEqual(
            by_id["V2_LogAmount20_base"]["downstream_indicator"],
            "V2_AmountLevel20Pct_in_R0_T05",
        )

    def test_generation_authorizations_stop_at_synthetic_raw_metrics(self) -> None:
        self.assertEqual(
            self.config["pcvt_raw_metric_generation_authorized"], "synthetic_only"
        )
        for key in (
            "real_data_read_authorized",
            "duckdb_write_authorized",
            "formal_data_version_authorized",
            "pcvt_percentile_generation_authorized",
            "pcvt_score_generation_authorized",
            "pcvt_state_generation_authorized",
            "state_interval_generation_authorized",
            "future_label_generation_authorized",
            "returns_generation_authorized",
            "backtest_generation_authorized",
            "portfolio_generation_authorized",
            "AmountLevel20Pct_generated_by_this_task",
            "strict_past_percentiles_generated_by_this_task",
            "scores_generated_by_this_task",
            "states_generated_by_this_task",
        ):
            self.assertFalse(self.config[key])

    def test_turnover_and_amount_contracts_match_r0_t03_boundary(self) -> None:
        by_id = {
            metric["indicator_id"]: metric
            for metric in self.config["active_raw_metrics"]
        }
        turnover_fields = set(by_id["V1_TurnoverShrink20_60"]["source_field_names"])
        self.assertTrue(
            {
                "turnover_float",
                "turnover_field_status",
                "share_field_status",
                "provider_turnover_crosscheck_status",
                "volume_shares",
                "float_share_shares",
                "corporate_action_types_in_window",
                "share_comparability_corporate_action_in_window",
                "common_share_basis_policy",
                "volume_comparability_policy",
            }.issubset(turnover_fields)
        )
        amount_fields = set(by_id["V2_LogAmount20_base"]["source_field_names"])
        self.assertTrue(
            {
                "amount_yuan",
                "amount_unit",
                "amount_volume_unit_status",
                "zero_amount_flag",
                "trading_status",
                "suspension_flag",
            }.issubset(amount_fields)
        )

    def test_forbidden_outputs_and_reason_vocabulary_are_declared(self) -> None:
        prohibited = set(self.config["prohibited_outputs"])
        self.assertIn("AmountLevel20Pct", prohibited)
        self.assertIn("pcvt_percentiles", prohibited)
        self.assertIn("pcvt_scores", prohibited)
        self.assertIn("pcvt_states", prohibited)
        self.assertIn("future_labels", prohibited)
        reasons = set(self.config["reason_code_vocabulary"])
        self.assertIn("residual_se_zero_slope_nonzero", reasons)
        self.assertIn("adjusted_vwap_policy_missing", reasons)
        self.assertIn("corporate_action_turnover_comparability_policy_missing", reasons)
        self.assertIn("forbidden_output_field", reasons)

    def test_readme_advances_to_r0_t05_after_r0_t04_completion(self) -> None:
        text = README_PATH.read_text(encoding="utf-8")
        self.assertIn("current_stage: R1", text)
        self.assertIn(
            "current_task: R1-T01 状态存在性与频率轮廓",
            text,
        )
        self.assertIn(
            "next_planned_task: R1-T02 结构关系与协同约束检验",
            text,
        )
        self.assertRegex(
            text,
            r"`R0-T04` PCVT raw metric engine 与合成测试：completed via PR #\d+",
        )


if __name__ == "__main__":
    unittest.main()
