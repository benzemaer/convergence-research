from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from src.r0.r0_t09_input_manifest_builder import _contract_grid_payload
from src.r0.r0_t10_formal_materializer import (
    BASELINE_CANDIDATE_CONFIG_ID,
    evaluate_formal_upstream_readiness,
    run_r0_t10_formal_materialization,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r0/r0_t10_formal_materialization_contract.v1.json"
SCHEMA_PATH = ROOT / "schemas/r0/r0_t10_formal_materialization_contract.schema.json"


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_full_grid_upstream(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    payload = _contract_grid_payload()
    paths = {
        "t04": directory / "r0_t04_raw_metric_results.json",
        "t05": directory / "r0_t05_score_results.json",
        "t06": directory / "r0_t06_nested_daily_state_results.json",
        "t07": directory / "r0_t07_confirmation_results.json",
    }
    paths["t04"].write_text(
        json.dumps({"raw_metric_results": payload["raw_metric_results"]}),
        encoding="utf-8",
    )
    paths["t05"].write_text(
        json.dumps(
            {
                "indicator_score_results": payload["indicator_score_results"],
                "dimension_score_results": payload["dimension_score_results"],
            }
        ),
        encoding="utf-8",
    )
    paths["t06"].write_text(
        json.dumps(
            {"nested_daily_state_results": payload["nested_daily_state_results"]}
        ),
        encoding="utf-8",
    )
    paths["t07"].write_text(
        json.dumps(
            {
                "daily_confirmation_results": payload["daily_confirmation_results"],
                "confirmed_interval_results": payload["confirmed_interval_results"],
            }
        ),
        encoding="utf-8",
    )
    return paths


class R0T10FormalMaterializationContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_json(SCHEMA_PATH)
        cls.config = load_json(CONFIG_PATH)

    def test_config_passes_schema_validation(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        Draft202012Validator(self.schema, format_checker=FormatChecker()).validate(
            self.config
        )

    def test_contract_stops_before_full_grid_in_phase_1(self) -> None:
        self.assertEqual(self.config["task_id"], "R0-T10")
        self.assertEqual(
            self.config["contract_scope"],
            "formal_upstream_materialization_and_full_grid_execution",
        )
        self.assertTrue(self.config["phase_1_stops_before_full_grid"])
        self.assertFalse(
            self.config["r0_t09_full_grid_execution_authorized_in_phase_1"]
        )
        self.assertEqual(self.config["max_workers_default"], 2)
        self.assertEqual(self.config["max_workers_upper_bound"], 2)
        self.assertFalse(self.config["audit_report_generation_authorized"])
        self.assertFalse(self.config["r1_handoff_generation_authorized"])


class R0T10FormalMaterializerTest(unittest.TestCase):
    def test_missing_formal_upstream_inputs_blocks_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r0_t10_formal_materialization(
                output_dir=Path(tmp) / "r0_t10",
                run_id="r0_t10_missing_inputs",
                code_commit="abcdef",
                data_root=Path(tmp) / "data",
            )

            self.assertEqual(result.summary["status"], "blocked")
            self.assertIn(
                "formal_upstream_inputs_missing", result.summary["reason_codes"]
            )
            self.assertFalse(result.summary["authorized_input_manifest_written"])
            self.assertEqual(result.summary["full_grid_status"], "not_started")
            self.assertFalse(
                (
                    result.output_dir
                    / "r0_t09_inputs"
                    / "authorized_input_manifest.json"
                ).exists()
            )
            self.assertTrue(
                (
                    result.output_dir / "upstream" / "upstream_generation_summary.json"
                ).is_file()
            )

    def test_existing_reports_with_false_r0_flags_are_blocking_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "data" / "generated" / "d3" / "candidate"
            report_dir.mkdir(parents=True)
            (report_dir / "handoff.json").write_text(
                json.dumps(
                    {
                        "formal_use_authorized": False,
                        "pcvt_values_generated": False,
                        "r0_state_generated": False,
                    }
                ),
                encoding="utf-8",
            )

            readiness = evaluate_formal_upstream_readiness(data_root=Path(tmp) / "data")

            self.assertEqual(readiness["validity_status"], "blocked")
            self.assertIn("formal_use_authorized_false", readiness["reason_codes"])
            self.assertIn("pcvt_values_not_generated", readiness["reason_codes"])
            self.assertIn("r0_state_not_generated", readiness["reason_codes"])

    def test_fixture_like_formal_input_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture_dir = Path(tmp) / "tests" / "fixtures" / "r0"
            fixture_dir.mkdir(parents=True)
            path = fixture_dir / "r0_t04_raw_metric_results.json"
            path.write_text(json.dumps({"raw_metric_results": [{}]}), encoding="utf-8")

            readiness = evaluate_formal_upstream_readiness(
                data_root=Path(tmp) / "data",
                upstream_paths={
                    "r0_t04": path,
                    "r0_t05": None,
                    "r0_t06": None,
                    "r0_t07": None,
                },
            )

            self.assertEqual(readiness["validity_status"], "blocked")
            self.assertIn(
                "formal_input_fixture_path_forbidden", readiness["reason_codes"]
            )

    def test_pre_full_grid_can_build_manifest_dry_run_and_baseline_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = write_full_grid_upstream(root / "upstream_inputs")
            result = run_r0_t10_formal_materialization(
                output_dir=root / "r0_t10",
                run_id="r0_t10_pre_full_grid",
                code_commit="abcdef",
                data_root=root / "data",
                r0_t04_input=upstream["t04"],
                r0_t05_input=upstream["t05"],
                r0_t06_input=upstream["t06"],
                r0_t07_input=upstream["t07"],
                dry_run_r0_t09=True,
                baseline_r0_t09=True,
                max_workers=2,
            )

            self.assertEqual(result.summary["status"], "pre_full_grid_completed")
            self.assertTrue(result.summary["authorized_input_manifest_written"])
            self.assertEqual(
                result.summary["full_grid_status"], "deferred_pending_review"
            )
            self.assertEqual(result.summary["dry_run_result"]["status"], "dry_run")
            self.assertEqual(
                result.summary["dry_run_result"]["selected_config_count"], 27
            )
            self.assertEqual(result.summary["baseline_result"]["status"], "completed")
            self.assertEqual(
                result.summary["baseline_result"]["run_scope"], "single_config"
            )
            self.assertEqual(
                result.summary["baseline_result"]["selected_config_ids"],
                [BASELINE_CANDIDATE_CONFIG_ID],
            )
            self.assertFalse((result.output_dir / "audit_report.md").exists())
            self.assertFalse((result.output_dir / "r1_handoff.md").exists())
            self.assertFalse(result.summary["audit_report_generated"])
            self.assertFalse(result.summary["r1_handoff_generated"])

    def test_full_grid_request_is_blocked_for_first_submission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_r0_t10_formal_materialization(
                output_dir=Path(tmp) / "r0_t10",
                run_id="r0_t10_full_grid_blocked",
                code_commit="abcdef",
                full_grid_r0_t09=True,
            )

            self.assertEqual(result.summary["status"], "blocked")
            self.assertIn(
                "full_grid_requires_second_submission", result.summary["reason_codes"]
            )
            self.assertEqual(
                result.summary["full_grid_status"], "deferred_pending_review"
            )

    def test_cli_without_upstream_inputs_exits_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            command = [
                sys.executable,
                "scripts/r0/run_r0_t10_formal_materialization.py",
                "--output-dir",
                str(Path(tmp) / "r0_t10"),
                "--run-id",
                "r0_t10_cli",
                "--code-commit",
                "abcdef",
                "--data-root",
                str(Path(tmp) / "data"),
            ]
            completed = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 2)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["status"], "blocked")
            self.assertIn("formal_upstream_inputs_missing", summary["reason_codes"])


if __name__ == "__main__":
    unittest.main()
