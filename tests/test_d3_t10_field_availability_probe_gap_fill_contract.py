from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

from scripts.probe_d3_t10_field_availability import (
    build_field_matrix,
    indicator_status,
    run_probe,
)
from scripts.probe_d3_t10_tnskhdata_fields import (
    run_probe_with_client,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = (
    ROOT / "configs/d3/d3_t10_field_availability_probe_gap_fill_contract.v1.json"
)
SCHEMA_PATH = (
    ROOT / "schemas/d3_t10_field_availability_probe_gap_fill_contract.schema.json"
)
D3_VALUES_CONFIG_PATH = (
    ROOT / "configs/d3/daily_market_observation_values_contract.v1.json"
)


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class FakeTnskhdataClient:
    def daily(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> list[dict[str, object]]:
        return [
            {
                "ts_code": ts_code,
                "trade_date": start_date,
                "low": 9.0,
                "high": 11.0,
                "vol": 100.0,
                "amount": 100.0,
            }
        ]

    def daily_basic(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> list[dict[str, object]]:
        return [
            {
                "ts_code": ts_code,
                "trade_date": start_date,
                "close": 10.0,
                "turnover_rate": 1.0,
                "turnover_rate_f": 2.0,
                "volume_ratio": 1.2,
                "total_share": 200.0,
                "float_share": 100.0,
                "free_share": 50.0,
                "total_mv": 2000.0,
                "circ_mv": 1000.0,
                "limit_status": "0",
            }
        ]


class D3T10FieldAvailabilityProbeGapFillContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.config = load_json(CONFIG_PATH)
        cls.d3_values_config = load_json(D3_VALUES_CONFIG_PATH)

    def test_contract_passes_schema_validation(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema, format_checker=FormatChecker()).validate(
            self.config
        )

    def test_contract_blocks_pcvt_r0_and_formal_outputs(self) -> None:
        for key in (
            "formal_data_version_authorized",
            "duckdb_write_authorized",
            "pcvt_metric_calculation_authorized",
            "pcvt_percentile_generation_authorized",
            "pcvt_score_generation_authorized",
            "pcvt_state_generation_authorized",
            "future_label_generation_authorized",
            "returns_generation_authorized",
            "backtest_generation_authorized",
            "portfolio_generation_authorized",
            "provider_probe_raw_payload_commit_authorized",
            "credential_commit_authorized",
        ):
            self.assertFalse(self.config[key])

    def test_contract_declares_standardized_units_and_turnover_fields(self) -> None:
        rules = self.config["standardization_rules"]
        self.assertEqual(rules["volume_unit"], "hand")
        self.assertEqual(rules["amount_unit"], "thousand_yuan")
        self.assertEqual(rules["total_share_unit"], "ten_thousand_shares")
        fields = set(self.config["generic_d3_fields_to_add"])
        self.assertTrue(
            {
                "volume_shares",
                "amount_yuan",
                "float_share_shares",
                "free_share_shares",
                "turnover_float",
                "turnover_free",
                "turnover_rate",
                "turnover_rate_f",
            }.issubset(fields)
        )

    def test_d3_values_contract_has_d3_t10_generic_fields(self) -> None:
        groups = self.d3_values_config["value_field_groups"]
        self.assertIn("share_turnover_value_fields", groups)
        self.assertIn("corporate_action_comparability_fields", groups)
        self.assertIn("turnover_float", groups["share_turnover_value_fields"])
        self.assertIn("turnover_free", groups["share_turnover_value_fields"])
        policy = self.d3_values_config["d3_t10_future_alternative_v_policy"]
        self.assertTrue(policy["r0_baseline_unchanged"])
        self.assertEqual(
            policy["baseline_v_indicators"],
            ["V1_VolShrink20_60", "V2_AmountLevel20Pct"],
        )
        replacements = self.d3_values_config["d3_t10_standardized_replacements"]
        self.assertEqual(replacements["turnover"], ["turnover_float", "turnover_free"])
        self.assertEqual(
            replacements["float_shares"], ["float_share_shares", "free_share_shares"]
        )

    def test_field_matrix_marks_missing_d3_t10_fields(self) -> None:
        available = {"adjusted_high", "adjusted_low", "adjusted_close", "amount"}
        matrix = build_field_matrix(available, "synthetic")
        by_field = {row["field_name"]: row for row in matrix}
        self.assertEqual(by_field["amount"]["current_status"], "present")
        self.assertEqual(by_field["amount_yuan"]["current_status"], "missing")
        statuses = {row["indicator_id"]: row for row in indicator_status(matrix)}
        self.assertFalse(statuses["C2_AdjVWAPSpread_5_60"]["ready_by_schema"])
        self.assertIn(
            "amount_yuan", statuses["C2_AdjVWAPSpread_5_60"]["missing_fields"]
        )

    def test_c2_requires_raw_low_raw_high_and_amount_volume_unit_status(self) -> None:
        matrix = build_field_matrix(
            {
                "amount_yuan",
                "volume_shares",
                "daily_vwap",
                "daily_vwap_range_status",
                "adjusted_vwap_policy",
            },
            "synthetic",
        )
        statuses = {row["indicator_id"]: row for row in indicator_status(matrix)}
        c2 = statuses["C2_AdjVWAPSpread_5_60"]
        self.assertFalse(c2["ready_by_schema"])
        self.assertIn("raw_low", c2["missing_fields"])
        self.assertIn("raw_high", c2["missing_fields"])
        self.assertIn("amount_volume_unit_status", c2["missing_fields"])

    def test_c2_ready_by_schema_when_all_required_fields_present(self) -> None:
        matrix = build_field_matrix(
            {
                "amount_yuan",
                "volume_shares",
                "amount_volume_unit_status",
                "daily_vwap",
                "daily_vwap_range_status",
                "raw_low",
                "raw_high",
                "adjusted_vwap_policy",
            },
            "synthetic",
        )
        statuses = {row["indicator_id"]: row for row in indicator_status(matrix)}
        self.assertTrue(statuses["C2_AdjVWAPSpread_5_60"]["ready_by_schema"])

    def test_duckdb_probe_is_read_only_and_reports_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "data/generated/d3/d3_t07_candidate_daily_observation"
            base.mkdir(parents=True)
            db_path = base / "d3_t07_candidate_daily_observation.duckdb"
            conn = duckdb.connect(str(db_path))
            conn.execute(
                """
                CREATE TABLE d3_candidate_daily_observation (
                  adjusted_high DOUBLE,
                  adjusted_low DOUBLE,
                  adjusted_close DOUBLE,
                  amount DOUBLE,
                  vol DOUBLE
                )
                """
            )
            conn.close()
            summary = run_probe(
                d3_duckdb=db_path,
                contract=CONFIG_PATH,
                table="d3_candidate_daily_observation",
            )
        self.assertFalse(summary["remote_provider_called"])
        self.assertFalse(summary["pcvt_values_generated"])
        self.assertFalse(summary["r0_state_generated"])

    def test_tnskhdata_fake_client_summary_is_redacted(self) -> None:
        summary = run_probe_with_client(
            FakeTnskhdataClient(),
            securities=["000001.SZ"],
            start_date="20260601",
            end_date="20260605",
        )
        self.assertTrue(summary["raw_payload_redacted"])
        self.assertEqual(summary["daily_field_non_null_rates"]["vol"], 1.0)
        self.assertEqual(
            summary["joined_quality_checks"][0]["provider_turnover_crosscheck_status"],
            "valid",
        )
        self.assertNotIn("raw_rows", summary)

    def test_tnskhdata_cli_without_token_exits_cleanly(self) -> None:
        env = os.environ.copy()
        for key in ("TNSKHDATA_TOKEN", "TUSHARE_TOKEN", "TNS_TOKEN"):
            env.pop(key, None)
        result = subprocess.run(
            [sys.executable, "scripts/probe_d3_t10_tnskhdata_fields.py"],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("blocked_missing_tnskhdata_token", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_direct_cli_help_works(self) -> None:
        for script in (
            "scripts/probe_d3_t10_field_availability.py",
            "scripts/probe_d3_t10_tnskhdata_fields.py",
        ):
            result = subprocess.run(
                [sys.executable, script, "--help"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_readme_advances_to_d3_t10_and_keeps_r0_t03_planned(self) -> None:
        text = (ROOT / "docs/tasks/README.md").read_text(encoding="utf-8")
        self.assertIn("current_stage: D3", text)
        self.assertIn(
            "current_task: R0-T04 PCVT raw metric engine 与合成测试",
            text,
        )
        self.assertIn(
            "next_planned_task: R0-T05 严格过去分位、eligible 样本与 Score 体系",
            text,
        )
        self.assertIn(
            (
                "R0-T01` PCVT 候选指标规格、状态族与 candidate spec "
                "contract：completed via PR #56"
            ),
            text,
        )
        self.assertIn(
            (
                "R0-T02` 输入 readiness gate 与 C2/V1 公司行为口径审计："
                "completed via PR #57"
            ),
            text,
        )
        self.assertIn(
            "R0-T03` V层 turnover 替代指标可行性、口径决策与输入门禁"
            "：completed via PR #61",
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


if __name__ == "__main__":
    unittest.main()
