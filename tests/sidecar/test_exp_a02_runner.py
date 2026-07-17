from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from scripts.sidecar.run_exp_a02_raw_domain_availability_validity import run_synthetic
from scripts.sidecar.validate_exp_a02_raw_domain_availability_validity import (
    main as validate_main,
)
from src.sidecar.exp_a02_raw_domain_availability_validity import OUTPUT_FILES
from src.sidecar.exp_a02_raw_domain_availability_validity_validator import (
    CONFIG_PATH,
    cheap_validate_final_package,
    validate_package,
)
from tests.sidecar.test_exp_a02_lineage import build_synthetic_input_package


def run_existing_fixture(
    root: Path, inputs: dict[str, Path | int], run_id: str
) -> tuple[dict[str, Path | int], Path]:
    output = root / run_id
    result = run_synthetic(
        Namespace(
            config=CONFIG_PATH,
            input_manifest=inputs["manifest"],
            output_root=output,
            run_id=run_id,
            failure_root=root / "failures",
            allow_synthetic_fixture=True,
        )
    )
    if result["status"] != "passed":
        raise AssertionError(result)
    return inputs, output


def run_fixture(root: Path, run_id: str) -> tuple[dict[str, Path | int], Path]:
    inputs = build_synthetic_input_package(root / f"inputs-{run_id}")
    return run_existing_fixture(root, inputs, run_id)


class ExpA02RunnerTest(unittest.TestCase):
    def test_two_synthetic_runs_have_identical_compact_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_synthetic_input_package(root / "shared-inputs")
            _, first = run_existing_fixture(root, inputs, "EXP-A02-20260717T000001000Z")
            _, second = run_existing_fixture(
                root, inputs, "EXP-A02-20260717T000002000Z"
            )
            for profile_name in (
                "raw_domain_profile",
                "indicator_availability",
                "common_valid_availability",
                "validity_status_profile",
                "reason_code_profile",
                "reason_combination_profile",
                "year_availability",
                "security_availability",
                "extreme_value_sample",
            ):
                filename = OUTPUT_FILES[profile_name]
                self.assertEqual(
                    (first / filename).read_bytes(), (second / filename).read_bytes()
                )
            self.assertFalse(any(first.glob("*.duckdb")))
            self.assertFalse(any(second.glob("*.duckdb")))
            first_manifest = json.loads(
                (first / OUTPUT_FILES["manifest"]).read_text(encoding="utf-8")
            )
            second_manifest = json.loads(
                (second / OUTPUT_FILES["manifest"]).read_text(encoding="utf-8")
            )
            self.assertEqual(
                first_manifest["input_artifacts"], second_manifest["input_artifacts"]
            )
            self.assertEqual(
                {
                    name: first_manifest["output_artifacts"][name]["row_count"]
                    for name in first_manifest["output_artifacts"]
                    if name.endswith(".csv")
                },
                {
                    name: second_manifest["output_artifacts"][name]["row_count"]
                    for name in second_manifest["output_artifacts"]
                    if name.endswith(".csv")
                },
            )

    def test_runner_executes_one_core_and_one_cheap_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_synthetic_input_package(root / "inputs")
            run_id = "EXP-A02-20260717T000005000Z"
            with (
                patch(
                    "scripts.sidecar.run_exp_a02_raw_domain_availability_validity.validate_package",
                    wraps=validate_package,
                ) as core_validator,
                patch(
                    "scripts.sidecar.run_exp_a02_raw_domain_availability_validity.cheap_validate_final_package",
                    wraps=cheap_validate_final_package,
                ) as cheap_validator,
            ):
                _, output = run_existing_fixture(root, inputs, run_id)
            self.assertTrue(output.is_dir())
            self.assertEqual(core_validator.call_count, 1)
            self.assertEqual(cheap_validator.call_count, 1)

    def test_standalone_cli_validates_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, output = run_fixture(root, "EXP-A02-20260717T000003000Z")
            before = {
                path.name: path.read_bytes()
                for path in output.iterdir()
                if path.is_file()
            }
            exit_code = validate_main(
                [
                    "--config",
                    str(CONFIG_PATH),
                    "--input-manifest",
                    str(inputs["manifest"]),
                    "--package-dir",
                    str(output),
                    "--run-id",
                    "EXP-A02-20260717T000003000Z",
                    "--allow-synthetic-fixture",
                ]
            )
            self.assertEqual(exit_code, 0)
            after = {
                path.name: path.read_bytes()
                for path in output.iterdir()
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_diagnostics_contain_aggregate_metadata_not_row_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, output = run_fixture(root, "EXP-A02-20260717T000006000Z")
            forbidden_keys = {
                "raw_rows",
                "row_payload",
                "observations",
                "security_date_results",
            }

            def walk(value: object) -> list[str]:
                found: list[str] = []
                if isinstance(value, dict):
                    found.extend(str(key) for key in value if key in forbidden_keys)
                    for child in value.values():
                        found.extend(walk(child))
                elif isinstance(value, list):
                    for child in value:
                        found.extend(walk(child))
                return found

            for filename in (
                OUTPUT_FILES["manifest"],
                OUTPUT_FILES["validator_result"],
                OUTPUT_FILES["anomaly_scan"],
            ):
                payload = json.loads((output / filename).read_text(encoding="utf-8"))
                self.assertEqual(walk(payload), [])

    def test_failed_run_preserves_compact_diagnostics_without_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_synthetic_input_package(root / "inputs")
            run_id = "EXP-A02-20260717T000004000Z"
            output = root / run_id
            fake_result = {
                "task_id": "EXP-A02",
                "run_id": run_id,
                "status": "failed",
                "valid": False,
                "errors": ["forced_test_failure"],
                "mismatch_counts": {"aggregate_csv_mismatch": 1},
            }
            with patch(
                "scripts.sidecar.run_exp_a02_raw_domain_availability_validity.validate_package",
                return_value=fake_result,
            ):
                result = run_synthetic(
                    Namespace(
                        config=CONFIG_PATH,
                        input_manifest=inputs["manifest"],
                        output_root=output,
                        run_id=run_id,
                        failure_root=root / "failures",
                        allow_synthetic_fixture=True,
                    )
                )
            self.assertEqual(result["status"], "failed")
            self.assertFalse(output.exists())
            failure_package = root / "failures" / run_id / "package"
            self.assertTrue(failure_package.is_dir())
            self.assertTrue(
                (failure_package / OUTPUT_FILES["validator_result"]).is_file()
            )
            self.assertTrue((failure_package / OUTPUT_FILES["anomaly_scan"]).is_file())
            self.assertTrue(
                (failure_package / OUTPUT_FILES["raw_domain_profile"]).is_file()
            )
            self.assertTrue((failure_package / "failure_summary.json").is_file())
            self.assertFalse(any(failure_package.glob("*.duckdb")))
            summary = json.loads(
                (failure_package / "failure_summary.json").read_text(encoding="utf-8")
            )
            self.assertFalse(summary["published"])
            self.assertFalse(summary["formal_artifacts_generated"])
            self.assertFalse(summary["usable_as_formal_result"])
            self.assertFalse(
                (failure_package / OUTPUT_FILES["result_analysis"]).exists()
            )
            self.assertTrue((failure_package / OUTPUT_FILES["manifest"]).exists())
            preliminary_manifest = json.loads(
                (failure_package / OUTPUT_FILES["manifest"]).read_text(encoding="utf-8")
            )
            self.assertFalse(preliminary_manifest["final_manifest"])


if __name__ == "__main__":
    unittest.main()
