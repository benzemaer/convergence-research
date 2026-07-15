from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import duckdb

from scripts.sidecar.run_exp_c01_c_layer_ablation import (
    inspect_input_artifact,
    resolve_input_paths,
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
