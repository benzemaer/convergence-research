from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.r0.candidate_artifact_engine import build_candidate_configs
from src.r0.main_grid_materialization_runner import (
    load_authorized_input,
    run_main_grid_materialization,
    validate_r0_t09_payload_coverage,
)
from src.r0.r0_t09_input_manifest_builder import (
    R0T09InputManifestBuilderError,
    build_r0_t09_input_manifest,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[2]


class R0T09InputManifestBuilderTest(unittest.TestCase):
    def test_builds_formal_manifest_payload_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = build_r0_t09_input_manifest(
                output_dir=Path(tmp) / "inputs",
                run_id="r0_t09_builder_test",
                code_commit="abcdef",
            )

            self.assertTrue(result.payload_path.is_file())
            self.assertTrue(result.manifest_path.is_file())
            self.assertTrue(result.summary_path.is_file())
            self.assertEqual(result.payload_sha256, sha256_file(result.payload_path))

            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["authorized_r0_input"])
            self.assertEqual(
                manifest["input_payload_path"], "r0_t09_full_grid_payload.json"
            )
            self.assertEqual(manifest["input_content_hash"], result.payload_sha256)
            self.assertNotIn("\\", manifest["input_payload_path"])

            authorized = load_authorized_input(result.manifest_path)
            guard = validate_r0_t09_payload_coverage(
                authorized.payload,
                [config.as_dict() for config in build_candidate_configs()],
            )
            self.assertEqual(guard["validity_status"], "valid")

            summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["coverage_summary"]["nested_wq_count"], 9)
            self.assertEqual(
                summary["coverage_summary"]["confirmation_wqk_state_count"], 108
            )
            self.assertFalse(summary["coverage_summary"]["contains_k1"])
            self.assertEqual(summary["coverage_summary"]["legacy_v1_field_count"], 0)
            self.assertEqual(
                summary["coverage_summary"]["future_or_return_field_count"], 0
            )

    def test_dry_run_accepts_generated_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = build_r0_t09_input_manifest(
                output_dir=Path(tmp) / "inputs",
                run_id="r0_t09_builder_test",
                code_commit="abcdef",
            )
            dry_run = run_main_grid_materialization(
                input_manifest=result.manifest_path,
                output_dir=Path(tmp) / "r0_t09_dry_run",
                dry_run=True,
                max_workers=2,
                run_id="r0_t09_builder_test_dry_run",
                code_commit="abcdef",
            )

            self.assertEqual(dry_run["status"], "dry_run")
            self.assertEqual(dry_run["candidate_config_count"], 27)
            self.assertEqual(dry_run["selected_config_count"], 27)
            self.assertEqual(dry_run["run_scope"], "full_grid")
            self.assertEqual(dry_run["max_workers"], 2)
            self.assertFalse(dry_run["artifacts_written"])
            self.assertEqual(
                dry_run["input_payload_coverage_guard"]["validity_status"], "valid"
            )

    def test_rejects_legacy_v1_field_from_supplied_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            t04 = root / "t04.json"
            t04.write_text(
                json.dumps(
                    {
                        "raw_metric_results": [
                            {
                                "security_id": "000001.SZ",
                                "trading_date": "2026-02-03",
                                "indicator_id": "V1_TurnoverShrink20_60",
                                "VolShrink20_60_raw": 0.1,
                                "raw_value": 0.1,
                                "validity_status": "valid",
                                "reason_codes": ["valid_no_blocker"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(R0T09InputManifestBuilderError, "forbidden"):
                build_r0_t09_input_manifest(
                    output_dir=root / "inputs",
                    run_id="r0_t09_builder_test",
                    code_commit="abcdef",
                    r0_t04_input=t04,
                )

    def test_rejects_confirmation_k1_from_supplied_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = build_r0_t09_input_manifest(
                output_dir=root / "seed",
                run_id="seed",
                code_commit="abcdef",
            )
            payload = json.loads(result.payload_path.read_text(encoding="utf-8"))
            payload["daily_confirmation_results"].append(
                {
                    "security_id": "000001.SZ",
                    "trading_date": "2026-02-03",
                    "percentile_window_W": 250,
                    "q": 0.20,
                    "weak_delta": 0.10,
                    "confirmation_k": 1,
                    "state_name": "S_PCVT",
                    "raw_state": True,
                    "raw_streak": 1,
                    "confirmed_state": True,
                    "validity_status": "valid",
                    "reason_codes": ["valid_no_blocker"],
                }
            )
            t07 = root / "t07.json"
            t07.write_text(
                json.dumps(
                    {
                        "daily_confirmation_results": payload[
                            "daily_confirmation_results"
                        ],
                        "confirmed_interval_results": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                R0T09InputManifestBuilderError, "coverage incomplete|K=1"
            ):
                build_r0_t09_input_manifest(
                    output_dir=root / "inputs",
                    run_id="r0_t09_builder_test",
                    code_commit="abcdef",
                    r0_t07_input=t07,
                )

    def test_cli_writes_manifest_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "inputs"
            command = [
                sys.executable,
                "scripts/r0/build_r0_t09_input_manifest.py",
                "--output-dir",
                str(output_dir),
                "--run-id",
                "r0_t09_cli_test",
                "--code-commit",
                "abcdef",
            ]
            completed = subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["status"], "completed")
            self.assertTrue((output_dir / "r0_t09_full_grid_payload.json").is_file())
            self.assertTrue((output_dir / "authorized_input_manifest.json").is_file())
            self.assertTrue((output_dir / "generation_summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
