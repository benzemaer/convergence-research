from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    ROOT / "configs/d3/d3_t11_volume_amount_share_turnover_candidate_contract.v1.json"
)
SCHEMA_PATH = (
    ROOT / "schemas/d3_t11_volume_amount_share_turnover_candidate_contract.schema.json"
)


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


class D3T11VolumeAmountShareTurnoverContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_json(CONFIG_PATH)
        cls.schema = load_json(SCHEMA_PATH)

    def test_contract_passes_schema_validation(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema, format_checker=FormatChecker()).validate(
            self.config
        )

    def test_contract_blocks_formal_research_and_raw_payload_outputs(self) -> None:
        for key in (
            "formal_data_version_authorized",
            "pcvt_metric_calculation_authorized",
            "pcvt_score_generation_authorized",
            "pcvt_state_generation_authorized",
            "future_label_generation_authorized",
            "returns_generation_authorized",
            "backtest_generation_authorized",
            "portfolio_generation_authorized",
            "provider_raw_payload_commit_authorized",
            "credential_commit_authorized",
        ):
            self.assertFalse(self.config[key])

    def test_contract_declares_d3_t10_standardized_fields(self) -> None:
        fields = set(self.config["standardized_fields"])
        self.assertTrue(
            {
                "volume_shares",
                "amount_yuan",
                "daily_vwap",
                "total_share_shares",
                "float_share_shares",
                "free_share_shares",
                "turnover_float",
                "turnover_free",
                "provider_turnover_crosscheck_status",
            }.issubset(fields)
        )

    def test_contract_keeps_r0_baseline_and_turnover_alternative_policy(self) -> None:
        self.assertTrue(self.config["r0_baseline_unchanged"])
        self.assertEqual(
            self.config["r0_baseline_v_indicators"],
            ["V1_VolShrink20_60", "V2_AmountLevel20Pct"],
        )
        self.assertIn("R0-T11", self.config["turnover_based_v_metrics_policy"])

    def test_readme_advances_to_d3_t12_and_keeps_r0_t03_planned(self) -> None:
        text = (ROOT / "docs/tasks/README.md").read_text(encoding="utf-8")
        self.assertIn(
            "current_task: R0-T10-01 真实数据源与 R0-T04 raw metrics 物化",
            text,
        )
        self.assertIn(
            "next_planned_task: R0-T10-02 R0-T05 strict-past score 物化",
            text,
        )
        self.assertIn(
            "D3-T10` D3 字段可用性探针与字段缺口补全：completed via PR #58", text
        )
        self.assertIn(
            "D3-T11` 量额股本换手字段全量候选物化与数据更新：completed via PR #59",
            text,
        )
        self.assertIn(
            "D3-T12` 开放候选层门禁与下游消费审计解耦：completed via PR #60",
            text,
        )
        self.assertIn(
            "R0-T03` V层 turnover 替代指标可行性、口径决策与输入门禁"
            "：completed via PR #61",
            text,
        )


if __name__ == "__main__":
    unittest.main()
