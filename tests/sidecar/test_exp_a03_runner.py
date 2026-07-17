from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import duckdb

import scripts.sidecar.run_exp_a03_candidate_intralayer_redundancy_selection as runner
from scripts.sidecar.run_exp_a03_candidate_intralayer_redundancy_selection import (
    run_formal,
    run_synthetic,
)
from src.sidecar.exp_a03_candidate_intralayer_redundancy_selection_validator import (
    CONFIG_PATH,
)
from tests.sidecar.test_exp_a03_lineage import (
    INDICATORS,
    build_synthetic_input_package,
    sha256,
    write_json,
)


class ExpA03RunnerTest(unittest.TestCase):
    def test_synthetic_runner_is_atomic_and_counts_one_validation_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_synthetic_input_package(root / "inputs")
            run_id = "EXP-A03-20260717T000004000Z"
            result = run_synthetic(
                Namespace(
                    config=CONFIG_PATH,
                    input_manifest=inputs["manifest"],
                    input_root=inputs["input_root"],
                    output_root=root / run_id,
                    failure_root=root / "failures",
                    run_id=run_id,
                    reviewed_implementation_sha=None,
                    allow_synthetic_fixture=True,
                    allow_formal_run=False,
                )
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["core_validator_execution_count"], 1)
            self.assertEqual(result["anomaly_scan_execution_count"], 1)
            self.assertEqual(result["cheap_validation_execution_count"], 1)
            self.assertFalse(any((root / run_id).glob("*.duckdb")))

    def test_failure_preserves_compact_diagnostics_without_raw_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_synthetic_input_package(root / "inputs")
            run_id = "EXP-A03-20260717T000005000Z"
            with patch(
                "scripts.sidecar.run_exp_a03_candidate_intralayer_redundancy_selection.validate_package",
                return_value={
                    "task_id": "EXP-A03",
                    "run_id": run_id,
                    "status": "failed",
                    "errors": ["synthetic_validator_mutation"],
                },
            ):
                result = run_synthetic(
                    Namespace(
                        config=CONFIG_PATH,
                        input_manifest=inputs["manifest"],
                        input_root=inputs["input_root"],
                        output_root=root / run_id,
                        failure_root=root / "failures",
                        run_id=run_id,
                        reviewed_implementation_sha=None,
                        allow_synthetic_fixture=True,
                        allow_formal_run=False,
                    )
                )
            self.assertEqual(result["status"], "failed")
            self.assertFalse((root / run_id).exists())
            failure = Path(result["failure_package"])
            self.assertTrue((failure / "failure_summary.json").is_file())
            self.assertFalse(any(failure.rglob("*.duckdb")))
            self.assertFalse(
                '"usable_as_formal_result":true'
                in (failure / "failure_summary.json").read_text(encoding="utf-8")
            )

    def test_undefined_year_correlation_is_blocking_and_not_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_synthetic_input_package(root / "inputs")
            connection = duckdb.connect(str(inputs["raw"]))
            try:
                connection.execute(
                    "UPDATE exp_a01_raw_metrics SET raw_value=0.5 WHERE indicator_id=?",
                    (INDICATORS[1],),
                )
            finally:
                connection.close()
            manifest = json.loads(inputs["manifest"].read_text(encoding="utf-8"))
            raw_hash = sha256(inputs["raw"])
            manifest["input_artifacts"]["exp_a01_raw_metrics"]["sha256"] = raw_hash
            manifest["cross_artifact_bindings"]["a01_raw_sha256"] = raw_hash
            write_json(inputs["manifest"], manifest)
            run_id = "EXP-A03-20260717T000009000Z"
            result = run_synthetic(
                Namespace(
                    config=CONFIG_PATH,
                    input_manifest=inputs["manifest"],
                    input_root=inputs["input_root"],
                    output_root=root / run_id,
                    failure_root=root / "failures",
                    run_id=run_id,
                    reviewed_implementation_sha=None,
                    allow_synthetic_fixture=True,
                    allow_formal_run=False,
                )
            )
            self.assertEqual(result["status"], "failed")
            self.assertFalse((root / run_id).exists())
            failure = Path(result["failure_package"])
            validator = json.loads(
                (failure / "exp_a03_validator_result.json").read_text(encoding="utf-8")
            )
            anomaly = json.loads(
                (failure / "exp_a03_anomaly_scan.json").read_text(encoding="utf-8")
            )
            self.assertTrue(
                any(
                    error.startswith("undefined_year_correlation:")
                    for error in validator["errors"]
                )
            )
            self.assertEqual(anomaly["status"], "failed")

    def test_formal_missing_reviewed_sha_fails_before_raw_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_synthetic_input_package(root / "inputs")
            args = Namespace(
                config=CONFIG_PATH,
                input_manifest=inputs["manifest"],
                input_root=inputs["input_root"],
                output_root=root / "EXP-A03-20260717T000006000Z",
                failure_root=root / "failures",
                run_id="EXP-A03-20260717T000006000Z",
                reviewed_implementation_sha=None,
                allow_synthetic_fixture=False,
                allow_formal_run=True,
            )
            with patch(
                "scripts.sidecar.run_exp_a03_candidate_intralayer_redundancy_selection.duckdb.connect"
            ) as connect:
                with self.assertRaises(RuntimeError):
                    run_formal(args)
                connect.assert_not_called()

    def test_formal_exact_sha_clean_branch_gates_fail_before_raw_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_synthetic_input_package(root / "inputs")
            for mutation in ("sha", "dirty", "branch", "mode"):
                with self.subTest(mutation=mutation):
                    run_id = "EXP-A03-20260717T000007000Z"
                    args = Namespace(
                        config=CONFIG_PATH,
                        input_manifest=inputs["manifest"],
                        input_root=inputs["input_root"],
                        output_root=root / run_id,
                        failure_root=root / "failures",
                        run_id=run_id,
                        reviewed_implementation_sha="a" * 40,
                        allow_synthetic_fixture=False,
                        allow_formal_run=mutation != "mode",
                    )
                    with (
                        patch.object(
                            runner,
                            "_git_head",
                            return_value="b" * 40 if mutation == "sha" else "a" * 40,
                        ),
                        patch.object(
                            runner,
                            "_git_worktree_status",
                            return_value="dirty" if mutation == "dirty" else "",
                        ),
                        patch.object(
                            runner,
                            "_git_branch",
                            return_value="wrong-branch"
                            if mutation == "branch"
                            else runner.EXPECTED_BRANCH,
                        ),
                        patch.object(runner.duckdb, "connect") as connect,
                    ):
                        with self.assertRaises(RuntimeError):
                            run_formal(args)
                        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
