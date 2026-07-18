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
    connection: duckdb.DuckDBPyConnection,
    query: str,
    reason_code: str,
    parameters: tuple[object, ...] = (),
) -> None:
    count = int(connection.execute(query, list(parameters)).fetchone()[0])
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
    q_text = str(row["q_by_dimension"])

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        parsed: dict[str, object] = {}
        for key, value in pairs:
            if key in parsed:
                raise ValueError(key)
            parsed[key] = value
        return parsed

    try:
        parsed_q = json.loads(q_text, object_pairs_hook=reject_duplicate_keys)
        canonical_q = json.dumps(
            parsed_q,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise DynamicOutputValidationError(
            "q_by_dimension_not_canonical", str(error)
        ) from error
    if not isinstance(parsed_q, dict) or q_text != canonical_q:
        raise DynamicOutputValidationError("q_by_dimension_not_canonical")
    envelope = {
        "request_schema_version": row["request_schema_version"],
        "request_id": row["request_id"],
        "request_hash": row["request_hash"],
        "spec": {
            "request_schema_version": "r2a_t02_dynamic_request_spec.v1",
            "dynamic_protocol_version": row["dynamic_protocol_version"],
            "score_release_id": row["score_release_id"],
            "selected_dimensions": row["selected_dimensions"],
            "q_by_dimension": parsed_q,
            "confirmation_k": row["confirmation_k"],
        },
    }
    return validate_canonical_request(envelope)


def _validate_scope(
    connection: duckdb.DuckDBPyConnection,
    request_id: str,
    selected_dimension_count: int,
) -> dict[str, Any]:
    rows = connection.execute("SELECT * FROM evaluation_scope").fetchall()
    if len(rows) != 1:
        raise DynamicOutputValidationError("evaluation_scope_row_count", str(len(rows)))
    columns = [item[0] for item in connection.description]
    scope = dict(zip(columns, rows[0], strict=True))
    if scope["request_id"] != request_id:
        raise DynamicOutputValidationError("scope_request_id_mismatch")
    if scope["security_scope"] not in {"all", "explicit"}:
        raise DynamicOutputValidationError("security_scope_invalid")
    actual_ids = [
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT security_id FROM daily_joint_states ORDER BY security_id"
        ).fetchall()
    ]
    requested_ids = list(scope["requested_security_ids"])
    if scope["security_scope"] == "all":
        if requested_ids:
            raise DynamicOutputValidationError("scope_security_set_mismatch")
    elif (
        not requested_ids
        or requested_ids != sorted(requested_ids)
        or len(requested_ids) != len(set(requested_ids))
        or requested_ids != actual_ids
    ):
        raise DynamicOutputValidationError("scope_security_set_mismatch")
    actual_count, date_min, date_max, row_count = connection.execute(
        "SELECT count(DISTINCT security_id), min(trading_date), max(trading_date), "
        "count(*) FROM daily_joint_states"
    ).fetchone()
    if int(actual_count) != int(scope["evaluated_security_count"]):
        raise DynamicOutputValidationError("scope_security_set_mismatch")
    if date_min != scope["date_min"] or date_max != scope["date_max"]:
        raise DynamicOutputValidationError("scope_date_coverage_mismatch")
    if int(row_count) != int(scope["spine_row_count"]):
        raise DynamicOutputValidationError("joint_cardinality_mismatch")
    if int(scope["selected_dimension_count"]) != selected_dimension_count:
        raise DynamicOutputValidationError("selected_dimension_count_mismatch")
    _fail_if_nonzero(
        connection,
        "WITH domains AS (SELECT security_id, min(observation_sequence) lo, "
        "max(observation_sequence) hi, count(*) n, "
        "count(DISTINCT observation_sequence) dn FROM daily_joint_states "
        "GROUP BY security_id) SELECT count(*) FROM domains "
        "WHERE lo<>0 OR hi<>n-1 OR dn<>n",
        "joint_sequence_domain_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "WITH ordered AS (SELECT security_id, trading_date, observation_sequence, "
        "lag(trading_date) OVER (PARTITION BY security_id "
        "ORDER BY observation_sequence) previous_date FROM daily_joint_states) "
        "SELECT count(*) FROM ordered WHERE previous_date IS NOT NULL "
        "AND trading_date<=previous_date",
        "joint_sequence_domain_mismatch",
    )
    return scope


def _dimension_reason_expression() -> str:
    upstream = (
        "list_transform(coalesce(d.source_reason_codes, []::VARCHAR[]), "
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
        "[d.dimension_id || ':dimension_not_eligible'] "
        "ELSE []::VARCHAR[] END, "
        "CASE WHEN d.score_dimension IS NULL OR d.score_dimension_min IS NULL OR "
        "NOT isfinite(d.score_dimension) OR NOT isfinite(d.score_dimension_min) "
        "THEN [d.dimension_id || ':score_non_finite'] "
        "ELSE []::VARCHAR[] END)"
    )
    return f"list_sort(list_distinct(list_concat({upstream}, {derived})))"


def _validate_dimension_derivation(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM daily_dimension_states WHERE "
        "(dimension_ready AND dimension_active IS NULL) OR "
        "(NOT dimension_ready AND dimension_active IS NOT NULL)",
        "dimension_active_readiness_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM daily_dimension_states d "
        "LEFT JOIN _validator_request_dimensions r USING (dimension_id) "
        "WHERE r.dimension_id IS NULL OR d.q_bp<>r.q_bp",
        "dimension_q_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM daily_dimension_states d JOIN "
        "_validator_request_dimensions r USING (dimension_id) WHERE "
        "NOT isfinite(d.main_threshold) OR NOT isfinite(d.weak_threshold) OR "
        "abs(d.main_threshold-(1.0-r.q_bp/10000.0))>1e-15 OR "
        "abs(d.weak_threshold-(1.0-r.q_bp/10000.0-0.10))>1e-15",
        "dimension_threshold_mismatch",
    )
    ready = (
        "d.expected_observation_status='present' "
        "AND d.eligible_dimension IS TRUE AND d.validity_status='valid' "
        "AND d.score_dimension IS NOT NULL AND isfinite(d.score_dimension) "
        "AND d.score_dimension_min IS NOT NULL "
        "AND isfinite(d.score_dimension_min)"
    )
    _fail_if_nonzero(
        connection,
        f"SELECT count(*) FROM daily_dimension_states d WHERE "
        f"d.dimension_ready IS DISTINCT FROM ({ready})",
        "dimension_ready_semantics_mismatch",
    )
    _fail_if_nonzero(
        connection,
        f"SELECT count(*) FROM daily_dimension_states d WHERE "
        "d.dimension_active IS DISTINCT FROM CASE WHEN "
        f"{ready} THEN d.score_dimension>=d.main_threshold-1e-12 "
        "AND d.score_dimension_min>=d.weak_threshold-1e-12 ELSE NULL END",
        "dimension_active_semantics_mismatch",
    )
    reasons = _dimension_reason_expression()
    _fail_if_nonzero(
        connection,
        f"SELECT count(*) FROM daily_dimension_states d WHERE "
        f"d.dimension_reason_codes IS DISTINCT FROM {reasons}",
        "dimension_reason_codes_mismatch",
    )


def _create_expected_joint(connection: duckdb.DuckDBPyConnection) -> None:
    _fail_if_nonzero(
        connection,
        "WITH groups AS (SELECT d.request_id, d.security_id, d.trading_date, "
        "d.observation_sequence, count(*) n, count(DISTINCT d.dimension_id) dn, "
        "count(DISTINCT d.expected_observation_status) statuses, "
        "count(DISTINCT d.observation_available_time) spine_times, "
        "count(DISTINCT d.available_time) available_times, "
        "bool_and(d.observation_available_time=d.available_time) aligned "
        "FROM daily_dimension_states d GROUP BY d.request_id, d.security_id, "
        "d.trading_date, d.observation_sequence) SELECT count(*) FROM groups g "
        "CROSS JOIN dynamic_request r WHERE g.n<>len(r.selected_dimensions) OR "
        "g.dn<>len(r.selected_dimensions) OR statuses<>1 OR spine_times<>1 OR "
        "available_times<>1 OR NOT aligned",
        "joint_dimension_alignment_mismatch",
    )
    connection.execute(
        "CREATE TEMP TABLE _validator_expected_joint AS WITH aggregated AS ("
        "SELECT d.request_id, d.security_id, d.trading_date, "
        "d.observation_sequence, min(d.expected_observation_status) "
        "AS expected_observation_status, min(d.observation_available_time) "
        "AS available_time, max(CASE d.validity_status "
        "WHEN 'blocked' THEN 4 WHEN 'diagnostic_required' THEN 3 "
        "WHEN 'unknown' THEN 2 ELSE 1 END) validity_rank, "
        "bool_and(d.dimension_ready) dimensions_ready, "
        "bool_and(d.dimension_active) dimensions_active, "
        "flatten(list(d.dimension_reason_codes ORDER BY r.dimension_rank)) "
        "AS dimension_reasons FROM daily_dimension_states d JOIN "
        "_validator_request_dimensions r USING (dimension_id) "
        "GROUP BY d.request_id, d.security_id, d.trading_date, "
        "d.observation_sequence) SELECT *, CASE validity_rank "
        "WHEN 4 THEN 'blocked' WHEN 3 THEN 'diagnostic_required' "
        "WHEN 2 THEN 'unknown' ELSE 'valid' END AS joint_validity_status, "
        "expected_observation_status='present' AND dimensions_ready "
        "AS joint_ready, list_concat(CASE expected_observation_status "
        "WHEN 'missing' THEN ['expected_observation_missing'] "
        "WHEN 'listing_pause' THEN ['expected_observation_listing_pause'] "
        "ELSE []::VARCHAR[] END, dimension_reasons) AS joint_reason_codes, "
        "CASE WHEN expected_observation_status='present' AND dimensions_ready "
        "THEN dimensions_active ELSE NULL END AS raw_state FROM aggregated"
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM _validator_expected_joint e FULL OUTER JOIN "
        "daily_joint_states j USING (request_id, security_id, trading_date, "
        "observation_sequence) WHERE e.security_id IS NULL OR j.security_id IS NULL",
        "dimension_joint_key_reconciliation_mismatch",
    )
    comparisons = (
        ("expected_observation_status", "joint_dimension_alignment_mismatch"),
        ("available_time", "joint_dimension_alignment_mismatch"),
        ("joint_validity_status", "joint_validity_mismatch"),
        ("joint_ready", "joint_ready_semantics_mismatch"),
        ("joint_reason_codes", "joint_reason_codes_mismatch"),
        ("raw_state", "raw_state_semantics_mismatch"),
    )
    for field, reason in comparisons:
        _fail_if_nonzero(
            connection,
            "SELECT count(*) FROM _validator_expected_joint e JOIN "
            "daily_joint_states j USING (request_id, security_id, trading_date, "
            f"observation_sequence) WHERE j.{field} IS DISTINCT FROM e.{field}",
            reason,
        )


def _create_expected_daily(
    connection: duckdb.DuckDBPyConnection, confirmation_k: int
) -> None:
    connection.execute(
        "CREATE TEMP TABLE _validator_expected_daily AS WITH runs AS ("
        "SELECT *, sum(CASE WHEN raw_state IS TRUE THEN 0 ELSE 1 END) OVER ("
        "PARTITION BY security_id ORDER BY observation_sequence ROWS BETWEEN "
        "UNBOUNDED PRECEDING AND CURRENT ROW) run_id "
        "FROM _validator_expected_joint), streaks AS (SELECT *, CASE "
        "WHEN raw_state IS TRUE THEN count(*) FILTER (WHERE raw_state IS TRUE) "
        "OVER (PARTITION BY security_id, run_id ORDER BY observation_sequence "
        "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)::INTEGER "
        "WHEN raw_state IS FALSE THEN 0 ELSE NULL END raw_streak, CASE "
        "WHEN raw_state IS TRUE THEN min(trading_date) FILTER "
        "(WHERE raw_state IS TRUE) OVER (PARTITION BY security_id, run_id) "
        "ELSE NULL END raw_streak_start_date FROM runs), confirmed AS ("
        "SELECT *, coalesce(raw_streak=?, false) confirmation_event, CASE "
        "WHEN raw_state IS NULL THEN NULL WHEN raw_state IS FALSE THEN false "
        "ELSE raw_streak>=? END confirmed_state FROM streaks) SELECT *, CASE "
        "WHEN confirmed_state IS TRUE THEN sum(CASE WHEN confirmation_event "
        "THEN 1 ELSE 0 END) OVER (PARTITION BY security_id "
        "ORDER BY observation_sequence ROWS BETWEEN UNBOUNDED PRECEDING "
        "AND CURRENT ROW)-1 ELSE NULL END::BIGINT confirmed_interval_ordinal "
        "FROM confirmed",
        [confirmation_k, confirmation_k],
    )
    comparisons = (
        ("raw_streak", "raw_streak_mismatch"),
        ("raw_streak_start_date", "raw_streak_start_mismatch"),
        ("confirmation_event", "confirmation_event_mismatch"),
        ("confirmed_state", "confirmed_state_mismatch"),
        ("confirmed_interval_ordinal", "confirmed_interval_ordinal_mismatch"),
    )
    for field, reason in comparisons:
        _fail_if_nonzero(
            connection,
            "SELECT count(*) FROM _validator_expected_daily e JOIN "
            "daily_joint_states j USING (request_id, security_id, trading_date, "
            f"observation_sequence) WHERE j.{field} IS DISTINCT FROM e.{field}",
            reason,
        )


def _termination_reason_sql(alias: str) -> str:
    return (
        f"CASE WHEN {alias}.termination_sequence IS NULL "
        "THEN 'input_end_open_right_censored' "
        f"WHEN {alias}.termination_expected_status='missing' "
        "THEN 'expected_observation_missing' "
        f"WHEN {alias}.termination_expected_status='listing_pause' "
        "THEN 'expected_observation_listing_pause' "
        f"WHEN {alias}.termination_validity='blocked' "
        "THEN 'selected_dimension_blocked' "
        f"WHEN {alias}.termination_validity='diagnostic_required' "
        "THEN 'selected_dimension_diagnostic_required' "
        f"WHEN {alias}.termination_validity='unknown' "
        "THEN 'selected_dimension_unknown' "
        f"WHEN list_count(list_filter({alias}.termination_codes, "
        "x -> ends_with(x, ':dimension_not_eligible'))) > 0 "
        "THEN 'selected_dimension_not_eligible' "
        f"WHEN list_count(list_filter({alias}.termination_codes, "
        "x -> ends_with(x, ':score_non_finite'))) > 0 "
        "THEN 'selected_dimension_score_non_finite' ELSE 'raw_false' END"
    )


def _validate_intervals(connection: duckdb.DuckDBPyConnection) -> None:
    reason = _termination_reason_sql("terminated")
    connection.execute(
        "CREATE TEMP TABLE _validator_expected_intervals AS WITH confirmed AS ("
        "SELECT request_id, security_id, confirmed_interval_ordinal interval_ordinal, "
        "min(trading_date) confirmation_date, min(observation_sequence) "
        "confirmation_sequence, max(trading_date) end_date, "
        "max(observation_sequence) end_sequence, count(*) confirmed_count "
        "FROM _validator_expected_daily WHERE confirmed_state IS TRUE "
        "GROUP BY request_id, security_id, confirmed_interval_ordinal), starts AS ("
        "SELECT c.*, d.raw_streak_start_date raw_start_date, "
        "d.observation_sequence-d.raw_streak+1 raw_start_sequence "
        "FROM confirmed c JOIN _validator_expected_daily d ON "
        "c.request_id=d.request_id AND c.security_id=d.security_id AND "
        "c.confirmation_sequence=d.observation_sequence), terminated AS ("
        "SELECT s.*, t.trading_date termination_date, "
        "t.observation_sequence termination_sequence, "
        "t.expected_observation_status termination_expected_status, "
        "t.joint_validity_status termination_validity, "
        "t.joint_reason_codes termination_codes FROM starts s LEFT JOIN "
        "_validator_expected_daily t ON s.request_id=t.request_id AND "
        "s.security_id=t.security_id AND t.observation_sequence=s.end_sequence+1) "
        "SELECT terminated.request_id, terminated.security_id, interval_ordinal, "
        "raw_start_date, raw_start_sequence, confirmation_date, "
        "confirmation_sequence, end_date, end_sequence, termination_date, "
        f"termination_sequence, {reason} termination_reason, "
        "coalesce(termination_codes, []::VARCHAR[]) termination_reason_codes, "
        "termination_sequence IS NULL right_censored, r.selected_dimensions, "
        "r.q_by_dimension, r.confirmation_k, confirmed_count "
        "FROM terminated CROSS JOIN dynamic_request r"
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM _validator_expected_intervals e FULL OUTER JOIN "
        "confirmed_intervals i USING (request_id, security_id, interval_ordinal) "
        "WHERE e.security_id IS NULL OR i.security_id IS NULL",
        "interval_daily_reconciliation_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM _validator_expected_intervals e JOIN "
        "confirmed_intervals i USING (request_id, security_id, interval_ordinal) "
        "WHERE i.raw_start_date IS DISTINCT FROM e.raw_start_date OR "
        "i.raw_start_observation_sequence IS DISTINCT FROM e.raw_start_sequence",
        "interval_raw_start_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM _validator_expected_intervals e JOIN "
        "confirmed_intervals i USING (request_id, security_id, interval_ordinal) "
        "WHERE i.selected_dimensions IS DISTINCT FROM e.selected_dimensions OR "
        "i.q_by_dimension IS DISTINCT FROM e.q_by_dimension OR "
        "i.confirmation_k IS DISTINCT FROM e.confirmation_k",
        "interval_request_parameters_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM confirmed_intervals i JOIN "
        "(SELECT security_id, max(observation_sequence) max_sequence "
        "FROM daily_joint_states GROUP BY security_id) m USING (security_id) "
        "WHERE i.right_censored AND "
        "i.last_confirmed_end_observation_sequence<>m.max_sequence",
        "right_censored_not_at_input_end",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM confirmed_intervals WHERE "
        "raw_start_date>confirmation_date OR "
        "confirmation_date>last_confirmed_end_date OR "
        "confirmed_observation_count<1 OR (right_censored AND "
        "(termination_date IS NOT NULL OR "
        "termination_observation_sequence IS NOT NULL OR "
        "termination_reason<>'input_end_open_right_censored')) OR "
        "(NOT right_censored AND (termination_date IS NULL OR "
        "termination_observation_sequence IS NULL OR "
        "last_confirmed_end_observation_sequence>="
        "termination_observation_sequence))",
        "interval_boundary_mismatch",
    )
    fields = (
        ("confirmation_date", "confirmation_date"),
        ("confirmation_observation_sequence", "confirmation_sequence"),
        ("last_confirmed_end_date", "end_date"),
        ("last_confirmed_end_observation_sequence", "end_sequence"),
        ("termination_date", "termination_date"),
        ("termination_observation_sequence", "termination_sequence"),
        ("termination_reason", "termination_reason"),
        ("termination_reason_codes", "termination_reason_codes"),
        ("right_censored", "right_censored"),
        ("confirmed_observation_count", "confirmed_count"),
    )
    predicate = " OR ".join(
        f"i.{actual} IS DISTINCT FROM e.{expected}" for actual, expected in fields
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM _validator_expected_intervals e JOIN "
        "confirmed_intervals i USING (request_id, security_id, interval_ordinal) "
        f"WHERE {predicate}",
        "interval_recalculation_mismatch",
    )
    _fail_if_nonzero(
        connection,
        "SELECT count(*) FROM confirmed_intervals WHERE NOT right_censored AND "
        "termination_observation_sequence<>"
        "last_confirmed_end_observation_sequence+1",
        "interval_termination_reconciliation_mismatch",
    )


def validate_dynamic_evaluation_output(
    connection: duckdb.DuckDBPyConnection,
) -> DynamicEvaluationSummary:
    """Validate persisted output independently of evaluator return values."""

    _validate_inventory(connection)
    envelope = _request_from_output(connection)
    request_id = str(envelope["request_id"])
    spec = envelope["spec"]
    selected = list(spec["selected_dimensions"])
    q_by_dimension = spec["q_by_dimension"]
    temporary_tables = (
        "_validator_expected_intervals",
        "_validator_expected_daily",
        "_validator_expected_joint",
        "_validator_request_dimensions",
    )
    try:
        connection.execute(
            "CREATE TEMP TABLE _validator_request_dimensions ("
            "dimension_id VARCHAR, q_bp INTEGER, dimension_rank INTEGER)"
        )
        connection.executemany(
            "INSERT INTO _validator_request_dimensions VALUES (?, ?, ?)",
            [
                (dimension, int(q_by_dimension[dimension]), rank)
                for rank, dimension in enumerate(selected)
            ],
        )
        scope = _validate_scope(connection, request_id, len(selected))
        dimension_count = int(
            connection.execute(
                "SELECT count(*) FROM daily_dimension_states"
            ).fetchone()[0]
        )
        joint_count = int(
            connection.execute("SELECT count(*) FROM daily_joint_states").fetchone()[0]
        )
        interval_count = int(
            connection.execute("SELECT count(*) FROM confirmed_intervals").fetchone()[0]
        )
        if dimension_count != joint_count * len(selected):
            raise DynamicOutputValidationError("dimension_cardinality_mismatch")
        _fail_if_nonzero(
            connection,
            "SELECT count(*) FROM (SELECT request_id FROM evaluation_scope UNION ALL "
            "SELECT request_id FROM daily_dimension_states UNION ALL "
            "SELECT request_id FROM daily_joint_states UNION ALL "
            "SELECT request_id FROM confirmed_intervals) WHERE request_id<>?",
            "output_request_id_mismatch",
            (request_id,),
        )
        _validate_dimension_derivation(connection)
        _create_expected_joint(connection)
        _create_expected_daily(connection, int(spec["confirmation_k"]))
        _validate_intervals(connection)
        return DynamicEvaluationSummary(
            request_id=request_id,
            request_hash=str(envelope["request_hash"]),
            evaluated_security_count=int(scope["evaluated_security_count"]),
            daily_dimension_state_count=dimension_count,
            daily_joint_state_count=joint_count,
            confirmed_interval_count=interval_count,
        )
    finally:
        for table in temporary_tables:
            connection.execute(f"DROP TABLE IF EXISTS {table}")
