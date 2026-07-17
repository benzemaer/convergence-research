from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from scripts.sidecar.run_exp_a03_candidate_intralayer_redundancy_selection import (
    run_synthetic,
)
from src.sidecar.exp_a03_candidate_intralayer_redundancy_selection_validator import (
    CONFIG_PATH,
    load_json,
    validate_package,
)
from tests.sidecar.test_exp_a03_lineage import build_synthetic_input_package


def run_fixture(root: Path, run_id: str) -> tuple[dict[str, object], Path]:
    inputs = build_synthetic_input_package(root / "inputs")
    output = root / run_id
    result = run_synthetic(
        Namespace(
            config=CONFIG_PATH,
            input_manifest=inputs["manifest"],
            input_root=inputs["input_root"],
            output_root=output,
            failure_root=root / "failures",
            run_id=run_id,
            reviewed_implementation_sha=None,
            allow_synthetic_fixture=True,
            allow_formal_run=False,
        )
    )
    if result["status"] != "passed":
        raise AssertionError(result)
    return inputs, output


class ExpA03ValidatorTest(unittest.TestCase):
    def test_standalone_validator_replays_lineage_and_persisted_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, output = run_fixture(root, "EXP-A03-20260717T000001000Z")
            result = validate_package(
                output,
                config=load_json(CONFIG_PATH),
                input_manifest_path=inputs["manifest"],
                input_root=inputs["input_root"],
                run_id=output.name,
                allow_synthetic_fixture=True,
                require_final_manifest=True,
            )
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual(result["core_validator_execution_count"], 1)

    def test_committed_csv_mutation_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, output = run_fixture(root, "EXP-A03-20260717T000002000Z")
            path = output / "exp_a03_pairwise_overall.csv"
            path.write_text(
                path.read_text(encoding="utf-8").replace(",231,", ",230,", 1),
                encoding="utf-8",
                newline="\n",
            )
            result = validate_package(
                output,
                config=load_json(CONFIG_PATH),
                input_manifest_path=inputs["manifest"],
                input_root=inputs["input_root"],
                run_id=output.name,
                allow_synthetic_fixture=True,
                require_final_manifest=True,
            )
            self.assertEqual(result["status"], "failed")
            self.assertTrue(
                any(
                    "output_hash_mismatch" in error or "aggregate_csv_mismatch" in error
                    for error in result["errors"]
                )
            )

    def test_disposition_mutation_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, output = run_fixture(root, "EXP-A03-20260717T000003000Z")
            path = output / "exp_a03_candidate_disposition.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["A_layer_registered"] = True
            path.write_text(
                json.dumps(payload, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            result = validate_package(
                output,
                config=load_json(CONFIG_PATH),
                input_manifest_path=inputs["manifest"],
                input_root=inputs["input_root"],
                run_id=output.name,
                allow_synthetic_fixture=True,
                require_final_manifest=True,
            )
            self.assertEqual(result["status"], "failed")
            self.assertTrue(
                any(
                    "governance" in error or "output_hash_mismatch" in error
                    for error in result["errors"]
                )
            )

    def test_each_compact_csv_mutation_is_detected(self) -> None:
        mutations = {
            "exp_a03_pairwise_overall.csv": ("common_count", "230"),
            "exp_a03_pairwise_year.csv": ("common_count", "20"),
            "exp_a03_pairwise_security.csv": ("common_count", "230"),
            "exp_a03_tail_overlap.csv": ("left_selected_count", "12"),
            "exp_a03_a2_a2b_conditional_profile.csv": ("row_count", "10"),
            "exp_a03_a2_a2b_variance_decomposition.csv": (
                "reconciliation_residual",
                "1.0",
            ),
            "exp_a03_stability_summary.csv": ("year_count", "10"),
        }
        for filename, (field, value) in mutations.items():
            with (
                self.subTest(filename=filename),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                inputs, output = run_fixture(root, "EXP-A03-20260717T000008000Z")
                path = output / filename
                rows = list(
                    csv.DictReader(path.read_text(encoding="utf-8").splitlines())
                )
                rows[0][field] = value
                buffer = io.StringIO(newline="")
                writer = csv.DictWriter(
                    buffer, fieldnames=rows[0].keys(), lineterminator="\n"
                )
                writer.writeheader()
                writer.writerows(rows)
                path.write_text(buffer.getvalue(), encoding="utf-8", newline="\n")
                result = validate_package(
                    output,
                    config=load_json(CONFIG_PATH),
                    input_manifest_path=inputs["manifest"],
                    input_root=inputs["input_root"],
                    run_id=output.name,
                    allow_synthetic_fixture=True,
                    require_final_manifest=True,
                )
                self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
