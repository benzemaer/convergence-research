"""Canonical seven-table contract and package manifest helpers for R2A-T01."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

from src.common.canonical_io import formal_source_binding
from src.r2a.r2a_t01_input_manifest import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]

TABLE_ORDER = (
    "securities",
    "trading_sessions",
    "security_observation_spine",
    "dimension_definitions",
    "dimension_components",
    "daily_component_scores",
    "daily_dimension_scores",
)

COLUMN_DEFINITIONS: dict[str, tuple[tuple[str, str, bool], ...]] = {
    "securities": (
        ("score_release_id", "VARCHAR", False),
        ("security_id", "VARCHAR", False),
        ("universe_id", "VARCHAR", False),
        ("first_expected_date", "DATE", False),
        ("last_expected_date", "DATE", False),
        ("expected_observation_count", "BIGINT", False),
    ),
    "trading_sessions": (
        ("score_release_id", "VARCHAR", False),
        ("trading_date", "DATE", False),
        ("session_sequence", "BIGINT", False),
        ("expected_security_count", "BIGINT", False),
        ("present_security_count", "BIGINT", False),
        ("available_time", "TIMESTAMP WITH TIME ZONE", False),
    ),
    "security_observation_spine": (
        ("score_release_id", "VARCHAR", False),
        ("security_id", "VARCHAR", False),
        ("trading_date", "DATE", False),
        ("observation_sequence", "BIGINT", False),
        ("expected_observation_status", "VARCHAR", False),
        ("source_contract", "VARCHAR", False),
        ("source_ref", "VARCHAR", False),
        ("observation_available_time", "TIMESTAMP WITH TIME ZONE", False),
    ),
    "dimension_definitions": (
        ("score_release_id", "VARCHAR", False),
        ("dimension_id", "VARCHAR", False),
        ("canonical_order", "INTEGER", False),
        ("dimension_name", "VARCHAR", False),
        ("component_count", "INTEGER", False),
        ("aggregation_method", "VARCHAR", False),
        ("score_direction", "VARCHAR", False),
        ("percentile_window_W", "INTEGER", False),
        ("definition_version", "VARCHAR", False),
    ),
    "dimension_components": (
        ("score_release_id", "VARCHAR", False),
        ("dimension_id", "VARCHAR", False),
        ("component_id", "VARCHAR", False),
        ("component_order", "INTEGER", False),
        ("weight", "DOUBLE", False),
        ("raw_metric_name", "VARCHAR", False),
        ("raw_value_direction", "VARCHAR", False),
        ("score_formula", "VARCHAR", False),
        ("tie_method", "VARCHAR", False),
        ("current_value_in_reference_set", "BOOLEAN", False),
        ("source_role", "VARCHAR", False),
        ("definition_version", "VARCHAR", False),
    ),
    "daily_component_scores": (
        ("score_release_id", "VARCHAR", False),
        ("security_id", "VARCHAR", False),
        ("trading_date", "DATE", False),
        ("observation_sequence", "BIGINT", False),
        ("dimension_id", "VARCHAR", False),
        ("component_id", "VARCHAR", False),
        ("percentile_window_W", "INTEGER", False),
        ("raw_value", "DOUBLE", True),
        ("percentile", "DOUBLE", True),
        ("score", "DOUBLE", True),
        ("eligible", "BOOLEAN", False),
        ("validity_status", "VARCHAR", False),
        ("reason_codes", "VARCHAR[]", False),
        ("reference_observation_count", "INTEGER", False),
        ("reference_window_start", "BIGINT", True),
        ("reference_window_end", "BIGINT", True),
        ("current_value_in_reference_set", "BOOLEAN", False),
        ("tie_method", "VARCHAR", False),
        ("score_engine_version", "VARCHAR", False),
        ("source_role", "VARCHAR", False),
        ("source_run_id", "VARCHAR", False),
        ("available_time", "TIMESTAMP WITH TIME ZONE", False),
    ),
    "daily_dimension_scores": (
        ("score_release_id", "VARCHAR", False),
        ("security_id", "VARCHAR", False),
        ("trading_date", "DATE", False),
        ("observation_sequence", "BIGINT", False),
        ("dimension_id", "VARCHAR", False),
        ("percentile_window_W", "INTEGER", False),
        ("score_dimension", "DOUBLE", True),
        ("score_dimension_min", "DOUBLE", True),
        ("eligible_dimension", "BOOLEAN", False),
        ("validity_status", "VARCHAR", False),
        ("reason_codes", "VARCHAR[]", False),
        ("component_count", "INTEGER", False),
        ("score_engine_version", "VARCHAR", False),
        ("source_role", "VARCHAR", False),
        ("available_time", "TIMESTAMP WITH TIME ZONE", False),
    ),
}
TABLE_COLUMNS = {
    table: tuple(column[0] for column in columns)
    for table, columns in COLUMN_DEFINITIONS.items()
}
PRIMARY_KEYS = {
    "securities": ("score_release_id", "security_id"),
    "trading_sessions": ("score_release_id", "trading_date"),
    "security_observation_spine": (
        "score_release_id",
        "security_id",
        "trading_date",
    ),
    "dimension_definitions": ("score_release_id", "dimension_id"),
    "dimension_components": (
        "score_release_id",
        "dimension_id",
        "component_id",
    ),
    "daily_component_scores": (
        "score_release_id",
        "security_id",
        "trading_date",
        "dimension_id",
        "component_id",
    ),
    "daily_dimension_scores": (
        "score_release_id",
        "security_id",
        "trading_date",
        "dimension_id",
    ),
}
FOREIGN_KEYS = {
    "securities": (),
    "trading_sessions": (),
    "security_observation_spine": (
        {
            "columns": ["score_release_id", "security_id"],
            "referenced_table": "securities",
            "referenced_columns": ["score_release_id", "security_id"],
        },
        {
            "columns": ["score_release_id", "trading_date"],
            "referenced_table": "trading_sessions",
            "referenced_columns": ["score_release_id", "trading_date"],
        },
    ),
    "dimension_definitions": (),
    "dimension_components": (
        {
            "columns": ["score_release_id", "dimension_id"],
            "referenced_table": "dimension_definitions",
            "referenced_columns": ["score_release_id", "dimension_id"],
        },
    ),
    "daily_component_scores": (
        {
            "columns": ["score_release_id", "security_id", "trading_date"],
            "referenced_table": "security_observation_spine",
            "referenced_columns": [
                "score_release_id",
                "security_id",
                "trading_date",
            ],
        },
        {
            "columns": ["score_release_id", "dimension_id", "component_id"],
            "referenced_table": "dimension_components",
            "referenced_columns": [
                "score_release_id",
                "dimension_id",
                "component_id",
            ],
        },
    ),
    "daily_dimension_scores": (
        {
            "columns": ["score_release_id", "security_id", "trading_date"],
            "referenced_table": "security_observation_spine",
            "referenced_columns": [
                "score_release_id",
                "security_id",
                "trading_date",
            ],
        },
        {
            "columns": ["score_release_id", "dimension_id"],
            "referenced_table": "dimension_definitions",
            "referenced_columns": ["score_release_id", "dimension_id"],
        },
    ),
}
UNIQUE_CONSTRAINTS = {
    "securities": (),
    "trading_sessions": (("score_release_id", "session_sequence"),),
    "security_observation_spine": (
        ("score_release_id", "security_id", "observation_sequence"),
    ),
    "dimension_definitions": (("score_release_id", "canonical_order"),),
    "dimension_components": (
        ("score_release_id", "component_id"),
        ("score_release_id", "dimension_id", "component_order"),
    ),
    "daily_component_scores": (),
    "daily_dimension_scores": (),
}
ENUM_DOMAINS = {
    "securities": {},
    "trading_sessions": {},
    "security_observation_spine": {
        "expected_observation_status": ["present", "missing", "listing_pause"]
    },
    "dimension_definitions": {
        "dimension_id": ["P", "C", "A", "V", "T"],
        "aggregation_method": ["equal_weight_mean_and_min"],
        "score_direction": ["higher_is_more_convergent"],
    },
    "dimension_components": {
        "tie_method": ["midrank"],
        "source_role": ["accepted_r0_w120", "recomputed_a_raw"],
    },
    "daily_component_scores": {
        "validity_status": ["valid", "unknown", "diagnostic_required", "blocked"],
        "tie_method": ["midrank"],
        "source_role": ["accepted_r0_w120", "recomputed_a_raw"],
    },
    "daily_dimension_scores": {
        "validity_status": ["valid", "unknown", "diagnostic_required", "blocked"],
        "source_role": ["accepted_r0_w120", "recomputed_a_raw"],
    },
}
CHECK_CONSTRAINTS = {
    "securities": [
        "expected_observation_count >= 0",
        "first_expected_date <= last_expected_date",
    ],
    "trading_sessions": [
        "session_sequence >= 0",
        "expected_security_count >= 0",
        "present_security_count >= 0",
        "present_security_count <= expected_security_count",
    ],
    "security_observation_spine": [
        "observation_sequence >= 0",
        "expected_observation_status in (present,missing,listing_pause)",
    ],
    "dimension_definitions": [
        "canonical_order between 1 and 5",
        "component_count = 2",
        "dimension_id in (P,C,A,V,T)",
        "aggregation_method = equal_weight_mean_and_min",
        "score_direction = higher_is_more_convergent",
        "percentile_window_W = 120",
    ],
    "dimension_components": [
        "component_order in (1,2)",
        "weight = 0.5",
        "tie_method = midrank",
        "current_value_in_reference_set = false",
        "source_role in (accepted_r0_w120,recomputed_a_raw)",
    ],
    "daily_component_scores": [
        "observation_sequence >= 0",
        "percentile_window_W = 120",
        "validity_status in (valid,unknown,diagnostic_required,blocked)",
        "reason_codes nonempty",
        "reference_observation_count between 0 and 120",
        "current_value_in_reference_set = false",
        "tie_method = midrank",
        "source_role in (accepted_r0_w120,recomputed_a_raw)",
        "eligible_score_consistency",
    ],
    "daily_dimension_scores": [
        "observation_sequence >= 0",
        "percentile_window_W = 120",
        "validity_status in (valid,unknown,diagnostic_required,blocked)",
        "reason_codes nonempty",
        "component_count = 2",
        "source_role in (accepted_r0_w120,recomputed_a_raw)",
        "eligible_dimension_score_consistency",
    ],
}

FORMAL_EXECUTION_SURFACE = (
    "configs/r2a/r2a_t01_pcavt_score_release.v1.json",
    "configs/r2a/r2a_t01_eod_availability_policy.v1.json",
    "schemas/r2a/r2a_t01_pcavt_score_release_config.schema.json",
    "schemas/r2a/r2a_t01_eod_availability_policy.schema.json",
    "schemas/r2a/r2a_t01_score_release_schema.schema.json",
    "schemas/r2a/r2a_t01_score_release_manifest.schema.json",
    "schemas/r2a/r2a_t01_validation_receipt.schema.json",
    "schemas/r2a/r2a_t01_authorized_input_manifest.schema.json",
    "src/r2a/__init__.py",
    "src/r2a/score_engine.py",
    "src/r2a/r2a_t01_input_manifest.py",
    "src/r2a/r2a_t01_formal_input_adapter.py",
    "src/r2a/r2a_t01_artifact_manifest.py",
    "src/r2a/r2a_t01_score_release.py",
    "src/r2a/r2a_t01_validator.py",
    "src/r2a/r2a_t01_result_analysis.py",
    "scripts/r2a/build_r2a_t01_authorized_input_manifest.py",
    "scripts/r2a/run_r2a_t01_score_release.py",
    "scripts/r2a/validate_r2a_t01_score_release.py",
    "scripts/r2a/analyze_r2a_t01_score_release.py",
    "requirements-dev.txt",
)


def schema_descriptor() -> dict[str, Any]:
    return {
        "schema_version": "r2a_t01_score_release_schema.v1",
        "table_order": list(TABLE_ORDER),
        "tables": {
            table: {
                "columns": [
                    {"name": name, "type": data_type, "nullable": nullable}
                    for name, data_type, nullable in COLUMN_DEFINITIONS[table]
                ],
                "primary_key": list(PRIMARY_KEYS[table]),
                "foreign_keys": list(FOREIGN_KEYS[table]),
                "unique_constraints": [
                    list(item) for item in UNIQUE_CONSTRAINTS[table]
                ],
                "check_constraints": list(CHECK_CONSTRAINTS[table]),
                "enum_domains": ENUM_DOMAINS[table],
                "canonical_order": list(TABLE_COLUMNS[table]),
            }
            for table in TABLE_ORDER
        },
    }


def write_schema(path: str | Path) -> dict[str, Any]:
    payload = schema_descriptor()
    descriptor_schema = json.loads(
        (ROOT / "schemas/r2a/r2a_t01_score_release_schema.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(descriptor_schema).validate(payload)
    write_json_atomic(path, payload)
    return payload


def build_manifest(
    *,
    package_dir: str | Path,
    run_id: str,
    score_release_id: str,
    score_release_preimage_sha256: str,
    authorized_input_manifest: str | Path,
    input_summary: Mapping[str, Mapping[str, Any]],
    formal_authorization_id: str | None,
    config_path: str | Path,
    availability_policy_path: str | Path,
    worker_count: int,
    synthetic_only: bool,
    execution_commit: str | None,
) -> dict[str, Any]:
    package = Path(package_dir)
    policy_path = Path(availability_policy_path)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    bindings: dict[str, dict[str, Any]] = {}
    if not synthetic_only and execution_commit is not None:
        for relative in FORMAL_EXECUTION_SURFACE:
            bindings[relative] = formal_source_binding(
                ROOT / relative, execution_commit, root=ROOT
            )
    config_key = Path(config_path).resolve().relative_to(ROOT).as_posix()
    policy_key = policy_path.resolve().relative_to(ROOT).as_posix()
    config_hash = (
        bindings[config_key]["committed_byte_sha256"]
        if bindings
        else sha256_file(config_path)
    )
    policy_hash = (
        bindings[policy_key]["committed_byte_sha256"]
        if bindings
        else sha256_file(policy_path)
    )
    database = package / "score_data.duckdb"
    with duckdb.connect(str(database), read_only=True) as connection:
        row_counts = {
            table: int(
                connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            )
            for table in TABLE_ORDER
        }
        coverage = {table: _table_coverage(connection, table) for table in TABLE_ORDER}
        semantic = {
            table: _semantic_fingerprint(connection, table) for table in TABLE_ORDER
        }
        registry_fingerprints = {
            table: _small_table_sha256(connection, table)
            for table in ("dimension_definitions", "dimension_components")
        }
    payload = {
        "manifest_version": "r2a_t01_score_release_manifest.v1",
        "run_id": run_id,
        "score_release_id": score_release_id,
        "score_release_preimage_sha256": score_release_preimage_sha256,
        "synthetic_only": synthetic_only,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authorized_input_manifest_sha256": sha256_file(authorized_input_manifest),
        "formal_authorization_id": formal_authorization_id,
        "input_summary": {name: dict(value) for name, value in input_summary.items()},
        "score_data_sha256": sha256_file(database),
        "database_byte_size": database.stat().st_size,
        "schema_sha256": sha256_file(package / "schema.json"),
        "config_sha256": config_hash,
        "availability_policy_id": policy["policy_id"],
        "availability_policy_version": policy["policy_version"],
        "availability_policy_sha256": policy_hash,
        "timezone": policy["timezone"],
        "market_information_cutoff": policy["market_information_cutoff"],
        "execution_commit": execution_commit,
        "environment_lock_sha256": (
            bindings["requirements-dev.txt"]["committed_byte_sha256"]
            if bindings
            else sha256_file(ROOT / "requirements-dev.txt")
        ),
        "formal_source_bindings": bindings,
        "worker_count": worker_count,
        "row_counts": row_counts,
        "coverage": coverage,
        "table_semantic_fingerprints": semantic,
        "registry_fingerprints": registry_fingerprints,
    }
    manifest_schema = json.loads(
        (ROOT / "schemas/r2a/r2a_t01_score_release_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(manifest_schema, format_checker=FormatChecker()).validate(
        payload
    )
    write_json_atomic(package / "manifest.json", payload)
    return payload


def _table_coverage(
    connection: duckdb.DuckDBPyConnection, table: str
) -> dict[str, Any]:
    columns = set(TABLE_COLUMNS[table])
    security_count = (
        int(
            connection.execute(
                f'SELECT count(DISTINCT security_id) FROM "{table}"'
            ).fetchone()[0]
        )
        if "security_id" in columns
        else 0
    )
    if "trading_date" in columns:
        values = connection.execute(
            f'SELECT min(trading_date),max(trading_date) FROM "{table}"'
        ).fetchone()
    elif table == "securities":
        values = connection.execute(
            "SELECT min(first_expected_date),max(last_expected_date) FROM securities"
        ).fetchone()
    else:
        values = (None, None)
    return {
        "security_count": security_count,
        "date_min": None if values[0] is None else str(values[0]),
        "date_max": None if values[1] is None else str(values[1]),
    }


def _semantic_fingerprint(
    connection: duckdb.DuckDBPyConnection, table: str
) -> dict[str, Any]:
    columns = ",".join(f'"{name}"' for name in TABLE_COLUMNS[table])
    count, xor_hash, sum_hash = connection.execute(
        f"SELECT count(*),bit_xor(hash({columns})),sum(hash({columns})::HUGEINT) "
        f'FROM "{table}"'
    ).fetchone()
    return {
        "row_count": int(count),
        "xor_hash": str(xor_hash or 0),
        "sum_hash": str(sum_hash or 0),
    }


def _small_table_sha256(connection: duckdb.DuckDBPyConnection, table: str) -> str:
    order = ",".join(f'"{name}"' for name in PRIMARY_KEYS[table])
    rows: Sequence[Sequence[Any]] = connection.execute(
        f'SELECT * FROM "{table}" ORDER BY {order}'
    ).fetchall()
    encoded = json.dumps(rows, default=str, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
