from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import duckdb

from src.sidecar.exp_a03_candidate_intralayer_redundancy_selection_validator import (
    _invariants,
    prepare_input_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "data/generated/sidecar/exp_a02/exp_a02_accepted_result_handoff.json"
A02_ROOT = ROOT / "data/generated/sidecar/exp_a02/EXP-A02-20260717T100527443Z"
RAW_COLUMNS = (
    "run_id",
    "security_id",
    "trading_date",
    "observation_sequence",
    "expected_observation_status",
    "indicator_id",
    "raw_metric_name",
    "raw_value",
    "validity_status",
    "reason_codes_json",
    "input_window_start",
    "input_window_end",
    "required_observation_count",
    "actual_valid_observation_count",
    "metric_engine_version",
    "source_ref",
)
INDICATORS = (
    "A1_LogBodyCenterToMACloudCenter_5_60",
    "A2_BodyCenterOutsideMACloudRate20_5_60",
    "A2b_BodyToMACloudGapMean20_5_60",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def create_synthetic_raw(
    path: Path,
    *,
    securities: tuple[str, ...] = ("SEC001",),
    years: tuple[int, ...] = tuple(range(2016, 2027)),
) -> tuple[int, int, str, str]:
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            "CREATE TABLE exp_a01_raw_metrics ("
            "run_id VARCHAR,security_id VARCHAR,trading_date DATE,"
            "observation_sequence INTEGER,expected_observation_status VARCHAR,"
            "indicator_id VARCHAR,raw_metric_name VARCHAR,raw_value DOUBLE,"
            "validity_status VARCHAR,reason_codes_json VARCHAR,"
            "input_window_start DATE,input_window_end DATE,"
            "required_observation_count INTEGER,"
            "actual_valid_observation_count INTEGER,"
            "metric_engine_version VARCHAR,source_ref VARCHAR)"
        )
        rows: list[tuple[Any, ...]] = []
        start = date(2016, 1, 4)
        for security_index, security_id in enumerate(securities):
            for year_index, year in enumerate(years):
                for level in range(21):
                    trading_date = date(year, 1, 4) + timedelta(days=level)
                    a2 = level / 20.0
                    values = (
                        0.1 + a2 + security_index * 0.001,
                        a2,
                        0.02 + a2 * 0.5 + (level % 3) * 0.001,
                    )
                    for indicator_id, value in zip(INDICATORS, values, strict=True):
                        rows.append(
                            (
                                "EXP-A01-SYNTHETIC",
                                security_id,
                                trading_date,
                                year_index * 21 + level,
                                "present",
                                indicator_id,
                                indicator_id,
                                value,
                                "valid",
                                '["valid_no_blocker"]',
                                trading_date - timedelta(days=20),
                                trading_date,
                                60,
                                60,
                                "synthetic",
                                "synthetic",
                            )
                        )
        connection.executemany(
            "INSERT INTO exp_a01_raw_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    finally:
        connection.close()
    return (
        len(rows),
        len(rows) // 3,
        min(start + timedelta(days=365 * i) for i in range(len(years))),
        max(date(year, 1, 24) for year in years),
    )


def build_synthetic_input_package(
    root: Path, *, mutate: str | None = None
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    raw = root / "synthetic_raw.duckdb"
    row_count, key_count, date_min, date_max = create_synthetic_raw(raw)
    artifacts = {
        "exp_a02_accepted_result_handoff": (HANDOFF, "handoff_json", HANDOFF.name),
        "exp_a02_manifest": (
            A02_ROOT / "exp_a02_manifest.json",
            "a02_manifest_json",
            "exp_a02_manifest.json",
        ),
        "exp_a02_validator_result": (
            A02_ROOT / "exp_a02_validator_result.json",
            "a02_validator_json",
            "exp_a02_validator_result.json",
        ),
        "exp_a02_anomaly_scan": (
            A02_ROOT / "exp_a02_anomaly_scan.json",
            "a02_anomaly_json",
            "exp_a02_anomaly_scan.json",
        ),
        "exp_a01_raw_metrics": (raw, "duckdb_table", raw.name),
    }
    for artifact_id, (path, kind, filename) in list(artifacts.items()):
        if artifact_id != "exp_a01_raw_metrics":
            local = root / filename
            shutil.copyfile(path, local)
            artifacts[artifact_id] = (local, kind, filename)
    declarations: dict[str, Any] = {}
    for artifact_id, (path, kind, filename) in artifacts.items():
        declarations[artifact_id] = {
            "artifact_id": artifact_id,
            "artifact_kind": kind,
            "filename": filename,
            "path": str(path),
            "path_policy": "synthetic_fixture",
            "sha256": sha256(path),
            "table": "exp_a01_raw_metrics"
            if artifact_id == "exp_a01_raw_metrics"
            else None,
            "row_count": row_count if artifact_id == "exp_a01_raw_metrics" else None,
            "expected_key_count": key_count
            if artifact_id == "exp_a01_raw_metrics"
            else None,
            "security_count": 1 if artifact_id == "exp_a01_raw_metrics" else None,
            "date_min": str(date_min) if artifact_id == "exp_a01_raw_metrics" else None,
            "date_max": str(date_max) if artifact_id == "exp_a01_raw_metrics" else None,
            "required_json_fields": ["task_id", "status"]
            if artifact_id != "exp_a01_raw_metrics"
            else [],
        }
        declarations[artifact_id] = {
            key: value
            for key, value in declarations[artifact_id].items()
            if value is not None
        }
    handoff_payload = json.loads(HANDOFF.read_text(encoding="utf-8"))
    binding = {
        "a02_run_id": handoff_payload["accepted_run_id"],
        "a02_reviewed_implementation_sha": handoff_payload[
            "reviewed_implementation_sha"
        ],
        "a02_result_commit": handoff_payload["result_commit"],
        "a02_quality_run_id": handoff_payload["result_commit_quality_run_id"],
        "a02_manifest_sha256": sha256(artifacts["exp_a02_manifest"][0]),
        "a02_validator_sha256": sha256(artifacts["exp_a02_validator_result"][0]),
        "a02_validator_status": "passed",
        "a02_anomaly_sha256": sha256(artifacts["exp_a02_anomaly_scan"][0]),
        "a02_anomaly_status": "passed",
        "a01_raw_sha256": sha256(raw),
        "a01_raw_row_count": row_count,
        "expected_key_count": key_count,
        "triple_common_valid_count": key_count,
        "security_count": 1,
        "date_min": str(date_min),
        "date_max": str(date_max),
        "a03_reviewed_implementation_sha": "a" * 40,
    }
    if mutate == "raw_sha":
        binding["a01_raw_sha256"] = "0" * 64
    if mutate == "common_count":
        binding["triple_common_valid_count"] = key_count + 1
    if mutate == "extra":
        declarations["extra"] = declarations["exp_a02_manifest"]
    manifest = {
        "$schema": (
            "../../schemas/sidecar/exp_a03_authorized_input_manifest.schema.json"
        ),
        "manifest_type": "exp_a03_synthetic_input_manifest",
        "manifest_version": "1.0.0",
        "task_id": "EXP-A03",
        "authorized_for_task": "EXP-A03",
        "formal_data_version": False,
        "authorization": {
            "status": "synthetic_fixture_only",
            "formal_run_allowed": False,
            "evidence": "temporary synthetic fixture",
        },
        "input_artifacts": declarations,
        "cross_artifact_bindings": binding,
    }
    manifest_path = root / "exp_a03_authorized_input_manifest.json"
    write_json(manifest_path, manifest)
    return {
        "manifest": manifest_path,
        "input_root": root,
        "raw": raw,
        "row_count": row_count,
        "key_count": key_count,
    }


class ExpA03LineageTest(unittest.TestCase):
    def test_handoff_and_synthetic_manifest_validate_before_raw_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = build_synthetic_input_package(Path(temporary))
            info = prepare_input_manifest(
                package["manifest"],
                input_root=package["input_root"],
                allow_synthetic_fixture=True,
            )
            self.assertEqual(info["common_valid_count"], package["key_count"])
            self.assertEqual(info["handoff"]["status"], "completed_accepted")

    def test_raw_sha_and_common_count_mutations_fail_closed(self) -> None:
        for mutation in ("raw_sha", "common_count", "extra"):
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as temporary,
            ):
                package = build_synthetic_input_package(
                    Path(temporary), mutate=mutation
                )
                with self.assertRaises(Exception):
                    prepare_input_manifest(
                        package["manifest"],
                        input_root=package["input_root"],
                        allow_synthetic_fixture=True,
                    )

    def test_handoff_identity_mutations_fail_before_raw_use(self) -> None:
        for field, value in (
            ("accepted_run_id", "EXP-A02-20990101T000000000Z"),
            ("result_commit", "0" * 40),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                package = build_synthetic_input_package(Path(temporary))
                handoff_path = (
                    Path(package["input_root"]) / "exp_a02_accepted_result_handoff.json"
                )
                payload = json.loads(handoff_path.read_text(encoding="utf-8"))
                payload[field] = value
                write_json(handoff_path, payload)
                manifest = json.loads(package["manifest"].read_text(encoding="utf-8"))
                manifest["input_artifacts"]["exp_a02_accepted_result_handoff"][
                    "sha256"
                ] = sha256(handoff_path)
                write_json(package["manifest"], manifest)
                with self.assertRaises(Exception):
                    prepare_input_manifest(
                        package["manifest"],
                        input_root=package["input_root"],
                        allow_synthetic_fixture=True,
                    )

    def test_a02_artifact_mutations_fail_against_frozen_handoff_before_raw_use(
        self,
    ) -> None:
        artifact_bindings = {
            "exp_a02_manifest": ("exp_a02_manifest.json", "a02_manifest_sha256"),
            "exp_a02_validator_result": (
                "exp_a02_validator_result.json",
                "a02_validator_sha256",
            ),
            "exp_a02_anomaly_scan": (
                "exp_a02_anomaly_scan.json",
                "a02_anomaly_sha256",
            ),
        }
        for artifact_id, (filename, binding_field) in artifact_bindings.items():
            with (
                self.subTest(artifact_id=artifact_id),
                tempfile.TemporaryDirectory() as temporary,
            ):
                package = build_synthetic_input_package(Path(temporary))
                artifact_path = Path(package["input_root"]) / filename
                payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                payload["lineage_mutation_marker"] = artifact_id
                write_json(artifact_path, payload)
                manifest = json.loads(package["manifest"].read_text(encoding="utf-8"))
                mutated_hash = sha256(artifact_path)
                manifest["input_artifacts"][artifact_id]["sha256"] = mutated_hash
                manifest["cross_artifact_bindings"][binding_field] = mutated_hash
                write_json(package["manifest"], manifest)
                with patch(
                    "src.sidecar.exp_a03_candidate_intralayer_redundancy_selection_validator.duckdb.connect"
                ) as connect:
                    with self.assertRaisesRegex(
                        ValueError, "A02 accepted artifact hash mismatch"
                    ):
                        prepare_input_manifest(
                            package["manifest"],
                            input_root=package["input_root"],
                            allow_synthetic_fixture=True,
                        )
                    connect.assert_not_called()

    def test_common_universe_does_not_treat_a1_only_as_a_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = build_synthetic_input_package(Path(temporary))
            connection = duckdb.connect(str(package["raw"]))
            try:
                row = connection.execute(
                    "SELECT * FROM exp_a01_raw_metrics WHERE indicator_id=? LIMIT 1",
                    (INDICATORS[0],),
                ).fetchone()
                connection.execute(
                    "INSERT INTO exp_a01_raw_metrics "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        row[0],
                        "A1ONLY",
                        row[2],
                        row[3],
                        row[4],
                        row[5],
                        row[6],
                        row[7],
                        row[8],
                        row[9],
                        row[10],
                        row[11],
                        row[12],
                        row[13],
                        row[14],
                        row[15],
                    ),
                )
                self.assertEqual(
                    _invariants(connection, package["key_count"]),
                    {
                        "duplicate_common_key": 0,
                        "common_count_mismatch": 0,
                        "missing_common_value": 0,
                        "nonfinite_common_raw": 0,
                        "a2_grid_violation": 0,
                        "a2_a2b_valid_set_mismatch": 0,
                    },
                )
            finally:
                connection.close()

    def test_common_duplicate_and_set_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = build_synthetic_input_package(Path(temporary))
            connection = duckdb.connect(str(package["raw"]))
            try:
                row = connection.execute(
                    "SELECT * FROM exp_a01_raw_metrics WHERE indicator_id=? LIMIT 1",
                    (INDICATORS[0],),
                ).fetchone()
                connection.execute(
                    "INSERT INTO exp_a01_raw_metrics "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    row,
                )
                self.assertGreater(
                    _invariants(connection, package["key_count"])[
                        "duplicate_common_key"
                    ],
                    0,
                )
            finally:
                connection.close()
        with tempfile.TemporaryDirectory() as temporary:
            package = build_synthetic_input_package(Path(temporary))
            connection = duckdb.connect(str(package["raw"]))
            try:
                key = connection.execute(
                    "SELECT security_id,trading_date,observation_sequence "
                    "FROM exp_a01_raw_metrics WHERE indicator_id=? LIMIT 1",
                    (INDICATORS[2],),
                ).fetchone()
                connection.execute(
                    "UPDATE exp_a01_raw_metrics SET validity_status='blocked' "
                    "WHERE security_id=? AND trading_date=? "
                    "AND observation_sequence=? AND indicator_id=?",
                    (*key, INDICATORS[2]),
                )
                invariant = _invariants(connection, package["key_count"])
                self.assertNotEqual(invariant["common_count_mismatch"], 0)
                self.assertGreater(invariant["a2_a2b_valid_set_mismatch"], 0)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
