from __future__ import annotations

import csv
import json
import tempfile
import unittest
from argparse import Namespace
from collections.abc import Callable
from pathlib import Path

import duckdb

from scripts.sidecar.run_exp_a02_raw_domain_availability_validity import run_synthetic
from src.sidecar.exp_a02_raw_domain_availability_validity import OUTPUT_FILES
from src.sidecar.exp_a02_raw_domain_availability_validity_validator import (
    CONFIG_PATH,
    validate_package,
)
from tests.sidecar.test_exp_a02_lineage import (
    build_synthetic_input_package,
    sha256,
    write_json,
)


def run_fixture(root: Path) -> tuple[dict[str, Path | int], Path, str]:
    inputs = build_synthetic_input_package(root / "inputs")
    run_id = "EXP-A02-20260717T000000000Z"
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
    return inputs, output, run_id


def refresh_raw_binding(manifest_path: Path, raw_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    connection = duckdb.connect(str(raw_path), read_only=True)
    try:
        row_count = int(
            connection.execute("SELECT COUNT(*) FROM exp_a01_raw_metrics").fetchone()[0]
        )
    finally:
        connection.close()
    raw_hash = sha256(raw_path)
    declaration = manifest["input_artifacts"]["exp_a01_raw_metrics"]
    declaration["sha256"] = raw_hash
    declaration["row_count"] = row_count
    manifest["cross_artifact_bindings"]["raw_artifact_sha256"] = raw_hash
    write_json(manifest_path, manifest)


def mutate_raw(raw_path: Path, mutation: str) -> None:
    connection = duckdb.connect(str(raw_path))
    try:
        if mutation == "delete":
            connection.execute(
                """DELETE FROM exp_a01_raw_metrics
                WHERE indicator_id='A1_LogBodyCenterToMACloudCenter_5_60'
                  AND security_id='SEC001' AND observation_sequence=0"""
            )
        elif mutation == "duplicate":
            connection.execute(
                """INSERT INTO exp_a01_raw_metrics
                SELECT * FROM exp_a01_raw_metrics
                WHERE indicator_id='A1_LogBodyCenterToMACloudCenter_5_60'
                  AND security_id='SEC001' AND observation_sequence=0"""
            )
        elif mutation == "unknown_indicator":
            connection.execute(
                """UPDATE exp_a01_raw_metrics SET indicator_id='UNKNOWN'
                WHERE indicator_id='A1_LogBodyCenterToMACloudCenter_5_60'
                  AND security_id='SEC001' AND observation_sequence=0"""
            )
        elif mutation == "valid_null":
            connection.execute(
                """UPDATE exp_a01_raw_metrics SET raw_value=NULL
                WHERE indicator_id='A1_LogBodyCenterToMACloudCenter_5_60'
                  AND security_id='SEC001' AND observation_sequence=1"""
            )
        elif mutation == "nonvalid_nonnull":
            connection.execute(
                """UPDATE exp_a01_raw_metrics SET raw_value=0.25
                WHERE indicator_id='A1_LogBodyCenterToMACloudCenter_5_60'
                  AND security_id='SEC002' AND observation_sequence=8"""
            )
        elif mutation == "blocked_nonnull":
            connection.execute(
                """UPDATE exp_a01_raw_metrics SET raw_value=0.25
                WHERE indicator_id='A1_LogBodyCenterToMACloudCenter_5_60'
                  AND security_id='SEC002' AND observation_sequence=9"""
            )
        elif mutation == "a1_negative":
            connection.execute(
                """UPDATE exp_a01_raw_metrics SET raw_value=-1.0
                WHERE indicator_id='A1_LogBodyCenterToMACloudCenter_5_60'
                  AND security_id='SEC001' AND observation_sequence=1"""
            )
        elif mutation == "a2_above_one":
            connection.execute(
                """UPDATE exp_a01_raw_metrics SET raw_value=1.1
                WHERE indicator_id='A2_BodyCenterOutsideMACloudRate20_5_60'
                  AND security_id='SEC001' AND observation_sequence=1"""
            )
        elif mutation == "a2_off_grid":
            connection.execute(
                """UPDATE exp_a01_raw_metrics SET raw_value=0.123
                WHERE indicator_id='A2_BodyCenterOutsideMACloudRate20_5_60'
                  AND security_id='SEC001' AND observation_sequence=1"""
            )
        elif mutation == "a2_a2b_status":
            connection.execute(
                """UPDATE exp_a01_raw_metrics
                SET validity_status='unknown', raw_value=NULL,
                    reason_codes_json='[\"missing_required_history\"]'
                WHERE indicator_id='A2_BodyCenterOutsideMACloudRate20_5_60'
                  AND security_id='SEC001' AND observation_sequence=1"""
            )
        elif mutation == "a2_a2b_reason":
            connection.execute(
                """UPDATE exp_a01_raw_metrics
                SET reason_codes_json='[\"window_insufficient\"]'
                WHERE indicator_id='A2_BodyCenterOutsideMACloudRate20_5_60'
                  AND security_id='SEC001' AND observation_sequence=1"""
            )
        elif mutation == "a2_valid_a1_nonvalid":
            connection.execute(
                """UPDATE exp_a01_raw_metrics
                SET validity_status='unknown', raw_value=NULL,
                    reason_codes_json='[\"missing_required_history\"]'
                WHERE indicator_id='A1_LogBodyCenterToMACloudCenter_5_60'
                  AND security_id='SEC001' AND observation_sequence=1"""
            )
        else:
            raise AssertionError(f"unknown raw mutation: {mutation}")
    finally:
        connection.close()


def mutate_csv(
    package_root: Path,
    filename: str,
    field: str,
    value: str,
    predicate: Callable[[dict[str, str]], bool] | None = None,
) -> None:
    path = package_root / filename
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = rows[0].keys()
    changed = False
    for row in rows:
        if predicate is None or predicate(row):
            row[field] = value
            changed = True
            break
    if not changed:
        raise AssertionError(f"no CSV row matched {filename}:{field}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, lineterminator="\n", extrasaction="raise"
        )
        writer.writeheader()
        writer.writerows(rows)


class ExpA02ValidatorTest(unittest.TestCase):
    def assert_package_passes(
        self, package_root: Path, manifest: Path, run_id: str
    ) -> None:
        result = validate_package(
            package_root,
            config=json.loads(CONFIG_PATH.read_text(encoding="utf-8")),
            input_manifest_path=manifest,
            run_id=run_id,
            require_final_manifest=True,
            allow_synthetic_fixture=True,
            require_diagnostics=True,
        )
        self.assertEqual(result["status"], "passed", result)

    def test_standalone_validator_replays_full_synthetic_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, output, run_id = run_fixture(root)
            self.assert_package_passes(output, inputs["manifest"], run_id)

    def test_raw_lineage_and_domain_mutations_fail_closed(self) -> None:
        mutations = (
            "delete",
            "duplicate",
            "unknown_indicator",
            "valid_null",
            "nonvalid_nonnull",
            "blocked_nonnull",
            "a1_negative",
            "a2_above_one",
            "a2_off_grid",
            "a2_a2b_status",
            "a2_a2b_reason",
            "a2_valid_a1_nonvalid",
        )
        for mutation in mutations:
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                inputs, output, run_id = run_fixture(root)
                mutate_raw(inputs["raw"], mutation)
                refresh_raw_binding(inputs["manifest"], inputs["raw"])
                result = validate_package(
                    output,
                    config=json.loads(CONFIG_PATH.read_text(encoding="utf-8")),
                    input_manifest_path=inputs["manifest"],
                    run_id=run_id,
                    require_final_manifest=True,
                    allow_synthetic_fixture=True,
                    require_diagnostics=True,
                )
                self.assertEqual(result["status"], "failed")
                self.assertGreater(sum(result["mismatch_counts"].values()), 0)

    def test_each_compact_aggregate_family_is_checked(self) -> None:
        mutations = (
            (
                OUTPUT_FILES["raw_domain_profile"],
                "valid_count",
                "19",
                None,
            ),
            (
                OUTPUT_FILES["indicator_availability"],
                "native_valid_rate_expected",
                "0.1",
                None,
            ),
            (
                OUTPUT_FILES["raw_domain_profile"],
                "q01_value",
                "999",
                None,
            ),
            (
                OUTPUT_FILES["reason_code_profile"],
                "row_count",
                "0",
                lambda row: row["reason_code"] == "valid_no_blocker",
            ),
            (
                OUTPUT_FILES["year_availability"],
                "valid_count",
                "0",
                None,
            ),
            (
                OUTPUT_FILES["security_availability"],
                "valid_count",
                "0",
                None,
            ),
            (OUTPUT_FILES["extreme_value_sample"], "raw_value", "999", None),
        )
        for filename, field, value, predicate in mutations:
            with (
                self.subTest(filename=filename, field=field),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                inputs, output, run_id = run_fixture(root)
                mutate_csv(output, filename, field, value, predicate)
                result = validate_package(
                    output,
                    config=json.loads(CONFIG_PATH.read_text(encoding="utf-8")),
                    input_manifest_path=inputs["manifest"],
                    run_id=run_id,
                    require_final_manifest=True,
                    allow_synthetic_fixture=True,
                    require_diagnostics=True,
                )
                self.assertEqual(result["status"], "failed")
                self.assertGreater(
                    result["mismatch_counts"]["aggregate_csv_mismatch"], 0
                )

    def test_lineage_and_evidence_artifact_mutations_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, output, run_id = run_fixture(root)
            manifest = json.loads(inputs["manifest"].read_text(encoding="utf-8"))
            manifest["cross_artifact_bindings"]["implementation_sha"] = "0" * 40
            write_json(inputs["manifest"], manifest)
            result = validate_package(
                output,
                config=json.loads(CONFIG_PATH.read_text(encoding="utf-8")),
                input_manifest_path=inputs["manifest"],
                run_id=run_id,
                require_final_manifest=True,
                allow_synthetic_fixture=True,
                require_diagnostics=True,
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["mismatch_counts"]["lineage_mismatch"], 1)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, output, run_id = run_fixture(root)
            validator_path = output / OUTPUT_FILES["validator_result"]
            validator = json.loads(validator_path.read_text(encoding="utf-8"))
            validator["status"] = "failed"
            validator["valid"] = False
            write_json(validator_path, validator)
            result = validate_package(
                output,
                config=json.loads(CONFIG_PATH.read_text(encoding="utf-8")),
                input_manifest_path=inputs["manifest"],
                run_id=run_id,
                require_final_manifest=True,
                allow_synthetic_fixture=True,
                require_diagnostics=True,
            )
            self.assertEqual(result["status"], "failed")
            self.assertGreater(
                result["mismatch_counts"]["validator_artifact_mismatch"], 0
            )


if __name__ == "__main__":
    unittest.main()
