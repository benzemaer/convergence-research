"""Independent, fail-closed validator for R2A-T01 score release packages."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

from src.common.canonical_io import formal_source_binding
from src.r2a.r2a_t01_artifact_manifest import (
    CHECK_CONSTRAINTS,
    COLUMN_DEFINITIONS,
    FOREIGN_KEYS,
    FORMAL_EXECUTION_SURFACE,
    PRIMARY_KEYS,
    TABLE_ORDER,
    UNIQUE_CONSTRAINTS,
    _semantic_fingerprint,
    _table_coverage,
    schema_descriptor,
)
from src.r2a.r2a_t01_formal_input_adapter import FormalInputAdapter
from src.r2a.r2a_t01_input_manifest import sha256_file, write_json_atomic
from src.r2a.r2a_t01_score_release import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_POLICY_PATH,
    PCVT_COMPONENTS,
    _load_json,
    _stage_formal_inputs,
    _stage_synthetic_inputs,
    compute_score_release_id,
)
from src.r2a.score_engine import A_COMPONENTS

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SCHEMA = ROOT / "schemas/r2a/r2a_t01_score_release_manifest.schema.json"
RELEASE_SCHEMA = ROOT / "schemas/r2a/r2a_t01_score_release_schema.schema.json"
INPUT_SCHEMA = ROOT / "schemas/r2a/r2a_t01_authorized_input_manifest.schema.json"
RECEIPT_SCHEMA = ROOT / "schemas/r2a/r2a_t01_validation_receipt.schema.json"


class ValidationError(RuntimeError):
    """Raised when a package cannot be inspected safely."""


def validate_score_release(
    package_dir: str | Path,
    *,
    authorized_input_manifest: str | Path | None = None,
    formal: bool = False,
) -> dict[str, Any]:
    """Validate actual package bytes, schema, source lineage, and Score semantics."""

    package = Path(package_dir).resolve()
    required = ("score_data.duckdb", "manifest.json", "schema.json")
    missing = [name for name in required if not (package / name).is_file()]
    if missing:
        raise ValidationError(f"missing_required_files:{','.join(missing)}")
    if authorized_input_manifest is None:
        raise ValidationError("authorized_input_manifest_required")
    input_path = Path(authorized_input_manifest).resolve()
    manifest = _read_json(package / "manifest.json")
    descriptor = _read_json(package / "schema.json")
    input_manifest = _read_json(input_path)
    _validate_json(manifest, MANIFEST_SCHEMA)
    _validate_json(descriptor, RELEASE_SCHEMA)
    _validate_json(input_manifest, INPUT_SCHEMA)

    checks: dict[str, bool] = {
        "database_hash": sha256_file(package / "score_data.duckdb")
        == manifest["score_data_sha256"],
        "database_byte_size": (package / "score_data.duckdb").stat().st_size
        == manifest["database_byte_size"],
        "schema_hash": sha256_file(package / "schema.json")
        == manifest["schema_sha256"],
        "schema_descriptor_contract": descriptor == schema_descriptor(),
        "authorized_input_manifest_hash": sha256_file(input_path)
        == manifest["authorized_input_manifest_sha256"],
        "config_hash": sha256_file(DEFAULT_CONFIG_PATH) == manifest["config_sha256"],
        "availability_policy_hash": sha256_file(DEFAULT_POLICY_PATH)
        == manifest["availability_policy_sha256"],
        "mode_consistency": (
            manifest.get("synthetic_only") is False
            if formal
            else manifest.get("synthetic_only") is True
        ),
        "input_mode_consistency": (
            input_manifest.get("synthetic_only") is False
            if formal
            else input_manifest.get("synthetic_only") is True
        ),
    }
    config = _load_json(DEFAULT_CONFIG_PATH)
    release_id, preimage_hash = compute_score_release_id(
        config=config,
        availability_policy_path=DEFAULT_POLICY_PATH,
        input_manifest=input_manifest,
        availability_policy_sha256=manifest["availability_policy_sha256"],
    )
    checks["score_release_id_recomputed"] = release_id == manifest["score_release_id"]
    checks["score_release_preimage_hash"] = (
        preimage_hash == manifest["score_release_preimage_sha256"]
    )
    metrics: dict[str, Any] = {}

    temporary = Path(tempfile.mkdtemp(prefix="r2a-t01-validator-"))
    try:
        staging_path = temporary / "staging.duckdb"
        if input_manifest.get("synthetic_only") is True:
            observed_input_summary = _stage_synthetic_inputs(input_path, staging_path)
        else:
            adapter = FormalInputAdapter(input_path)
            observed_input_summary = _stage_formal_inputs(adapter, staging_path)
        checks["manifest_input_summary"] = (
            observed_input_summary == manifest["input_summary"]
        )
        checks["formal_authorization_id"] = manifest.get(
            "formal_authorization_id"
        ) == input_manifest.get("formal_authorization_id")
        with duckdb.connect(
            str(package / "score_data.duckdb"), read_only=True
        ) as connection:
            quoted_staging = str(staging_path).replace("'", "''")
            connection.execute(f"ATTACH '{quoted_staging}' AS source (READ_ONLY)")
            database_checks, database_metrics = _validate_database(
                connection, manifest, descriptor
            )
            checks.update(database_checks)
            metrics.update(database_metrics)
            source_checks, source_metrics = _validate_sources(connection)
            checks.update(source_checks)
            metrics.update(source_metrics)
            recompute_checks, recompute_metrics = _independent_score_recomputation(
                connection
            )
            checks.update(recompute_checks)
            metrics.update(recompute_metrics)
            if formal:
                checks.update(_validate_formal_cardinality(connection))
        checks.update(_validate_execution_source_bindings(manifest))
    except Exception as exc:
        checks[f"input_or_source_validation:{type(exc).__name__}"] = False
        metrics["input_or_source_validation_error"] = str(exc)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    reason_codes = sorted(name for name, passed in checks.items() if not passed)
    receipt = {
        "receipt_version": "r2a_t01_validation_receipt.v1",
        "run_id": manifest["run_id"],
        "score_release_id": manifest["score_release_id"],
        "validated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "passed" if not reason_codes else "failed",
        "checks": checks,
        "metrics": metrics,
        "reason_codes": reason_codes,
    }
    _validate_json(receipt, RECEIPT_SCHEMA)
    write_json_atomic(package / "validation_receipt.json", receipt)
    return receipt


def _validate_database(
    connection: duckdb.DuckDBPyConnection,
    manifest: Mapping[str, Any],
    descriptor: Mapping[str, Any],
) -> tuple[dict[str, bool], dict[str, Any]]:
    checks: dict[str, bool] = {}
    tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    checks["seven_table_set"] = tables == set(TABLE_ORDER)
    checks["schema_introspection"] = _schema_introspection_matches(
        connection, descriptor
    )
    row_counts = {
        table: int(connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
        for table in TABLE_ORDER
    }
    checks["manifest_row_counts"] = row_counts == manifest["row_counts"]
    checks["manifest_coverage"] = {
        table: _table_coverage(connection, table) for table in TABLE_ORDER
    } == manifest["coverage"]
    checks["manifest_semantic_fingerprints"] = {
        table: _semantic_fingerprint(connection, table) for table in TABLE_ORDER
    } == manifest["table_semantic_fingerprints"]
    checks["score_release_id_total"] = all(
        connection.execute(
            f"SELECT count(DISTINCT score_release_id)=1 AND min(score_release_id)=? "
            f'FROM "{table}"',
            [manifest["score_release_id"]],
        ).fetchone()[0]
        for table in TABLE_ORDER
    )
    spine_count = row_counts["security_observation_spine"]
    checks["component_cardinality"] = (
        row_counts["daily_component_scores"] == 10 * spine_count
    )
    checks["dimension_cardinality"] = (
        row_counts["daily_dimension_scores"] == 5 * spine_count
    )
    checks["registry_cardinality"] = (
        row_counts["dimension_definitions"] == 5
        and row_counts["dimension_components"] == 10
    )
    checks["canonical_dimension_order"] = connection.execute(
        "SELECT list(dimension_id ORDER BY canonical_order)=['P','C','A','V','T'] "
        "FROM dimension_definitions"
    ).fetchone()[0]
    checks["session_sequence_zero_based_contiguous"] = connection.execute(
        "SELECT min(session_sequence)=0 AND max(session_sequence)+1=count(*) "
        "AND count(DISTINCT session_sequence)=count(*) FROM trading_sessions"
    ).fetchone()[0]
    checks["spine_sequence_zero_based_contiguous"] = connection.execute(
        "SELECT count(*)=0 FROM (SELECT security_id FROM security_observation_spine "
        "GROUP BY 1 HAVING min(observation_sequence)<>0 OR "
        "max(observation_sequence)+1<>count(*) OR "
        "count(DISTINCT observation_sequence)<>count(*))"
    ).fetchone()[0]
    checks["session_trading_date_strictly_increasing"] = connection.execute(
        "SELECT count(*)=0 FROM (SELECT score_release_id,trading_date,"
        "lag(trading_date) OVER(PARTITION BY score_release_id ORDER BY session_sequence) "
        "previous_date FROM trading_sessions) WHERE previous_date IS NOT NULL "
        "AND trading_date<=previous_date"
    ).fetchone()[0]
    checks["spine_trading_date_strictly_increasing"] = connection.execute(
        "SELECT count(*)=0 FROM (SELECT score_release_id,security_id,trading_date,"
        "lag(trading_date) OVER(PARTITION BY score_release_id,security_id "
        "ORDER BY observation_sequence) previous_date FROM security_observation_spine) "
        "WHERE previous_date IS NOT NULL AND trading_date<=previous_date"
    ).fetchone()[0]
    checks.update(_availability_checks(connection))
    checks.update(_score_and_dimension_checks(connection))
    checks.update(_expected_empty_checks(connection))
    checks.update(_anomaly_checks(connection))
    metrics = {"validated_row_counts": row_counts}
    return checks, metrics


def _schema_introspection_matches(
    connection: duckdb.DuckDBPyConnection, descriptor: Mapping[str, Any]
) -> bool:
    if descriptor != schema_descriptor():
        return False
    constraints = connection.execute(
        "SELECT table_name,constraint_type,constraint_column_names,referenced_table,"
        "referenced_column_names FROM duckdb_constraints()"
    ).fetchall()
    for table in TABLE_ORDER:
        info = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        actual_columns = [(row[1], row[2], not bool(row[3])) for row in info]
        if actual_columns != list(COLUMN_DEFINITIONS[table]):
            return False
        table_constraints = [row for row in constraints if row[0] == table]
        primary = [
            tuple(row[2]) for row in table_constraints if row[1] == "PRIMARY KEY"
        ]
        if primary != [PRIMARY_KEYS[table]]:
            return False
        uniques = {tuple(row[2]) for row in table_constraints if row[1] == "UNIQUE"}
        if uniques != set(UNIQUE_CONSTRAINTS[table]):
            return False
        foreign = {
            (tuple(row[2]), row[3], tuple(row[4]))
            for row in table_constraints
            if row[1] == "FOREIGN KEY"
        }
        expected_foreign = {
            (
                tuple(item["columns"]),
                item["referenced_table"],
                tuple(item["referenced_columns"]),
            )
            for item in FOREIGN_KEYS[table]
        }
        if foreign != expected_foreign:
            return False
        check_count = sum(1 for row in table_constraints if row[1] == "CHECK")
        if check_count != len(CHECK_CONSTRAINTS[table]):
            return False
    return True


def _availability_checks(connection: duckdb.DuckDBPyConnection) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for label, table, column in (
        ("session", "trading_sessions", "available_time"),
        ("spine", "security_observation_spine", "observation_available_time"),
        ("component", "daily_component_scores", "available_time"),
        ("dimension", "daily_dimension_scores", "available_time"),
    ):
        checks[f"{label}_availability_policy_exact"] = connection.execute(
            f'SELECT count(*)=0 FROM "{table}" WHERE "{column}" IS NULL OR '
            f"({column} AT TIME ZONE 'Asia/Shanghai')::TIME<>TIME '15:00:00' OR "
            f"({column} AT TIME ZONE 'Asia/Shanghai')::DATE<>trading_date"
        ).fetchone()[0]
    return checks


def _score_and_dimension_checks(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, bool]:
    return {
        "score_equals_one_minus_percentile": connection.execute(
            "SELECT count(*)=0 FROM daily_component_scores WHERE eligible AND "
            "abs(score-(1-percentile))>1e-12"
        ).fetchone()[0],
        "reference_window_current_excluded": connection.execute(
            "SELECT count(*)=0 FROM daily_component_scores WHERE eligible AND "
            "(reference_observation_count<>120 OR reference_window_end>=trading_date "
            "OR reference_window_start>reference_window_end)"
        ).fetchone()[0],
        "component_domain": connection.execute(
            "SELECT count(*)=0 FROM daily_component_scores WHERE "
            "(eligible AND (score NOT BETWEEN 0 AND 1 OR percentile NOT BETWEEN 0 AND 1)) "
            "OR (NOT eligible AND (score IS NOT NULL OR percentile IS NOT NULL))"
        ).fetchone()[0],
        "all_dimension_mean_min_recomputed": connection.execute(
            "WITH recomputed AS (SELECT score_release_id,security_id,trading_date,dimension_id,"
            "bool_and(eligible) ready,avg(score) mean_score,min(score) min_score "
            "FROM daily_component_scores GROUP BY 1,2,3,4) SELECT count(*)=0 FROM "
            "daily_dimension_scores d JOIN recomputed r USING(score_release_id,security_id,"
            "trading_date,dimension_id) WHERE d.eligible_dimension<>r.ready OR "
            "(d.eligible_dimension AND (abs(d.score_dimension-r.mean_score)>1e-12 OR "
            "abs(d.score_dimension_min-r.min_score)>1e-12))"
        ).fetchone()[0],
    }


def _expected_empty_checks(connection: duckdb.DuckDBPyConnection) -> dict[str, bool]:
    expected = int(
        connection.execute(
            "SELECT count(*) FROM security_observation_spine WHERE "
            "expected_observation_status IN ('missing','listing_pause')"
        ).fetchone()[0]
    )
    component = connection.execute(
        "SELECT count(*),count(*) FILTER(WHERE NOT eligible AND score IS NULL AND "
        "percentile IS NULL AND validity_status='blocked') FROM daily_component_scores c "
        "JOIN security_observation_spine s USING(score_release_id,security_id,trading_date) "
        "WHERE s.expected_observation_status IN ('missing','listing_pause')"
    ).fetchone()
    dimension = connection.execute(
        "SELECT count(*),count(*) FILTER(WHERE NOT eligible_dimension AND score_dimension IS NULL "
        "AND score_dimension_min IS NULL AND validity_status='blocked') "
        "FROM daily_dimension_scores d JOIN security_observation_spine s "
        "USING(score_release_id,security_id,trading_date) WHERE "
        "s.expected_observation_status IN ('missing','listing_pause')"
    ).fetchone()
    return {
        "expected_empty_component_blocked": component == (expected * 10, expected * 10),
        "expected_empty_dimension_blocked": dimension == (expected * 5, expected * 5),
    }


def _anomaly_checks(connection: duckdb.DuckDBPyConnection) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for label, table, column, eligible in (
        ("component", "daily_component_scores", "score", "eligible"),
        (
            "dimension",
            "daily_dimension_scores",
            "score_dimension",
            "eligible_dimension",
        ),
    ):
        values = connection.execute(
            f"SELECT count(*) FILTER(WHERE {eligible}),count({column}) FILTER(WHERE {eligible}),"
            f"min({column}) FILTER(WHERE {eligible}),max({column}) FILTER(WHERE {eligible}) "
            f"FROM {table}"
        ).fetchone()
        checks[f"{label}_scores_not_all_null"] = (
            values[0] > 0 and values[1] == values[0]
        )
        checks[f"{label}_scores_not_all_zero"] = values[2] is not None and not (
            values[2] == 0 and values[3] == 0
        )
        checks[f"{label}_scores_not_all_one"] = values[2] is not None and not (
            values[2] == 1 and values[3] == 1
        )
    return checks


def _validate_sources(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[dict[str, bool], dict[str, Any]]:
    checks: dict[str, bool] = {}
    metrics: dict[str, Any] = {}
    component_key = "security_id,trading_date,dimension_id,component_id"
    dimension_key = "security_id,trading_date,dimension_id"
    checks["pcvt_component_source_keyset_reconciled"] = _bidirectional_keyset(
        connection,
        "source.main.stage_pcvt_component_scores",
        "(SELECT o.* FROM daily_component_scores o JOIN security_observation_spine s "
        "USING(score_release_id,security_id,trading_date) WHERE o.dimension_id<>'A' "
        "AND s.expected_observation_status='present')",
        component_key,
    )
    checks["pcvt_dimension_source_keyset_reconciled"] = _bidirectional_keyset(
        connection,
        "source.main.stage_pcvt_dimension_scores",
        "(SELECT o.* FROM daily_dimension_scores o JOIN security_observation_spine s "
        "USING(score_release_id,security_id,trading_date) WHERE o.dimension_id<>'A' "
        "AND s.expected_observation_status='present')",
        dimension_key,
    )
    component_mismatches = int(
        connection.execute(
            "SELECT count(*) FROM source.main.stage_pcvt_component_scores x JOIN "
            "daily_component_scores o USING(security_id,trading_date,dimension_id,component_id) "
            "JOIN security_observation_spine s USING(score_release_id,security_id,trading_date) "
            "WHERE s.expected_observation_status='present' AND (x.eligible<>o.eligible "
            "OR x.validity_status<>o.validity_status OR "
            "x.reference_observation_count<>o.reference_observation_count OR "
            "x.reference_window_start IS DISTINCT FROM o.reference_window_start OR "
            "x.reference_window_end IS DISTINCT FROM o.reference_window_end OR "
            "x.raw_value IS DISTINCT FROM o.raw_value OR x.percentile IS DISTINCT FROM o.percentile "
            "OR x.score IS DISTINCT FROM o.score OR x.observation_sequence<>o.observation_sequence "
            "OR x.percentile_window_W<>o.percentile_window_W OR x.reason_codes<>o.reason_codes "
            "OR x.current_value_in_reference_set<>o.current_value_in_reference_set "
            "OR x.score_engine_version<>o.score_engine_version OR x.source_run_id<>o.source_run_id)"
        ).fetchone()[0]
    )
    dimension_mismatches = int(
        connection.execute(
            "SELECT count(*) FROM source.main.stage_pcvt_dimension_scores x JOIN "
            "daily_dimension_scores o USING(security_id,trading_date,dimension_id) "
            "JOIN security_observation_spine s USING(score_release_id,security_id,trading_date) "
            "WHERE s.expected_observation_status='present' AND "
            "(x.eligible_dimension<>o.eligible_dimension OR "
            "x.validity_status<>o.validity_status OR "
            "x.score_dimension IS DISTINCT FROM o.score_dimension OR "
            "x.score_dimension_min IS DISTINCT FROM o.score_dimension_min OR "
            "x.observation_sequence<>o.observation_sequence OR "
            "x.percentile_window_W<>o.percentile_window_W OR x.reason_codes<>o.reason_codes OR "
            "x.score_engine_version<>o.score_engine_version)"
        ).fetchone()[0]
    )
    checks["pcvt_component_source_values_reconciled"] = component_mismatches == 0
    checks["pcvt_dimension_source_values_reconciled"] = dimension_mismatches == 0
    source_valid = int(
        connection.execute(
            "SELECT count(*) FROM source.main.stage_pcvt_component_scores WHERE eligible"
        ).fetchone()[0]
    )
    output_valid = int(
        connection.execute(
            "SELECT count(*) FROM daily_component_scores o JOIN security_observation_spine s "
            "USING(score_release_id,security_id,trading_date) WHERE o.dimension_id<>'A' "
            "AND s.expected_observation_status='present' AND o.eligible"
        ).fetchone()[0]
    )
    checks["source_valid_output_coverage"] = source_valid == output_valid
    metrics.update(
        {
            "pcvt_component_source_mismatches": component_mismatches,
            "pcvt_dimension_source_mismatches": dimension_mismatches,
            "pcvt_source_valid_rows": source_valid,
            "pcvt_output_valid_rows": output_valid,
        }
    )
    return checks, metrics


def _bidirectional_keyset(
    connection: duckdb.DuckDBPyConnection,
    source_relation: str,
    output_relation: str,
    key_columns: str,
) -> bool:
    missing = connection.execute(
        f"SELECT count(*) FROM (SELECT {key_columns} FROM {source_relation} EXCEPT "
        f"SELECT {key_columns} FROM {output_relation})"
    ).fetchone()[0]
    extra = connection.execute(
        f"SELECT count(*) FROM (SELECT {key_columns} FROM {output_relation} EXCEPT "
        f"SELECT {key_columns} FROM {source_relation})"
    ).fetchone()[0]
    return missing == 0 and extra == 0


def _independent_score_recomputation(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[dict[str, bool], dict[str, Any]]:
    securities = [
        str(row[0])
        for row in connection.execute(
            "SELECT security_id FROM securities ORDER BY security_id LIMIT 5"
        ).fetchall()
    ]
    placeholders = ",".join("?" for _ in securities)
    pcvt_raw = connection.execute(
        "SELECT security_id,trading_date,observation_sequence,component_id,raw_value,"
        "validity_status FROM source.main.stage_pcvt_validation_raw WHERE security_id "
        f"IN ({placeholders}) ORDER BY security_id,component_id,observation_sequence",
        securities,
    ).fetchall()
    a_raw = connection.execute(
        "SELECT security_id,trading_date,observation_sequence,component_id,raw_value,"
        "validity_status FROM source.main.stage_a_raw_observations WHERE security_id "
        f"IN ({placeholders}) ORDER BY security_id,component_id,observation_sequence",
        securities,
    ).fetchall()
    pcvt_count, pcvt_mismatches = _compare_raw_recomputation(
        connection, pcvt_raw, set(PCVT_COMPONENTS)
    )
    a_count, a_mismatches = _compare_raw_recomputation(
        connection, a_raw, set(A_COMPONENTS)
    )
    return (
        {
            "pcvt_raw_score_independent_recomputation": pcvt_mismatches == 0,
            "a_raw_score_independent_recomputation": a_mismatches == 0,
        },
        {
            "pcvt_independent_sample_count": pcvt_count,
            "pcvt_independent_mismatch_count": pcvt_mismatches,
            "a_independent_sample_count": a_count,
            "a_independent_mismatch_count": a_mismatches,
        },
    )


def _compare_raw_recomputation(
    connection: duckdb.DuckDBPyConnection,
    rows: Sequence[Sequence[Any]],
    allowed_components: set[str],
) -> tuple[int, int]:
    groups: dict[tuple[str, str], list[Sequence[Any]]] = defaultdict(list)
    for row in rows:
        if str(row[3]) not in allowed_components:
            return 0, 1
        groups[(str(row[0]), str(row[3]))].append(row)
    compared = 0
    mismatches = 0
    for (security_id, component_id), group in groups.items():
        history: list[tuple[int, str, float]] = []
        for row in sorted(group, key=lambda item: int(item[2])):
            trading_date = str(row[1])
            sequence = int(row[2])
            raw_value = _finite(row[4])
            valid = str(row[5]) == "valid" and raw_value is not None
            reference = history[-120:]
            expected_count = len(reference)
            eligible = valid and expected_count == 120
            if eligible:
                less = sum(value < raw_value for _, _, value in reference)
                equal = sum(value == raw_value for _, _, value in reference)
                percentile = (less + 0.5 * equal) / 120
                score = 1 - percentile
            else:
                percentile = score = None
            actual = connection.execute(
                "SELECT eligible,percentile,score,reference_observation_count,"
                "reference_window_start,reference_window_end FROM daily_component_scores "
                "WHERE security_id=? AND trading_date=? AND component_id=?",
                [security_id, trading_date, component_id],
            ).fetchone()
            compared += 1
            expected = (
                eligible,
                percentile,
                score,
                expected_count,
                date.fromisoformat(reference[0][1]) if reference else None,
                date.fromisoformat(reference[-1][1]) if reference else None,
            )
            if actual is None or not _row_equivalent(actual, expected):
                mismatches += 1
            if valid:
                history.append((sequence, trading_date, raw_value))
    return compared, mismatches


def _validate_formal_cardinality(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, bool]:
    count = connection.execute("SELECT count(*) FROM securities").fetchone()[0]
    years = connection.execute(
        "SELECT min(year(trading_date)),max(year(trading_date)) FROM trading_sessions"
    ).fetchone()
    return {
        "formal_security_count_800": count == 800,
        "formal_calendar_year_domain": years == (2016, 2026),
    }


def _validate_execution_source_bindings(
    manifest: Mapping[str, Any],
) -> dict[str, bool]:
    declared = manifest.get("formal_source_bindings")
    commit = manifest.get("execution_commit")
    if not declared and commit is None:
        return {"formal_execution_source_bindings": True}
    if not isinstance(declared, Mapping) or not isinstance(commit, str):
        return {"formal_execution_source_bindings": False}
    try:
        observed = {
            path: formal_source_binding(ROOT / path, commit, root=ROOT)
            for path in FORMAL_EXECUTION_SURFACE
        }
    except Exception:
        return {"formal_execution_source_bindings": False}
    return {"formal_execution_source_bindings": observed == declared}


def _row_equivalent(actual: Sequence[Any], expected: Sequence[Any]) -> bool:
    for left, right in zip(actual, expected, strict=True):
        if left is None or right is None:
            if left is not None or right is not None:
                return False
        elif isinstance(left, float) or isinstance(right, float):
            if not math.isclose(float(left), float(right), abs_tol=1e-12):
                return False
        elif left != right:
            return False
    return True


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _validate_json(payload: Mapping[str, Any], schema_path: Path) -> None:
    schema = _read_json(schema_path)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValidationError(f"json_object_required:{path.name}")
    return payload
