from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import duckdb

from scripts.sidecar.run_exp_c01_c_layer_ablation import (
    inspect_input_artifact,
    resolve_input_paths,
)
from src.sidecar.exp_c01_c_layer_ablation_validator import (
    _canonical_optional_date_text,
    _validate_duckdb_binding,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = (
    ROOT / "configs" / "sidecar" / "exp_c01_c_layer_indicator_ablation_w120.v1.json"
)


def _load_config() -> dict[str, object]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _sql_type(column: str) -> str:
    if column in {"trading_date"}:
        return "DATE"
    if column in {
        "percentile_window_W",
    }:
        return "INTEGER"
    if column in {
        "score",
        "score_dimension",
        "score_dimension_min",
        "q",
        "weak_delta",
    }:
        return "DOUBLE"
    if column in {"eligible", "eligible_dimension", "dimension_active_weak"}:
        return "BOOLEAN"
    return "VARCHAR"


def _make_database(path: Path, table: str, columns: list[str]) -> None:
    connection = duckdb.connect(str(path))
    try:
        definition = ", ".join(f"{column} {_sql_type(column)}" for column in columns)
        connection.execute(f"CREATE TABLE {table} ({definition})")
    finally:
        connection.close()


def _make_indicator_database(
    path: Path, trading_date_type: str, date_values: list[str]
) -> None:
    table = "r0_t05_indicator_score_results"
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            f"""
            CREATE TABLE {table} (
                security_id VARCHAR,
                trading_date {trading_date_type},
                percentile_window_W INTEGER,
                indicator_id VARCHAR,
                score DOUBLE,
                eligible BOOLEAN,
                validity_status VARCHAR
            )
            """
        )
        for trading_date in date_values:
            connection.execute(
                f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    "SEC0001",
                    trading_date,
                    120,
                    "C1_LogMASpread_5_60",
                    0.85,
                    True,
                    "valid",
                ],
            )
    finally:
        connection.close()


class ExpC01LineageTest(unittest.TestCase):
    def _source_fixture(
        self,
    ) -> tuple[dict[str, object], Path, Path, dict[str, dict[str, object]]]:
        config = _load_config()
        with_temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, with_temp, ignore_errors=True)
        manifest_dir = with_temp / "manifest_parent"
        input_root = with_temp / "input_root"
        manifest_dir.mkdir()
        input_root.mkdir()
        declarations: dict[str, dict[str, object]] = {}
        artifacts = config["input_contract"]["artifacts"]  # type: ignore[index]
        for name, artifact in artifacts.items():  # type: ignore[union-attr]
            filename = str(artifact["filename"])
            table = str(artifact["table"])
            path = manifest_dir / filename
            _make_database(path, table, list(artifact["required_columns"]))
            declarations[name] = {
                "path": filename,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "row_count": 0,
                "table": table,
            }
        manifest = {
            "schema_version": "synthetic_source.v1",
            "input_artifacts": declarations,
        }
        manifest_path = manifest_dir / "authorized_source.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
        )
        return config, input_root, manifest_path, declarations

    def _date_fixture(
        self, trading_date_type: str, date_values: list[str]
    ) -> tuple[dict[str, object], dict[str, object], Path]:
        config = _load_config()
        artifact = config["input_contract"]["artifacts"]["indicator_score"]  # type: ignore[index]
        fixture_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, fixture_root, ignore_errors=True)
        path = fixture_root / str(artifact["filename"])
        _make_indicator_database(path, trading_date_type, date_values)
        declaration = {
            "path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "row_count": len(date_values),
            "table": artifact["table"],
            "security_count": 1,
            "date_min": "20160104",
            "date_max": "20260630",
        }
        return artifact, declaration, path  # type: ignore[return-value]

    def test_source_dates_use_one_normalization_for_varchar_and_date_values(
        self,
    ) -> None:
        for storage_type, date_values in (
            ("VARCHAR", ["20160104", "20260630"]),
            ("DATE", ["2016-01-04", "2026-06-30"]),
        ):
            with self.subTest(storage_type=storage_type):
                artifact, declaration, path = self._date_fixture(
                    storage_type, date_values
                )
                for declared_min, declared_max in (
                    ("20160104", "20260630"),
                    ("2016-01-04", "2026-06-30"),
                ):
                    with self.subTest(
                        declared_min=declared_min, declared_max=declared_max
                    ):
                        metadata = inspect_input_artifact(
                            path,
                            artifact,
                            {
                                **declaration,
                                "date_min": declared_min,
                                "date_max": declared_max,
                            },
                        )
                        self.assertEqual(metadata["actual_date_min"], "2016-01-04")
                        self.assertEqual(metadata["actual_date_max"], "2026-06-30")
                        self.assertEqual(
                            _validate_duckdb_binding(
                                path,
                                str(artifact["table"]),
                                [
                                    str(column)
                                    for column in artifact["required_columns"]
                                ],
                                len(date_values),
                                expected_security_count=1,
                                expected_date_min=declared_min,
                                expected_date_max=declared_max,
                            ),
                            [],
                        )

    def test_source_date_mismatch_is_checked_for_both_boundaries(self) -> None:
        artifact, declaration, path = self._date_fixture(
            "VARCHAR", ["20160104", "20260630"]
        )
        for field, value in (("date_min", "20160105"), ("date_max", "20260629")):
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    RuntimeError, f"source manifest {field} mismatch"
                ):
                    inspect_input_artifact(
                        path, artifact, {**declaration, field: value}
                    )

    def test_date_normalization_handles_optional_and_invalid_values(self) -> None:
        self.assertIsNone(_canonical_optional_date_text(None))
        self.assertIsNone(_canonical_optional_date_text(""))
        self.assertIsNone(_canonical_optional_date_text("   "))
        self.assertEqual(_canonical_optional_date_text(date(2016, 1, 4)), "2016-01-04")
        self.assertEqual(
            _canonical_optional_date_text(datetime(2016, 1, 4, 12, 30)),
            "2016-01-04",
        )
        for invalid in (
            "2016/01/04",
            "2016-1-04",
            "2016014",
            "20160230",
            "2016-02-30",
            20160104,
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    _canonical_optional_date_text(invalid)

        artifact, declaration, path = self._date_fixture(
            "VARCHAR", ["20160104", "20260630"]
        )
        with self.assertRaises(ValueError):
            inspect_input_artifact(
                path, artifact, {**declaration, "date_min": "2016-02-30"}
            )

        invalid_actual_artifact, invalid_actual_declaration, invalid_actual_path = (
            self._date_fixture("VARCHAR", ["20160230", "20260630"])
        )
        with self.assertRaises(ValueError):
            inspect_input_artifact(
                invalid_actual_path,
                invalid_actual_artifact,
                invalid_actual_declaration,
            )

    def test_relative_declared_paths_resolve_from_manifest_parent(self) -> None:
        config, input_root, manifest_path, _declarations = self._source_fixture()
        resolved, _manifest = resolve_input_paths(
            input_root, config, manifest_path=manifest_path
        )
        self.assertEqual(
            {path.parent for path in resolved.values()}, {manifest_path.parent}
        )

    def test_exact_manifest_path_is_required_and_no_recursive_fallback_is_used(
        self,
    ) -> None:
        config, input_root, manifest_path, declarations = self._source_fixture()
        with self.assertRaises(RuntimeError):
            resolve_input_paths(input_root, config)

        missing = manifest_path.parent / str(
            config["input_contract"]["artifacts"]["indicator_score"]["filename"]  # type: ignore[index]
        )
        missing.unlink()
        nested = input_root / "nested"
        nested.mkdir()
        nested_file = nested / missing.name
        nested_file.write_bytes(b"arbitrary-not-authorized")
        with self.assertRaisesRegex(RuntimeError, "relocation is not authorized"):
            resolve_input_paths(input_root, config, manifest_path=manifest_path)

        declarations["indicator_score"]["path_policy"] = "basename_local_only"
        manifest = {
            "schema_version": "synthetic_source.v1",
            "input_artifacts": declarations,
        }
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
        )
        (input_root / "one").mkdir()
        (input_root / "two").mkdir()
        (input_root / "one" / missing.name).write_bytes(b"one")
        (input_root / "two" / missing.name).write_bytes(b"two")
        with self.assertRaisesRegex(
            RuntimeError, "relocated indicator_score input is missing"
        ):
            resolve_input_paths(input_root, config, manifest_path=manifest_path)

    def test_source_hash_row_count_table_and_required_column_mutations_fail_closed(
        self,
    ) -> None:
        config, input_root, manifest_path, declarations = self._source_fixture()
        artifact = config["input_contract"]["artifacts"]["indicator_score"]  # type: ignore[index]
        path = manifest_path.parent / str(artifact["filename"])
        good = copy.deepcopy(declarations["indicator_score"])
        self.assertEqual(
            inspect_input_artifact(path, artifact, good)["source_full_row_count"],  # type: ignore[arg-type]
            0,
        )
        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            inspect_input_artifact(
                path,
                artifact,
                {**good, "sha256": "0" * 64},  # type: ignore[arg-type]
            )

        hash_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        hash_manifest["input_artifacts"]["indicator_score"]["sha256"] = "0" * 64
        manifest_path.write_text(
            json.dumps(hash_manifest, sort_keys=True) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            resolve_input_paths(input_root, config, manifest_path=manifest_path)

        with self.assertRaisesRegex(RuntimeError, "row count mismatch"):
            bad_row_count = {**good, "row_count": 1}
            inspect_input_artifact(path, artifact, bad_row_count)  # type: ignore[arg-type]
        with self.assertRaisesRegex(RuntimeError, "table mismatch"):
            bad_table = {**good, "table": "different_table"}
            inspect_input_artifact(path, artifact, bad_table)  # type: ignore[arg-type]

        reduced_columns = list(artifact["required_columns"])[1:]  # type: ignore[index]
        bad_path = manifest_path.parent / "missing_required_column.duckdb"
        _make_database(bad_path, str(artifact["table"]), reduced_columns)
        with self.assertRaisesRegex(RuntimeError, "required columns are missing"):
            inspect_input_artifact(
                bad_path,
                artifact,
                {
                    **good,
                    "path": bad_path.name,
                    "sha256": hashlib.sha256(bad_path.read_bytes()).hexdigest(),
                },  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
