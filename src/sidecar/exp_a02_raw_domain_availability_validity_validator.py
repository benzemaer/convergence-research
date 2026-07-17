# ruff: noqa: E501

"""Independent validator for the EXP-A02 aggregate package.

The validator replays the accepted A01 handoff from disk, opens the declared
input DuckDB read-only, performs set-based raw invariant checks, and
recomputes each compact CSV with independent SQL. It does not call the A02
producer query functions and it never performs a Python row-by-row oracle over
the upstream raw table.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

from src.sidecar.exp_a02_raw_domain_availability_validity import (
    A01_IMPLEMENTATION_SHA,
    A01_RESULT_COMMIT,
    A01_RUN_ID,
    A1_ID,
    A2_ID,
    A2B_ID,
    CSV_FIELDS,
    EXTREME_TAIL_SIZE,
    FORBIDDEN_OUTPUT_FIELD_NAMES,
    GRID_RESIDUAL_TOLERANCE,
    INDICATOR_IDS,
    OUTPUT_FILES,
    RAW_COLUMNS,
    RAW_TABLE,
    REASON_CODES,
    VALIDITY_STATUSES,
)

TASK_ID = "EXP-A02"
ROOT = Path(__file__).resolve().parents[2]
HANDOFF_SCHEMA = ROOT / "schemas/sidecar/exp_a01_accepted_result_handoff.schema.json"
INPUT_MANIFEST_SCHEMA = (
    ROOT / "schemas/sidecar/exp_a02_authorized_input_manifest.schema.json"
)
CONFIG_SCHEMA = (
    ROOT / "schemas/sidecar/exp_a02_raw_domain_availability_validity.schema.json"
)
CONFIG_PATH = ROOT / "configs/sidecar/exp_a02_raw_domain_availability_validity.v1.json"
EXPECTED_MANIFEST_ARTIFACTS = (
    "exp_a01_accepted_result_handoff",
    "exp_a01_raw_metrics",
    "exp_a01_manifest",
    "exp_a01_validator_result",
    "exp_a01_anomaly_scan",
)
EXPECTED_ARTIFACT_KINDS = {
    "exp_a01_accepted_result_handoff": "handoff_json",
    "exp_a01_raw_metrics": "duckdb_table",
    "exp_a01_manifest": "a01_manifest_json",
    "exp_a01_validator_result": "a01_validator_json",
    "exp_a01_anomaly_scan": "a01_anomaly_json",
}
SHA40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
FORMAL_MANIFEST_TYPE = "exp_a02_authorized_input_manifest"
SYNTHETIC_MANIFEST_TYPE = "exp_a02_synthetic_input_manifest"
VALIDATION_STRATEGY = "r0_t10_artifact_bound_full_aggregate_recompute_v1"
EXPECTED_KEY_FIELDS = ("security_id", "trading_date", "observation_sequence")
RAW_TYPE_EXPECTATIONS = {
    "run_id": "VARCHAR",
    "security_id": "VARCHAR",
    "trading_date": "DATE",
    "observation_sequence": "INTEGER",
    "expected_observation_status": "VARCHAR",
    "indicator_id": "VARCHAR",
    "raw_metric_name": "VARCHAR",
    "raw_value": "DOUBLE",
    "validity_status": "VARCHAR",
    "reason_codes_json": "VARCHAR",
    "input_window_start": "DATE",
    "input_window_end": "DATE",
    "required_observation_count": "INTEGER",
    "actual_valid_observation_count": "INTEGER",
    "metric_engine_version": "VARCHAR",
    "source_ref": "VARCHAR",
}
MISMATCH_KEYS = (
    "lineage_mismatch",
    "input_hash_mismatch",
    "raw_table_schema_mismatch",
    "raw_row_count_mismatch",
    "indicator_row_count_mismatch",
    "duplicate_indicator_key",
    "unknown_indicator",
    "validity_domain_mismatch",
    "valid_raw_null",
    "nonvalid_raw_nonnull",
    "nonfinite_valid_raw",
    "domain_violation",
    "a2_grid_violation",
    "reason_code_domain_mismatch",
    "a2_a2b_validity_mismatch",
    "a2_a2b_reason_mismatch",
    "a2_a2b_window_field_mismatch",
    "a2_a2b_valid_key_mismatch",
    "a2_valid_a1_nonvalid",
    "a2b_valid_a1_nonvalid",
    "indicator_without_valid_rows",
    "common_triple_without_valid_rows",
    "aggregate_csv_mismatch",
    "output_manifest_mismatch",
    "output_artifact_hash_mismatch",
    "validator_artifact_mismatch",
    "anomaly_artifact_mismatch",
    "forbidden_output_field",
)
RESULT_ANALYSIS_HEADINGS = (
    "## 1. Actual run / reviewed SHA",
    "## 2. Accepted EXP-A01 handoff",
    "## 3. Input artifact and hash bindings",
    "## 4. Raw-table cardinality",
    "## 5. Raw domains",
    "## 6. Indicator availability",
    "## 7. Common-valid availability",
    "## 8. Validity-status distribution",
    "## 9. Reason-code distribution",
    "## 10. Reason-combination distribution",
    "## 11. Year availability",
    "## 12. Security availability",
    "## 13. Deterministic extreme-value sample",
    "## 14. Full invariant validation",
    "## 15. Independent aggregate recomputation",
    "## 16. Validator result",
    "## 17. Anomaly scan",
    "## 18. Supported conclusions",
    "## 19. Unsupported conclusions",
    "## 20. Readiness for user Formal-result review",
)
RESULT_ANALYSIS_READINESS_VALUES = frozenset(
    {
        "ready_for_user_formal_result_review",
        "needs_investigation_before_user_review",
    }
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_text_errors(raw: bytes) -> list[str]:
    errors: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append("BOM")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("UTF-8")
    if b"\r" in raw:
        errors.append("bare_or_CRLF")
    if not raw.endswith(b"\n"):
        errors.append("missing_final_LF")
    if raw.endswith(b"\n\n"):
        errors.append("multiple_final_LF")
    return errors


def load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    errors = canonical_text_errors(raw)
    if errors:
        raise ValueError(f"non-canonical JSON text {path}: {errors}")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _result_analysis_text_errors(path: Path) -> list[str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [f"result_analysis_read:{exc}"]
    errors = canonical_text_errors(raw)
    if errors:
        return [f"result_analysis_text_contract:{error}" for error in errors]
    text = raw.decode("utf-8")
    lines = text.splitlines()
    heading_lines = tuple(line for line in lines if line.startswith("## "))
    if heading_lines != RESULT_ANALYSIS_HEADINGS:
        errors.append("result_analysis_heading_order_or_set_invalid")
    for heading in RESULT_ANALYSIS_HEADINGS:
        if text.count(heading) != 1:
            errors.append(f"result_analysis_heading_count:{heading}")
    if not lines or lines[-1] not in RESULT_ANALYSIS_READINESS_VALUES:
        errors.append("analysis_readiness_value_invalid")
    return errors


def _validate_schema(payload: Mapping[str, Any], schema_path: Path) -> None:
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)


def validate_static_config(config: Mapping[str, Any]) -> list[str]:
    """Validate frozen A02 implementation config without reading any raw data."""

    errors: list[str] = []
    try:
        _validate_schema(config, CONFIG_SCHEMA)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"config_schema:{exc}")
        return errors
    upstream = config["upstream"]
    if upstream["accepted_implementation_sha"] != A01_IMPLEMENTATION_SHA:
        errors.append("accepted_implementation_sha_mismatch")
    if config["formal_run_allowed"] is not False:
        errors.append("formal_run_allowed_not_false")
    if config["formal_run_executed"] is not False:
        errors.append("formal_run_executed_not_false")
    if config["formal_artifacts_generated"] is not False:
        errors.append("formal_artifacts_generated_not_false")
    if config["phase"] != "formal_execution_activation_implementation_review":
        errors.append("phase_not_formal_execution_activation_implementation_review")
    if config["program_phase"] != "A02_formal_execution_activation_implementation":
        errors.append("program_phase_not_formal_execution_activation_implementation")
    if config["input_contract"]["manifest_artifact_names"] != list(
        EXPECTED_MANIFEST_ARTIFACTS
    ):
        errors.append("manifest_artifact_names_mismatch")
    if config["indicator_universe"]["indicator_ids"] != list(INDICATOR_IDS):
        errors.append("indicator_universe_mismatch")
    if config["indicator_universe"]["validity_statuses"] != list(VALIDITY_STATUSES):
        errors.append("validity_statuses_mismatch")
    if config["indicator_universe"]["reason_codes"] != list(REASON_CODES):
        errors.append("reason_codes_mismatch")
    output = config["output_contract"]
    if output["raw_duckdb_generated"] is not False:
        errors.append("raw_duckdb_generation_not_false")
    if output["extreme_tail_size"] != EXTREME_TAIL_SIZE:
        errors.append("extreme_tail_size_mismatch")
    validation = config["validation_contract"]
    frozen_validation = {
        "strategy": "r0_t10_artifact_bound_full_aggregate_recompute_v1",
        "upstream_consumption": "accepted_EXP_A01_artifact_only",
        "full_raw_python_recompute": False,
        "full_set_based_invariant_scan": True,
        "full_output_aggregate_recompute": True,
        "deterministic_sample_output": True,
        "single_giant_json_payload": False,
        "row_payload_in_manifest": False,
        "row_payload_in_summary": False,
        "core_validator_execution_count": 1,
        "final_package_validation": "manifest_hash_text_binding_only",
    }
    for key, expected in frozen_validation.items():
        if validation.get(key) != expected:
            errors.append(f"validation_contract_{key}_mismatch")
    execution = config["execution_contract"]
    expected_execution = {
        "implementation_synthetic_only": False,
        "formal_execution_capable": True,
        "formal_execution_allowed": False,
        "formal_run_not_implemented": False,
        "formal_activation_requires_exact_sha_review": True,
        "formal_authorization_mode": "authorized_manifest_plus_cli_exact_sha",
        "read_only_upstream_raw": True,
        "new_duckdb_forbidden": True,
        "copy_upstream_raw_forbidden": True,
        "pandas_forbidden": True,
        "full_raw_python_iteration_forbidden": True,
        "failure_package_preservation": True,
    }
    for key, expected in expected_execution.items():
        if execution.get(key) != expected:
            errors.append(f"execution_contract_{key}_mismatch")
    return errors


def validate_handoff(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    _validate_schema(payload, HANDOFF_SCHEMA)
    return payload


def _resolve_declared_path(
    manifest_path: Path,
    declaration: Mapping[str, Any],
    *,
    input_root: Path | None,
    synthetic_fixture: bool,
) -> Path:
    declared = str(declaration["path"])
    policy = declaration["path_policy"]
    declared_path = Path(declared)
    if policy == "absolute_declared_path":
        if not declared_path.is_absolute():
            raise ValueError("absolute_declared_path requires an absolute path")
        return declared_path.resolve()
    if policy == "relative_to_manifest":
        if declared_path.is_absolute():
            raise ValueError("relative_to_manifest requires a relative path")
        return (manifest_path.parent / declared_path).resolve()
    if policy == "basename_local_only":
        if input_root is None:
            raise ValueError("basename_local_only requires --input-root")
        if declared_path.name != declared or declared_path.is_absolute():
            raise ValueError("basename_local_only declaration must be a basename")
        return (input_root.resolve() / declared_path).resolve()
    if policy == "synthetic_fixture":
        if not synthetic_fixture or declared_path.is_absolute():
            raise ValueError("synthetic_fixture path policy is synthetic-only")
        return (manifest_path.parent / declared_path).resolve()
    raise ValueError(f"unsupported input path policy: {policy}")


def _required_json_fields(
    payload: Mapping[str, Any], fields: Sequence[str]
) -> list[str]:
    return [field for field in fields if field not in payload]


def _inspect_duckdb(path: Path, declaration: Mapping[str, Any]) -> dict[str, Any]:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        tables = [row[0] for row in connection.execute("SHOW TABLES").fetchall()]
        table = str(declaration.get("table") or RAW_TABLE)
        if table not in tables:
            raise ValueError(f"missing table {table}")
        description = connection.execute(f'DESCRIBE "{table}"').fetchall()
        columns = [str(row[0]) for row in description]
        required = list(declaration.get("required_columns", RAW_COLUMNS))
        missing = [field for field in required if field not in columns]
        if missing:
            raise ValueError(f"missing required columns: {missing}")
        row_count = int(
            connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        )
        key_count = int(
            connection.execute(
                f'SELECT COUNT(*) FROM (SELECT DISTINCT security_id,trading_date,observation_sequence FROM "{table}")'
            ).fetchone()[0]
        )
        security_count = int(
            connection.execute(
                f'SELECT COUNT(DISTINCT security_id) FROM "{table}"'
            ).fetchone()[0]
        )
        date_range = connection.execute(
            f'SELECT MIN(trading_date),MAX(trading_date) FROM "{table}"'
        ).fetchone()
        return {
            "table": table,
            "columns": columns,
            "row_count": row_count,
            "key_count": key_count,
            "security_count": security_count,
            "date_min": date_range[0].isoformat() if date_range[0] else None,
            "date_max": date_range[1].isoformat() if date_range[1] else None,
        }
    finally:
        connection.close()


def _inspect_json(path: Path, declaration: Mapping[str, Any]) -> dict[str, Any]:
    payload = load_json(path)
    missing = _required_json_fields(
        payload, declaration.get("required_json_fields", ())
    )
    if missing:
        raise ValueError(f"missing JSON fields {missing}: {path.name}")
    return {"payload": payload, "row_count": None}


def prepare_input_manifest(
    manifest_path: Path,
    *,
    input_root: Path | None,
    allow_synthetic_fixture: bool,
    allow_formal_run: bool,
    reviewed_implementation_sha: str | None,
) -> dict[str, Any]:
    """Validate manifest, authorization, paths, hashes and JSON evidence."""

    manifest_path = manifest_path.resolve()
    manifest = load_json(manifest_path)
    _validate_schema(manifest, INPUT_MANIFEST_SCHEMA)
    manifest_type = manifest["manifest_type"]
    synthetic = manifest_type == SYNTHETIC_MANIFEST_TYPE
    formal = manifest_type == FORMAL_MANIFEST_TYPE
    authorization = manifest["authorization"]
    if synthetic:
        if not allow_synthetic_fixture or allow_formal_run:
            raise RuntimeError("synthetic manifest requires synthetic mode only")
        if reviewed_implementation_sha is not None:
            raise ValueError("synthetic mode must not receive a reviewed SHA")
        if (
            authorization["status"] != "synthetic_fixture_only"
            or authorization["formal_run_allowed"] is not False
        ):
            raise ValueError("synthetic manifest authorization status mismatch")
    elif formal:
        if allow_synthetic_fixture or not allow_formal_run:
            raise RuntimeError("authorized manifest requires formal mode only")
        if not reviewed_implementation_sha or not SHA40_PATTERN.fullmatch(
            reviewed_implementation_sha
        ):
            raise ValueError(
                "formal mode requires a 40-character lowercase reviewed SHA"
            )
        if (
            authorization["status"] != "approved"
            or authorization["formal_run_allowed"] is not True
        ):
            raise ValueError("formal manifest authorization is not approved")
        if (
            authorization.get("reviewed_implementation_sha")
            != reviewed_implementation_sha
        ):
            raise ValueError("formal reviewed implementation SHA mismatch")
        if authorization.get("authorized_for_task") != TASK_ID:
            raise ValueError("formal authorization task mismatch")
        if authorization.get("authorization_scope") != (
            "EXP-A02 formal raw-domain availability validity only"
        ):
            raise ValueError("formal authorization scope mismatch")
    else:
        raise ValueError(f"unsupported EXP-A02 manifest type: {manifest_type}")
    artifacts = manifest["input_artifacts"]
    if set(artifacts) != set(EXPECTED_MANIFEST_ARTIFACTS) or len(artifacts) != len(
        EXPECTED_MANIFEST_ARTIFACTS
    ):
        raise ValueError(
            "EXP-A02 input manifest must contain exactly the five A01 artifacts"
        )
    bindings = manifest["cross_artifact_bindings"]
    if bindings["accepted_run_id"] != A01_RUN_ID:
        raise ValueError("accepted A01 run binding mismatch")
    if bindings["implementation_sha"] != A01_IMPLEMENTATION_SHA:
        raise ValueError("accepted A01 implementation binding mismatch")
    if bindings["result_commit"] != A01_RESULT_COMMIT:
        raise ValueError("accepted A01 result commit binding mismatch")
    for binding_name in ("raw_artifact_sha256", "a01_manifest_sha256"):
        if not SHA64_PATTERN.fullmatch(str(bindings[binding_name])):
            raise ValueError(f"invalid SHA-256 binding: {binding_name}")

    metadata: dict[str, Any] = {}
    paths: dict[str, Path] = {}
    payloads: dict[str, dict[str, Any]] = {}
    artifact_hashes: dict[str, str] = {}
    for artifact_id in EXPECTED_MANIFEST_ARTIFACTS:
        declaration = artifacts[artifact_id]
        if declaration["artifact_id"] != artifact_id:
            raise ValueError(f"artifact_id mismatch: {artifact_id}")
        if declaration["artifact_kind"] != EXPECTED_ARTIFACT_KINDS[artifact_id]:
            raise ValueError(f"artifact_kind mismatch: {artifact_id}")
        if declaration["filename"] != Path(declaration["path"]).name:
            raise ValueError(f"artifact filename/path mismatch: {artifact_id}")
        policy = declaration["path_policy"]
        if synthetic and policy != "synthetic_fixture":
            raise ValueError("synthetic manifest requires synthetic_fixture paths")
        if formal and policy == "synthetic_fixture":
            raise ValueError("formal manifest cannot use synthetic_fixture paths")
        path = _resolve_declared_path(
            manifest_path,
            declaration,
            input_root=input_root,
            synthetic_fixture=synthetic,
        )
        if not path.is_file():
            raise FileNotFoundError(f"input artifact is missing: {path}")
        if not SHA64_PATTERN.fullmatch(str(declaration["sha256"])):
            raise ValueError(f"invalid artifact SHA-256: {artifact_id}")
        actual_sha = sha256_file(path)
        if actual_sha != declaration["sha256"]:
            raise ValueError(f"input artifact hash mismatch: {artifact_id}")
        paths[artifact_id] = path
        artifact_hashes[artifact_id] = actual_sha

    for artifact_id in EXPECTED_MANIFEST_ARTIFACTS:
        declaration = artifacts[artifact_id]
        if declaration["artifact_kind"] != "duckdb_table":
            inspected = _inspect_json(paths[artifact_id], declaration)
            payloads[artifact_id] = inspected["payload"]
            metadata[artifact_id] = {"row_count": None}

    # The accepted A01 handoff is a frozen upstream contract.  Required-field
    # checks above are insufficient because the handoff schema also binds the
    # accepted run, raw artifact cardinality/hash, compact manifest hash and
    # review statuses.  Replay it through the fixed schema before any raw
    # DuckDB is opened.
    handoff = validate_handoff(paths["exp_a01_accepted_result_handoff"])
    payloads["exp_a01_accepted_result_handoff"] = handoff
    if (
        handoff["accepted_run_id"] != A01_RUN_ID
        or handoff["implementation_sha"] != A01_IMPLEMENTATION_SHA
    ):
        raise ValueError("accepted A01 handoff identity mismatch")
    if (
        handoff["status"] != "completed_accepted"
        or handoff["formal_result_review_status"] != "accepted"
    ):
        raise ValueError("accepted A01 handoff status mismatch")
    if handoff["downstream_authorization"]["EXP_A02_input_eligible"] is not True:
        raise ValueError("A02 is not authorized to consume the accepted A01 result")
    a01_manifest = payloads["exp_a01_manifest"]
    if (
        a01_manifest.get("task_id") != "EXP-A01"
        or a01_manifest.get("run_id") != A01_RUN_ID
    ):
        raise ValueError("A01 manifest identity mismatch")
    if a01_manifest.get("reviewed_implementation_sha") != A01_IMPLEMENTATION_SHA:
        raise ValueError("A01 manifest implementation binding mismatch")
    validator = payloads["exp_a01_validator_result"]
    if validator.get("status") != "passed" or validator.get("valid") is not True:
        raise ValueError("A01 validator status is not passed")
    anomaly = payloads["exp_a01_anomaly_scan"]
    if anomaly.get("status") != "passed" or anomaly.get("blocking_anomalies"):
        raise ValueError("A01 anomaly status is not passed")
    if bindings["raw_artifact_sha256"] != artifacts["exp_a01_raw_metrics"]["sha256"]:
        raise ValueError("raw artifact cross-binding mismatch")
    if bindings["a01_manifest_sha256"] != artifacts["exp_a01_manifest"]["sha256"]:
        raise ValueError("A01 manifest cross-binding mismatch")
    if bindings["validator_status"] != validator.get("status"):
        raise ValueError("validator cross-binding mismatch")
    if bindings["anomaly_status"] != anomaly.get("status"):
        raise ValueError("anomaly cross-binding mismatch")
    if not synthetic:
        accepted_raw = handoff["raw_artifact"]
        if bindings["raw_artifact_sha256"] != accepted_raw["sha256"]:
            raise ValueError("accepted A01 raw binding mismatch: raw_artifact_sha256")
        if (
            bindings["a01_manifest_sha256"]
            != handoff["compact_result"]["manifest_sha256"]
        ):
            raise ValueError("accepted A01 manifest binding mismatch")

    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha256": sha256_file(manifest_path),
        "synthetic_fixture": synthetic,
        "paths": paths,
        "payloads": payloads,
        "metadata": metadata,
        "handoff": handoff,
        "declarations": artifacts,
        "artifact_hashes": artifact_hashes,
        "reviewed_implementation_sha": reviewed_implementation_sha,
    }


def _validate_raw_input_manifest_metadata(input_info: dict[str, Any]) -> dict[str, Any]:
    """Validate raw table metadata after the caller has recorded input hashes."""

    artifacts = input_info["declarations"]
    bindings = input_info["manifest"]["cross_artifact_bindings"]
    raw_declaration = artifacts["exp_a01_raw_metrics"]
    artifact_metadata = _inspect_duckdb(
        input_info["paths"]["exp_a01_raw_metrics"], raw_declaration
    )
    if raw_declaration.get("row_count") != artifact_metadata["row_count"]:
        raise ValueError("input row count declaration mismatch: exp_a01_raw_metrics")
    if raw_declaration.get("table") != artifact_metadata["table"]:
        raise ValueError("input table declaration mismatch: exp_a01_raw_metrics")
    for field in ("security_count", "date_min", "date_max"):
        if (
            field in raw_declaration
            and raw_declaration[field] != artifact_metadata[field]
        ):
            raise ValueError(f"input {field} declaration mismatch: exp_a01_raw_metrics")
    input_info["metadata"]["exp_a01_raw_metrics"] = artifact_metadata
    expected_cross_bindings = {
        "raw_row_count": artifact_metadata["row_count"],
        "raw_key_count": artifact_metadata["key_count"],
        "security_count": artifact_metadata["security_count"],
        "date_min": artifact_metadata["date_min"],
        "date_max": artifact_metadata["date_max"],
    }
    for field, expected in expected_cross_bindings.items():
        if bindings[field] != expected:
            raise ValueError(f"raw cross-binding mismatch: {field}")
    if not input_info["synthetic_fixture"]:
        accepted_raw = input_info["handoff"]["raw_artifact"]
        accepted_bindings = {
            "raw_artifact_sha256": accepted_raw["sha256"],
            "raw_row_count": accepted_raw["row_count"],
            "raw_key_count": accepted_raw["expected_index_row_count"],
            "security_count": accepted_raw["security_count"],
            "date_min": accepted_raw["date_min"],
            "date_max": accepted_raw["date_max"],
        }
        for field, expected in accepted_bindings.items():
            if bindings[field] != expected:
                raise ValueError(f"accepted A01 raw binding mismatch: {field}")
    return input_info


def validate_input_manifest(
    manifest_path: Path,
    *,
    input_root: Path | None,
    allow_synthetic_fixture: bool,
    allow_formal_run: bool,
    reviewed_implementation_sha: str | None,
) -> dict[str, Any]:
    """Replay all five input bindings, including the raw table metadata."""

    return _validate_raw_input_manifest_metadata(
        prepare_input_manifest(
            manifest_path,
            input_root=input_root,
            allow_synthetic_fixture=allow_synthetic_fixture,
            allow_formal_run=allow_formal_run,
            reviewed_implementation_sha=reviewed_implementation_sha,
        )
    )


def _type_matches(actual: str, expected: str) -> bool:
    actual = actual.upper()
    expected = expected.upper()
    if expected == "INTEGER":
        return actual in {
            "INTEGER",
            "BIGINT",
            "SMALLINT",
            "TINYINT",
            "UBIGINT",
            "UINTEGER",
        }
    if expected == "DOUBLE":
        return actual in {"DOUBLE", "FLOAT", "DECIMAL"} or actual.startswith("DECIMAL")
    return actual == expected


def _empty_mismatches() -> dict[str, int]:
    return {key: 0 for key in MISMATCH_KEYS}


def _count(connection: Any, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0] or 0)


def _raw_invariants(
    connection: Any,
    *,
    expected_row_count: int,
    table: str = RAW_TABLE,
) -> tuple[dict[str, int], dict[str, Any]]:
    mismatches = _empty_mismatches()
    description = connection.execute(f'DESCRIBE "{table}"').fetchall()
    actual_types = {str(row[0]): str(row[1]) for row in description}
    missing = [field for field in RAW_COLUMNS if field not in actual_types]
    wrong_types = [
        field
        for field, expected in RAW_TYPE_EXPECTATIONS.items()
        if field in actual_types and not _type_matches(actual_types[field], expected)
    ]
    mismatches["raw_table_schema_mismatch"] = len(missing) + len(wrong_types)
    row_count = _count(connection, f'SELECT COUNT(*) FROM "{table}"')
    expected_raw_rows = expected_row_count * len(INDICATOR_IDS)
    mismatches["raw_row_count_mismatch"] = int(row_count != expected_raw_rows)
    mismatches["duplicate_indicator_key"] = _count(
        connection,
        f'''SELECT COUNT(*) FROM (
          SELECT security_id,trading_date,observation_sequence,indicator_id
          FROM "{table}" GROUP BY 1,2,3,4 HAVING COUNT(*)<>1
        )''',
    )
    mismatches["indicator_row_count_mismatch"] = _count(
        connection,
        f'''SELECT COUNT(*) FROM (
          SELECT indicator_id,COUNT(*) AS n FROM "{table}"
          GROUP BY indicator_id HAVING indicator_id NOT IN ('{A1_ID}','{A2_ID}','{A2B_ID}') OR n<>{expected_row_count}
        )''',
    )
    mismatches["unknown_indicator"] = _count(
        connection,
        f'''SELECT COUNT(*) FROM "{table}"
        WHERE indicator_id NOT IN ('{A1_ID}','{A2_ID}','{A2B_ID}')''',
    )
    mismatches["validity_domain_mismatch"] = _count(
        connection,
        f'''SELECT COUNT(*) FROM "{table}"
        WHERE validity_status NOT IN ('valid','unknown','blocked','diagnostic_required')''',
    )
    mismatches["valid_raw_null"] = _count(
        connection,
        f'''SELECT COUNT(*) FROM "{table}" WHERE validity_status='valid' AND raw_value IS NULL''',
    )
    mismatches["nonvalid_raw_nonnull"] = _count(
        connection,
        f'''SELECT COUNT(*) FROM "{table}" WHERE validity_status<>'valid' AND raw_value IS NOT NULL''',
    )
    mismatches["nonfinite_valid_raw"] = _count(
        connection,
        f'''SELECT COUNT(*) FROM "{table}"
        WHERE validity_status='valid' AND (raw_value IS NULL OR NOT isfinite(raw_value))''',
    )
    mismatches["domain_violation"] = _count(
        connection,
        f'''SELECT COUNT(*) FROM "{table}" WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)
        AND ((indicator_id IN ('{A1_ID}','{A2B_ID}') AND raw_value<0)
          OR (indicator_id='{A2_ID}' AND (raw_value<0 OR raw_value>1)))''',
    )
    mismatches["a2_grid_violation"] = _count(
        connection,
        f'''SELECT COUNT(*) FROM "{table}" WHERE indicator_id='{A2_ID}' AND validity_status='valid'
        AND ABS(raw_value*20.0-ROUND(raw_value*20.0))>{GRID_RESIDUAL_TOLERANCE}''',
    )
    mismatches["reason_code_domain_mismatch"] = _count(
        connection,
        f'''SELECT COUNT(*) FROM "{table}" r
        WHERE NOT json_valid(r.reason_codes_json)
          OR json_array_length(r.reason_codes_json)=0
          OR EXISTS (
            SELECT 1 FROM json_each(CASE WHEN json_valid(r.reason_codes_json) THEN r.reason_codes_json ELSE '[]' END) j
            WHERE json_extract_string(j.value,'$') NOT IN ({",".join(repr(code) for code in REASON_CODES)})
          )''',
    )
    mismatch_sql = f'''
WITH keys AS (
 SELECT security_id,trading_date,observation_sequence,
  MAX(CASE WHEN indicator_id='{A2_ID}' THEN validity_status END) AS a2_status,
  MAX(CASE WHEN indicator_id='{A2B_ID}' THEN validity_status END) AS a2b_status,
  MAX(CASE WHEN indicator_id='{A2_ID}' THEN reason_codes_json END) AS a2_reason,
  MAX(CASE WHEN indicator_id='{A2B_ID}' THEN reason_codes_json END) AS a2b_reason,
  MAX(CASE WHEN indicator_id='{A2_ID}' THEN required_observation_count END) AS a2_required,
  MAX(CASE WHEN indicator_id='{A2B_ID}' THEN required_observation_count END) AS a2b_required,
  MAX(CASE WHEN indicator_id='{A2_ID}' THEN actual_valid_observation_count END) AS a2_count,
  MAX(CASE WHEN indicator_id='{A2B_ID}' THEN actual_valid_observation_count END) AS a2b_count,
  MAX(CASE WHEN indicator_id='{A2_ID}' THEN input_window_start END) AS a2_start,
  MAX(CASE WHEN indicator_id='{A2B_ID}' THEN input_window_start END) AS a2b_start,
  MAX(CASE WHEN indicator_id='{A2_ID}' THEN input_window_end END) AS a2_end,
  MAX(CASE WHEN indicator_id='{A2B_ID}' THEN input_window_end END) AS a2b_end
 FROM "{table}" GROUP BY 1,2,3
),
a1 AS (
 SELECT security_id,trading_date,observation_sequence,
  MAX(CASE WHEN indicator_id='{A1_ID}' THEN validity_status END) AS a1_status
 FROM "{table}" GROUP BY 1,2,3
)
SELECT
 SUM(CASE WHEN a2_status IS DISTINCT FROM a2b_status THEN 1 ELSE 0 END),
 SUM(CASE WHEN a2_reason IS DISTINCT FROM a2b_reason THEN 1 ELSE 0 END),
 SUM(CASE WHEN a2_required IS DISTINCT FROM a2b_required OR a2_count IS DISTINCT FROM a2b_count OR a2_start IS DISTINCT FROM a2b_start OR a2_end IS DISTINCT FROM a2b_end THEN 1 ELSE 0 END),
 SUM(CASE WHEN a2_status='valid' AND a2b_status<>'valid' THEN 1 ELSE 0 END),
 SUM(CASE WHEN a2_status='valid' AND a1.a1_status<>'valid' THEN 1 ELSE 0 END),
 SUM(CASE WHEN a2b_status='valid' AND a1.a1_status<>'valid' THEN 1 ELSE 0 END)
FROM keys JOIN a1 USING (security_id,trading_date,observation_sequence)
'''
    pair = connection.execute(mismatch_sql).fetchone()
    mismatches["a2_a2b_validity_mismatch"] = int(pair[0] or 0)
    mismatches["a2_a2b_reason_mismatch"] = int(pair[1] or 0)
    mismatches["a2_a2b_window_field_mismatch"] = int(pair[2] or 0)
    mismatches["a2_a2b_valid_key_mismatch"] = _count(
        connection,
        f'''WITH a2 AS (SELECT security_id,trading_date,observation_sequence FROM "{table}" WHERE indicator_id='{A2_ID}' AND validity_status='valid'),
        a2b AS (SELECT security_id,trading_date,observation_sequence FROM "{table}" WHERE indicator_id='{A2B_ID}' AND validity_status='valid')
        SELECT (SELECT COUNT(*) FROM (SELECT * FROM a2 EXCEPT SELECT * FROM a2b)) +
               (SELECT COUNT(*) FROM (SELECT * FROM a2b EXCEPT SELECT * FROM a2))''',
    )
    mismatches["a2_valid_a1_nonvalid"] = int(pair[4] or 0)
    mismatches["a2b_valid_a1_nonvalid"] = int(pair[5] or 0)
    for indicator_id in INDICATOR_IDS:
        if (
            _count(
                connection,
                f'''SELECT COUNT(*) FROM "{table}" WHERE indicator_id='{indicator_id}' AND validity_status='valid' ''',
            )
            == 0
        ):
            mismatches["indicator_without_valid_rows"] += 1
    common_count = _count(
        connection,
        f'''SELECT COUNT(*) FROM (
          SELECT security_id,trading_date,observation_sequence
          FROM "{table}" GROUP BY 1,2,3
          HAVING COUNT(*)=3 AND COUNT(*) FILTER (WHERE validity_status='valid')=3
        )''',
    )
    mismatches["common_triple_without_valid_rows"] = int(common_count == 0)
    details = {
        "row_count": row_count,
        "expected_row_count": expected_row_count,
        "expected_raw_row_count": expected_raw_rows,
        "key_count": _count(
            connection,
            f'''SELECT COUNT(*) FROM (SELECT DISTINCT security_id,trading_date,observation_sequence FROM "{table}")''',
        ),
        "security_count": _count(
            connection, f'SELECT COUNT(DISTINCT security_id) FROM "{table}"'
        ),
        "date_range": [
            value.isoformat() if value is not None else None
            for value in connection.execute(
                f'SELECT MIN(trading_date),MAX(trading_date) FROM "{table}"'
            ).fetchone()
        ],
    }
    return mismatches, details


def _read_csv(path: Path, fields: Sequence[str]) -> list[dict[str, str]]:
    raw = path.read_bytes()
    errors = canonical_text_errors(raw)
    if errors:
        raise ValueError(f"non-canonical CSV text {path}: {errors}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(fields):
            raise ValueError(f"CSV header mismatch {path.name}")
        rows = list(reader)
    if any(set(row) != set(fields) for row in rows):
        raise ValueError(f"CSV row field mismatch {path.name}")
    return rows


def _normalize_cell(value: Any, field: str) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, date | datetime):
        return value.isoformat()
    if field in {
        "total_row_count",
        "valid_count",
        "unknown_count",
        "blocked_count",
        "diagnostic_required_count",
        "valid_raw_null_count",
        "nonvalid_raw_nonnull_count",
        "nonfinite_valid_count",
        "domain_violation_count",
        "zero_count",
        "positive_count",
        "unique_value_count",
        "grid_violation_count",
        "expected_row_count",
        "present_row_count",
        "native_valid_count",
        "total_security_count",
        "valid_security_count",
        "total_year_count",
        "valid_year_count",
        "expected_key_count",
        "all_member_rows_present_count",
        "common_valid_count",
        "union_valid_count",
        "row_count",
        "denominator_count",
        "calendar_year",
        "present_count",
        "unique_security_count",
        "rank",
        "observation_sequence",
    }:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if field in {
        "valid_rate",
        "native_valid_rate_expected",
        "native_valid_rate_present",
        "common_valid_rate_expected",
        "union_valid_rate_expected",
        "row_share",
        "valid_rate_expected",
        "valid_rate_present",
        "min_value",
        "q01_value",
        "q05_value",
        "q25_value",
        "median_value",
        "q75_value",
        "q95_value",
        "q99_value",
        "max_value",
        "mean_value",
        "stddev_pop_value",
        "zero_rate_among_valid",
        "discrete_grid_step",
        "grid_residual_max",
        "raw_value",
        "max_year_valid_share",
        "max_security_valid_share",
    }:
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


def _compare_rows(
    expected: Sequence[Mapping[str, Any]],
    actual: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
    key_fields: Sequence[str],
) -> int:
    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return tuple(_normalize_cell(row.get(field), field) for field in key_fields)

    expected_map = {key(row): row for row in expected}
    actual_map = {key(row): row for row in actual}
    mismatches = len(set(expected_map) ^ set(actual_map))
    for row_key in set(expected_map) & set(actual_map):
        for field in fields:
            left = _normalize_cell(expected_map[row_key].get(field), field)
            right = _normalize_cell(actual_map[row_key].get(field), field)
            if isinstance(left, float) and isinstance(right, float):
                if not math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12):
                    mismatches += 1
            elif left != right:
                mismatches += 1
    return mismatches


def _query_rows(
    connection: Any, query: str, fields: Sequence[str]
) -> list[dict[str, Any]]:
    return [
        dict(zip(fields, row, strict=True))
        for row in connection.execute(query).fetchall()
    ]


def _ind_order(column: str = "indicator_id") -> str:
    return f"CASE {column} WHEN '{A1_ID}' THEN 0 WHEN '{A2_ID}' THEN 1 WHEN '{A2B_ID}' THEN 2 ELSE 99 END,{column}"


def _validator_profiles(
    connection: Any,
    *,
    expected_row_count: int,
    table: str = RAW_TABLE,
) -> dict[str, list[dict[str, Any]]]:
    """Independent SQL aggregate replay; do not replace with producer calls."""

    indicators = ",".join(
        f"('{indicator}',{index})" for index, indicator in enumerate(INDICATOR_IDS)
    )
    statuses = ",".join(
        f"('{status}',{index})" for index, status in enumerate(VALIDITY_STATUSES)
    )
    reasons = ",".join(
        f"('{reason}',{index})" for index, reason in enumerate(REASON_CODES)
    )
    raw_query = f"""
WITH il(indicator_id,io) AS (VALUES {indicators}), a AS (
 SELECT indicator_id,COUNT(*) total_row_count,
 COUNT(*) FILTER(WHERE validity_status='valid') valid_count,
 COUNT(*) FILTER(WHERE validity_status='unknown') unknown_count,
 COUNT(*) FILTER(WHERE validity_status='blocked') blocked_count,
 COUNT(*) FILTER(WHERE validity_status='diagnostic_required') diagnostic_required_count,
 COUNT(*) FILTER(WHERE validity_status='valid' AND raw_value IS NULL) valid_raw_null_count,
 COUNT(*) FILTER(WHERE validity_status<>'valid' AND raw_value IS NOT NULL) nonvalid_raw_nonnull_count,
 COUNT(*) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND NOT isfinite(raw_value)) nonfinite_valid_count,
 COUNT(*) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value) AND ((indicator_id IN ('{A1_ID}','{A2B_ID}') AND raw_value<0) OR (indicator_id='{A2_ID}' AND (raw_value<0 OR raw_value>1)))) domain_violation_count,
 COUNT(*) FILTER(WHERE validity_status='valid')::DOUBLE/NULLIF(COUNT(*),0) valid_rate,
 MIN(raw_value) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) min_value,
 QUANTILE_CONT(raw_value,0.01) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) q01_value,
 QUANTILE_CONT(raw_value,0.05) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) q05_value,
 QUANTILE_CONT(raw_value,0.25) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) q25_value,
 QUANTILE_CONT(raw_value,0.50) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) median_value,
 QUANTILE_CONT(raw_value,0.75) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) q75_value,
 QUANTILE_CONT(raw_value,0.95) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) q95_value,
 QUANTILE_CONT(raw_value,0.99) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) q99_value,
 MAX(raw_value) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) max_value,
 AVG(raw_value) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) mean_value,
 STDDEV_POP(raw_value) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) stddev_pop_value,
 COUNT(*) FILTER(WHERE validity_status='valid' AND raw_value=0) zero_count,
 COUNT(*) FILTER(WHERE validity_status='valid' AND raw_value=0)::DOUBLE/NULLIF(COUNT(*) FILTER(WHERE validity_status='valid'),0) zero_rate_among_valid,
 COUNT(*) FILTER(WHERE validity_status='valid' AND raw_value>0) positive_count,
 COUNT(DISTINCT raw_value) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) unique_value_count,
 MIN(trading_date) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) first_valid_date,
 MAX(trading_date) FILTER(WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) last_valid_date,
 MAX(ABS(raw_value*20-ROUND(raw_value*20))) FILTER(WHERE indicator_id='{A2_ID}' AND validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) grid_residual_max,
 COUNT(*) FILTER(WHERE indicator_id='{A2_ID}' AND validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value) AND ABS(raw_value*20-ROUND(raw_value*20))>{GRID_RESIDUAL_TOLERANCE}) grid_violation_count
 FROM "{table}" GROUP BY indicator_id)
SELECT il.indicator_id,COALESCE(a.total_row_count,0),COALESCE(a.valid_count,0),COALESCE(a.unknown_count,0),COALESCE(a.blocked_count,0),COALESCE(a.diagnostic_required_count,0),COALESCE(a.valid_rate,0.0),COALESCE(a.valid_raw_null_count,0),COALESCE(a.nonvalid_raw_nonnull_count,0),COALESCE(a.nonfinite_valid_count,0),COALESCE(a.domain_violation_count,0),a.min_value,a.q01_value,a.q05_value,a.q25_value,a.median_value,a.q75_value,a.q95_value,a.q99_value,a.max_value,a.mean_value,a.stddev_pop_value,COALESCE(a.zero_count,0),COALESCE(a.zero_rate_among_valid,0.0),COALESCE(a.positive_count,0),COALESCE(a.unique_value_count,0),CASE WHEN il.indicator_id='{A2_ID}' THEN 0.05 ELSE NULL END,CASE WHEN il.indicator_id='{A2_ID}' THEN COALESCE(a.grid_violation_count,0) ELSE 0 END,CASE WHEN il.indicator_id='{A2_ID}' THEN a.grid_residual_max ELSE NULL END,a.first_valid_date,a.last_valid_date
FROM il LEFT JOIN a USING(indicator_id) ORDER BY il.io
"""
    profiles: dict[str, list[dict[str, Any]]] = {
        "raw_domain_profile": _query_rows(
            connection, raw_query, CSV_FIELDS["raw_domain_profile"]
        ),
    }

    availability_query = f"""
WITH k AS (SELECT security_id,trading_date,observation_sequence,MAX(CASE WHEN expected_observation_status='present' THEN 1 ELSE 0 END) present FROM "{table}" GROUP BY 1,2,3),
b AS (SELECT indicator_id,COUNT(*) FILTER(WHERE validity_status='valid') native_valid_count,COUNT(*) FILTER(WHERE validity_status='unknown') unknown_count,COUNT(*) FILTER(WHERE validity_status='blocked') blocked_count,COUNT(*) FILTER(WHERE validity_status='diagnostic_required') diagnostic_required_count,COUNT(DISTINCT security_id) total_security_count,COUNT(DISTINCT security_id) FILTER(WHERE validity_status='valid') valid_security_count,COUNT(DISTINCT YEAR(trading_date)) total_year_count,COUNT(DISTINCT YEAR(trading_date)) FILTER(WHERE validity_status='valid') valid_year_count,MIN(trading_date) FILTER(WHERE validity_status='valid') first_valid_date,MAX(trading_date) FILTER(WHERE validity_status='valid') last_valid_date FROM "{table}" GROUP BY indicator_id),
y AS (SELECT indicator_id,YEAR(trading_date) yr,COUNT(*) FILTER(WHERE validity_status='valid') v FROM "{table}" GROUP BY 1,2),
s AS (SELECT indicator_id,security_id,COUNT(*) FILTER(WHERE validity_status='valid') v FROM "{table}" GROUP BY 1,2),
ys AS (SELECT y.indicator_id,MAX(y.v::DOUBLE/NULLIF(b.native_valid_count,0)) max_year_valid_share FROM y JOIN b USING(indicator_id) GROUP BY y.indicator_id),
ss AS (SELECT s.indicator_id,MAX(s.v::DOUBLE/NULLIF(b.native_valid_count,0)) max_security_valid_share FROM s JOIN b USING(indicator_id) GROUP BY s.indicator_id),
il(indicator_id,io) AS (VALUES {indicators})
SELECT il.indicator_id,{expected_row_count},COALESCE((SELECT COUNT(*) FROM k WHERE present=1),0),COALESCE(b.native_valid_count,0),COALESCE(b.native_valid_count::DOUBLE/NULLIF({expected_row_count},0),0.0),COALESCE(b.native_valid_count::DOUBLE/NULLIF((SELECT COUNT(*) FROM k WHERE present=1),0),0.0),COALESCE(b.unknown_count,0),COALESCE(b.blocked_count,0),COALESCE(b.diagnostic_required_count,0),COALESCE(b.total_security_count,0),COALESCE(b.valid_security_count,0),COALESCE(b.total_year_count,0),COALESCE(b.valid_year_count,0),b.first_valid_date,b.last_valid_date,COALESCE(ys.max_year_valid_share,0.0),COALESCE(ss.max_security_valid_share,0.0)
FROM il LEFT JOIN b USING(indicator_id) LEFT JOIN ys USING(indicator_id) LEFT JOIN ss USING(indicator_id) ORDER BY il.io
"""
    profiles["indicator_availability"] = _query_rows(
        connection, availability_query, CSV_FIELDS["indicator_availability"]
    )

    groups = (
        ("A1_A2", (A1_ID, A2_ID)),
        ("A1_A2b", (A1_ID, A2B_ID)),
        ("A2_A2b", (A2_ID, A2B_ID)),
        ("A1_A2_A2b", INDICATOR_IDS),
    )
    common_rows: list[dict[str, Any]] = []
    for set_id, members in groups:
        members_sql = ",".join(repr(item) for item in members)
        flags = ",".join(
            f"MAX(CASE WHEN indicator_id={item!r} AND validity_status='valid' THEN 1 ELSE 0 END) v{index}"
            for index, item in enumerate(members)
        )
        total = "+".join(f"v{index}" for index in range(len(members)))
        query = f"""
WITH k AS (SELECT security_id,trading_date,observation_sequence,COUNT(DISTINCT indicator_id) FILTER(WHERE indicator_id IN({members_sql})) member_rows,{flags} FROM "{table}" GROUP BY 1,2,3)
SELECT {set_id!r},{json.dumps(list(members), separators=(",", ":"))!r},{expected_row_count},COUNT(*) FILTER(WHERE member_rows={len(members)}),COUNT(*) FILTER(WHERE member_rows={len(members)} AND {total}={len(members)}),COUNT(*) FILTER(WHERE member_rows={len(members)} AND {total}={len(members)})::DOUBLE/NULLIF({expected_row_count},0),COUNT(*) FILTER(WHERE member_rows={len(members)} AND {total}>0),COUNT(*) FILTER(WHERE member_rows={len(members)} AND {total}>0)::DOUBLE/NULLIF({expected_row_count},0) FROM k
"""
        common_rows.extend(
            _query_rows(connection, query, CSV_FIELDS["common_valid_availability"])
        )
    profiles["common_valid_availability"] = common_rows

    status_query = f"""
WITH il(indicator_id,io) AS (VALUES {indicators}), sl(validity_status,so) AS (VALUES {statuses}), t AS (SELECT indicator_id,COUNT(*) denominator_count FROM "{table}" GROUP BY 1)
SELECT il.indicator_id,sl.validity_status,COUNT(r.indicator_id),COALESCE(t.denominator_count,0),COUNT(r.indicator_id)::DOUBLE/NULLIF(t.denominator_count,0)
FROM il CROSS JOIN sl LEFT JOIN "{table}" r ON r.indicator_id=il.indicator_id AND r.validity_status=sl.validity_status LEFT JOIN t ON t.indicator_id=il.indicator_id
GROUP BY il.indicator_id,il.io,sl.validity_status,sl.so,t.denominator_count ORDER BY il.io,sl.so
"""
    profiles["validity_status_profile"] = _query_rows(
        connection, status_query, CSV_FIELDS["validity_status_profile"]
    )

    reason_query = f"""
WITH il(indicator_id,io) AS (VALUES {indicators}), rl(reason_code,ro) AS (VALUES {reasons}), t AS (SELECT indicator_id,COUNT(*) denominator_count FROM "{table}" GROUP BY 1), rr AS (SELECT r.indicator_id,json_extract_string(j.value,'$') reason_code FROM "{table}" r,LATERAL json_each(CASE WHEN json_valid(r.reason_codes_json) THEN r.reason_codes_json ELSE '[]' END) j)
SELECT il.indicator_id,rl.reason_code,COUNT(rr.reason_code),COALESCE(t.denominator_count,0),COUNT(rr.reason_code)::DOUBLE/NULLIF(t.denominator_count,0)
FROM il CROSS JOIN rl LEFT JOIN rr ON rr.indicator_id=il.indicator_id AND rr.reason_code=rl.reason_code LEFT JOIN t ON t.indicator_id=il.indicator_id
GROUP BY il.indicator_id,il.io,rl.reason_code,rl.ro,t.denominator_count ORDER BY il.io,rl.ro
"""
    profiles["reason_code_profile"] = _query_rows(
        connection, reason_query, CSV_FIELDS["reason_code_profile"]
    )

    combination_query = f"""
WITH t AS (SELECT indicator_id,COUNT(*) denominator_count FROM "{table}" GROUP BY 1)
SELECT r.indicator_id,r.reason_codes_json,COUNT(*),t.denominator_count,COUNT(*)::DOUBLE/NULLIF(t.denominator_count,0)
FROM "{table}" r JOIN t USING(indicator_id) GROUP BY r.indicator_id,r.reason_codes_json,t.denominator_count
ORDER BY {_ind_order("r.indicator_id")},r.reason_codes_json
"""
    profiles["reason_combination_profile"] = _query_rows(
        connection, combination_query, CSV_FIELDS["reason_combination_profile"]
    )

    year_query = f"""
SELECT YEAR(trading_date),indicator_id,COUNT(*),COUNT(*) FILTER(WHERE expected_observation_status='present'),COUNT(*) FILTER(WHERE validity_status='valid'),COUNT(*) FILTER(WHERE validity_status='valid')::DOUBLE/NULLIF(COUNT(*),0),COUNT(*) FILTER(WHERE validity_status='valid')::DOUBLE/NULLIF(COUNT(*) FILTER(WHERE expected_observation_status='present'),0),COUNT(*) FILTER(WHERE validity_status='unknown'),COUNT(*) FILTER(WHERE validity_status='blocked'),COUNT(*) FILTER(WHERE validity_status='diagnostic_required'),COUNT(DISTINCT security_id),COUNT(DISTINCT security_id) FILTER (WHERE validity_status='valid')
FROM "{table}" GROUP BY YEAR(trading_date),indicator_id ORDER BY YEAR(trading_date),{_ind_order()}
"""
    profiles["year_availability"] = _query_rows(
        connection, year_query, CSV_FIELDS["year_availability"]
    )

    security_query = f"""
SELECT security_id,indicator_id,COUNT(*),COUNT(*) FILTER(WHERE expected_observation_status='present'),COUNT(*) FILTER(WHERE validity_status='valid'),COUNT(*) FILTER(WHERE validity_status='valid')::DOUBLE/NULLIF(COUNT(*),0),COUNT(*) FILTER(WHERE validity_status='valid')::DOUBLE/NULLIF(COUNT(*) FILTER(WHERE expected_observation_status='present'),0),COUNT(*) FILTER(WHERE validity_status='unknown'),COUNT(*) FILTER(WHERE validity_status='blocked'),COUNT(*) FILTER(WHERE validity_status='diagnostic_required'),MIN(trading_date),MAX(trading_date),MIN(trading_date) FILTER (WHERE validity_status='valid'),MAX(trading_date) FILTER (WHERE validity_status='valid')
FROM "{table}" GROUP BY security_id,indicator_id ORDER BY security_id,{_ind_order()}
"""
    profiles["security_availability"] = _query_rows(
        connection, security_query, CSV_FIELDS["security_availability"]
    )

    extreme_query = f"""
WITH valid_rows AS (
  SELECT indicator_id, security_id, trading_date, observation_sequence, raw_value,
    ROW_NUMBER() OVER (
      PARTITION BY indicator_id
      ORDER BY raw_value, security_id, observation_sequence
    ) AS lower_rank,
    ROW_NUMBER() OVER (
      PARTITION BY indicator_id
      ORDER BY raw_value DESC, security_id, observation_sequence
    ) AS upper_rank
  FROM "{table}"
  WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)
), tails AS (
  SELECT indicator_id, 'lower' AS tail, lower_rank AS rank,
    security_id, trading_date, observation_sequence, raw_value
  FROM valid_rows
  WHERE lower_rank <= {EXTREME_TAIL_SIZE}
  UNION ALL
  SELECT indicator_id, 'upper' AS tail, upper_rank AS rank,
    security_id, trading_date, observation_sequence, raw_value
  FROM valid_rows
  WHERE upper_rank <= {EXTREME_TAIL_SIZE}
)
SELECT indicator_id, tail, rank, security_id, trading_date,
  observation_sequence, raw_value
FROM tails
ORDER BY {_ind_order("indicator_id")},
  CASE tail WHEN 'lower' THEN 0 ELSE 1 END, rank
"""
    profiles["extreme_value_sample"] = _query_rows(
        connection, extreme_query, CSV_FIELDS["extreme_value_sample"]
    )
    return profiles


def _load_persisted_profiles(package_root: Path) -> dict[str, list[dict[str, str]]]:
    profiles: dict[str, list[dict[str, str]]] = {}
    for profile_name, filename in OUTPUT_FILES.items():
        if profile_name not in CSV_FIELDS:
            continue
        profiles[profile_name] = _read_csv(
            package_root / filename, CSV_FIELDS[profile_name]
        )
    return profiles


def _validate_output_manifest(
    package_root: Path,
    *,
    input_info: Mapping[str, Any],
    run_id: str,
    require_final_manifest: bool,
) -> tuple[int, dict[str, Any] | None]:
    path = package_root / OUTPUT_FILES["manifest"]
    if not path.is_file():
        return (1 if require_final_manifest else 0), None
    try:
        manifest = load_json(path)
    except Exception:
        return 1, None
    mismatches = 0
    if manifest.get("task_id") != TASK_ID or manifest.get("run_id") != run_id:
        mismatches += 1
    synthetic = bool(input_info["synthetic_fixture"])
    expected_phase = "implementation_synthetic_fixture" if synthetic else "formal_run"
    if manifest.get("phase") != expected_phase:
        mismatches += 1
    if manifest.get("synthetic_fixture") is not synthetic:
        mismatches += 1
    expected_flags = {
        "formal_run_allowed": not synthetic,
        "formal_run_executed": not synthetic,
        "formal_artifacts_generated": not synthetic,
    }
    for field, expected in expected_flags.items():
        if manifest.get(field) is not expected:
            mismatches += 1
    if not synthetic and manifest.get("reviewed_implementation_sha") != input_info.get(
        "reviewed_implementation_sha"
    ):
        mismatches += 1
    if manifest.get("EXP_A03_started") is not False:
        mismatches += 1
    if manifest.get("A_layer_registered") is not False:
        mismatches += 1
    if manifest.get("PCATV_created") is not False:
        mismatches += 1
    if manifest.get("input_manifest_sha256") != input_info["manifest_sha256"]:
        mismatches += 1
    if not require_final_manifest and manifest.get("final_manifest") is not True:
        return mismatches, manifest
    expected_files = set(OUTPUT_FILES.values()) - {OUTPUT_FILES["manifest"]}
    actual_files = {item.name for item in package_root.iterdir() if item.is_file()}
    if actual_files != expected_files | {OUTPUT_FILES["manifest"]}:
        mismatches += 1
    declared = manifest.get("output_artifacts")
    if not isinstance(declared, dict) or set(declared) != expected_files:
        mismatches += 1
    else:
        for filename in expected_files:
            file_path = package_root / filename
            if not file_path.is_file():
                mismatches += 1
                continue
            declaration = declared[filename]
            if declaration.get("sha256") != sha256_file(file_path):
                mismatches += 1
            if declaration.get("path") != filename:
                mismatches += 1
    return mismatches, manifest


def _validate_input_hash_bindings(
    output_manifest: Mapping[str, Any] | None,
    input_info: Mapping[str, Any],
) -> tuple[list[str], dict[str, str] | None, dict[str, str] | None, int | None]:
    if output_manifest is None:
        return (["input_hash_manifest_missing"], None, None, None)
    before_value = output_manifest.get("input_hashes_before")
    after_value = output_manifest.get("input_hashes_after")
    if not isinstance(before_value, dict) or not isinstance(after_value, dict):
        return (["input_hash_bindings_missing"], None, None, None)
    before = {str(key): str(value) for key, value in before_value.items()}
    after = {str(key): str(value) for key, value in after_value.items()}
    expected = {
        str(key): str(value) for key, value in input_info["artifact_hashes"].items()
    }
    errors: list[str] = []
    if set(before) != set(EXPECTED_MANIFEST_ARTIFACTS):
        errors.append("input_hashes_before_artifact_set_mismatch")
    if set(after) != set(EXPECTED_MANIFEST_ARTIFACTS):
        errors.append("input_hashes_after_artifact_set_mismatch")
    if after != expected:
        errors.append("input_hashes_after_current_mismatch")
    changed_count = sum(
        before.get(artifact_id) != after.get(artifact_id)
        for artifact_id in EXPECTED_MANIFEST_ARTIFACTS
    )
    if before != after:
        errors.append("input_hashes_before_after_differ")
    declared_changed_count = output_manifest.get("input_hash_changed_count")
    if declared_changed_count != changed_count:
        errors.append("input_hash_changed_count_mismatch")
    if changed_count != 0:
        errors.append("input_hash_changed_count_nonzero")
    return errors, before, after, changed_count


def _validate_small_json_artifact(
    package_root: Path, filename: str, task_id: str, run_id: str
) -> tuple[int, dict[str, Any] | None]:
    path = package_root / filename
    try:
        payload = load_json(path)
    except Exception:
        return 1, None
    mismatch = int(payload.get("task_id") != task_id or payload.get("run_id") != run_id)
    return mismatch, payload


def _forbidden_output_mismatches(package_root: Path) -> int:
    mismatches = 0
    exact_forbidden = set(FORBIDDEN_OUTPUT_FIELD_NAMES)
    for filename in OUTPUT_FILES.values():
        if (
            filename == OUTPUT_FILES["result_analysis"]
            or not (package_root / filename).is_file()
        ):
            continue
        if filename.endswith(".csv"):
            try:
                header = (
                    (package_root / filename)
                    .read_text(encoding="utf-8")
                    .splitlines()[0]
                    .split(",")
                )
            except Exception:
                continue
            mismatches += sum(field in exact_forbidden for field in header)
        elif filename.endswith(".json"):
            try:
                value = load_json(package_root / filename)
            except Exception:
                continue
            stack: list[Any] = [value]
            while stack:
                current = stack.pop()
                if isinstance(current, dict):
                    mismatches += sum(key in exact_forbidden for key in current)
                    stack.extend(current.values())
                elif isinstance(current, list):
                    stack.extend(current)
    return mismatches


def validate_package(
    package_root: Path,
    *,
    config: Mapping[str, Any],
    input_manifest_path: Path,
    run_id: str,
    require_final_manifest: bool = True,
    allow_synthetic_fixture: bool = True,
    require_diagnostics: bool = True,
    input_root: Path | None = None,
    allow_formal_run: bool = False,
    reviewed_implementation_sha: str | None = None,
) -> dict[str, Any]:
    """Validate one A02 package and return a compact diagnostic result."""

    package_root = package_root.resolve()
    mismatches = _empty_mismatches()
    errors: list[str] = []
    try:
        config_errors = validate_static_config(config)
        if config_errors:
            errors.extend(config_errors)
        input_info = validate_input_manifest(
            input_manifest_path,
            input_root=input_root,
            allow_synthetic_fixture=allow_synthetic_fixture,
            allow_formal_run=allow_formal_run,
            reviewed_implementation_sha=reviewed_implementation_sha,
        )
    except Exception as exc:  # noqa: BLE001
        mismatches["lineage_mismatch"] = 1
        return {
            "task_id": TASK_ID,
            "run_id": run_id,
            "status": "failed",
            "valid": False,
            "errors": [f"lineage:{exc}"],
            "warnings": [],
            "mismatch_counts": mismatches,
            "lineage_replayed_from_disk": True,
            "full_set_based_invariant_scan_performed": False,
            "full_output_aggregate_recompute_performed": False,
            "core_validator_execution_count": 1,
        }

    raw_path = input_info["paths"]["exp_a01_raw_metrics"]
    raw_metadata = input_info["metadata"]["exp_a01_raw_metrics"]
    expected_row_count = raw_metadata["key_count"]
    raw_details: dict[str, Any] = {}
    connection = duckdb.connect(str(raw_path), read_only=True)
    try:
        raw_mismatches, raw_details = _raw_invariants(
            connection, expected_row_count=expected_row_count
        )
        for key, value in raw_mismatches.items():
            mismatches[key] += int(value)
        recomputed = _validator_profiles(
            connection, expected_row_count=expected_row_count
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"aggregate_recompute:{exc}")
        mismatches["aggregate_csv_mismatch"] += 1
        recomputed = {}
    finally:
        connection.close()

    try:
        persisted = _load_persisted_profiles(package_root)
        key_fields = {
            "raw_domain_profile": ("indicator_id",),
            "indicator_availability": ("indicator_id",),
            "common_valid_availability": ("set_id",),
            "validity_status_profile": ("indicator_id", "validity_status"),
            "reason_code_profile": ("indicator_id", "reason_code"),
            "reason_combination_profile": ("indicator_id", "reason_codes_json"),
            "year_availability": ("calendar_year", "indicator_id"),
            "security_availability": ("security_id", "indicator_id"),
            "extreme_value_sample": ("indicator_id", "tail", "rank"),
        }
        for profile_name, fields in CSV_FIELDS.items():
            mismatches["aggregate_csv_mismatch"] += _compare_rows(
                recomputed.get(profile_name, ()),
                persisted.get(profile_name, ()),
                fields,
                key_fields[profile_name],
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"persisted_csv:{exc}")
        mismatches["aggregate_csv_mismatch"] += 1

    manifest_mismatch, output_manifest = _validate_output_manifest(
        package_root,
        input_info=input_info,
        run_id=run_id,
        require_final_manifest=require_final_manifest,
    )
    mismatches["output_manifest_mismatch"] += manifest_mismatch
    (
        input_hash_errors,
        input_hashes_before,
        input_hashes_after,
        input_hash_changed_count,
    ) = _validate_input_hash_bindings(output_manifest, input_info)
    errors.extend(input_hash_errors)
    mismatches["input_hash_mismatch"] += len(input_hash_errors)
    if output_manifest is not None:
        for filename, declaration in output_manifest.get(
            "output_artifacts", {}
        ).items():
            if (
                filename in OUTPUT_FILES.values()
                and (package_root / filename).is_file()
            ):
                mismatches["output_artifact_hash_mismatch"] += int(
                    declaration.get("sha256") != sha256_file(package_root / filename)
                )

    if require_diagnostics:
        validator_mismatch, validator_artifact = _validate_small_json_artifact(
            package_root, OUTPUT_FILES["validator_result"], TASK_ID, run_id
        )
        anomaly_mismatch, anomaly_artifact = _validate_small_json_artifact(
            package_root, OUTPUT_FILES["anomaly_scan"], TASK_ID, run_id
        )
        mismatches["validator_artifact_mismatch"] += validator_mismatch
        mismatches["anomaly_artifact_mismatch"] += anomaly_mismatch
        if validator_artifact is not None:
            mismatches["validator_artifact_mismatch"] += int(
                validator_artifact.get("status") != "passed"
                or validator_artifact.get("valid") is not True
            )
            if input_hashes_before is not None and input_hashes_after is not None:
                mismatches["validator_artifact_mismatch"] += int(
                    validator_artifact.get("input_hashes_before") != input_hashes_before
                    or validator_artifact.get("input_hashes_after")
                    != input_hashes_after
                    or validator_artifact.get("input_hash_changed_count")
                    != input_hash_changed_count
                )
        if anomaly_artifact is not None:
            mismatches["anomaly_artifact_mismatch"] += int(
                anomaly_artifact.get("status")
                not in {"passed", "passed_with_investigation_items"}
                or bool(anomaly_artifact.get("blocking_anomalies", []))
            )
        mismatches["forbidden_output_field"] += _forbidden_output_mismatches(
            package_root
        )
        analysis_path = package_root / OUTPUT_FILES["result_analysis"]
        if not analysis_path.is_file():
            errors.append("result_analysis_missing")
            mismatches["output_manifest_mismatch"] += 1
        else:
            analysis_errors = _result_analysis_text_errors(analysis_path)
            errors.extend(analysis_errors)
            mismatches["output_manifest_mismatch"] += len(analysis_errors)

    blocking = sum(mismatches.values())
    status = "failed" if blocking or errors else "passed"
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": status,
        "valid": status == "passed",
        "errors": errors,
        "warnings": [],
        "mismatch_counts": mismatches,
        "lineage_replayed_from_disk": True,
        "full_set_based_invariant_scan_performed": True,
        "full_output_aggregate_recompute_performed": True,
        "core_validator_execution_count": 1,
        "raw_details": raw_details,
        "input_manifest_sha256": input_info["manifest_sha256"],
        "input_artifact_hashes": {
            name: sha256_file(path) for name, path in input_info["paths"].items()
        },
        "input_hashes_before": input_hashes_before,
        "input_hashes_after": input_hashes_after,
        "input_hash_changed_count": input_hash_changed_count,
        "reviewed_implementation_sha": input_info.get("reviewed_implementation_sha"),
        "checked_files": sorted(path.name for path in package_root.glob("*")),
        "checked_tables": [RAW_TABLE],
    }


def cheap_validate_final_package(
    package_root: Path,
    *,
    input_manifest_sha256: str,
    run_id: str,
    synthetic_fixture: bool | None = None,
    reviewed_implementation_sha: str | None = None,
    input_info: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate final text/hash bindings; never reopen raw or recompute aggregates."""

    errors: list[str] = []
    manifest_path = package_root / OUTPUT_FILES["manifest"]
    try:
        manifest = load_json(manifest_path)
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "errors": [f"manifest:{exc}"]}
    if manifest.get("task_id") != TASK_ID:
        errors.append("manifest_task_id_mismatch")
    if manifest.get("run_id") != run_id:
        errors.append("manifest_run_id_mismatch")
    if manifest.get("final_manifest") is not True:
        errors.append("final_manifest_flag_missing")
    if manifest.get("input_manifest_sha256") != input_manifest_sha256:
        errors.append("input_manifest_sha256_mismatch")
    if synthetic_fixture is None:
        synthetic = manifest.get("synthetic_fixture")
        if not isinstance(synthetic, bool):
            errors.append("synthetic_fixture_flag_missing")
            synthetic = False
    else:
        synthetic = synthetic_fixture
        if manifest.get("synthetic_fixture") is not synthetic:
            errors.append("synthetic_fixture_flag_mismatch")

    expected_phase = "implementation_synthetic_fixture" if synthetic else "formal_run"
    if manifest.get("phase") != expected_phase:
        errors.append("phase_mismatch")
    if manifest.get("formal_data_version") is not False:
        errors.append("formal_data_version_mismatch")
    expected_formal = not synthetic
    for field in (
        "formal_run_allowed",
        "formal_run_executed",
        "formal_artifacts_generated",
    ):
        if manifest.get(field) is not expected_formal:
            errors.append(f"{field}_mismatch")
    if synthetic:
        if manifest.get("reviewed_implementation_sha") is not None:
            errors.append("synthetic_reviewed_implementation_sha_mismatch")
    elif (
        not reviewed_implementation_sha
        or not SHA40_PATTERN.fullmatch(reviewed_implementation_sha)
        or manifest.get("reviewed_implementation_sha") != reviewed_implementation_sha
    ):
        errors.append("reviewed_implementation_sha_mismatch")

    if manifest.get("validation_strategy") != VALIDATION_STRATEGY:
        errors.append("validation_strategy_mismatch")
    if manifest.get("core_validator_execution_count") != 1:
        errors.append("core_validator_execution_count_mismatch")
    expected_upstream = {
        "task_id": "EXP-A01",
        "accepted_run_id": A01_RUN_ID,
        "implementation_sha": A01_IMPLEMENTATION_SHA,
        "result_commit": A01_RESULT_COMMIT,
    }
    accepted_upstream = manifest.get("accepted_upstream")
    if not isinstance(accepted_upstream, Mapping):
        errors.append("accepted_upstream_missing")
    else:
        for field, expected in expected_upstream.items():
            if accepted_upstream.get(field) != expected:
                errors.append(f"accepted_upstream_{field}_mismatch")
    for field in ("EXP_A03_started", "A_layer_registered", "PCATV_created"):
        if manifest.get(field) is not False:
            errors.append(f"{field}_mismatch")

    before_value = manifest.get("input_hashes_before")
    after_value = manifest.get("input_hashes_after")
    if not isinstance(before_value, dict) or not isinstance(after_value, dict):
        errors.append("input_hash_bindings_missing")
    else:
        before = {str(key): str(value) for key, value in before_value.items()}
        after = {str(key): str(value) for key, value in after_value.items()}
        expected_artifact_ids = set(EXPECTED_MANIFEST_ARTIFACTS)
        if set(before) != expected_artifact_ids:
            errors.append("input_hashes_before_artifact_set_mismatch")
        if set(after) != expected_artifact_ids:
            errors.append("input_hashes_after_artifact_set_mismatch")
        if before != after:
            errors.append("input_hashes_before_after_differ")
        if manifest.get("input_hash_changed_count") != 0:
            errors.append("input_hash_changed_count_nonzero")
        input_artifacts = manifest.get("input_artifacts")
        if not isinstance(input_artifacts, Mapping):
            errors.append("input_artifacts_missing")
        else:
            declared_hashes: dict[str, str] = {}
            for artifact_id in EXPECTED_MANIFEST_ARTIFACTS:
                declaration = input_artifacts.get(artifact_id)
                if not isinstance(declaration, Mapping):
                    errors.append(f"input_artifact_missing:{artifact_id}")
                    continue
                declared_hashes[artifact_id] = str(declaration.get("sha256"))
            if after != declared_hashes:
                errors.append("input_hashes_input_artifact_binding_mismatch")
        if input_info is not None:
            expected_hashes = input_info.get("artifact_hashes")
            if isinstance(expected_hashes, Mapping):
                expected_hashes = {
                    str(key): str(value) for key, value in expected_hashes.items()
                }
                if after != expected_hashes:
                    errors.append("input_hashes_current_input_mismatch")

    raw_artifacts = manifest.get("input_artifacts")
    raw_declaration = (
        raw_artifacts.get("exp_a01_raw_metrics")
        if isinstance(raw_artifacts, Mapping)
        else None
    )
    raw_binding_fields = {
        "raw_row_count": "row_count",
        "expected_key_count": "actual_key_count",
        "security_count": "security_count",
        "date_min": "date_min",
        "date_max": "date_max",
    }
    if not isinstance(raw_declaration, Mapping):
        errors.append("raw_input_artifact_binding_missing")
    else:
        for manifest_field, declaration_field in raw_binding_fields.items():
            if manifest.get(manifest_field) != raw_declaration.get(declaration_field):
                errors.append(f"{manifest_field}_binding_mismatch")
        if input_info is not None:
            raw_metadata = input_info.get("metadata", {}).get("exp_a01_raw_metrics")
            if isinstance(raw_metadata, Mapping):
                expected_metadata = {
                    "raw_row_count": raw_metadata.get("row_count"),
                    "expected_key_count": raw_metadata.get("key_count"),
                    "security_count": raw_metadata.get("security_count"),
                    "date_min": raw_metadata.get("date_min"),
                    "date_max": raw_metadata.get("date_max"),
                }
                for field, expected in expected_metadata.items():
                    if manifest.get(field) != expected:
                        errors.append(f"{field}_input_metadata_mismatch")
    expected = set(OUTPUT_FILES.values()) - {OUTPUT_FILES["manifest"]}
    actual_files = {item.name for item in package_root.iterdir() if item.is_file()}
    if actual_files != expected | {OUTPUT_FILES["manifest"]}:
        errors.append("output_file_set_mismatch")
    declared = manifest.get("output_artifacts")
    if not isinstance(declared, dict) or set(declared) != expected:
        errors.append("output_artifact_set_mismatch")
    else:
        for filename in sorted(expected):
            path = package_root / filename
            if not path.is_file():
                errors.append(f"missing_output:{filename}")
                continue
            if declared[filename].get("sha256") != sha256_file(path):
                errors.append(f"output_hash_mismatch:{filename}")
    if any(path.suffix.lower() == ".duckdb" for path in package_root.iterdir()):
        errors.append("new_duckdb_output_forbidden")
    analysis_path = package_root / OUTPUT_FILES["result_analysis"]
    if not analysis_path.is_file():
        errors.append("result_analysis_missing")
    else:
        errors.extend(_result_analysis_text_errors(analysis_path))
    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "aggregate_recomputation_performed": False,
    }
