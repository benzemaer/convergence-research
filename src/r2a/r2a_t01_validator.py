"""Independent validator for R2A-T01 score-release packages."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

from src.common.canonical_io import formal_source_binding
from src.r2a.r2a_t01_artifact_manifest import TABLE_COLUMNS, TABLE_ORDER
from src.r2a.r2a_t01_input_manifest import (
    load_bound_inputs,
    sha256_file,
    write_json_atomic,
)
from src.r2a.score_engine import A_COMPONENTS, PERCENTILE_WINDOW

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SCHEMA = ROOT / "schemas/r2a/r2a_t01_score_release_manifest.schema.json"
RELEASE_SCHEMA = ROOT / "schemas/r2a/r2a_t01_score_release_schema.schema.json"
INPUT_SCHEMA = ROOT / "schemas/r2a/r2a_t01_authorized_input_manifest.schema.json"
RECEIPT_SCHEMA = ROOT / "schemas/r2a/r2a_t01_validation_receipt.schema.json"
FORBIDDEN_COLUMN = re.compile(
    r"(^|_)(q|k|state|streak|confirmation|interval)(_|$)", re.IGNORECASE
)


class ValidationError(RuntimeError):
    """Raised when a package cannot be inspected as a release candidate."""


def validate_score_release(
    package_dir: str | Path, *, formal: bool = False
) -> dict[str, Any]:
    """Reopen actual artifacts, independently recompute fields, and write a receipt."""

    package = Path(package_dir)
    required = ("score_data.duckdb", "manifest.json", "schema.json")
    missing = [name for name in required if not (package / name).is_file()]
    if missing:
        raise ValidationError(f"missing_package_files:{','.join(missing)}")

    manifest = _load_json(package / "manifest.json")
    descriptor = _load_json(package / "schema.json")
    input_manifest_path = Path(manifest["authorized_input_manifest"])
    input_manifest = _load_json(input_manifest_path)
    _validate_json(manifest, MANIFEST_SCHEMA)
    _validate_json(descriptor, RELEASE_SCHEMA)
    _validate_json(input_manifest, INPUT_SCHEMA)

    checks: dict[str, bool] = {
        "score_data_hash": sha256_file(package / "score_data.duckdb")
        == manifest["score_data_sha256"],
        "schema_hash": sha256_file(package / "schema.json")
        == manifest["schema_sha256"],
        "authorized_input_manifest_hash": sha256_file(input_manifest_path)
        == manifest["authorized_input_manifest_sha256"],
        "synthetic_only": manifest.get("synthetic_only") is True,
        "environment_lock_hash": sha256_file(ROOT / "requirements-dev.txt")
        == manifest["environment_lock_sha256"],
    }

    source_inputs = load_bound_inputs(input_manifest_path, formal_authorized=formal)
    if formal:
        checks.update(_validate_formal_source_bindings(manifest))
    with duckdb.connect(
        str(package / "score_data.duckdb"), read_only=True
    ) as connection:
        checks.update(
            _validate_database(connection, manifest, descriptor, source_inputs)
        )
        if formal:
            checks.update(_validate_formal_cardinality(connection))

    failed = sorted(name for name, passed in checks.items() if not passed)
    receipt = {
        "receipt_version": "r2a_t01_validation_receipt.v1",
        "run_id": manifest["run_id"],
        "score_release_id": manifest["score_release_id"],
        "validated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "passed" if not failed else "failed",
        "checks": dict(sorted(checks.items())),
        "reason_codes": failed or ["valid_no_blocker"],
    }
    _validate_json(receipt, RECEIPT_SCHEMA)
    write_json_atomic(package / "validation_receipt.json", receipt)
    return receipt


def _validate_database(
    connection: duckdb.DuckDBPyConnection,
    manifest: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    inputs: Mapping[str, list[dict[str, Any]]],
) -> dict[str, bool]:
    tables = {
        row[0]
        for row in connection.execute("SHOW TABLES").fetchall()
        if not str(row[0]).startswith("duckdb_")
    }
    checks: dict[str, bool] = {"exact_table_set": tables == set(TABLE_ORDER)}
    forbidden = False
    exact_columns = True
    timestamp_types = True
    for table in TABLE_ORDER:
        if table not in tables:
            exact_columns = False
            continue
        info = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        columns = [row[1] for row in info]
        exact_columns &= columns == list(TABLE_COLUMNS[table])
        forbidden |= any(FORBIDDEN_COLUMN.search(column) for column in columns)
        if table in {
            "trading_sessions",
            "security_observation_spine",
            "daily_component_scores",
            "daily_dimension_scores",
        }:
            expected = {
                "trading_sessions": "available_time",
                "security_observation_spine": "observation_available_time",
                "daily_component_scores": "available_time",
                "daily_dimension_scores": "available_time",
            }[table]
            type_by_name = {row[1]: str(row[2]).upper() for row in info}
            timestamp_types &= type_by_name.get(expected) in {
                "TIMESTAMP WITH TIME ZONE",
                "TIMESTAMPTZ",
            }
    checks["exact_column_contract"] = exact_columns
    checks["forbidden_release_columns_absent"] = not forbidden
    checks["availability_columns_are_timestamptz"] = timestamp_types
    if not checks["exact_table_set"]:
        return checks

    counts = {
        table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        for table in TABLE_ORDER
    }
    checks["manifest_row_counts"] = counts == manifest["row_counts"]
    spine_count = counts["security_observation_spine"]
    checks["five_dimensions"] = counts["dimension_definitions"] == 5
    checks["ten_components"] = counts["dimension_components"] == 10
    checks["component_cardinality"] = (
        counts["daily_component_scores"] == 10 * spine_count
    )
    checks["dimension_cardinality"] = (
        counts["daily_dimension_scores"] == 5 * spine_count
    )
    checks["a2b_absent"] = connection.execute(
        "SELECT count(*)=0 FROM dimension_components WHERE indicator_id ILIKE '%A2b%'"
    ).fetchone()[0]
    checks["canonical_dimension_order"] = connection.execute(
        "SELECT list(dimension_id ORDER BY dimension_order)=['P','C','A','V','T'] "
        "FROM dimension_definitions"
    ).fetchone()[0]
    checks["two_components_per_dimension"] = connection.execute(
        "SELECT count(*)=0 FROM (SELECT dimension_id FROM dimension_components "
        "GROUP BY dimension_id HAVING count(*)<>2)"
    ).fetchone()[0]
    checks["component_spine_sequence_reconciled"] = connection.execute(
        "SELECT count(*)=0 FROM daily_component_scores c JOIN security_observation_spine s "
        "USING(security_id,trading_date) WHERE c.observation_sequence<>s.observation_sequence"
    ).fetchone()[0]
    checks["dimension_spine_sequence_reconciled"] = connection.execute(
        "SELECT count(*)=0 FROM daily_dimension_scores d JOIN security_observation_spine s "
        "USING(security_id,trading_date) WHERE d.observation_sequence<>s.observation_sequence"
    ).fetchone()[0]
    checks["spine_sequence_contiguous"] = connection.execute(
        "SELECT count(*)=0 FROM (SELECT security_id FROM security_observation_spine "
        "GROUP BY security_id HAVING max(observation_sequence)-min(observation_sequence)+1<>count(*) "
        "OR count(DISTINCT observation_sequence)<>count(*))"
    ).fetchone()[0]
    checks.update(_availability_checks(connection))
    checks.update(_score_domain_checks(connection))
    checks["reason_codes_stable"] = _reason_codes_are_stable(connection)
    checks["pcvt_component_source_reconciled"] = _reconcile_pcvt_components(
        connection, inputs["pcvt_component_scores"]
    )
    checks["pcvt_dimension_source_reconciled"] = _reconcile_pcvt_dimensions(
        connection, inputs["pcvt_dimension_scores"]
    )
    checks.update(
        _independent_a_recomputation(connection, inputs["a_raw_observations"])
    )
    checks.update(_anomaly_checks(connection))
    return checks


def _availability_checks(connection: duckdb.DuckDBPyConnection) -> dict[str, bool]:
    return {
        "availability_non_null": connection.execute(
            "SELECT (SELECT count(*) FROM trading_sessions WHERE available_time IS NULL)=0 "
            "AND (SELECT count(*) FROM security_observation_spine "
            "WHERE observation_available_time IS NULL)=0 "
            "AND (SELECT count(*) FROM daily_component_scores WHERE available_time IS NULL)=0 "
            "AND (SELECT count(*) FROM daily_dimension_scores WHERE available_time IS NULL)=0"
        ).fetchone()[0],
        "availability_policy_exact": connection.execute(
            "SELECT (SELECT count(*) FROM trading_sessions WHERE "
            "(available_time AT TIME ZONE 'Asia/Shanghai')::DATE<>trading_date "
            "OR (available_time AT TIME ZONE 'Asia/Shanghai')::TIME<>TIME '15:00:00')=0 "
            "AND (SELECT count(*) FROM security_observation_spine WHERE "
            "(observation_available_time AT TIME ZONE 'Asia/Shanghai')::DATE<>trading_date "
            "OR (observation_available_time AT TIME ZONE 'Asia/Shanghai')::TIME<>TIME '15:00:00')=0"
        ).fetchone()[0],
        "component_availability_not_early": connection.execute(
            "SELECT count(*)=0 FROM daily_component_scores c JOIN security_observation_spine s "
            "USING(security_id,trading_date) WHERE c.available_time<s.observation_available_time"
        ).fetchone()[0],
        "dimension_availability_not_early": connection.execute(
            "SELECT count(*)=0 FROM daily_dimension_scores d JOIN security_observation_spine s "
            "USING(security_id,trading_date) WHERE d.available_time<s.observation_available_time"
        ).fetchone()[0],
        "component_availability_policy_exact": connection.execute(
            "SELECT count(*)=0 FROM daily_component_scores c JOIN security_observation_spine s "
            "USING(security_id,trading_date) WHERE c.available_time<>s.observation_available_time"
        ).fetchone()[0],
        "dimension_availability_policy_exact": connection.execute(
            "SELECT count(*)=0 FROM daily_dimension_scores d JOIN security_observation_spine s "
            "USING(security_id,trading_date) WHERE d.available_time<>s.observation_available_time"
        ).fetchone()[0],
    }


def _score_domain_checks(connection: duckdb.DuckDBPyConnection) -> dict[str, bool]:
    return {
        "component_score_domain": connection.execute(
            "SELECT count(*)=0 FROM daily_component_scores WHERE eligible AND "
            "(NOT isfinite(score) OR NOT isfinite(percentile) OR score<0 OR score>1 "
            "OR percentile<0 OR percentile>1)"
        ).fetchone()[0],
        "dimension_score_domain": connection.execute(
            "SELECT count(*)=0 FROM daily_dimension_scores WHERE eligible_dimension AND "
            "(NOT isfinite(score_dimension) OR NOT isfinite(score_dimension_min) "
            "OR score_dimension<0 OR score_dimension>1 "
            "OR score_dimension_min<0 OR score_dimension_min>1)"
        ).fetchone()[0],
        "component_non_ready_null": connection.execute(
            "SELECT count(*)=0 FROM daily_component_scores WHERE NOT eligible "
            "AND (score IS NOT NULL OR percentile IS NOT NULL)"
        ).fetchone()[0],
        "dimension_non_ready_null": connection.execute(
            "SELECT count(*)=0 FROM daily_dimension_scores WHERE NOT eligible_dimension "
            "AND (score_dimension IS NOT NULL OR score_dimension_min IS NOT NULL)"
        ).fetchone()[0],
    }


def _reason_codes_are_stable(connection: duckdb.DuckDBPyConnection) -> bool:
    for table in ("daily_component_scores", "daily_dimension_scores"):
        for (codes,) in connection.execute(
            f'SELECT reason_codes FROM "{table}"'
        ).fetchall():
            if not codes or list(codes) != sorted(set(codes)):
                return False
    return True


def _reconcile_pcvt_components(
    connection: duckdb.DuckDBPyConnection, source_rows: Sequence[Mapping[str, Any]]
) -> bool:
    for source in source_rows:
        key = (source["security_id"], source["trading_date"], source["indicator_id"])
        row = connection.execute(
            "SELECT eligible,percentile,score,validity_status,reason_codes "
            "FROM daily_component_scores WHERE security_id=? AND trading_date=? "
            "AND indicator_id=?",
            key,
        ).fetchone()
        if row is None:
            return False
        expected = (
            bool(source.get("eligible", False)),
            source.get("percentile"),
            source.get("score"),
            source.get("validity_status", "unknown"),
            sorted(set(source.get("reason_codes", ()))),
        )
        if not _row_equivalent(row, expected):
            return False
    return True


def _reconcile_pcvt_dimensions(
    connection: duckdb.DuckDBPyConnection, source_rows: Sequence[Mapping[str, Any]]
) -> bool:
    for source in source_rows:
        dimension = source.get("dimension_id", source.get("dimension"))
        key = (source["security_id"], source["trading_date"], dimension)
        row = connection.execute(
            "SELECT eligible_dimension,score_dimension,score_dimension_min,"
            "validity_status,reason_codes FROM daily_dimension_scores "
            "WHERE security_id=? AND trading_date=? AND dimension_id=?",
            key,
        ).fetchone()
        if row is None:
            return False
        expected = (
            bool(source.get("eligible_dimension", source.get("eligible", False))),
            source.get("score_dimension"),
            source.get("score_dimension_min"),
            source.get("validity_status", "unknown"),
            sorted(set(source.get("reason_codes", ()))),
        )
        if not _row_equivalent(row, expected):
            return False
    return True


def _independent_a_recomputation(
    connection: duckdb.DuckDBPyConnection, raw_rows: Sequence[Mapping[str, Any]]
) -> dict[str, bool]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        if row.get("indicator_id") in A_COMPONENTS:
            groups[(str(row["security_id"]), str(row["indicator_id"]))].append(row)
    component_ok = True
    for (security_id, indicator_id), rows in groups.items():
        history: list[float] = []
        for source in sorted(rows, key=lambda item: int(item["observation_sequence"])):
            value = _finite(source.get("raw_value"))
            status = source.get("validity_status")
            if (
                status == "valid"
                and value is not None
                and len(history) >= PERCENTILE_WINDOW
            ):
                reference = history[-PERCENTILE_WINDOW:]
                less = sum(item < value for item in reference)
                equal = sum(item == value for item in reference)
                percentile = (less + 0.5 * equal) / PERCENTILE_WINDOW
                expected_score = 1.0 - percentile
                actual = connection.execute(
                    "SELECT percentile,score,reference_observation_count "
                    "FROM daily_component_scores WHERE security_id=? AND trading_date=? "
                    "AND indicator_id=?",
                    (security_id, source["trading_date"], indicator_id),
                ).fetchone()
                if (
                    actual is None
                    or actual[0] is None
                    or actual[1] is None
                    or not (
                        math.isclose(actual[0], percentile, abs_tol=1e-12)
                        and math.isclose(actual[1], expected_score, abs_tol=1e-12)
                        and actual[2] == PERCENTILE_WINDOW
                    )
                ):
                    component_ok = False
            if status == "valid" and value is not None:
                history.append(value)

    dimension_ok = connection.execute(
        "SELECT count(*)=0 FROM daily_dimension_scores d JOIN "
        "daily_component_scores a1 USING(security_id,trading_date) JOIN "
        "daily_component_scores a2 USING(security_id,trading_date) "
        "WHERE d.dimension_id='A' "
        "AND a1.indicator_id='A1_LogBodyCenterToMACloudCenter_5_60' "
        "AND a2.indicator_id='A2_BodyCenterOutsideMACloudRate20_5_60' "
        "AND ((a1.eligible AND a2.eligible AND "
        "(NOT d.eligible_dimension OR abs(d.score_dimension-(a1.score+a2.score)/2)>1e-12 "
        "OR abs(d.score_dimension_min-least(a1.score,a2.score))>1e-12)) "
        "OR ((NOT a1.eligible OR NOT a2.eligible) AND d.eligible_dimension))"
    ).fetchone()[0]
    return {
        "a_component_independent_recomputation": component_ok,
        "a_dimension_mean_min_independent_recomputation": dimension_ok,
    }


def _anomaly_checks(connection: duckdb.DuckDBPyConnection) -> dict[str, bool]:
    component = connection.execute(
        "SELECT count(*),count(score),min(score),max(score) FROM daily_component_scores"
    ).fetchone()
    dimension = connection.execute(
        "SELECT count(*),count(score_dimension),min(score_dimension),max(score_dimension) "
        "FROM daily_dimension_scores"
    ).fetchone()
    return {
        "component_scores_not_all_null": component[1] > 0,
        "dimension_scores_not_all_null": dimension[1] > 0,
        "component_scores_not_all_zero": component[2] != 0 or component[3] != 0,
        "component_scores_not_all_one": component[2] != 1 or component[3] != 1,
        "dimension_scores_not_all_zero": dimension[2] != 0 or dimension[3] != 0,
        "dimension_scores_not_all_one": dimension[2] != 1 or dimension[3] != 1,
    }


def _validate_formal_cardinality(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, bool]:
    security_count = connection.execute("SELECT count(*) FROM securities").fetchone()[0]
    years = connection.execute(
        "SELECT min(year(trading_date)),max(year(trading_date)) FROM trading_sessions"
    ).fetchone()
    return {
        "formal_security_count_800": security_count == 800,
        "formal_calendar_year_domain": years == (2016, 2026),
    }


def _validate_formal_source_bindings(manifest: Mapping[str, Any]) -> dict[str, bool]:
    commit = manifest.get("execution_commit")
    declared = manifest.get("formal_source_bindings")
    if not isinstance(commit, str) or not isinstance(declared, dict):
        return {"formal_source_bindings": False}
    try:
        observed = {
            path: formal_source_binding(ROOT / path, commit, root=ROOT)
            for path in declared
        }
    except Exception:
        return {"formal_source_bindings": False}
    return {"formal_source_bindings": observed == declared}


def _row_equivalent(actual: Sequence[Any], expected: Sequence[Any]) -> bool:
    for left, right in zip(actual, expected, strict=True):
        if isinstance(left, list):
            if list(left) != list(right):
                return False
        elif isinstance(left, float) or isinstance(right, float):
            if (
                left is None
                or right is None
                or not math.isclose(float(left), float(right), abs_tol=1e-12)
            ):
                return False
        elif left != right:
            return False
    return True


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _validate_json(payload: Mapping[str, Any], schema_path: Path) -> None:
    schema = _load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValidationError(f"json_object_required:{path.name}")
    return payload
