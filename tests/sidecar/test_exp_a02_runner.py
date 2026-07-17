from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.sidecar.run_exp_a02_raw_domain_availability_validity import (
    _formal_analysis_with_readiness,
    run_formal,
    run_synthetic,
)
from scripts.sidecar.validate_exp_a02_raw_domain_availability_validity import (
    main as validate_main,
)
from src.sidecar.exp_a02_raw_domain_availability_validity import OUTPUT_FILES
from src.sidecar.exp_a02_raw_domain_availability_validity import (
    build_result_analysis as build_a02_result_analysis,
)
from src.sidecar.exp_a02_raw_domain_availability_validity_validator import (
    CONFIG_PATH,
    cheap_validate_final_package,
    sha256_file,
    validate_package,
)
from tests.sidecar.test_exp_a02_lineage import (
    REVIEWED_ACTIVATION_SHA,
    build_formal_input_package,
    build_synthetic_input_package,
    write_json,
)


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


def run_formal_fixture(root: Path, run_id: str) -> tuple[dict[str, Any], Path]:
    inputs = build_formal_input_package(root / f"formal-inputs-{run_id}")
    output = root / run_id
    with (
        patch(
            "scripts.sidecar.run_exp_a02_raw_domain_availability_validity._git_head",
            return_value=REVIEWED_ACTIVATION_SHA,
        ),
        patch(
            "scripts.sidecar.run_exp_a02_raw_domain_availability_validity._git_worktree_status",
            return_value="",
        ),
        patch(
            "src.sidecar.exp_a02_raw_domain_availability_validity_validator.validate_handoff",
            return_value=inputs["formal_handoff_payload"],
        ),
    ):
        result = run_formal(
            Namespace(
                config=CONFIG_PATH,
                input_manifest=inputs["manifest"],
                input_root=inputs["input_root"],
                output_root=output,
                run_id=run_id,
                failure_root=root / "failures",
                allow_formal_run=True,
                reviewed_implementation_sha=REVIEWED_ACTIVATION_SHA,
            )
        )
    if result["status"] != "passed":
        raise AssertionError(result)
    return inputs, output


class ExpA02RunnerTest(unittest.TestCase):
    def test_formal_and_synthetic_modes_materialize_identical_csv_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, synthetic_output = run_fixture(root, "EXP-A02-20260717T000008000Z")
            formal_inputs, formal_output = run_formal_fixture(
                root, "EXP-A02-20260717T000009000Z"
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
                    (synthetic_output / filename).read_bytes(),
                    (formal_output / filename).read_bytes(),
                )
            self.assertFalse(any(formal_output.glob("*.duckdb")))
            manifest = json.loads(
                (formal_output / OUTPUT_FILES["manifest"]).read_text(encoding="utf-8")
            )
            self.assertFalse(manifest["synthetic_fixture"])
            self.assertTrue(manifest["formal_run_allowed"])
            self.assertTrue(manifest["formal_run_executed"])
            self.assertEqual(
                set(manifest["input_hashes_before"]),
                {
                    "exp_a01_accepted_result_handoff",
                    "exp_a01_raw_metrics",
                    "exp_a01_manifest",
                    "exp_a01_validator_result",
                    "exp_a01_anomaly_scan",
                },
            )
            self.assertTrue(
                (formal_output / OUTPUT_FILES["result_analysis"])
                .read_text(encoding="utf-8")
                .find(REVIEWED_ACTIVATION_SHA)
                >= 0
            )
            self.assertTrue(
                (formal_output / OUTPUT_FILES["result_analysis"])
                .read_text(encoding="utf-8")
                .rstrip()
                .endswith(
                    "ready_for_user_formal_result_review"
                    if manifest["anomaly_status"] == "passed"
                    else "needs_investigation_before_user_review"
                )
            )
            self.assertEqual(
                manifest["input_manifest_sha256"],
                sha256_file(Path(formal_inputs["manifest"])),
            )
            before = {
                path.name: path.read_bytes()
                for path in formal_output.iterdir()
                if path.is_file()
            }
            with patch(
                "src.sidecar.exp_a02_raw_domain_availability_validity_validator.validate_handoff",
                return_value=formal_inputs["formal_handoff_payload"],
            ):
                self.assertEqual(
                    validate_main(
                        [
                            "--config",
                            str(CONFIG_PATH),
                            "--input-manifest",
                            str(formal_inputs["manifest"]),
                            "--input-root",
                            str(formal_inputs["input_root"]),
                            "--package-dir",
                            str(formal_output),
                            "--run-id",
                            "EXP-A02-20260717T000009000Z",
                            "--allow-formal-run",
                            "--reviewed-implementation-sha",
                            REVIEWED_ACTIVATION_SHA,
                        ]
                    ),
                    0,
                )
            after = {
                path.name: path.read_bytes()
                for path in formal_output.iterdir()
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_formal_runner_uses_single_read_only_core_and_cheap_validation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_formal_input_package(root / "inputs")
            run_id = "EXP-A02-20260717T000010000Z"
            output = root / run_id
            with (
                patch(
                    "scripts.sidecar.run_exp_a02_raw_domain_availability_validity._git_head",
                    return_value=REVIEWED_ACTIVATION_SHA,
                ),
                patch(
                    "scripts.sidecar.run_exp_a02_raw_domain_availability_validity._git_worktree_status",
                    return_value="",
                ),
                patch(
                    "scripts.sidecar.run_exp_a02_raw_domain_availability_validity.validate_package",
                    wraps=validate_package,
                ) as core_validator,
                patch(
                    "scripts.sidecar.run_exp_a02_raw_domain_availability_validity.cheap_validate_final_package",
                    wraps=cheap_validate_final_package,
                ) as cheap_validator,
                patch(
                    "src.sidecar.exp_a02_raw_domain_availability_validity_validator._validator_profiles",
                    wraps=__import__(
                        "src.sidecar.exp_a02_raw_domain_availability_validity_validator",
                        fromlist=["_validator_profiles"],
                    )._validator_profiles,
                ) as aggregate_recompute,
                patch(
                    "scripts.sidecar.run_exp_a02_raw_domain_availability_validity.duckdb.connect",
                    wraps=__import__("duckdb").connect,
                ) as raw_open,
                patch(
                    "src.sidecar.exp_a02_raw_domain_availability_validity_validator.validate_handoff",
                    return_value=inputs["formal_handoff_payload"],
                ),
            ):
                result = run_formal(
                    Namespace(
                        config=CONFIG_PATH,
                        input_manifest=inputs["manifest"],
                        input_root=inputs["input_root"],
                        output_root=output,
                        run_id=run_id,
                        failure_root=root / "failures",
                        allow_formal_run=True,
                        reviewed_implementation_sha=REVIEWED_ACTIVATION_SHA,
                    )
                )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(core_validator.call_count, 1)
            self.assertEqual(cheap_validator.call_count, 1)
            self.assertEqual(aggregate_recompute.call_count, 1)
            self.assertTrue(raw_open.call_count >= 3)
            self.assertTrue(
                all(
                    call.kwargs.get("read_only") is True
                    for call in raw_open.call_args_list
                )
            )
            self.assertFalse(any(output.glob("*.duckdb")))

    def test_exact_sha_gate_fails_before_raw_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_formal_input_package(root / "inputs")
            cases = (
                (
                    "bad-format",
                    "not-a-sha",
                    True,
                    REVIEWED_ACTIVATION_SHA,
                    "",
                    "EXP-A02-20260717T000011001Z",
                ),
                (
                    "head-mismatch",
                    REVIEWED_ACTIVATION_SHA,
                    True,
                    "b" * 40,
                    "",
                    "EXP-A02-20260717T000011002Z",
                ),
                (
                    "dirty",
                    REVIEWED_ACTIVATION_SHA,
                    True,
                    REVIEWED_ACTIVATION_SHA,
                    " M file",
                    "EXP-A02-20260717T000011003Z",
                ),
                (
                    "missing-formal-flag",
                    REVIEWED_ACTIVATION_SHA,
                    False,
                    REVIEWED_ACTIVATION_SHA,
                    "",
                    "EXP-A02-20260717T000011004Z",
                ),
                (
                    "missing-reviewed-sha",
                    None,
                    True,
                    REVIEWED_ACTIVATION_SHA,
                    "",
                    "EXP-A02-20260717T000011005Z",
                ),
            )
            for (
                case,
                reviewed_sha,
                allow_formal,
                head,
                status,
                run_id,
            ) in cases:
                with (
                    self.subTest(case=case),
                    patch(
                        "scripts.sidecar.run_exp_a02_raw_domain_availability_validity._git_head",
                        return_value=head,
                    ),
                    patch(
                        "scripts.sidecar.run_exp_a02_raw_domain_availability_validity._git_worktree_status",
                        return_value=status,
                    ),
                    patch(
                        "scripts.sidecar.run_exp_a02_raw_domain_availability_validity.duckdb.connect"
                    ) as runner_raw_open,
                    patch(
                        "src.sidecar.exp_a02_raw_domain_availability_validity_validator.duckdb.connect"
                    ) as validator_raw_open,
                ):
                    with self.assertRaises(Exception):
                        run_formal(
                            Namespace(
                                config=CONFIG_PATH,
                                input_manifest=inputs["manifest"],
                                input_root=inputs["input_root"],
                                output_root=root / run_id,
                                run_id=run_id,
                                failure_root=root / "failures",
                                allow_formal_run=allow_formal,
                                reviewed_implementation_sha=reviewed_sha,
                            )
                        )
                    runner_raw_open.assert_not_called()
                    validator_raw_open.assert_not_called()

    def test_formal_input_mutation_is_preserved_as_failed_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_formal_input_package(root / "inputs")
            run_id = "EXP-A02-20260717T000012000Z"
            output = root / run_id
            from scripts.sidecar import (
                run_exp_a02_raw_domain_availability_validity as runner,
            )

            original_anomaly_scan = runner.build_anomaly_scan

            def mutate_input(*args: object, **kwargs: object) -> dict[str, object]:
                result = original_anomaly_scan(*args, **kwargs)
                handoff = Path(inputs["handoff"])
                handoff.write_bytes(handoff.read_bytes() + b" ")
                return result

            with (
                patch(
                    "scripts.sidecar.run_exp_a02_raw_domain_availability_validity._git_head",
                    return_value=REVIEWED_ACTIVATION_SHA,
                ),
                patch(
                    "scripts.sidecar.run_exp_a02_raw_domain_availability_validity._git_worktree_status",
                    return_value="",
                ),
                patch(
                    "scripts.sidecar.run_exp_a02_raw_domain_availability_validity.build_anomaly_scan",
                    side_effect=mutate_input,
                ),
                patch(
                    "src.sidecar.exp_a02_raw_domain_availability_validity_validator.validate_handoff",
                    return_value=inputs["formal_handoff_payload"],
                ),
            ):
                result = run_formal(
                    Namespace(
                        config=CONFIG_PATH,
                        input_manifest=inputs["manifest"],
                        input_root=inputs["input_root"],
                        output_root=output,
                        run_id=run_id,
                        failure_root=root / "failures",
                        allow_formal_run=True,
                        reviewed_implementation_sha=REVIEWED_ACTIVATION_SHA,
                    )
                )
            self.assertEqual(result["status"], "failed")
            self.assertFalse(output.exists())
            failure_package = root / "failures" / run_id / "package"
            self.assertTrue(failure_package.is_dir())
            self.assertFalse(any(failure_package.glob("*.duckdb")))
            summary = json.loads(
                (failure_package / "failure_summary.json").read_text(encoding="utf-8")
            )
            self.assertGreater(summary["input_hash_changed_count"], 0)
            self.assertNotEqual(
                summary["input_hashes_before"], summary["input_hashes_after"]
            )

    def test_formal_analysis_readiness_values(self) -> None:
        analysis = "section\nold_readiness\n"
        self.assertTrue(
            _formal_analysis_with_readiness(analysis, "passed").endswith(
                "ready_for_user_formal_result_review\n"
            )
        )
        self.assertTrue(
            _formal_analysis_with_readiness(
                analysis, "passed_with_investigation_items"
            ).endswith("needs_investigation_before_user_review\n")
        )

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

    def test_preliminary_manifest_mismatch_is_not_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_synthetic_input_package(root / "inputs")
            run_id = "EXP-A02-20260717T000013000Z"
            output = root / run_id
            original_validate = validate_package

            def corrupt_preliminary(
                package_root: Path, **kwargs: object
            ) -> dict[str, Any]:
                manifest_path = package_root / OUTPUT_FILES["manifest"]
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["phase"] = "wrong_preliminary_phase"
                write_json(manifest_path, manifest)
                return original_validate(package_root, **kwargs)

            with patch(
                "scripts.sidecar.run_exp_a02_raw_domain_availability_validity.validate_package",
                side_effect=corrupt_preliminary,
            ) as core_validator:
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
            self.assertEqual(result["failure_stage"], "anomaly_scan")
            self.assertEqual(core_validator.call_count, 1)
            self.assertFalse(output.exists())
            failure_package = root / "failures" / run_id / "package"
            validator_result = json.loads(
                (failure_package / OUTPUT_FILES["validator_result"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(validator_result["status"], "failed")
            self.assertGreater(
                validator_result["mismatch_counts"]["output_manifest_mismatch"],
                0,
            )

    def test_cheap_final_manifest_rejects_governance_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_synthetic_input_package(root / "inputs")
            run_id = "EXP-A02-20260717T000014000Z"
            output = root / run_id
            original_cheap = cheap_validate_final_package

            def corrupt_final(package_root: Path, **kwargs: object) -> dict[str, Any]:
                manifest_path = package_root / OUTPUT_FILES["manifest"]
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["EXP_A03_started"] = True
                write_json(manifest_path, manifest)
                return original_cheap(package_root, **kwargs)

            with patch(
                "scripts.sidecar.run_exp_a02_raw_domain_availability_validity.cheap_validate_final_package",
                side_effect=corrupt_final,
            ) as cheap_validator:
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
            self.assertEqual(result["failure_stage"], "cheap_final_package_validation")
            self.assertEqual(cheap_validator.call_count, 1)
            self.assertFalse(output.exists())

    def test_runner_rejects_analysis_missing_middle_section(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_synthetic_input_package(root / "inputs")
            run_id = "EXP-A02-20260717T000007000Z"
            output = root / run_id

            def missing_section(**kwargs: object) -> str:
                return build_a02_result_analysis(**kwargs).replace(
                    "## 11. Year availability\n", "", 1
                )

            with patch(
                "scripts.sidecar.run_exp_a02_raw_domain_availability_validity.build_result_analysis",
                side_effect=missing_section,
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
            self.assertEqual(result["failure_stage"], "cheap_final_package_validation")
            self.assertFalse(output.exists())
            failure_package = root / "failures" / run_id / "package"
            self.assertTrue(
                (failure_package / OUTPUT_FILES["result_analysis"]).is_file()
            )

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
