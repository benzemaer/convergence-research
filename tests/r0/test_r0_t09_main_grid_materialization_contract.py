from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r0/r0_t09_main_grid_materialization_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/r0/r0_t09_main_grid_materialization_contract.schema.json"
README_PATH = ROOT / "docs/tasks/README.md"


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class R0T09MainGridMaterializationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.config = load_json(CONFIG_PATH)

    def test_config_passes_schema_validation(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema, format_checker=FormatChecker()).validate(
            self.config
        )

    def test_scope_authorizes_materialization_but_not_audit_or_handoff(self) -> None:
        self.assertTrue(self.config["authorized_input_manifest_required"])
        self.assertTrue(self.config["real_data_read_authorized"])
        self.assertTrue(self.config["duckdb_write_authorized"])
        self.assertTrue(self.config["csv_write_authorized"])
        self.assertTrue(self.config["generated_artifact_write_authorized"])
        self.assertTrue(self.config["main_grid_materialization_authorized"])
        for key in (
            "provider_call_authorized",
            "data_raw_read_authorized",
            "data_external_read_authorized",
            "marketdb_read_authorized",
            "day_file_read_authorized",
            "unauthorized_generated_read_authorized",
            "formal_data_version_authorized",
            "audit_report_generation_authorized",
            "r1_handoff_generation_authorized",
            "future_label_generation_authorized",
            "returns_generation_authorized",
            "backtest_generation_authorized",
            "portfolio_generation_authorized",
            "release_event_generation_authorized",
            "gap_merge_generated_by_this_task",
            "cooldown_generated_by_this_task",
        ):
            self.assertFalse(self.config[key])

    def test_grid_workers_resume_and_v1_guard_are_fixed(self) -> None:
        self.assertEqual(self.config["percentile_window_W_values"], [120, 250, 500])
        self.assertEqual(self.config["low_quantile_q_values"], [0.10, 0.20, 0.30])
        self.assertEqual(self.config["confirmation_days_K_values"], [2, 3, 5])
        self.assertNotIn(1, self.config["confirmation_days_K_values"])
        self.assertEqual(
            self.config["baseline_candidate_config_id"], "R0_W250_Q20_K3_WEAK_D010"
        )
        self.assertEqual(self.config["main_grid_config_count"], 27)
        self.assertEqual(self.config["max_workers_default"], 2)
        self.assertEqual(self.config["max_workers_upper_bound"], 2)
        self.assertTrue(self.config["resume_authorized"])
        self.assertTrue(self.config["input_payload_coverage_guard_required"])
        self.assertEqual(
            self.config["manifest_run_scope_values"], ["full_grid", "single_config"]
        )
        self.assertTrue(self.config["per_config_isolated_output_required"])
        self.assertTrue(self.config["single_writer_per_duckdb_required"])
        self.assertEqual(
            self.config["active_v1_indicator_id"], "V1_TurnoverShrink20_60"
        )
        self.assertEqual(self.config["active_v1_raw_field"], "TurnoverShrink20_60_raw")
        self.assertEqual(
            self.config["legacy_v1_field_names_forbidden"],
            [
                "VolShrink20_60_raw",
                "V1_VolShrink20_60",
                "VolShrink20_60",
                "volume_shrink_20_60",
            ],
        )

    def test_marker_manifest_and_forbidden_fields_are_declared(self) -> None:
        for field in (
            "input_data_version",
            "input_schema_version",
            "input_content_hash",
            "input_row_counts",
            "source_lineage",
            "authorized_r0_input",
            "code_commit_or_data_build_id",
            "input_payload_path",
        ):
            self.assertIn(field, self.config["required_input_manifest_fields"])
        for field in (
            "daily_duckdb_hash",
            "daily_csv_hash",
            "interval_duckdb_hash",
            "interval_csv_hash",
            "daily_content_hash",
            "interval_content_hash",
            "status",
        ):
            self.assertIn(field, self.config["done_marker_required_fields"])
        for field in ("error_type", "error_message", "retry_command"):
            self.assertIn(field, self.config["failed_marker_required_fields"])
        for field in (
            "candidate_configs",
            "run_scope",
            "selected_config_count",
            "selected_config_ids",
            "per_config_status",
            "lineage_guard",
            "input_payload_coverage_guard",
        ):
            self.assertIn(field, self.config["global_manifest_required_fields"])
        for forbidden in (
            "future_return",
            "pnl",
            "win_rate",
            "backtest",
            "portfolio",
            "trade_signal",
            "audit_report",
            "r1_handoff",
        ):
            self.assertIn(forbidden, self.config["forbidden_outputs"])
        self.assertIn(
            "input_payload_grid_coverage_incomplete",
            self.config["reason_code_vocabulary"],
        )

    def test_readme_advances_to_r0_t10_after_r0_t09_completion(self) -> None:
        text = README_PATH.read_text(encoding="utf-8")
        self.assertIn("current_stage: R0", text)
        self.assertIn(
            "current_task: R0-T10-04 R0-T07 confirmation / interval 物化", text
        )
        self.assertIn(
            "next_planned_task: R0-T10-05 authorized input manifest "
            "与 27 组 full-grid 执行",
            text,
        )
        self.assertIn("`R0-T09` runner/contract/smoke：completed via PR #67", text)
        self.assertIn(
            "`R0-T09` formal input manifest：blocked / superseded by R0-T10-05 "
            "pending real R0-T04 -> R0-T07 upstream artifacts",
            text,
        )
        self.assertIn(
            "`R0-T09` production full-grid materialization：blocked until R0-T10-05 "
            "authorized input manifest and streaming/artifact-manifest mode",
            text,
        )


if __name__ == "__main__":
    unittest.main()
