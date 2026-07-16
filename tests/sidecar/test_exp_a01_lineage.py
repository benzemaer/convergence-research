from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import duckdb

from scripts.sidecar.run_exp_a01_price_ma_attachment import (
    inspect_input_artifact,
    resolve_declared_input_path,
    run_formal,
)
from src.sidecar.exp_a01_price_ma_attachment_validator import (
    canonical_text_errors,
    load_json,
    validate_static_config,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/sidecar/exp_a01_price_ma_attachment_candidates.v1.json"


def _make_database(path: Path, *, missing_column: str | None = None) -> int:
    config = load_json(CONFIG_PATH)
    artifact = config["input_contract"]["artifacts"]["adjusted_ohlc"]
    columns = [str(value) for value in artifact["required_columns"]]
    if missing_column is not None:
        columns.remove(missing_column)
    connection = duckdb.connect(str(path))
    try:
        definitions = []
        for column in columns:
            if column in {
                "security_id",
                "trading_status",
                "adjustment_method",
                "continuous_ohlc_integrity_status",
            }:
                sql_type = "VARCHAR"
            elif column == "trading_date":
                sql_type = "DATE"
            elif column == "factor_as_of_time":
                sql_type = "TIMESTAMP"
            elif column == "corporate_action_flag":
                sql_type = "BOOLEAN"
            else:
                sql_type = "DOUBLE"
            definitions.append(f"{column} {sql_type}")
        table = str(artifact["table"])
        connection.execute(f"CREATE TABLE {table} ({', '.join(definitions)})")
        values = []
        for column in columns:
            if column == "security_id":
                values.append("'SEC001'")
            elif column == "trading_date":
                values.append("DATE '2020-01-01'")
            elif column in {
                "trading_status",
                "adjustment_method",
                "continuous_ohlc_integrity_status",
            }:
                value = {
                    "trading_status": "normal_trading",
                    "adjustment_method": "identity_no_adjustment",
                    "continuous_ohlc_integrity_status": "valid",
                }[column]
                values.append(f"'{value}'")
            elif column == "factor_as_of_time":
                values.append("TIMESTAMP '2019-01-01 00:00:00'")
            elif column == "corporate_action_flag":
                values.append("FALSE")
            elif column in {"adj_open", "adj_close"}:
                values.append("100.0")
            else:
                values.append("1.0")
        connection.execute(f"INSERT INTO {table} VALUES ({', '.join(values)})")
        return 1
    finally:
        connection.close()


class ExpA01LineageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_json(CONFIG_PATH)
        self.artifact = self.config["input_contract"]["artifacts"]["adjusted_ohlc"]

    def _fixture(
        self, *, missing_column: str | None = None
    ) -> tuple[Path, Path, dict[str, object]]:
        temp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(temp_dir, ignore_errors=True)
        )
        db_path = temp_dir / "input.duckdb"
        row_count = _make_database(db_path, missing_column=missing_column)
        declaration: dict[str, object] = {
            "path": str(db_path),
            "sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
            "row_count": row_count,
            "table": self.artifact["table"],
            "required_columns": list(self.artifact["required_columns"]),
        }
        manifest_path = temp_dir / "authorized_input_manifest.json"
        manifest_path.write_bytes(
            (
                json.dumps(
                    {
                        "task_id": "EXP-A01",
                        "input_artifacts": {"adjusted_ohlc": declaration},
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        )
        return temp_dir, manifest_path, declaration

    def test_config_and_manifest_text_are_canonical(self) -> None:
        self.assertEqual(validate_static_config(self.config), [])
        self.assertEqual(canonical_text_errors(Path(CONFIG_PATH).read_bytes()), [])
        _root, manifest_path, _declaration = self._fixture()
        self.assertEqual(canonical_text_errors(manifest_path.read_bytes()), [])

    def test_absolute_manifest_path_resolves_without_recursive_search(self) -> None:
        input_root, manifest_path, declaration = self._fixture()
        resolved = resolve_declared_input_path(
            manifest_path, input_root, declaration, self.artifact
        )
        self.assertEqual(resolved, Path(str(declaration["path"])).resolve())

    def test_hash_table_row_count_and_columns_mutations_fail_closed(self) -> None:
        _root, manifest_path, declaration = self._fixture()
        path = Path(str(declaration["path"]))
        metadata = inspect_input_artifact(path, self.artifact, declaration)
        self.assertEqual(metadata["source_full_row_count"], 1)

        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            inspect_input_artifact(
                path, self.artifact, {**declaration, "sha256": "0" * 64}
            )
        with self.assertRaisesRegex(RuntimeError, "row count mismatch"):
            inspect_input_artifact(path, self.artifact, {**declaration, "row_count": 2})
        with self.assertRaisesRegex(RuntimeError, "required columns mismatch"):
            inspect_input_artifact(
                path,
                self.artifact,
                {
                    **declaration,
                    "required_columns": list(self.artifact["required_columns"])[:-1],
                },
            )
        with self.assertRaisesRegex(RuntimeError, "table declaration"):
            resolve_declared_input_path(
                manifest_path,
                path.parent,
                {**declaration, "table": "wrong_table"},
                self.artifact,
            )

    def test_actual_required_column_mutation_fails_closed(self) -> None:
        _root, manifest_path, declaration = self._fixture(
            missing_column="adjustment_factor"
        )
        path = Path(str(declaration["path"]))
        declaration = {
            **declaration,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        with self.assertRaisesRegex(RuntimeError, "required columns are missing"):
            inspect_input_artifact(path, self.artifact, declaration)

    def test_formal_runner_never_creates_output_without_authorization(self) -> None:
        output_dir = ROOT / "data/generated/sidecar/exp_a01/test-no-formal-output"
        if output_dir.exists():
            raise AssertionError(f"unexpected test output exists: {output_dir}")
        args = Namespace(
            allow_formal_run=False,
            reviewed_implementation_sha="",
            config=CONFIG_PATH,
            input_manifest=None,
            input_root=None,
            output_root=output_dir,
            run_id=output_dir.name,
        )
        with self.assertRaisesRegex(RuntimeError, "formal_run_not_allowed"):
            run_formal(args)
        self.assertFalse(output_dir.exists())

    def test_no_formal_output_directory_and_no_duckdb_import_in_core(self) -> None:
        self.assertFalse((ROOT / "data/generated/sidecar/exp_a01").exists())
        core_text = (ROOT / "src/sidecar/exp_a01_price_ma_attachment.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("import duckdb", core_text)


if __name__ == "__main__":
    unittest.main()
