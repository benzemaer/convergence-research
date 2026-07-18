"""R2A-T03 development output contract and independent validator."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import duckdb

from src.r2a.r2a_t02_request_identity import validate_canonical_request

EVALUATOR_VERSION = "r2a_t03_dynamic_evaluator.v1"
OUTPUT_SCHEMA_VERSION = "r2a_t03_dynamic_evaluation_output.v1"
OUTPUT_TABLE_ORDER = (
    "dynamic_request",
    "evaluation_scope",
    "daily_dimension_states",
    "daily_joint_states",
    "confirmed_intervals",
)


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    type: str
    nullable: bool = False


@dataclass(frozen=True)
class TableSpec:
    columns: tuple[ColumnSpec, ...]
    primary_key: tuple[str, ...]


@dataclass(frozen=True)
class DynamicEvaluationSummary:
    request_id: str
    request_hash: str
    evaluated_security_count: int
    daily_dimension_state_count: int
    daily_joint_state_count: int
    confirmed_interval_count: int


class DynamicOutputValidationError(ValueError):
    """Fail-closed output validation error."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        message = reason_code if detail is None else f"{reason_code}: {detail}"
        super().__init__(message)


def _c(name: str, type_: str, nullable: bool = False) -> ColumnSpec:
    return ColumnSpec(name, type_, nullable)


TABLE_CONTRACTS: dict[str, TableSpec] = {
    "dynamic_request": TableSpec(
        (
            _c("request_id", "VARCHAR"),
            _c("request_hash", "VARCHAR"),
            _c("request_schema_version", "VARCHAR"),
            _c("dynamic_protocol_version", "VARCHAR"),
            _c("evaluator_version", "VARCHAR"),
            _c("output_schema_version", "VARCHAR"),
            _c("score_release_id", "VARCHAR"),
            _c("selected_dimensions", "VARCHAR[]"),
            _c("q_by_dimension", "VARCHAR"),
            _c("confirmation_k", "INTEGER"),
            _c("weak_delta_bp", "INTEGER"),
            _c("floating_comparison_epsilon", "DOUBLE"),
        ),
        ("request_id",),
    ),
    "evaluation_scope": TableSpec(
        (
            _c("request_id", "VARCHAR"),
            _c("security_scope", "VARCHAR"),
            _c("requested_security_ids", "VARCHAR[]"),
            _c("evaluated_security_count", "BIGINT"),
            _c("date_min", "DATE"),
            _c("date_max", "DATE"),
            _c("spine_row_count", "BIGINT"),
            _c("selected_dimension_count", "INTEGER"),
        ),
        ("request_id",),
    ),
    "daily_dimension_states": TableSpec(
        (
            _c("request_id", "VARCHAR"),
            _c("security_id", "VARCHAR"),
            _c("trading_date", "DATE"),
            _c("observation_sequence", "BIGINT"),
            _c("expected_observation_status", "VARCHAR"),
            _c("observation_available_time", "TIMESTAMP WITH TIME ZONE"),
            _c("dimension_id", "VARCHAR"),
            _c("q_bp", "INTEGER"),
            _c("main_threshold", "DOUBLE"),
            _c("weak_threshold", "DOUBLE"),
            _c("score_dimension", "DOUBLE", True),
            _c("score_dimension_min", "DOUBLE", True),
            _c("eligible_dimension", "BOOLEAN"),
            _c("validity_status", "VARCHAR"),
            _c("source_reason_codes", "VARCHAR[]"),
            _c("dimension_ready", "BOOLEAN"),
            _c("dimension_active", "BOOLEAN", True),
            _c("dimension_reason_codes", "VARCHAR[]"),
            _c("available_time", "TIMESTAMP WITH TIME ZONE"),
        ),
        ("request_id", "security_id", "trading_date", "dimension_id"),
    ),
    "daily_joint_states": TableSpec(
        (
            _c("request_id", "VARCHAR"),
            _c("security_id", "VARCHAR"),
            _c("trading_date", "DATE"),
            _c("observation_sequence", "BIGINT"),
            _c("expected_observation_status", "VARCHAR"),
            _c("available_time", "TIMESTAMP WITH TIME ZONE"),
            _c("joint_validity_status", "VARCHAR"),
            _c("joint_ready", "BOOLEAN"),
            _c("joint_reason_codes", "VARCHAR[]"),
            _c("raw_state", "BOOLEAN", True),
            _c("raw_streak", "INTEGER", True),
            _c("raw_streak_start_date", "DATE", True),
            _c("confirmation_event", "BOOLEAN"),
            _c("confirmed_state", "BOOLEAN", True),
            _c("confirmed_interval_ordinal", "BIGINT", True),
        ),
        ("request_id", "security_id", "trading_date"),
    ),
    "confirmed_intervals": TableSpec(
        (
            _c("request_id", "VARCHAR"),
            _c("security_id", "VARCHAR"),
            _c("interval_ordinal", "BIGINT"),
            _c("raw_start_date", "DATE"),
            _c("raw_start_observation_sequence", "BIGINT"),
            _c("confirmation_date", "DATE"),
            _c("confirmation_observation_sequence", "BIGINT"),
            _c("last_confirmed_end_date", "DATE"),
            _c("last_confirmed_end_observation_sequence", "BIGINT"),
            _c("termination_date", "DATE", True),
            _c("termination_observation_sequence", "BIGINT", True),
            _c("termination_reason", "VARCHAR"),
            _c("termination_reason_codes", "VARCHAR[]"),
            _c("right_censored", "BOOLEAN"),
            _c("selected_dimensions", "VARCHAR[]"),
            _c("q_by_dimension", "VARCHAR"),
            _c("confirmation_k", "INTEGER"),
            _c("confirmed_observation_count", "BIGINT"),
        ),
        ("request_id", "security_id", "interval_ordinal"),
    ),
}


def contract_as_json() -> dict[str, Any]:
    return {
        table: {
            "columns": [
                {"name": item.name, "type": item.type, "nullable": item.nullable}
                for item in spec.columns
            ],
            "primary_key": list(spec.primary_key),
        }
        for table, spec in TABLE_CONTRACTS.items()
    }


def _fail_if_nonzero(
    connection: duckdb.DuckDBPyConnection, query: str, reason_code: str
) -> None:
    count = int(connection.execute(query).fetchone()[0])
    if count:
        raise DynamicOutputValidationError(reason_code, str(count))


def _validate_inventory(connection: duckdb.DuckDBPyConnection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM duckdb_tables() "
            "WHERE database_name = current_database() AND schema_name = 'main'"
        ).fetchall()
    }
    if tables != set(OUTPUT_TABLE_ORDER):
        raise DynamicOutputValidationError(
            "output_table_inventory_mismatch", str(sorted(tables))
        )
    views = int(
        connection.execute(
            "SELECT count(*) FROM duckdb_views() "
            "WHERE database_name = current_database() AND schema_name = 'main' "
            "AND NOT internal"
        ).fetchone()[0]
    )
    if views:
        raise DynamicOutputValidationError("unexpected_output_view", str(views))
    for table, spec in TABLE_CONTRACTS.items():
        rows = connection.execute(f"PRAGMA table_info('{table}')").fetchall()
        actual = [(row[1], row[2], not bool(row[3])) for row in rows]
        expected = [(item.name, item.type, item.nullable) for item in spec.columns]
        if actual != expected:
            raise DynamicOutputValidationError(
                "output_schema_mismatch", f"{table}: {actual!r}"
            )
        keys = ", ".join(f'"{item}"' for item in spec.primary_key)
        _fail_if_nonzero(
            connection,
            f"SELECT count(*) FROM (SELECT {keys}, count(*) AS n FROM {table} "
            f"GROUP BY {keys} HAVING n <> 1)",
            f"{table}_primary_key_duplicate",
        )


def _request_from_output(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    rows = connection.execute("SELECT * FROM dynamic_request").fetchall()
    if len(rows) != 1:
        raise DynamicOutputValidationError("dynamic_request_row_count", str(len(rows)))
    columns = [item[0] for item in connection.description]
    row = dict(zip(columns, rows[0], strict=True))
    if row["evaluator_version"] != EVALUATOR_VERSION:
        raise DynamicOutputValidationError("evaluator_version_mismatch")
    if row["output_schema_version"] != OUTPUT_SCHEMA_VERSION:
        raise DynamicOutputValidationError("output_schema_version_mismatch")
    if row["weak_delta_bp"] != 1000 or not math.isclose(
        row["floating_comparison_epsilon"], 1e-12, rel_tol=0, abs_tol=0
    ):
        raise DynamicOutputValidationError("protocol_constant_mismatch")
    envelope = {
        "request_schema_version": row["request_schema_version"],
        "request_id": row["request_id"],
        "request_hash": row["request_hash"],
        "spec": {
            "request_schema_version": "r2a_t02_dynamic_request_spec.v1",
            "dynamic_protocol_version": row["dynamic_protocol_version"],
            "score_release_id": row["score_release_id"],
            "selected_dimensions": row["selected_dimensions"],
            "q_by_dimension": json.loads(row["q_by_dimension"]),
            "confirmation_k": row["confirmation_k"],
        },
    }
    return validate_canonical_request(envelope)


def validate_dynamic_evaluation_output(
    connection: duckdb.DuckDBPyConnection,
) -> DynamicEvaluationSummary:
    """Validate persisted output independently of evaluator return values."""

    _validate_inventory(connection)
    envelope = _request_from_output(connection)
    request_id = str(envelope["request_id"])
    spec = envelope["spec"]
    k = int(spec["confirmation_k"])
    scope_rows = connection.execute("SELECT * FROM evaluation_scope").fetchall()
    if len(scope_rows) != 1:
        raise DynamicOutputValidationError(
            "evaluation_scope_row_count", str(len(scope_rows))
        )
    scope_columns = [item[0] for item in connection.description]
    scope = dict(zip(scope_columns, scope_rows[0], strict=True))
    if scope["request_id"] != request_id:
        raise DynamicOutputValidationError("scope_request_id_mismatch")
    if scope["security_scope"] not in {"all", "explicit"}:
        raise DynamicOutputValidationError("security_scope_invalid")
    requested_ids = list(scope["requested_security_ids"])
    if scope["security_scope"] == "all" and requested_ids:
        raise DynamicOutputValidationError("all_scope_requested_ids_not_empty")
    if scope["security_scope"] == "explicit" and (
        not requested_ids
        or requested_ids != sorted(requested_ids)
        or len(requested_ids) != len(set(requested_ids))
    ):
        raise DynamicOutputValidationError("explicit_scope_requested_ids_invalid")
    if scope["selected_dimension_count"] != len(spec["selected_dimensions"]):
        raise DynamicOutputValidationError("selected_dimension_count_mismatch")

    dimension_count = int(
        connection.execute("SELECT count(*) FROM daily_dimension_states").fetchone()[0]
    )
    joint_count = int(
        connection.execute("SELECT count(*) FROM daily_joint_states").fetchone()[0]
    )
    interval_count = int(
        connection.execute("SELECT count(*) FROM confirmed_intervals").fetchone()[0]
    )
    if dimension_count != scope["spine_row_count"] * scope["selected_dimension_count"]:
        raise DynamicOutputValidationError("dimension_cardinality_mismatch")
    if joint_count != scope["spine_row_count"]:
        raise DynamicOutputValidationError("joint_cardinality_mismatch")
    actual_security_count = int(
        connection.execute(
            "SELECT count(DISTINCT security_id) FROM daily_joint_states"
        ).fetchone()[0]
    )
    if actual_security_count != scope["evaluated_security_count"]:
        raise DynamicOutputValidationError("security_count_mismatch")
    selected = list(spec["selected_dimensions"])
    actual_dimensions = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT dimension_id FROM daily_dimension_states "
            "ORDER BY dimension_id"
        ).fetchall()
    ]
    if set(actual_dimensions) != set(selected):
        raise DynamicOutputValidationError("unselected_dimension_in_output")
    _fail_if_nonzero(
        connection,
        f"SELECT count(*) FROM (SELECT request_id FROM evaluation_scope UNION ALL "
        f"SELECT request_id FROM daily_dimension_states UNION ALL "
        f"SELECT request_id FROM daily_joint_states UNION ALL "
        f"SELECT request_id FROM confirmed_intervals) "
        f"WHERE request_id <> '{request_id}'",
        "output_request_id_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "WITH expected AS (SELECT j.request_id, j.security_id, j.trading_date, "
        "j.observation_sequence, unnest(r.selected_dimensions) AS dimension_id "
        "FROM daily_joint_states j CROSS JOIN dynamic_request r) "
        "SELECT count(*) FROM expected e FULL OUTER JOIN daily_dimension_states d "
        "USING (request_id, security_id, trading_date, "
        "observation_sequence, dimension_id) "
        "WHERE e.security_id IS NULL OR d.security_id IS NULL",
        "dimension_joint_key_reconciliation_mismatch",
    )

    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM daily_dimension_states WHERE "
        "(dimension_ready AND dimension_active IS NULL) OR "
        "(NOT dimension_ready AND dimension_active IS NOT NULL)",
        "dimension_active_readiness_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM daily_joint_states WHERE "
        "(joint_ready AND raw_state IS NULL) OR "
        "(NOT joint_ready AND raw_state IS NOT NULL)",
        "raw_state_readiness_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "WITH runs AS (SELECT *, sum(CASE WHEN raw_state IS TRUE THEN 0 ELSE 1 END) "
        "OVER (PARTITION BY security_id ORDER BY observation_sequence) AS run_id "
        "FROM daily_joint_states), expected AS (SELECT *, CASE "
        "WHEN raw_state IS TRUE THEN count(*) FILTER (WHERE raw_state IS TRUE) OVER "
        "(PARTITION BY security_id, run_id ORDER BY observation_sequence ROWS BETWEEN "
        "UNBOUNDED PRECEDING AND CURRENT ROW)::INTEGER "
        "WHEN raw_state IS FALSE THEN 0 ELSE NULL END AS expected_streak FROM runs) "
        "SELECT count(*) FROM expected WHERE "
        "raw_streak IS DISTINCT FROM expected_streak",
        "raw_streak_mismatch",
    )
    _fail_if_nonzero(
        connection,
        f"SELECT count(*) FROM daily_joint_states WHERE confirmation_event IS DISTINCT "
        f"FROM coalesce(raw_streak = {k}, false)",
        "confirmation_event_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM daily_joint_states WHERE "
        "confirmed_state IS DISTINCT FROM "
        f"CASE WHEN raw_state IS NULL THEN NULL WHEN raw_state IS FALSE THEN false "
        f"ELSE raw_streak >= {k} END",
        "confirmed_state_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM (SELECT security_id, min(interval_ordinal) AS lo, "
        "max(interval_ordinal) AS hi, count(DISTINCT interval_ordinal) AS n "
        "FROM confirmed_intervals GROUP BY security_id HAVING lo <> 0 OR hi <> n - 1)",
        "interval_ordinal_not_contiguous",
    )
    _fail_if_nonzero(
        connection,
        "WITH daily AS (SELECT request_id, security_id, confirmed_interval_ordinal, "
        "min(trading_date) AS start_date, max(trading_date) AS end_date, "
        "min(observation_sequence) AS start_seq, max(observation_sequence) AS end_seq, "
        "count(*) AS n FROM daily_joint_states WHERE confirmed_state IS TRUE "
        "GROUP BY request_id, security_id, confirmed_interval_ordinal) "
        "SELECT count(*) FROM confirmed_intervals i FULL OUTER JOIN daily d ON "
        "i.request_id=d.request_id AND i.security_id=d.security_id AND "
        "i.interval_ordinal=d.confirmed_interval_ordinal "
        "WHERE d.security_id IS NULL OR "
        "i.security_id IS NULL OR i.confirmation_date<>d.start_date OR "
        "i.last_confirmed_end_date<>d.end_date OR "
        "i.confirmation_observation_sequence<>d.start_seq OR "
        "i.last_confirmed_end_observation_sequence<>d.end_seq OR "
        "i.confirmed_observation_count<>d.n",
        "interval_daily_reconciliation_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM confirmed_intervals WHERE "
        "raw_start_date > confirmation_date OR "
        "confirmation_date > last_confirmed_end_date "
        "OR confirmed_observation_count < 1 OR "
        "(right_censored AND (termination_date IS NOT NULL OR "
        "termination_observation_sequence IS NOT NULL OR "
        "termination_reason <> 'input_end_open_right_censored')) OR "
        "(NOT right_censored AND (termination_date IS NULL OR "
        "termination_observation_sequence IS NULL OR "
        "last_confirmed_end_observation_sequence >= termination_observation_sequence))",
        "interval_boundary_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM confirmed_intervals i JOIN daily_joint_states t ON "
        "i.request_id=t.request_id AND i.security_id=t.security_id AND "
        "i.termination_observation_sequence=t.observation_sequence WHERE "
        "i.right_censored OR i.termination_date<>t.trading_date OR "
        "t.confirmed_state IS TRUE OR i.termination_reason_codes<>t.joint_reason_codes",
        "interval_termination_reconciliation_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM confirmed_intervals i JOIN daily_joint_states t ON "
        "i.request_id=t.request_id AND i.security_id=t.security_id AND "
        "i.termination_observation_sequence=t.observation_sequence WHERE "
        "i.termination_reason IS DISTINCT FROM CASE "
        "WHEN t.expected_observation_status='missing' "
        "THEN 'expected_observation_missing' "
        "WHEN t.expected_observation_status='listing_pause' "
        "THEN 'expected_observation_listing_pause' "
        "WHEN t.joint_validity_status='blocked' THEN 'selected_dimension_blocked' "
        "WHEN t.joint_validity_status='diagnostic_required' "
        "THEN 'selected_dimension_diagnostic_required' "
        "WHEN t.joint_validity_status='unknown' THEN 'selected_dimension_unknown' "
        "WHEN list_count(list_filter(t.joint_reason_codes, "
        "x -> ends_with(x, ':dimension_not_eligible'))) > 0 "
        "THEN 'selected_dimension_not_eligible' "
        "WHEN list_count(list_filter(t.joint_reason_codes, "
        "x -> ends_with(x, ':score_non_finite'))) > 0 "
        "THEN 'selected_dimension_score_non_finite' ELSE 'raw_false' END",
        "interval_termination_reason_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "WITH ordered AS (SELECT *, lag(last_confirmed_end_observation_sequence) OVER "
        "(PARTITION BY security_id ORDER BY interval_ordinal) AS previous_end "
        "FROM confirmed_intervals) SELECT count(*) FROM ordered "
        "WHERE previous_end IS NOT NULL AND "
        "raw_start_observation_sequence <= previous_end",
        "interval_overlap",
    )
    return DynamicEvaluationSummary(
        request_id=request_id,
        request_hash=str(envelope["request_hash"]),
        evaluated_security_count=int(scope["evaluated_security_count"]),
        daily_dimension_state_count=dimension_count,
        daily_joint_state_count=joint_count,
        confirmed_interval_count=interval_count,
    )
