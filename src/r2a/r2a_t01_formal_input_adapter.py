"""Exact, fail-closed DuckDB adapter for local-only R2A-T01 formal inputs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

from src.r2a.r2a_t01_input_manifest import sha256_file

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t01_authorized_input_manifest.schema.json"
FORMAL_INPUT_ORDER = (
    "securities",
    "trading_sessions",
    "security_observation_spine",
    "pcvt_component_scores",
    "pcvt_dimension_scores",
    "a_raw_observations",
    "pcvt_validation_raw",
)
VALIDATION_ONLY_INPUTS = {"pcvt_validation_raw"}
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class FormalInputError(RuntimeError):
    """Raised when a bound formal input differs from its authorization record."""


class FormalInputAdapter:
    """Validate and attach only the exact DuckDB tables named by a formal manifest."""

    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path).resolve()
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
        if payload.get("synthetic_only") is not False:
            raise FormalInputError("formal_adapter_requires_non_synthetic_manifest")
        self.manifest: dict[str, Any] = payload
        self.inputs: Mapping[str, Mapping[str, Any]] = payload["inputs"]

    @property
    def authorization_id(self) -> str:
        return str(self.manifest["formal_authorization_id"])

    def attach_and_validate(
        self, connection: duckdb.DuckDBPyConnection
    ) -> dict[str, str]:
        """ATTACH READ_ONLY, validate declared metadata, and return exact relations."""

        relations: dict[str, str] = {}
        for index, input_name in enumerate(FORMAL_INPUT_ORDER):
            entry = self.inputs[input_name]
            expected_role = (
                "validation_only"
                if input_name in VALIDATION_ONLY_INPUTS
                else "materialization"
            )
            if entry["input_role"] != expected_role:
                raise FormalInputError(f"input_role_mismatch:{input_name}")
            path = Path(str(entry["actual_path"])).resolve()
            if not path.is_file():
                raise FormalInputError(f"input_file_missing:{input_name}")
            if path.stat().st_size != int(entry["byte_size"]):
                raise FormalInputError(f"input_byte_size_mismatch:{input_name}")
            if sha256_file(path) != entry["sha256"]:
                raise FormalInputError(f"input_sha256_mismatch:{input_name}")
            table = str(entry["logical_table_name"])
            if not _IDENTIFIER.fullmatch(table):
                raise FormalInputError(f"unsafe_logical_table_name:{input_name}")
            alias = f"r2a_input_{index}"
            quoted_path = str(path).replace("'", "''")
            connection.execute(f"ATTACH '{quoted_path}' AS {alias} (READ_ONLY)")
            exists = connection.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_catalog=? AND table_schema='main' AND table_name=?",
                [alias, table],
            ).fetchone()[0]
            if exists != 1:
                raise FormalInputError(f"logical_table_missing:{input_name}")
            relation = f'{alias}.main."{table}"'
            actual = inspect_relation(connection, alias, table, input_name)
            for field in (
                "row_count",
                "security_count",
                "date_min",
                "date_max",
                "schema_identity",
            ):
                if actual[field] != entry[field]:
                    raise FormalInputError(f"{field}_mismatch:{input_name}")
            relations[input_name] = relation
        return relations

    def depathized_summary(self) -> dict[str, dict[str, Any]]:
        """Return formal lineage without leaking machine-local paths."""

        fields = (
            "sha256",
            "byte_size",
            "logical_table_name",
            "row_count",
            "security_count",
            "date_min",
            "date_max",
            "schema_identity",
            "source_artifact_id",
            "source_manifest_sha256",
            "source_acceptance_status",
            "input_role",
        )
        return {
            name: {field: self.inputs[name][field] for field in fields}
            for name in FORMAL_INPUT_ORDER
        }


def inspect_relation(
    connection: duckdb.DuckDBPyConnection,
    catalog: str,
    table: str,
    input_name: str,
) -> dict[str, Any]:
    """Compute the exact metadata covered by a formal input entry."""

    relation = f'{catalog}.main."{table}"'
    columns = connection.execute(
        "SELECT column_name,data_type,is_nullable FROM information_schema.columns "
        "WHERE table_catalog=? AND table_schema='main' AND table_name=? "
        "ORDER BY ordinal_position",
        [catalog, table],
    ).fetchall()
    schema_identity = hashlib.sha256(
        json.dumps(columns, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    row_count = int(
        connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
    )
    names = {row[0] for row in columns}
    if input_name == "trading_sessions":
        required = {"trading_date", "expected_security_count"}
        _require_columns(names, required, input_name)
        counts = connection.execute(
            "SELECT min(expected_security_count),max(expected_security_count) "
            f"FROM {relation}"
        ).fetchone()
        if counts[0] != counts[1]:
            raise FormalInputError("security_count_not_constant:trading_sessions")
        security_count = int(counts[0] or 0)
        date_expression = "trading_date"
    elif input_name == "securities":
        required = {"security_id", "first_expected_date", "last_expected_date"}
        _require_columns(names, required, input_name)
        security_count = int(
            connection.execute(
                f"SELECT count(DISTINCT security_id) FROM {relation}"
            ).fetchone()[0]
        )
        coverage = connection.execute(
            f"SELECT min(first_expected_date),max(last_expected_date) FROM {relation}"
        ).fetchone()
        return {
            "row_count": row_count,
            "security_count": security_count,
            "date_min": _date_text(coverage[0]),
            "date_max": _date_text(coverage[1]),
            "schema_identity": schema_identity,
        }
    else:
        required = {"security_id", "trading_date"}
        _require_columns(names, required, input_name)
        security_count = int(
            connection.execute(
                f"SELECT count(DISTINCT security_id) FROM {relation}"
            ).fetchone()[0]
        )
        date_expression = "trading_date"
    coverage = connection.execute(
        f"SELECT min({date_expression}),max({date_expression}) FROM {relation}"
    ).fetchone()
    return {
        "row_count": row_count,
        "security_count": security_count,
        "date_min": _date_text(coverage[0]),
        "date_max": _date_text(coverage[1]),
        "schema_identity": schema_identity,
    }


def _require_columns(names: set[str], required: set[str], input_name: str) -> None:
    missing = sorted(required - names)
    if missing:
        raise FormalInputError(
            f"required_columns_missing:{input_name}:{','.join(missing)}"
        )


def _date_text(value: object) -> str | None:
    return None if value is None else str(value)
