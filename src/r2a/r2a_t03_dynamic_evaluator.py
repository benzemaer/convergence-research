"""Parameterized R2A-T03 dynamic-state evaluator for one canonical request."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import duckdb

from src.r2a.r2a_t02_request_identity import validate_canonical_request
from src.r2a.r2a_t03_output_contract import (
    EVALUATOR_VERSION,
    OUTPUT_SCHEMA_VERSION,
    OUTPUT_TABLE_ORDER,
    TABLE_CONTRACTS,
    DynamicEvaluationSummary,
    validate_dynamic_evaluation_output,
)

ROOT = Path(__file__).resolve().parents[2]
T02_HANDOFF_PATH = (
    ROOT
    / "data/generated/r2a/r2a_t02/pcavt_dynamic_state_protocol.v1"
    / "r2a_t02_accepted_protocol_handoff.json"
)
T02_CONFIG_PATH = ROOT / "configs/r2a/r2a_t02_dynamic_state_protocol.v1.json"
T02_HANDOFF_SHA256 = "f8ff97543b95ba3676acd36ea3d48adb06dfb1f9ab51a7ee7b8413003e1b5082"
T02_CONFIG_SHA256 = "bd57b1c90a340fe19e52450676b48f3d9f8cba20b93e344da429b5f378540d99"
BOUND_SCORE_RELEASE_ID = "pcavt-score-w120-v1-c7e04f11a2cd09aa"
BOUND_PROTOCOL_VERSION = "pcavt_dynamic_state_protocol.v1"
DIMENSION_ORDER = ("P", "C", "A", "V", "T")
VALIDITY_STATUSES = ("valid", "unknown", "diagnostic_required", "blocked")
EXPECTED_STATUSES = ("present", "missing", "listing_pause")
STREAM_BATCH_SIZE = 10_000

SOURCE_TABLE_COLUMNS = {
    "security_observation_spine": (
        "score_release_id:VARCHAR",
        "security_id:VARCHAR",
        "trading_date:DATE",
        "observation_sequence:BIGINT",
        "expected_observation_status:VARCHAR",
        "observation_available_time:TIMESTAMP WITH TIME ZONE",
    ),
    "daily_dimension_scores": (
        "score_release_id:VARCHAR",
        "security_id:VARCHAR",
        "trading_date:DATE",
        "observation_sequence:BIGINT",
        "dimension_id:VARCHAR",
        "score_dimension:DOUBLE?",
        "score_dimension_min:DOUBLE?",
        "eligible_dimension:BOOLEAN",
        "validity_status:VARCHAR",
        "reason_codes:VARCHAR[]",
        "available_time:TIMESTAMP WITH TIME ZONE",
    ),
}
SECURITY_SCOPE_CONTRACT = {
    "allowed": ["all", "explicit"],
    "date_slicing_allowed": False,
    "duplicate_unknown_or_empty_explicit_scope": "reject",
    "included_in_request_identity": False,
}
ALGORITHM_CONTRACT = {
    "dimension_formula": ("ready ? mean>=1-q-epsilon AND min>=1-q-weak_delta : NULL"),
    "joint_formula": "complete_case_AND_selected_dimensions",
    "streak_formula": "true:previous_true+1;false:0;NULL:NULL_and_interrupt",
    "confirmation_formula": (
        "event=streak==K;confirmed=true only from Kth true without backfill"
    ),
    "interval_formula": (
        "start_confirmation_date;end_last_confirmed_before_false_or_NULL;"
        "input_end_right_censored"
    ),
    "weak_delta_bp": 1000,
    "floating_comparison_epsilon": 1e-12,
    "confirmation_k_domain": [2, 3, 4, 5, 6, 7],
}
TERMINATION_PRIORITY = [
    "expected_observation_missing",
    "expected_observation_listing_pause",
    "selected_dimension_blocked",
    "selected_dimension_diagnostic_required",
    "selected_dimension_unknown",
    "selected_dimension_not_eligible",
    "selected_dimension_score_non_finite",
    "raw_false",
]
ZERO_EVENT_BEHAVIOR = "completed_with_empty_confirmed_intervals_table"
NON_GOALS = [
    "real_score_data",
    "parameter_selection",
    "formal_dynamic_package",
    "cache",
    "date_slicing",
    "d",
    "g",
    "exit_delay",
    "gap_tolerance",
    "interval_merge",
    "DONE",
    "accepted_handoff",
    "R2A-T04",
]


def source_contract_as_json() -> dict[str, object]:
    """Return the immutable development source contract in JSON form."""

    return {
        "tables": {
            table: list(columns) for table, columns in SOURCE_TABLE_COLUMNS.items()
        },
        "read_only": True,
        "selected_dimensions_only": True,
        "full_observation_history_required": True,
    }


def algorithm_contract_as_json() -> dict[str, object]:
    """Return the immutable development algorithm contract in JSON form."""

    return dict(ALGORITHM_CONTRACT)


SOURCE_CONTRACT = {
    table: {
        item.split(":", 1)[0]: {item.split(":", 1)[1].removesuffix("?")}
        for item in columns
    }
    for table, columns in SOURCE_TABLE_COLUMNS.items()
}


class DynamicEvaluationError(ValueError):
    """Fail-closed evaluator error with a stable reason code."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        message = reason_code if detail is None else f"{reason_code}: {detail}"
        super().__init__(message)


def evaluate_confirmation_sequence(
    raw_states: Sequence[bool | None], confirmation_k: int
) -> tuple[tuple[int | None, bool, bool | None], ...]:
    """Pure protocol oracle for streak/confirmation, including the K=1 boundary.

    This helper does not validate the public request domain.  It exists so the
    mathematical state-machine boundary can be tested independently of DuckDB;
    public entry points still accept only T02-canonical requests (K=2..7).
    """

    if type(confirmation_k) is not int or confirmation_k < 1:
        raise DynamicEvaluationError("confirmation_k_mathematical_domain_invalid")
    streak = 0
    evaluated: list[tuple[int | None, bool, bool | None]] = []
    for raw_state in raw_states:
        if raw_state is True:
            streak += 1
            evaluated.append(
                (streak, streak == confirmation_k, streak >= confirmation_k)
            )
        elif raw_state is False:
            streak = 0
            evaluated.append((0, False, False))
        elif raw_state is None:
            streak = 0
            evaluated.append((None, False, None))
        else:
            raise DynamicEvaluationError("raw_state_mathematical_domain_invalid")
    return tuple(evaluated)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_accepted_binding() -> None:
    if _sha256(T02_HANDOFF_PATH) != T02_HANDOFF_SHA256:
        raise DynamicEvaluationError("accepted_t02_handoff_hash_mismatch")
    if _sha256(T02_CONFIG_PATH) != T02_CONFIG_SHA256:
        raise DynamicEvaluationError("accepted_protocol_config_hash_mismatch")
    handoff = json.loads(T02_HANDOFF_PATH.read_text(encoding="utf-8"))
    if (
        handoff.get("status") != "completed_accepted"
        or handoff.get("protocol_review_status") != "accepted"
        or handoff.get("dynamic_protocol_version") != BOUND_PROTOCOL_VERSION
        or handoff.get("score_release_id") != BOUND_SCORE_RELEASE_ID
    ):
        raise DynamicEvaluationError("accepted_t02_handoff_binding_mismatch")


def _table_columns(connection: duckdb.DuckDBPyConnection, table: str) -> dict[str, str]:
    try:
        rows = connection.execute(f"PRAGMA table_info('{table}')").fetchall()
    except duckdb.Error as error:
        raise DynamicEvaluationError("source_table_missing", table) from error
    if not rows:
        raise DynamicEvaluationError("source_table_missing", table)
    return {str(row[1]): str(row[2]).upper() for row in rows}


def _validate_source_schema(connection: duckdb.DuckDBPyConnection) -> None:
    for table, required in SOURCE_CONTRACT.items():
        actual = _table_columns(connection, table)
        for column, allowed_types in required.items():
            if column not in actual:
                raise DynamicEvaluationError(
                    "source_column_missing", f"{table}.{column}"
                )
            if actual[column] not in allowed_types:
                raise DynamicEvaluationError(
                    "source_column_type_mismatch",
                    f"{table}.{column}:{actual[column]}",
                )


def _placeholders(values: Sequence[object]) -> str:
    return ",".join("?" for _ in values)


def _duckdb_string_literal(value: str) -> str:
    if "\x00" in value:
        raise DynamicEvaluationError("source_database_path_invalid")
    return "'" + value.replace("'", "''") + "'"


def _scope_predicate(security_ids: Sequence[str]) -> tuple[str, list[object]]:
    return (
        f"security_id IN ({_placeholders(security_ids)})",
        list(security_ids),
    )


def _resolve_security_scope(
    connection: duckdb.DuckDBPyConnection,
    security_ids: Sequence[str] | None,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    available = tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT security_id FROM security_observation_spine "
            "ORDER BY security_id"
        ).fetchall()
    )
    if not available:
        raise DynamicEvaluationError("source_has_no_securities")
    if security_ids is None:
        return "all", (), available
    if isinstance(security_ids, str):
        raise DynamicEvaluationError("security_ids_must_be_sequence")
    requested = tuple(str(item) for item in security_ids)
    if not requested:
        raise DynamicEvaluationError("explicit_security_scope_empty")
    if len(requested) != len(set(requested)):
        raise DynamicEvaluationError("duplicate_security_id")
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise DynamicEvaluationError("unknown_security_id", ",".join(unknown))
    return "explicit", tuple(sorted(requested)), tuple(sorted(requested))


def _count(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[object] = (),
) -> int:
    return int(connection.execute(query, list(parameters)).fetchone()[0])


def _fail_if_nonzero(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[object],
    reason_code: str,
) -> None:
    count = _count(connection, query, parameters)
    if count:
        raise DynamicEvaluationError(reason_code, str(count))


def _validate_source_content(
    connection: duckdb.DuckDBPyConnection,
    evaluated_security_ids: tuple[str, ...],
    selected_dimensions: tuple[str, ...],
    score_release_id: str,
) -> None:
    scope_sql, scope_params = _scope_predicate(evaluated_security_ids)
    dimension_sql = f"dimension_id IN ({_placeholders(selected_dimensions)})"
    dimension_params = list(selected_dimensions)
    release_rows = connection.execute(
        "SELECT DISTINCT score_release_id FROM ("
        "SELECT score_release_id FROM security_observation_spine UNION ALL "
        "SELECT score_release_id FROM daily_dimension_scores) ORDER BY 1"
    ).fetchall()
    releases = [row[0] for row in release_rows]
    if releases != [score_release_id]:
        raise DynamicEvaluationError("score_release_id_mismatch", str(releases))
    _fail_if_nonzero(
        connection,
        f"SELECT count(*) FROM (SELECT security_id, trading_date, count(*) n "
        f"FROM security_observation_spine WHERE {scope_sql} "
        "GROUP BY security_id, trading_date HAVING n <> 1)",
        scope_params,
        "spine_primary_key_duplicate",
    )
    _fail_if_nonzero(
        connection,
        f"SELECT count(*) FROM (SELECT security_id, min(observation_sequence) lo, "
        "max(observation_sequence) hi, count(*) n, "
        "count(DISTINCT observation_sequence) dn "
        f"FROM security_observation_spine WHERE {scope_sql} GROUP BY security_id "
        "HAVING lo <> 0 OR hi <> n - 1 OR dn <> n)",
        scope_params,
        "observation_sequence_not_contiguous",
    )
    _fail_if_nonzero(
        connection,
        "WITH ordered AS (SELECT security_id, trading_date, observation_sequence, "
        "lag(trading_date) OVER (PARTITION BY security_id "
        "ORDER BY observation_sequence) prev "
        f"FROM security_observation_spine WHERE {scope_sql}) "
        "SELECT count(*) FROM ordered WHERE prev IS NOT NULL AND trading_date <= prev",
        scope_params,
        "trading_date_not_strictly_increasing",
    )
    _fail_if_nonzero(
        connection,
        f"SELECT count(*) FROM security_observation_spine WHERE {scope_sql} "
        f"AND expected_observation_status NOT IN ({_placeholders(EXPECTED_STATUSES)})",
        [*scope_params, *EXPECTED_STATUSES],
        "expected_observation_status_invalid",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM daily_dimension_scores WHERE "
        f"{scope_sql} AND {dimension_sql} "
        f"AND validity_status NOT IN ({_placeholders(VALIDITY_STATUSES)})",
        [*scope_params, *dimension_params, *VALIDITY_STATUSES],
        "validity_status_invalid",
    )
    expected_dimension_rows = _count(
        connection,
        f"SELECT count(*) FROM security_observation_spine WHERE {scope_sql}",
        scope_params,
    ) * len(selected_dimensions)
    actual_dimension_rows = _count(
        connection,
        "SELECT count(*) FROM daily_dimension_scores WHERE "
        f"{scope_sql} AND {dimension_sql}",
        [*scope_params, *dimension_params],
    )
    if actual_dimension_rows != expected_dimension_rows:
        raise DynamicEvaluationError(
            "selected_dimension_cardinality_mismatch",
            f"expected={expected_dimension_rows};actual={actual_dimension_rows}",
        )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM (SELECT security_id, trading_date, "
        "dimension_id, count(*) n "
        f"FROM daily_dimension_scores WHERE {scope_sql} AND {dimension_sql} "
        "GROUP BY security_id, trading_date, dimension_id HAVING n <> 1)",
        [*scope_params, *dimension_params],
        "selected_dimension_duplicate",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM daily_dimension_scores d LEFT JOIN "
        "security_observation_spine s "
        "ON d.security_id=s.security_id AND d.trading_date=s.trading_date "
        f"WHERE d.{scope_sql} AND d.{dimension_sql} AND s.security_id IS NULL",
        [*scope_params, *dimension_params],
        "selected_dimension_source_only_key",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM daily_dimension_scores d JOIN "
        "security_observation_spine s "
        "ON d.security_id=s.security_id AND d.trading_date=s.trading_date "
        f"WHERE d.{scope_sql} AND d.{dimension_sql} AND ("
        "d.observation_sequence <> s.observation_sequence OR "
        "d.available_time IS DISTINCT FROM s.observation_available_time)",
        [*scope_params, *dimension_params],
        "dimension_spine_reconciliation_mismatch",
    )


def _create_table_sql(table: str) -> str:
    spec = TABLE_CONTRACTS[table]
    columns = [
        f'"{item.name}" {item.type}{"" if item.nullable else " NOT NULL"}'
        for item in spec.columns
    ]
    primary = ", ".join(f'"{item}"' for item in spec.primary_key)
    columns.append(f"PRIMARY KEY ({primary})")
    return f"CREATE TABLE {table} ({', '.join(columns)})"


def _create_output_tables(connection: duckdb.DuckDBPyConnection) -> None:
    existing = _count(
        connection,
        "SELECT count(*) FROM duckdb_tables() WHERE database_name=current_database() "
        "AND schema_name='main'",
    )
    if existing:
        raise DynamicEvaluationError("output_connection_not_empty")
    for table in OUTPUT_TABLE_ORDER:
        connection.execute(_create_table_sql(table))
    connection.execute(
        "CREATE TEMP TABLE staging_spine (score_release_id VARCHAR NOT NULL, "
        "security_id VARCHAR NOT NULL, trading_date DATE NOT NULL, "
        "observation_sequence BIGINT NOT NULL, "
        "expected_observation_status VARCHAR NOT NULL, "
        "observation_available_time TIMESTAMP WITH TIME ZONE NOT NULL)"
    )
    connection.execute(
        "CREATE TEMP TABLE staging_dimensions (score_release_id VARCHAR NOT NULL, "
        "security_id VARCHAR NOT NULL, trading_date DATE NOT NULL, "
        "observation_sequence BIGINT NOT NULL, dimension_id VARCHAR NOT NULL, "
        "score_dimension DOUBLE, score_dimension_min DOUBLE, "
        "eligible_dimension BOOLEAN NOT NULL, validity_status VARCHAR NOT NULL, "
        "reason_codes VARCHAR[], available_time TIMESTAMP WITH TIME ZONE NOT NULL)"
    )


def _stream_query(
    source: duckdb.DuckDBPyConnection,
    output: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[object],
    insert_sql: str,
) -> int:
    cursor = source.execute(query, list(parameters))
    count = 0
    while True:
        rows = cursor.fetchmany(STREAM_BATCH_SIZE)
        if not rows:
            return count
        output.executemany(insert_sql, rows)
        count += len(rows)


def _copy_selected_source(
    source: duckdb.DuckDBPyConnection,
    output: duckdb.DuckDBPyConnection,
    securities: tuple[str, ...],
    dimensions: tuple[str, ...],
) -> int:
    scope_sql, scope_params = _scope_predicate(securities)
    spine_count = _stream_query(
        source,
        output,
        "SELECT score_release_id, security_id, trading_date, observation_sequence, "
        "expected_observation_status, observation_available_time "
        f"FROM security_observation_spine WHERE {scope_sql} "
        "ORDER BY security_id, observation_sequence",
        scope_params,
        "INSERT INTO staging_spine VALUES (?, ?, ?, ?, ?, ?)",
    )
    dimension_sql = f"dimension_id IN ({_placeholders(dimensions)})"
    _stream_query(
        source,
        output,
        "SELECT score_release_id, security_id, trading_date, observation_sequence, "
        "dimension_id, score_dimension, score_dimension_min, eligible_dimension, "
        "validity_status, reason_codes, available_time FROM daily_dimension_scores "
        f"WHERE {scope_sql} AND {dimension_sql} "
        "ORDER BY security_id, observation_sequence, dimension_id",
        [*scope_params, *dimensions],
        "INSERT INTO staging_dimensions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    return spine_count


def _copy_selected_source_bulk(
    *,
    source_database_path: Path,
    output: duckdb.DuckDBPyConnection,
    securities: tuple[str, ...],
    dimensions: tuple[str, ...],
) -> int:
    source_path = source_database_path.resolve()
    attached = False
    try:
        output.execute(
            f"ATTACH {_duckdb_string_literal(str(source_path))} "
            "AS score_source (READ_ONLY)"
        )
        attached = True
        output.execute(
            "CREATE TEMP TABLE selected_security_ids (security_id VARCHAR PRIMARY KEY)"
        )
        output.execute(
            "INSERT INTO selected_security_ids SELECT unnest(?)",
            [list(securities)],
        )
        output.execute(
            "INSERT INTO staging_spine "
            "SELECT s.score_release_id, s.security_id, s.trading_date, "
            "s.observation_sequence, s.expected_observation_status, "
            "s.observation_available_time "
            "FROM score_source.security_observation_spine AS s "
            "JOIN selected_security_ids AS scope USING (security_id) "
            "ORDER BY s.security_id, s.observation_sequence"
        )
        dimension_placeholders = _placeholders(dimensions)
        output.execute(
            "INSERT INTO staging_dimensions "
            "SELECT d.score_release_id, d.security_id, d.trading_date, "
            "d.observation_sequence, d.dimension_id, d.score_dimension, "
            "d.score_dimension_min, d.eligible_dimension, d.validity_status, "
            "d.reason_codes, d.available_time "
            "FROM score_source.daily_dimension_scores AS d "
            "JOIN selected_security_ids AS scope USING (security_id) "
            f"WHERE d.dimension_id IN ({dimension_placeholders}) "
            "ORDER BY d.security_id, d.observation_sequence, d.dimension_id",
            list(dimensions),
        )
        spine_count = _count(output, "SELECT count(*) FROM staging_spine")
        dimension_count = _count(output, "SELECT count(*) FROM staging_dimensions")
        if dimension_count != spine_count * len(dimensions):
            raise DynamicEvaluationError(
                "bulk_source_copy_cardinality_mismatch",
                f"spine={spine_count};dimensions={dimension_count};"
                f"selected_dimensions={len(dimensions)}",
            )
        return spine_count
    except DynamicEvaluationError:
        raise
    except duckdb.Error as error:
        raise DynamicEvaluationError("bulk_source_copy_failed") from error
    finally:
        try:
            output.execute("DROP TABLE IF EXISTS selected_security_ids")
        finally:
            if attached:
                try:
                    output.execute("DETACH score_source")
                except duckdb.Error as error:
                    raise DynamicEvaluationError("bulk_source_copy_failed") from error


def _dimension_reason_expression() -> str:
    upstream = (
        "list_transform(coalesce(d.reason_codes, []::VARCHAR[]), "
        "x -> d.dimension_id || ':' || x)"
    )
    derived = (
        "list_concat("
        "CASE d.validity_status WHEN 'blocked' THEN "
        "[d.dimension_id || ':validity_blocked'] "
        "WHEN 'diagnostic_required' THEN "
        "[d.dimension_id || ':validity_diagnostic_required'] "
        "WHEN 'unknown' THEN [d.dimension_id || ':validity_unknown'] "
        "ELSE []::VARCHAR[] END, "
        "CASE WHEN d.eligible_dimension IS NOT TRUE THEN "
        "[d.dimension_id || ':dimension_not_eligible'] ELSE []::VARCHAR[] END, "
        "CASE WHEN d.score_dimension IS NULL OR d.score_dimension_min IS NULL OR "
        "NOT isfinite(d.score_dimension) OR NOT isfinite(d.score_dimension_min) THEN "
        "[d.dimension_id || ':score_non_finite'] ELSE []::VARCHAR[] END)"
    )
    return f"list_sort(list_distinct(list_concat({upstream}, {derived})))"


def _populate_dimensions(
    output: duckdb.DuckDBPyConnection,
    request_id: str,
    selected_dimensions: tuple[str, ...],
    q_by_dimension: Mapping[str, int],
) -> None:
    output.execute(
        "CREATE TEMP TABLE request_dimensions (dimension_id VARCHAR, q_bp INTEGER)"
    )
    output.executemany(
        "INSERT INTO request_dimensions VALUES (?, ?)",
        [(item, int(q_by_dimension[item])) for item in selected_dimensions],
    )
    reasons = _dimension_reason_expression()
    output.execute(
        f"""
        INSERT INTO daily_dimension_states
        WITH base AS (
          SELECT
            ?::VARCHAR AS request_id,
            s.security_id, s.trading_date, s.observation_sequence,
            s.expected_observation_status, s.observation_available_time,
            d.dimension_id, r.q_bp,
            1.0-r.q_bp/10000.0 AS main_threshold,
            1.0-r.q_bp/10000.0-0.10 AS weak_threshold,
            d.score_dimension, d.score_dimension_min, d.eligible_dimension,
            d.validity_status,
            coalesce(d.reason_codes, []::VARCHAR[]) AS source_reason_codes,
            s.expected_observation_status='present'
              AND d.eligible_dimension IS TRUE
              AND d.validity_status='valid'
              AND d.score_dimension IS NOT NULL AND isfinite(d.score_dimension)
              AND d.score_dimension_min IS NOT NULL AND isfinite(d.score_dimension_min)
              AS dimension_ready,
            {reasons} AS dimension_reason_codes,
            d.available_time
          FROM staging_spine s
          JOIN staging_dimensions d
            USING (security_id, trading_date, observation_sequence)
          JOIN request_dimensions r USING (dimension_id)
        )
        SELECT request_id, security_id, trading_date, observation_sequence,
          expected_observation_status, observation_available_time,
          dimension_id, q_bp, main_threshold, weak_threshold,
          score_dimension, score_dimension_min, eligible_dimension, validity_status,
          source_reason_codes, dimension_ready,
          CASE WHEN dimension_ready THEN
            score_dimension >= main_threshold-1e-12
            AND score_dimension_min >= weak_threshold-1e-12
          ELSE NULL END AS dimension_active,
          dimension_reason_codes, available_time
        FROM base
        ORDER BY security_id, observation_sequence,
          CASE dimension_id WHEN 'P' THEN 1 WHEN 'C' THEN 2 WHEN 'A' THEN 3
          WHEN 'V' THEN 4 WHEN 'T' THEN 5 END
        """,
        [request_id],
    )


def _populate_joint_states(
    output: duckdb.DuckDBPyConnection, request_id: str, confirmation_k: int
) -> None:
    output.execute(
        """
        CREATE TEMP TABLE joint_base AS
        WITH aggregated AS (
          SELECT request_id, security_id, trading_date, observation_sequence,
            expected_observation_status,
            min(observation_available_time) AS available_time,
            max(CASE validity_status WHEN 'blocked' THEN 4
              WHEN 'diagnostic_required' THEN 3 WHEN 'unknown' THEN 2 ELSE 1 END)
              AS validity_rank,
            bool_and(dimension_ready) AS dimensions_ready,
            bool_and(dimension_active) AS dimensions_active,
            flatten(list(dimension_reason_codes ORDER BY
              CASE dimension_id WHEN 'P' THEN 1 WHEN 'C' THEN 2 WHEN 'A' THEN 3
              WHEN 'V' THEN 4 WHEN 'T' THEN 5 END)) AS dimension_reasons
          FROM daily_dimension_states
          GROUP BY request_id, security_id, trading_date, observation_sequence,
            expected_observation_status
        )
        SELECT *,
          CASE validity_rank WHEN 4 THEN 'blocked' WHEN 3 THEN 'diagnostic_required'
            WHEN 2 THEN 'unknown' ELSE 'valid' END AS joint_validity_status,
          expected_observation_status='present' AND dimensions_ready AS joint_ready,
          list_concat(
            CASE expected_observation_status
              WHEN 'missing' THEN ['expected_observation_missing']
              WHEN 'listing_pause' THEN ['expected_observation_listing_pause']
              ELSE []::VARCHAR[] END,
            dimension_reasons) AS joint_reason_codes,
          CASE WHEN expected_observation_status='present' AND dimensions_ready
            THEN dimensions_active ELSE NULL END AS raw_state
        FROM aggregated
        """
    )
    output.execute(
        """
        CREATE TEMP TABLE joint_runs AS
        SELECT *, sum(CASE WHEN raw_state IS TRUE THEN 0 ELSE 1 END) OVER (
          PARTITION BY security_id ORDER BY observation_sequence
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS run_id
        FROM joint_base
        """
    )
    output.execute(
        """
        CREATE TEMP TABLE joint_streaks AS
        SELECT *,
          CASE WHEN raw_state IS TRUE THEN count(*) FILTER (WHERE raw_state IS TRUE)
            OVER (PARTITION BY security_id, run_id ORDER BY observation_sequence
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)::INTEGER
            WHEN raw_state IS FALSE THEN 0 ELSE NULL END AS raw_streak,
          CASE WHEN raw_state IS TRUE THEN min(trading_date)
            FILTER (WHERE raw_state IS TRUE) OVER (
              PARTITION BY security_id, run_id) ELSE NULL END AS raw_streak_start_date
        FROM joint_runs
        """
    )
    output.execute(
        """
        CREATE TEMP TABLE joint_confirmed AS
        SELECT *, coalesce(raw_streak = ?, false) AS confirmation_event,
          CASE WHEN raw_state IS NULL THEN NULL WHEN raw_state IS FALSE THEN false
            ELSE raw_streak >= ? END AS confirmed_state
        FROM joint_streaks
        """,
        [confirmation_k, confirmation_k],
    )
    output.execute(
        """
        CREATE TEMP TABLE joint_final AS
        SELECT *, CASE WHEN confirmed_state IS TRUE THEN
          sum(CASE WHEN confirmation_event THEN 1 ELSE 0 END) OVER (
            PARTITION BY security_id ORDER BY observation_sequence
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)-1
          ELSE NULL END AS confirmed_interval_ordinal
        FROM joint_confirmed
        """
    )
    output.execute(
        """
        INSERT INTO daily_joint_states
        SELECT request_id, security_id, trading_date, observation_sequence,
          expected_observation_status, available_time, joint_validity_status,
          joint_ready, joint_reason_codes, raw_state, raw_streak,
          raw_streak_start_date, confirmation_event, confirmed_state,
          confirmed_interval_ordinal
        FROM joint_final
        ORDER BY security_id, observation_sequence
        """
    )
    if _count(
        output,
        "SELECT count(*) FROM daily_joint_states WHERE request_id <> ?",
        [request_id],
    ):
        raise DynamicEvaluationError("joint_request_id_mismatch")


def _populate_intervals(
    output: duckdb.DuckDBPyConnection,
    request_id: str,
    selected_dimensions: tuple[str, ...],
    q_json: str,
    confirmation_k: int,
) -> None:
    output.execute(
        """
        INSERT INTO confirmed_intervals
        WITH confirmed AS (
          SELECT request_id, security_id,
            confirmed_interval_ordinal AS interval_ordinal,
            min(trading_date) AS confirmation_date,
            min(observation_sequence) AS confirmation_sequence,
            max(trading_date) AS end_date,
            max(observation_sequence) AS end_sequence,
            count(*) AS confirmed_count
          FROM daily_joint_states WHERE confirmed_state IS TRUE
          GROUP BY request_id, security_id, confirmed_interval_ordinal
        ), starts AS (
          SELECT c.*, d.raw_streak_start_date AS raw_start_date
          FROM confirmed c JOIN daily_joint_states d ON
            c.request_id=d.request_id AND c.security_id=d.security_id
            AND c.confirmation_sequence=d.observation_sequence
        ), terminated AS (
          SELECT s.*, t.trading_date AS termination_date,
            t.observation_sequence AS termination_sequence,
            t.expected_observation_status AS termination_expected_status,
            t.joint_validity_status AS termination_validity,
            t.joint_reason_codes AS termination_codes,
            t.raw_state AS termination_raw_state
          FROM starts s LEFT JOIN daily_joint_states t ON
            s.request_id=t.request_id AND s.security_id=t.security_id
            AND t.observation_sequence=s.end_sequence+1
        )
        SELECT request_id, security_id, interval_ordinal,
          raw_start_date, confirmation_sequence-?+1 AS raw_start_observation_sequence,
          confirmation_date, confirmation_sequence,
          end_date, end_sequence, termination_date, termination_sequence,
          CASE WHEN termination_sequence IS NULL THEN 'input_end_open_right_censored'
            WHEN termination_expected_status='missing'
              THEN 'expected_observation_missing'
            WHEN termination_expected_status='listing_pause'
              THEN 'expected_observation_listing_pause'
            WHEN termination_validity='blocked' THEN 'selected_dimension_blocked'
            WHEN termination_validity='diagnostic_required'
              THEN 'selected_dimension_diagnostic_required'
            WHEN termination_validity='unknown' THEN 'selected_dimension_unknown'
            WHEN list_count(list_filter(termination_codes,
              x -> ends_with(x, ':dimension_not_eligible'))) > 0
              THEN 'selected_dimension_not_eligible'
            WHEN list_count(list_filter(termination_codes,
              x -> ends_with(x, ':score_non_finite'))) > 0
              THEN 'selected_dimension_score_non_finite'
            ELSE 'raw_false' END AS termination_reason,
          coalesce(termination_codes, []::VARCHAR[]) AS termination_reason_codes,
          termination_sequence IS NULL AS right_censored,
          ?::VARCHAR[] AS selected_dimensions, ?::VARCHAR AS q_by_dimension,
          ?::INTEGER AS confirmation_k, confirmed_count
        FROM terminated
        ORDER BY security_id, interval_ordinal
        """,
        [confirmation_k, list(selected_dimensions), q_json, confirmation_k],
    )
    if _count(
        output,
        "SELECT count(*) FROM confirmed_intervals WHERE request_id <> ?",
        [request_id],
    ):
        raise DynamicEvaluationError("interval_request_id_mismatch")


def _drop_temporary_tables(output: duckdb.DuckDBPyConnection) -> None:
    for table in (
        "joint_final",
        "joint_confirmed",
        "joint_streaks",
        "joint_runs",
        "joint_base",
        "request_dimensions",
        "staging_dimensions",
        "staging_spine",
    ):
        output.execute(f"DROP TABLE IF EXISTS {table}")


def _evaluate_dynamic_request_connections(
    *,
    source: duckdb.DuckDBPyConnection,
    output: duckdb.DuckDBPyConnection,
    canonical_request: Mapping[str, object],
    security_ids: Sequence[str] | None = None,
    source_database_path: Path | None = None,
) -> DynamicEvaluationSummary:
    """Evaluate one request using deterministic DuckDB SQL."""

    if source is output:
        raise DynamicEvaluationError("source_output_connection_same")
    _verify_accepted_binding()
    envelope = validate_canonical_request(canonical_request)
    spec = envelope["spec"]
    selected_dimensions = tuple(str(item) for item in spec["selected_dimensions"])
    q_by_dimension = {
        str(key): int(value) for key, value in spec["q_by_dimension"].items()
    }
    confirmation_k = int(spec["confirmation_k"])
    _validate_source_schema(source)
    security_scope, requested_ids, evaluated_ids = _resolve_security_scope(
        source, security_ids
    )
    _validate_source_content(
        source,
        evaluated_ids,
        selected_dimensions,
        str(spec["score_release_id"]),
    )
    _create_output_tables(output)
    if source_database_path is None:
        spine_count = _copy_selected_source(
            source, output, evaluated_ids, selected_dimensions
        )
    else:
        spine_count = _copy_selected_source_bulk(
            source_database_path=source_database_path,
            output=output,
            securities=evaluated_ids,
            dimensions=selected_dimensions,
        )
    q_json = json.dumps(
        q_by_dimension,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    output.execute(
        "INSERT INTO dynamic_request VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            envelope["request_id"],
            envelope["request_hash"],
            envelope["request_schema_version"],
            spec["dynamic_protocol_version"],
            EVALUATOR_VERSION,
            OUTPUT_SCHEMA_VERSION,
            spec["score_release_id"],
            list(selected_dimensions),
            q_json,
            confirmation_k,
            1000,
            1e-12,
        ],
    )
    date_min, date_max = output.execute(
        "SELECT min(trading_date), max(trading_date) FROM staging_spine"
    ).fetchone()
    output.execute(
        "INSERT INTO evaluation_scope VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            envelope["request_id"],
            security_scope,
            list(requested_ids),
            len(evaluated_ids),
            date_min,
            date_max,
            spine_count,
            len(selected_dimensions),
        ],
    )
    _populate_dimensions(
        output,
        str(envelope["request_id"]),
        selected_dimensions,
        q_by_dimension,
    )
    _populate_joint_states(output, str(envelope["request_id"]), confirmation_k)
    _populate_intervals(
        output,
        str(envelope["request_id"]),
        selected_dimensions,
        q_json,
        confirmation_k,
    )
    _drop_temporary_tables(output)
    return validate_dynamic_evaluation_output(output)


def evaluate_dynamic_request_connections(
    *,
    source: duckdb.DuckDBPyConnection,
    output: duckdb.DuckDBPyConnection,
    canonical_request: Mapping[str, object],
    security_ids: Sequence[str] | None = None,
) -> DynamicEvaluationSummary:
    """Evaluate one request through the legacy streaming connection oracle."""

    return _evaluate_dynamic_request_connections(
        source=source,
        output=output,
        canonical_request=canonical_request,
        security_ids=security_ids,
        source_database_path=None,
    )


def evaluate_dynamic_request(
    *,
    score_database: Path,
    canonical_request: Mapping[str, object],
    output_database: Path,
    security_ids: Sequence[str] | None = None,
) -> DynamicEvaluationSummary:
    """Atomically publish one validated dynamic evaluation database."""

    source_path = Path(score_database)
    target = Path(output_database)
    if not source_path.is_file():
        raise DynamicEvaluationError("score_database_missing", str(source_path))
    if source_path.resolve() == target.resolve():
        raise DynamicEvaluationError("source_output_path_same")
    if not target.parent.is_dir():
        raise DynamicEvaluationError("output_parent_missing", str(target.parent))
    if target.exists():
        raise DynamicEvaluationError("output_already_exists", str(target))
    descriptor, name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp.duckdb"
    )
    os.close(descriptor)
    temporary = Path(name)
    temporary.unlink()
    summary: DynamicEvaluationSummary | None = None
    try:
        with (
            duckdb.connect(str(source_path), read_only=True) as source,
            duckdb.connect(str(temporary)) as output,
        ):
            summary = _evaluate_dynamic_request_connections(
                source=source,
                output=output,
                canonical_request=canonical_request,
                security_ids=security_ids,
                source_database_path=source_path.resolve(),
            )
            output.execute("CHECKPOINT")
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            raise DynamicEvaluationError(
                "output_already_exists", str(target)
            ) from error
    finally:
        temporary.unlink(missing_ok=True)
    if summary is None:  # pragma: no cover - defensive invariant
        raise DynamicEvaluationError("evaluation_summary_missing")
    return summary
