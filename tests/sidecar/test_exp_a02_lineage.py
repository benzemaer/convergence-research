from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import duckdb

from src.sidecar.exp_a02_raw_domain_availability_validity import (
    A01_IMPLEMENTATION_SHA,
    A01_RESULT_COMMIT,
    A01_RUN_ID,
    RAW_COLUMNS,
)
from src.sidecar.exp_a02_raw_domain_availability_validity_validator import (
    EXPECTED_MANIFEST_ARTIFACTS,
    validate_handoff,
    validate_input_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
A01_RESULT_ROOT = ROOT / "data/generated/sidecar/exp_a01/EXP-A01-20260717T040145984Z"
HANDOFF_PATH = A01_RESULT_ROOT / "exp_a01_accepted_result_handoff.json"
REVIEWED_ACTIVATION_SHA = "a" * 40


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_synthetic_raw(path: Path) -> int:
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE exp_a01_raw_metrics (
              run_id VARCHAR,
              security_id VARCHAR,
              trading_date DATE,
              observation_sequence INTEGER,
              expected_observation_status VARCHAR,
              indicator_id VARCHAR,
              raw_metric_name VARCHAR,
              raw_value DOUBLE,
              validity_status VARCHAR,
              reason_codes_json VARCHAR,
              input_window_start DATE,
              input_window_end DATE,
              required_observation_count INTEGER,
              actual_valid_observation_count INTEGER,
              metric_engine_version VARCHAR,
              source_ref VARCHAR
            )
            """
        )
        indicators = (
            "A1_LogBodyCenterToMACloudCenter_5_60",
            "A2_BodyCenterOutsideMACloudRate20_5_60",
            "A2b_BodyToMACloudGapMean20_5_60",
        )
        rows: list[tuple[Any, ...]] = []
        start = date(2019, 12, 20)
        for key_index in range(24):
            security_id = "SEC001" if key_index < 12 else "SEC002"
            sequence = key_index % 12
            trading_date = start + timedelta(days=key_index)
            if key_index < 20:
                expected_status = "present"
                validity = "valid"
                reasons = ["valid_no_blocker"]
            elif key_index == 21:
                expected_status = "listing_pause"
                validity = "blocked"
                reasons = ["listing_pause_in_required_window"]
            elif key_index == 22:
                expected_status = "unresolved"
                validity = "diagnostic_required"
                reasons = ["reopen_after_suspension"]
            else:
                expected_status = "missing"
                validity = "unknown"
                reasons = ["missing_required_history"]
            reason_json = json.dumps(reasons, separators=(",", ":"))
            a2_value = 1.0 if key_index == 19 else float(key_index % 20) / 20.0
            values = (
                0.0 if key_index == 0 else float(key_index + 1) / 10.0,
                a2_value,
                0.0 if key_index == 0 else float(key_index + 1) / 5.0,
            )
            for indicator_id, value in zip(indicators, values, strict=True):
                rows.append(
                    (
                        A01_RUN_ID,
                        security_id,
                        trading_date,
                        sequence,
                        expected_status,
                        indicator_id,
                        indicator_id,
                        value if validity == "valid" else None,
                        validity,
                        reason_json,
                        trading_date - timedelta(days=20),
                        trading_date,
                        20,
                        20 if validity == "valid" else 0,
                        "EXP-A01-SYNTHETIC",
                        f"synthetic:{security_id}:{trading_date.isoformat()}:{indicator_id}",
                    )
                )
        connection.executemany(
            "INSERT INTO exp_a01_raw_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        return len(rows)
    finally:
        connection.close()


def build_synthetic_input_package(root: Path) -> dict[str, Path | int]:
    root.mkdir(parents=True, exist_ok=True)
    raw_path = root / "exp_a01_raw_metrics.duckdb"
    row_count = create_synthetic_raw(raw_path)
    copied = {
        "exp_a01_accepted_result_handoff": root
        / "exp_a01_accepted_result_handoff.json",
        "exp_a01_manifest": root / "exp_a01_manifest.json",
        "exp_a01_validator_result": root / "exp_a01_validator_result.json",
        "exp_a01_anomaly_scan": root / "exp_a01_anomaly_scan.json",
    }
    shutil.copyfile(HANDOFF_PATH, copied["exp_a01_accepted_result_handoff"])
    for artifact_id, filename in (
        ("exp_a01_manifest", "exp_a01_manifest.json"),
        ("exp_a01_validator_result", "exp_a01_validator_result.json"),
        ("exp_a01_anomaly_scan", "exp_a01_anomaly_scan.json"),
    ):
        shutil.copyfile(A01_RESULT_ROOT / filename, copied[artifact_id])

    declarations: dict[str, dict[str, Any]] = {
        "exp_a01_accepted_result_handoff": {
            "artifact_id": "exp_a01_accepted_result_handoff",
            "artifact_kind": "handoff_json",
            "filename": copied["exp_a01_accepted_result_handoff"].name,
            "path": copied["exp_a01_accepted_result_handoff"].name,
            "path_policy": "synthetic_fixture",
            "sha256": sha256(copied["exp_a01_accepted_result_handoff"]),
            "required_json_fields": [
                "task_id",
                "status",
                "formal_result_review_status",
                "accepted_run_id",
                "implementation_sha",
                "result_commit",
                "formal_data_version",
                "raw_artifact",
                "compact_result",
                "downstream_authorization",
            ],
        },
        "exp_a01_raw_metrics": {
            "artifact_id": "exp_a01_raw_metrics",
            "artifact_kind": "duckdb_table",
            "filename": raw_path.name,
            "path": raw_path.name,
            "path_policy": "synthetic_fixture",
            "sha256": sha256(raw_path),
            "table": "exp_a01_raw_metrics",
            "row_count": row_count,
            "required_columns": list(RAW_COLUMNS),
            "security_count": 2,
            "date_min": "2019-12-20",
            "date_max": "2020-01-12",
        },
        "exp_a01_manifest": {
            "artifact_id": "exp_a01_manifest",
            "artifact_kind": "a01_manifest_json",
            "filename": copied["exp_a01_manifest"].name,
            "path": copied["exp_a01_manifest"].name,
            "path_policy": "synthetic_fixture",
            "sha256": sha256(copied["exp_a01_manifest"]),
            "required_json_fields": [
                "task_id",
                "run_id",
                "reviewed_implementation_sha",
                "input_manifest_sha256",
                "output_artifacts",
            ],
        },
        "exp_a01_validator_result": {
            "artifact_id": "exp_a01_validator_result",
            "artifact_kind": "a01_validator_json",
            "filename": copied["exp_a01_validator_result"].name,
            "path": copied["exp_a01_validator_result"].name,
            "path_policy": "synthetic_fixture",
            "sha256": sha256(copied["exp_a01_validator_result"]),
            "required_json_fields": [
                "task_id",
                "run_id",
                "status",
                "valid",
                "mismatch_counts",
            ],
        },
        "exp_a01_anomaly_scan": {
            "artifact_id": "exp_a01_anomaly_scan",
            "artifact_kind": "a01_anomaly_json",
            "filename": copied["exp_a01_anomaly_scan"].name,
            "path": copied["exp_a01_anomaly_scan"].name,
            "path_policy": "synthetic_fixture",
            "sha256": sha256(copied["exp_a01_anomaly_scan"]),
            "required_json_fields": [
                "task_id",
                "run_id",
                "status",
                "blocking_anomalies",
                "investigation_items",
            ],
        },
    }
    manifest = {
        "$schema": (
            "../../schemas/sidecar/exp_a02_authorized_input_manifest.schema.json"
        ),
        "manifest_type": "exp_a02_synthetic_input_manifest",
        "manifest_version": "1.0.0",
        "task_id": "EXP-A02",
        "authorized_for_task": "EXP-A02",
        "formal_data_version": False,
        "authorization": {
            "status": "synthetic_fixture_only",
            "formal_run_allowed": False,
            "evidence": "EXP-A02 implementation synthetic fixture contract",
        },
        "input_artifacts": declarations,
        "cross_artifact_bindings": {
            "accepted_run_id": A01_RUN_ID,
            "implementation_sha": A01_IMPLEMENTATION_SHA,
            "result_commit": A01_RESULT_COMMIT,
            "raw_artifact_sha256": declarations["exp_a01_raw_metrics"]["sha256"],
            "raw_row_count": row_count,
            "raw_key_count": row_count // 3,
            "security_count": declarations["exp_a01_raw_metrics"]["security_count"],
            "date_min": declarations["exp_a01_raw_metrics"]["date_min"],
            "date_max": declarations["exp_a01_raw_metrics"]["date_max"],
            "a01_manifest_sha256": declarations["exp_a01_manifest"]["sha256"],
            "validator_status": "passed",
            "anomaly_status": "passed",
        },
    }
    manifest_path = root / "exp_a02_synthetic_input_manifest.json"
    write_json(manifest_path, manifest)
    return {
        "manifest": manifest_path,
        "raw": raw_path,
        "handoff": copied["exp_a01_accepted_result_handoff"],
        "row_count": row_count,
    }


def build_formal_input_package(
    root: Path,
    reviewed_implementation_sha: str = REVIEWED_ACTIVATION_SHA,
) -> dict[str, Path | int | str]:
    package = build_synthetic_input_package(root)
    manifest_path = Path(package["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    handoff_path = Path(package["handoff"])
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    raw_declaration = manifest["input_artifacts"]["exp_a01_raw_metrics"]
    handoff["raw_artifact"].update(
        {
            "sha256": raw_declaration["sha256"],
            "row_count": raw_declaration["row_count"],
            "expected_index_row_count": manifest["cross_artifact_bindings"][
                "raw_key_count"
            ],
            "security_count": raw_declaration["security_count"],
            "date_min": raw_declaration["date_min"],
            "date_max": raw_declaration["date_max"],
        }
    )
    handoff["compact_result"]["manifest_sha256"] = manifest["input_artifacts"][
        "exp_a01_manifest"
    ]["sha256"]
    write_json(handoff_path, handoff)
    manifest["input_artifacts"]["exp_a01_accepted_result_handoff"]["sha256"] = sha256(
        handoff_path
    )
    manifest["manifest_type"] = "exp_a02_authorized_input_manifest"
    manifest["authorization"] = {
        "status": "approved",
        "formal_run_allowed": True,
        "reviewed_implementation_sha": reviewed_implementation_sha,
        "authorized_for_task": "EXP-A02",
        "authorization_scope": "EXP-A02 formal raw-domain availability validity only",
    }
    for declaration in manifest["input_artifacts"].values():
        declaration["path_policy"] = "relative_to_manifest"
    formal_manifest = root / "exp_a02_authorized_input_manifest.json"
    write_json(formal_manifest, manifest)
    package["manifest"] = formal_manifest
    package["input_root"] = root
    return package


class ExpA02LineageTest(unittest.TestCase):
    def test_accepted_handoff_is_schema_valid(self) -> None:
        handoff = validate_handoff(HANDOFF_PATH)
        self.assertEqual(handoff["status"], "completed_accepted")
        self.assertTrue(handoff["downstream_authorization"]["EXP_A02_input_eligible"])

    def test_synthetic_manifest_replays_exactly_five_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = build_synthetic_input_package(Path(temporary))
            result = validate_input_manifest(
                package["manifest"],
                input_root=None,
                allow_synthetic_fixture=True,
                allow_formal_run=False,
                reviewed_implementation_sha=None,
            )
            self.assertEqual(
                set(result["declarations"]), set(EXPECTED_MANIFEST_ARTIFACTS)
            )
            self.assertEqual(result["metadata"]["exp_a01_raw_metrics"]["key_count"], 24)

    def test_manifest_mutations_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = build_synthetic_input_package(root)
            original = json.loads(package["manifest"].read_text(encoding="utf-8"))
            mutated = copy.deepcopy(original)
            mutated["cross_artifact_bindings"]["accepted_run_id"] = "wrong"
            mutated_path = root / "mutated.json"
            write_json(mutated_path, mutated)
            with self.assertRaises(Exception):
                validate_input_manifest(
                    mutated_path,
                    input_root=None,
                    allow_synthetic_fixture=True,
                    allow_formal_run=False,
                    reviewed_implementation_sha=None,
                )

            mutated = copy.deepcopy(original)
            mutated["input_artifacts"]["d3_t08"] = mutated["input_artifacts"].pop(
                "exp_a01_anomaly_scan"
            )
            write_json(mutated_path, mutated)
            with self.assertRaises(Exception):
                validate_input_manifest(
                    mutated_path,
                    input_root=None,
                    allow_synthetic_fixture=True,
                    allow_formal_run=False,
                    reviewed_implementation_sha=None,
                )

    def test_each_declared_lineage_binding_mutation_fails_closed(self) -> None:
        mutations = (
            (
                "accepted_run_id",
                ("cross_artifact_bindings", "accepted_run_id"),
                "wrong",
            ),
            (
                "implementation_sha",
                ("cross_artifact_bindings", "implementation_sha"),
                "0" * 40,
            ),
            (
                "result_commit",
                ("cross_artifact_bindings", "result_commit"),
                "0" * 40,
            ),
            (
                "raw_sha",
                ("input_artifacts", "exp_a01_raw_metrics", "sha256"),
                "0" * 64,
            ),
            (
                "raw_row_count",
                ("input_artifacts", "exp_a01_raw_metrics", "row_count"),
                0,
            ),
            (
                "manifest_sha",
                ("cross_artifact_bindings", "a01_manifest_sha256"),
                "0" * 64,
            ),
            (
                "validator_status",
                ("cross_artifact_bindings", "validator_status"),
                "failed",
            ),
            (
                "anomaly_status",
                ("cross_artifact_bindings", "anomaly_status"),
                "failed",
            ),
        )
        for name, path, value in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                package = build_synthetic_input_package(root)
                mutated = json.loads(package["manifest"].read_text(encoding="utf-8"))
                target: Any = mutated
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                mutated_path = root / "mutated.json"
                write_json(mutated_path, mutated)
                with self.assertRaises(Exception):
                    validate_input_manifest(
                        mutated_path,
                        input_root=None,
                        allow_synthetic_fixture=True,
                        allow_formal_run=False,
                        reviewed_implementation_sha=None,
                    )

    def test_formal_manifest_gates_fail_before_raw_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = build_formal_input_package(root)
            for kwargs, expected in (
                (
                    {
                        "allow_synthetic_fixture": False,
                        "allow_formal_run": False,
                        "reviewed_implementation_sha": REVIEWED_ACTIVATION_SHA,
                    },
                    "formal mode only",
                ),
                (
                    {
                        "allow_synthetic_fixture": True,
                        "allow_formal_run": False,
                        "reviewed_implementation_sha": None,
                    },
                    "formal mode only",
                ),
            ):
                with (
                    self.subTest(kwargs=kwargs),
                    patch(
                        "src.sidecar.exp_a02_raw_domain_availability_validity_validator.duckdb.connect"
                    ) as raw_open,
                ):
                    with self.assertRaisesRegex(RuntimeError, expected):
                        validate_input_manifest(
                            package["manifest"],
                            input_root=None,
                            **kwargs,
                        )
                    raw_open.assert_not_called()

            mutations = (
                ("status", "pending"),
                ("formal_run_allowed", False),
                (
                    "reviewed_implementation_sha",
                    "b" * 40,
                ),
            )
            original = json.loads(package["manifest"].read_text(encoding="utf-8"))
            for field, value in mutations:
                mutated = copy.deepcopy(original)
                mutated["authorization"][field] = value
                path = root / f"mutated-{field}.json"
                write_json(path, mutated)
                with (
                    self.subTest(field=field),
                    patch(
                        "src.sidecar.exp_a02_raw_domain_availability_validity_validator.duckdb.connect"
                    ) as raw_open,
                ):
                    with self.assertRaises(Exception):
                        validate_input_manifest(
                            path,
                            input_root=None,
                            allow_synthetic_fixture=False,
                            allow_formal_run=True,
                            reviewed_implementation_sha=REVIEWED_ACTIVATION_SHA,
                        )
                    raw_open.assert_not_called()

    def test_formal_manifest_success_and_path_policies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = build_formal_input_package(root)
            with patch(
                "src.sidecar.exp_a02_raw_domain_availability_validity_validator.duckdb.connect",
                wraps=duckdb.connect,
            ) as raw_open:
                result = validate_input_manifest(
                    package["manifest"],
                    input_root=None,
                    allow_synthetic_fixture=False,
                    allow_formal_run=True,
                    reviewed_implementation_sha=REVIEWED_ACTIVATION_SHA,
                )
            self.assertEqual(result["metadata"]["exp_a01_raw_metrics"]["row_count"], 72)
            self.assertTrue(
                any(
                    call.kwargs.get("read_only") is True
                    for call in raw_open.call_args_list
                )
            )

            manifest = json.loads(Path(package["manifest"]).read_text(encoding="utf-8"))
            for declaration in manifest["input_artifacts"].values():
                declaration["path_policy"] = "basename_local_only"
            basename_manifest = root / "basename.json"
            write_json(basename_manifest, manifest)
            basename_result = validate_input_manifest(
                basename_manifest,
                input_root=root,
                allow_synthetic_fixture=False,
                allow_formal_run=True,
                reviewed_implementation_sha=REVIEWED_ACTIVATION_SHA,
            )
            self.assertEqual(
                basename_result["metadata"]["exp_a01_raw_metrics"]["key_count"], 24
            )

            manifest = json.loads(Path(package["manifest"]).read_text(encoding="utf-8"))
            for declaration in manifest["input_artifacts"].values():
                path = root / declaration["path"]
                declaration["path_policy"] = "absolute_declared_path"
                declaration["path"] = str(path.resolve())
            absolute_manifest = root / "absolute.json"
            write_json(absolute_manifest, manifest)
            absolute_result = validate_input_manifest(
                absolute_manifest,
                input_root=None,
                allow_synthetic_fixture=False,
                allow_formal_run=True,
                reviewed_implementation_sha=REVIEWED_ACTIVATION_SHA,
            )
            self.assertEqual(
                absolute_result["metadata"]["exp_a01_raw_metrics"]["key_count"], 24
            )


if __name__ == "__main__":
    unittest.main()
