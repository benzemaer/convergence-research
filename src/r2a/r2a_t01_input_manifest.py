"""Synthetic and local-only formal authorized-input manifests for R2A-T01."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

INPUT_NAMES = (
    "securities",
    "trading_sessions",
    "security_observation_spine",
    "pcvt_component_scores",
    "pcvt_dimension_scores",
    "a_raw_observations",
    "pcvt_validation_raw",
)
FORMAL_INPUT_NAMES = (
    "security_observation_spine",
    "pcvt_component_scores",
    "pcvt_dimension_scores",
    "a_raw_observations",
    "pcvt_validation_raw",
)
FORMAL_SOURCE_FIELDS = (
    "actual_path",
    "logical_table_name",
    "source_artifact_id",
    "source_manifest_sha256",
    "source_run_id",
    "source_contract_id",
    "input_role",
)
MANIFEST_VERSION = "r2a_t01_authorized_input_manifest.v1"
ROOT = Path(__file__).resolve().parents[2]
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class InputManifestError(RuntimeError):
    """Raised for a non-synthetic or unbound input manifest."""


def build_synthetic_input_manifest(
    *,
    output_path: str | Path,
    run_id: str,
    synthetic_root: str | Path,
    inputs: Mapping[str, str | Path],
) -> dict[str, Any]:
    """Bind JSON-array fixtures that all live below one explicit temporary root."""

    root = Path(synthetic_root).resolve()
    target = Path(output_path).resolve()
    _reject_repository_data_path(root)
    _require_within(target, root)
    if set(inputs) != set(INPUT_NAMES):
        raise InputManifestError("input_set_mismatch")

    bound: dict[str, dict[str, Any]] = {}
    for name in INPUT_NAMES:
        path = Path(inputs[name]).resolve()
        _require_within(path, root)
        _reject_repository_data_path(path)
        if not path.is_file():
            raise InputManifestError(f"missing_input:{name}")
        _load_json_array(path)
        bound[name] = {
            "path": os.fspath(path),
            "sha256": sha256_file(path),
            "byte_size": path.stat().st_size,
        }

    payload = {
        "manifest_version": MANIFEST_VERSION,
        "manifest_type": "r2a_t01_synthetic_authorized_input",
        "run_id": run_id,
        "synthetic_only": True,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "inputs": bound,
    }
    _validate_manifest(payload)
    write_json_atomic(target, payload)
    return payload


def build_formal_input_manifest(
    *,
    output_path: str | Path,
    run_id: str,
    source_commit: str,
    formal_authorization_id: str,
    universe_id: str,
    inputs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Inspect five authorized DuckDB relations and bind their metadata read-only."""

    from src.r2a.r2a_t01_formal_input_adapter import inspect_relation

    if not isinstance(inputs, Mapping) or set(inputs) != set(FORMAL_INPUT_NAMES):
        raise InputManifestError("formal_input_set_mismatch")
    bound: dict[str, dict[str, Any]] = {}
    for index, name in enumerate(FORMAL_INPUT_NAMES):
        source = inputs[name]
        if not isinstance(source, Mapping) or set(source) != set(FORMAL_SOURCE_FIELDS):
            raise InputManifestError(f"formal_source_metadata_mismatch:{name}")
        expected_role = (
            "validation_only" if name == "pcvt_validation_raw" else "materialization"
        )
        if source["input_role"] != expected_role:
            raise InputManifestError(f"input_role_mismatch:{name}")
        path = Path(str(source["actual_path"])).resolve()
        if not path.is_file():
            raise InputManifestError(f"input_file_missing:{name}")
        table = str(source["logical_table_name"])
        if not _IDENTIFIER.fullmatch(table):
            raise InputManifestError(f"unsafe_logical_table_name:{name}")
        before_size = path.stat().st_size
        before_hash = sha256_file(path)
        with duckdb.connect() as connection:
            alias = f"formal_source_{index}"
            quoted_path = str(path).replace("'", "''")
            connection.execute(f"ATTACH '{quoted_path}' AS {alias} (READ_ONLY)")
            exists = connection.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_catalog=? "
                "AND table_schema='main' AND table_name=?",
                [alias, table],
            ).fetchone()[0]
            if exists != 1:
                raise InputManifestError(f"logical_table_missing:{name}")
            metadata = inspect_relation(connection, alias, table, name)
        if path.stat().st_size != before_size or sha256_file(path) != before_hash:
            raise InputManifestError(f"input_changed_during_inspection:{name}")
        bound[name] = {
            "actual_path": os.fspath(path),
            "sha256": before_hash,
            "byte_size": before_size,
            "logical_table_name": table,
            **metadata,
            "source_artifact_id": str(source["source_artifact_id"]),
            "source_manifest_sha256": str(source["source_manifest_sha256"]),
            "source_acceptance_status": "accepted",
            "source_run_id": str(source["source_run_id"]),
            "source_contract_id": str(source["source_contract_id"]),
            "input_role": expected_role,
        }

    payload = {
        "manifest_version": MANIFEST_VERSION,
        "manifest_type": "r2a_t01_formal_authorized_input",
        "run_id": run_id,
        "synthetic_only": False,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_commit": source_commit,
        "formal_authorization_id": formal_authorization_id,
        "universe_id": universe_id,
        "inputs": bound,
    }
    _validate_manifest(payload)
    write_json_atomic(Path(output_path).resolve(), payload)
    return payload


def load_bound_inputs(manifest_path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Verify and load only small synthetic JSON-array fixtures."""

    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    _validate_manifest(payload)
    if payload.get("manifest_version") != MANIFEST_VERSION:
        raise InputManifestError("manifest_version_mismatch")
    synthetic = payload.get("synthetic_only") is True
    if not synthetic:
        raise InputManifestError("json_array_loader_is_synthetic_only")
    entries = payload.get("inputs")
    if not isinstance(entries, dict) or set(entries) != set(INPUT_NAMES):
        raise InputManifestError("input_set_mismatch")

    loaded: dict[str, list[dict[str, Any]]] = {}
    for name in INPUT_NAMES:
        entry = entries[name]
        source = Path(entry["path"]).resolve()
        if synthetic:
            _reject_repository_data_path(source)
        if sha256_file(source) != entry.get("sha256"):
            raise InputManifestError(f"input_hash_mismatch:{name}")
        if source.stat().st_size != entry.get("byte_size"):
            raise InputManifestError(f"input_size_mismatch:{name}")
        loaded[name] = _load_json_array(source)
    return loaded


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary.write_text(data, encoding="utf-8", newline="\n")
    temporary.replace(target)


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or any(
        not isinstance(row, dict) for row in payload
    ):
        raise InputManifestError(f"input_not_json_object_array:{path.name}")
    return payload


def _require_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise InputManifestError("input_outside_synthetic_root") from exc


def _reject_repository_data_path(path: Path) -> None:
    try:
        path.relative_to((ROOT / "data").resolve())
    except ValueError:
        return
    raise InputManifestError("repository_data_path_forbidden_for_synthetic_manifest")


def _validate_manifest(payload: Any) -> None:
    schema_path = ROOT / "schemas/r2a/r2a_t01_authorized_input_manifest.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
