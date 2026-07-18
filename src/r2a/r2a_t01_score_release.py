"""Fail-closed materializer for the immutable R2A-T01 PCAVT score release."""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
from jsonschema import Draft202012Validator, FormatChecker

from src.r2a.r2a_t01_artifact_manifest import (
    TABLE_ORDER,
    build_manifest,
    write_schema,
)
from src.r2a.r2a_t01_input_manifest import load_bound_inputs
from src.r2a.score_engine import (
    ALL_COMPONENTS,
    COMPONENTS_BY_DIMENSION,
    DIMENSION_ORDER,
    PERCENTILE_WINDOW,
    compute_a_dimension_scores,
    compute_component_scores,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "configs/r2a/r2a_t01_pcavt_score_release.v1.json"
DEFAULT_POLICY_PATH = ROOT / "configs/r2a/r2a_t01_eod_availability_policy.v1.json"
PCVT_DIMENSIONS = {"P", "C", "V", "T"}
PCVT_COMPONENTS = {
    component
    for dimension in PCVT_DIMENSIONS
    for component in COMPONENTS_BY_DIMENSION[dimension]
}
VALIDITY_STATUSES = {"valid", "unknown", "diagnostic_required", "blocked"}
OBSERVATION_STATUSES = {"present", "missing", "listing_pause"}


class ScoreReleaseError(RuntimeError):
    """Raised when a synthetic release cannot be materialized atomically."""


def materialize_score_release(
    *,
    authorized_input_manifest: str | Path,
    output_dir: str | Path,
    run_id: str,
    score_release_id: str,
    worker_count: int = 1,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    availability_policy_path: str | Path = DEFAULT_POLICY_PATH,
    synthetic_only: bool = True,
    execution_commit: str | None = None,
) -> Path:
    """Build a seven-table synthetic package without validation or analysis files."""

    if worker_count < 1:
        raise ScoreReleaseError("worker_count_must_be_positive")
    target = Path(output_dir).resolve()
    if target.exists():
        raise ScoreReleaseError("output_directory_already_exists")

    config = _load_json(config_path)
    policy = _load_json(availability_policy_path)
    _validate_json_contract(
        config,
        ROOT / "schemas/r2a/r2a_t01_pcavt_score_release_config.schema.json",
    )
    _validate_json_contract(
        policy,
        ROOT / "schemas/r2a/r2a_t01_eod_availability_policy.schema.json",
    )
    _validate_runtime_contract(config, policy)
    input_manifest = _load_json(authorized_input_manifest)
    if synthetic_only:
        if input_manifest.get("synthetic_only") is not True:
            raise ScoreReleaseError("synthetic_run_requires_synthetic_manifest")
        _reject_formal_output_path(target)
    else:
        if not (
            config.get("formal_run_allowed") is True
            and config.get("real_input_read_allowed") is True
            and input_manifest.get("synthetic_only") is False
        ):
            raise ScoreReleaseError("formal_run_not_authorized")
        _require_formal_output_path(target)
        if input_manifest.get("source_commit") != execution_commit:
            raise ScoreReleaseError("formal_input_manifest_commit_mismatch")
    rows = load_bound_inputs(
        authorized_input_manifest, formal_authorized=not synthetic_only
    )

    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        database_path = temporary / "score_data.duckdb"
        with duckdb.connect(str(database_path)) as connection:
            _create_tables(connection)
            prepared = _prepare_rows(rows, policy, worker_count)
            if not synthetic_only:
                _enforce_formal_cardinality(prepared)
            _insert_all(connection, prepared)
            row_counts = {
                table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[
                    0
                ]
                for table in TABLE_ORDER
            }
            connection.execute("CHECKPOINT")
        write_schema(temporary / "schema.json")
        build_manifest(
            package_dir=temporary,
            run_id=run_id,
            score_release_id=score_release_id,
            authorized_input_manifest=authorized_input_manifest,
            config_path=config_path,
            availability_policy_path=availability_policy_path,
            row_counts=row_counts,
            worker_count=worker_count,
            synthetic_only=synthetic_only,
            execution_commit=execution_commit,
        )
        temporary.replace(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target


def _prepare_rows(
    inputs: Mapping[str, list[dict[str, Any]]],
    policy: Mapping[str, Any],
    worker_count: int,
) -> dict[str, list[tuple[Any, ...]]]:
    securities = _prepare_securities(inputs["securities"])
    sessions = _prepare_sessions(inputs["trading_sessions"], policy)
    session_by_date = {row[0]: row for row in sessions}
    spine = _prepare_spine(
        inputs["security_observation_spine"],
        {row[0] for row in securities},
        session_by_date,
        policy,
    )
    spine_by_key = {(row[0], row[1]): row for row in spine}

    pcvt_components = _prepare_pcvt_components(
        inputs["pcvt_component_scores"], spine_by_key
    )
    pcvt_dimensions = _prepare_pcvt_dimensions(
        inputs["pcvt_dimension_scores"], spine_by_key
    )
    a_raw = _complete_a_raw_rows(inputs["a_raw_observations"], spine)
    a_components = compute_component_scores(a_raw, worker_count=worker_count)
    a_dimensions = compute_a_dimension_scores(a_components)

    component_by_key = dict(pcvt_components)
    for row in a_components:
        key = (row.security_id, row.trading_date, row.indicator_id)
        component_by_key[key] = {
            "raw_value": row.raw_value,
            "eligible": row.eligible,
            "percentile": row.percentile,
            "score": row.score,
            "validity_status": row.validity_status,
            "reason_codes": row.reason_codes,
            "reference_observation_count": row.reference_observation_count,
            "reference_sequence_start": row.reference_sequence_start,
            "reference_sequence_end": row.reference_sequence_end,
            "source_release_id": "r2a_a1_a2_w120_recomputed",
        }

    dimension_by_key = dict(pcvt_dimensions)
    for row in a_dimensions:
        key = (row.security_id, row.trading_date, "A")
        dimension_by_key[key] = {
            "eligible_dimension": row.eligible_dimension,
            "score_dimension": row.score_dimension,
            "score_dimension_min": row.score_dimension_min,
            "validity_status": row.validity_status,
            "reason_codes": row.reason_codes,
            "source_release_id": "r2a_a1_a2_w120_recomputed",
        }

    component_rows: list[tuple[Any, ...]] = []
    dimension_rows: list[tuple[Any, ...]] = []
    for security_id, trading_date, _, observation_status, available_time in spine:
        for indicator_id in ALL_COMPONENTS:
            source = component_by_key.get((security_id, trading_date, indicator_id))
            if source is None:
                source = _missing_component(observation_status)
            component_rows.append(
                (
                    security_id,
                    trading_date,
                    spine_by_key[(security_id, trading_date)][2],
                    indicator_id,
                    PERCENTILE_WINDOW,
                    source.get("raw_value"),
                    bool(source.get("eligible", False)),
                    source.get("percentile"),
                    source.get("score"),
                    source.get("validity_status", "unknown"),
                    list(_stable_reasons(source.get("reason_codes", ()))),
                    int(source.get("reference_observation_count", 0)),
                    source.get("reference_sequence_start"),
                    source.get("reference_sequence_end"),
                    available_time,
                    source.get("source_release_id", "missing_source_row"),
                )
            )
        for dimension_id in DIMENSION_ORDER:
            source = dimension_by_key.get((security_id, trading_date, dimension_id))
            if source is None:
                source = _missing_dimension(observation_status)
            dimension_rows.append(
                (
                    security_id,
                    trading_date,
                    spine_by_key[(security_id, trading_date)][2],
                    dimension_id,
                    PERCENTILE_WINDOW,
                    bool(source.get("eligible_dimension", False)),
                    source.get("score_dimension"),
                    source.get("score_dimension_min"),
                    source.get("validity_status", "unknown"),
                    list(_stable_reasons(source.get("reason_codes", ()))),
                    available_time,
                    source.get("source_release_id", "missing_source_row"),
                )
            )

    definitions = [
        (dimension, index + 1, 2) for index, dimension in enumerate(DIMENSION_ORDER)
    ]
    components = [
        (dimension, component, index + 1)
        for dimension in DIMENSION_ORDER
        for index, component in enumerate(COMPONENTS_BY_DIMENSION[dimension])
    ]
    return {
        "securities": securities,
        "trading_sessions": sessions,
        "security_observation_spine": spine,
        "dimension_definitions": definitions,
        "dimension_components": components,
        "daily_component_scores": component_rows,
        "daily_dimension_scores": dimension_rows,
    }


def _create_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE securities(
          security_id VARCHAR PRIMARY KEY,
          security_name VARCHAR NOT NULL,
          universe_id VARCHAR NOT NULL
        );
        CREATE TABLE trading_sessions(
          trading_date DATE PRIMARY KEY,
          observation_sequence BIGINT NOT NULL UNIQUE CHECK(observation_sequence >= 1),
          available_time TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE security_observation_spine(
          security_id VARCHAR NOT NULL REFERENCES securities(security_id),
          trading_date DATE NOT NULL REFERENCES trading_sessions(trading_date),
          observation_sequence BIGINT NOT NULL CHECK(observation_sequence >= 1),
          observation_status VARCHAR NOT NULL
            CHECK(observation_status IN ('present','missing','listing_pause')),
          observation_available_time TIMESTAMPTZ NOT NULL,
          PRIMARY KEY(security_id, trading_date),
          UNIQUE(security_id, observation_sequence)
        );
        CREATE TABLE dimension_definitions(
          dimension_id VARCHAR PRIMARY KEY CHECK(dimension_id IN ('P','C','A','V','T')),
          dimension_order INTEGER NOT NULL UNIQUE CHECK(dimension_order BETWEEN 1 AND 5),
          component_count INTEGER NOT NULL CHECK(component_count = 2)
        );
        CREATE TABLE dimension_components(
          dimension_id VARCHAR NOT NULL REFERENCES dimension_definitions(dimension_id),
          indicator_id VARCHAR NOT NULL UNIQUE,
          component_order INTEGER NOT NULL CHECK(component_order IN (1,2)),
          PRIMARY KEY(dimension_id, indicator_id),
          UNIQUE(dimension_id, component_order)
        );
        CREATE TABLE daily_component_scores(
          security_id VARCHAR NOT NULL,
          trading_date DATE NOT NULL,
          observation_sequence BIGINT NOT NULL CHECK(observation_sequence >= 1),
          indicator_id VARCHAR NOT NULL REFERENCES dimension_components(indicator_id),
          percentile_window INTEGER NOT NULL CHECK(percentile_window = 120),
          raw_value DOUBLE,
          eligible BOOLEAN NOT NULL,
          percentile DOUBLE,
          score DOUBLE,
          validity_status VARCHAR NOT NULL
            CHECK(validity_status IN ('valid','unknown','diagnostic_required','blocked')),
          reason_codes VARCHAR[] NOT NULL CHECK(len(reason_codes) >= 1),
          reference_observation_count INTEGER NOT NULL
            CHECK(reference_observation_count BETWEEN 0 AND 120),
          reference_sequence_start BIGINT,
          reference_sequence_end BIGINT,
          available_time TIMESTAMPTZ NOT NULL,
          source_release_id VARCHAR NOT NULL,
          PRIMARY KEY(security_id, trading_date, indicator_id),
          FOREIGN KEY(security_id, trading_date)
            REFERENCES security_observation_spine(security_id, trading_date),
          CHECK((eligible AND validity_status='valid' AND percentile IS NOT NULL
                 AND score IS NOT NULL AND percentile BETWEEN 0 AND 1
                 AND score BETWEEN 0 AND 1)
             OR (NOT eligible AND percentile IS NULL AND score IS NULL))
        );
        CREATE TABLE daily_dimension_scores(
          security_id VARCHAR NOT NULL,
          trading_date DATE NOT NULL,
          observation_sequence BIGINT NOT NULL CHECK(observation_sequence >= 1),
          dimension_id VARCHAR NOT NULL REFERENCES dimension_definitions(dimension_id),
          percentile_window INTEGER NOT NULL CHECK(percentile_window = 120),
          eligible_dimension BOOLEAN NOT NULL,
          score_dimension DOUBLE,
          score_dimension_min DOUBLE,
          validity_status VARCHAR NOT NULL
            CHECK(validity_status IN ('valid','unknown','diagnostic_required','blocked')),
          reason_codes VARCHAR[] NOT NULL CHECK(len(reason_codes) >= 1),
          available_time TIMESTAMPTZ NOT NULL,
          source_release_id VARCHAR NOT NULL,
          PRIMARY KEY(security_id, trading_date, dimension_id),
          FOREIGN KEY(security_id, trading_date)
            REFERENCES security_observation_spine(security_id, trading_date),
          CHECK((eligible_dimension AND validity_status='valid'
                 AND score_dimension IS NOT NULL AND score_dimension_min IS NOT NULL
                 AND score_dimension BETWEEN 0 AND 1
                 AND score_dimension_min BETWEEN 0 AND 1)
             OR (NOT eligible_dimension AND score_dimension IS NULL
                 AND score_dimension_min IS NULL))
        );
        """
    )


def _insert_all(
    connection: duckdb.DuckDBPyConnection,
    rows: Mapping[str, Sequence[tuple[Any, ...]]],
) -> None:
    placeholders = {
        "securities": 3,
        "trading_sessions": 3,
        "security_observation_spine": 5,
        "dimension_definitions": 3,
        "dimension_components": 3,
        "daily_component_scores": 16,
        "daily_dimension_scores": 12,
    }
    connection.execute("BEGIN TRANSACTION")
    try:
        for table in TABLE_ORDER:
            values = rows[table]
            marker = ",".join("?" for _ in range(placeholders[table]))
            connection.executemany(f'INSERT INTO "{table}" VALUES ({marker})', values)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _prepare_securities(
    rows: Sequence[Mapping[str, Any]],
) -> list[tuple[str, str, str]]:
    output: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in rows:
        security_id = str(row.get("security_id", ""))
        if not security_id or security_id in seen:
            raise ScoreReleaseError("invalid_or_duplicate_security")
        seen.add(security_id)
        output.append(
            (
                security_id,
                str(row.get("security_name", security_id)),
                str(row.get("universe_id", "SYNTHETIC")),
            )
        )
    if not output:
        raise ScoreReleaseError("empty_securities")
    return sorted(output)


def _prepare_sessions(
    rows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> list[tuple[str, int, datetime]]:
    output: list[tuple[str, int, datetime]] = []
    seen_dates: set[str] = set()
    seen_sequences: set[int] = set()
    for row in rows:
        trading_date = str(row["trading_date"])
        sequence = int(row["observation_sequence"])
        if trading_date in seen_dates or sequence in seen_sequences:
            raise ScoreReleaseError("duplicate_trading_session")
        seen_dates.add(trading_date)
        seen_sequences.add(sequence)
        output.append((trading_date, sequence, _available_time(trading_date, policy)))
    ordered = sorted(output, key=lambda row: row[1])
    if [row[1] for row in ordered] != list(range(1, len(ordered) + 1)):
        raise ScoreReleaseError("trading_session_sequence_gap")
    return ordered


def _prepare_spine(
    rows: Sequence[Mapping[str, Any]],
    security_ids: set[str],
    sessions: Mapping[str, tuple[str, int, datetime]],
    policy: Mapping[str, Any],
) -> list[tuple[str, str, int, str, datetime]]:
    output: list[tuple[str, str, int, str, datetime]] = []
    seen: set[tuple[str, str]] = set()
    sequences: dict[str, list[int]] = {security_id: [] for security_id in security_ids}
    for row in rows:
        security_id = str(row["security_id"])
        trading_date = str(row["trading_date"])
        key = (security_id, trading_date)
        if (
            security_id not in security_ids
            or trading_date not in sessions
            or key in seen
        ):
            raise ScoreReleaseError("invalid_or_duplicate_spine_key")
        sequence = int(row["observation_sequence"])
        if sequence != sessions[trading_date][1]:
            raise ScoreReleaseError("spine_session_sequence_mismatch")
        status = str(row.get("observation_status", "present"))
        if status not in OBSERVATION_STATUSES:
            raise ScoreReleaseError("invalid_observation_status")
        seen.add(key)
        sequences[security_id].append(sequence)
        output.append(
            (
                security_id,
                trading_date,
                sequence,
                status,
                _available_time(trading_date, policy),
            )
        )
    for security_id, values in sequences.items():
        ordered = sorted(values)
        if not ordered or ordered != list(range(ordered[0], ordered[-1] + 1)):
            raise ScoreReleaseError(f"spine_sequence_gap:{security_id}")
    return sorted(output, key=lambda row: (row[0], row[2]))


def _prepare_pcvt_components(
    rows: Sequence[Mapping[str, Any]], spine: Mapping[tuple[str, str], tuple[Any, ...]]
) -> dict[tuple[str, str, str], dict[str, Any]]:
    output: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        indicator = str(row.get("indicator_id", ""))
        key = (str(row["security_id"]), str(row["trading_date"]), indicator)
        if indicator not in PCVT_COMPONENTS or key[:2] not in spine or key in output:
            raise ScoreReleaseError("invalid_pcvt_component_source_row")
        _require_w120(row)
        output[key] = _normalise_component_source(row)
    return output


def _prepare_pcvt_dimensions(
    rows: Sequence[Mapping[str, Any]], spine: Mapping[tuple[str, str], tuple[Any, ...]]
) -> dict[tuple[str, str, str], dict[str, Any]]:
    output: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        dimension = str(row.get("dimension_id", row.get("dimension", "")))
        key = (str(row["security_id"]), str(row["trading_date"]), dimension)
        if dimension not in PCVT_DIMENSIONS or key[:2] not in spine or key in output:
            raise ScoreReleaseError("invalid_pcvt_dimension_source_row")
        _require_w120(row)
        output[key] = _normalise_dimension_source(row)
    return output


def _complete_a_raw_rows(
    source_rows: Sequence[Mapping[str, Any]],
    spine: Sequence[tuple[str, str, int, str, datetime]],
) -> list[dict[str, Any]]:
    source: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in source_rows:
        indicator = str(row.get("indicator_id", ""))
        key = (str(row["security_id"]), str(row["trading_date"]), indicator)
        if indicator not in COMPONENTS_BY_DIMENSION["A"] or key in source:
            raise ScoreReleaseError("invalid_or_duplicate_a_raw_row")
        source[key] = row
    output: list[dict[str, Any]] = []
    for security_id, trading_date, sequence, observation_status, _ in spine:
        for indicator in COMPONENTS_BY_DIMENSION["A"]:
            row = source.get((security_id, trading_date, indicator))
            if row is None:
                output.append(
                    {
                        "security_id": security_id,
                        "trading_date": trading_date,
                        "observation_sequence": sequence,
                        "indicator_id": indicator,
                        "raw_value": None,
                        "validity_status": "unknown",
                        "reason_codes": [
                            "observation_not_present"
                            if observation_status != "present"
                            else "a_raw_observation_missing"
                        ],
                    }
                )
                continue
            if int(row["observation_sequence"]) != sequence:
                raise ScoreReleaseError("a_raw_sequence_mismatch")
            output.append(dict(row))
    return output


def _normalise_component_source(row: Mapping[str, Any]) -> dict[str, Any]:
    eligible = bool(row.get("eligible", False))
    status = str(row.get("validity_status", "unknown"))
    if status not in VALIDITY_STATUSES:
        raise ScoreReleaseError("invalid_component_validity")
    score = _finite_or_none(row.get("score"))
    percentile = _finite_or_none(row.get("percentile"))
    if eligible and (status != "valid" or score is None or percentile is None):
        raise ScoreReleaseError("invalid_ready_component_source")
    if not eligible and (score is not None or percentile is not None):
        raise ScoreReleaseError("non_ready_component_score_must_be_null")
    return {
        "raw_value": _finite_or_none(row.get("raw_value")),
        "eligible": eligible,
        "percentile": percentile,
        "score": score,
        "validity_status": status,
        "reason_codes": _stable_reasons(row.get("reason_codes", ())),
        "reference_observation_count": int(row.get("reference_observation_count", 0)),
        "reference_sequence_start": row.get("reference_sequence_start"),
        "reference_sequence_end": row.get("reference_sequence_end"),
        "source_release_id": str(row.get("source_release_id", "r0_t05_accepted_w120")),
    }


def _normalise_dimension_source(row: Mapping[str, Any]) -> dict[str, Any]:
    eligible = bool(row.get("eligible_dimension", row.get("eligible", False)))
    status = str(row.get("validity_status", "unknown"))
    score = _finite_or_none(row.get("score_dimension"))
    minimum = _finite_or_none(row.get("score_dimension_min"))
    if status not in VALIDITY_STATUSES:
        raise ScoreReleaseError("invalid_dimension_validity")
    if eligible and (status != "valid" or score is None or minimum is None):
        raise ScoreReleaseError("invalid_ready_dimension_source")
    if not eligible and (score is not None or minimum is not None):
        raise ScoreReleaseError("non_ready_dimension_score_must_be_null")
    return {
        "eligible_dimension": eligible,
        "score_dimension": score,
        "score_dimension_min": minimum,
        "validity_status": status,
        "reason_codes": _stable_reasons(row.get("reason_codes", ())),
        "source_release_id": str(row.get("source_release_id", "r0_t05_accepted_w120")),
    }


def _missing_component(observation_status: str) -> dict[str, Any]:
    return {
        "eligible": False,
        "validity_status": "unknown",
        "reason_codes": (
            "observation_not_present"
            if observation_status != "present"
            else "source_component_missing",
        ),
    }


def _missing_dimension(observation_status: str) -> dict[str, Any]:
    return {
        "eligible_dimension": False,
        "validity_status": "unknown",
        "reason_codes": (
            "observation_not_present"
            if observation_status != "present"
            else "source_dimension_missing",
        ),
    }


def _available_time(trading_date: str, policy: Mapping[str, Any]) -> datetime:
    cutoff = time.fromisoformat(str(policy["market_information_cutoff"]))
    return datetime.combine(
        date.fromisoformat(trading_date),
        cutoff,
        tzinfo=ZoneInfo(str(policy["timezone"])),
    )


def _require_w120(row: Mapping[str, Any]) -> None:
    window = int(row.get("percentile_window", row.get("percentile_window_W", 0)))
    if window != PERCENTILE_WINDOW:
        raise ScoreReleaseError("only_w120_source_rows_allowed")


def _finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    import math

    numeric = float(value)
    if not math.isfinite(numeric):
        raise ScoreReleaseError("non_finite_score_source")
    return numeric


def _stable_reasons(values: Sequence[Any]) -> tuple[str, ...]:
    reasons = sorted({str(value) for value in values if str(value)})
    return tuple(reasons or ["unspecified_non_ready"])


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ScoreReleaseError("contract_json_must_be_object")
    return payload


def _validate_json_contract(payload: Mapping[str, Any], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)


def _validate_runtime_contract(
    config: Mapping[str, Any], policy: Mapping[str, Any]
) -> None:
    if not isinstance(config.get("formal_run_allowed"), bool) or not isinstance(
        config.get("real_input_read_allowed"), bool
    ):
        raise ScoreReleaseError("run_authorization_flags_must_be_boolean")
    if config.get("percentile_window") != PERCENTILE_WINDOW:
        raise ScoreReleaseError("config_window_mismatch")
    if config.get("dimension_order") != list(DIMENSION_ORDER):
        raise ScoreReleaseError("dimension_order_mismatch")
    if policy.get("policy_id") != "r2a_t01_eod_close_1500_asia_shanghai.v1":
        raise ScoreReleaseError("availability_policy_mismatch")


def _reject_formal_output_path(path: Path) -> None:
    normalized = path.as_posix().lower()
    if "/data/generated/r2a/r2a_t01/" in f"/{normalized.strip('/')}/":
        raise ScoreReleaseError("formal_output_path_not_authorized")


def _require_formal_output_path(path: Path) -> None:
    root = (ROOT / "data/generated/r2a/r2a_t01").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ScoreReleaseError("formal_output_must_use_canonical_root") from exc


def _enforce_formal_cardinality(rows: Mapping[str, Sequence[tuple[Any, ...]]]) -> None:
    if len(rows["securities"]) != 800:
        raise ScoreReleaseError("formal_security_count_must_equal_800")
    years = {date.fromisoformat(str(row[0])).year for row in rows["trading_sessions"]}
    if not years or min(years) != 2016 or max(years) != 2026:
        raise ScoreReleaseError("formal_calendar_year_domain_must_be_2016_2026")
