"""Synthetic-input implementation candidate for R2A-T05.

The module consumes the accepted T03 daily-state/interval contract plus the
accepted Score component rows.  It deliberately does not implement a formal
run entry point: the public CLI accepts only an explicit synthetic fixture
manifest.  The calculations here are request-scoped and never use a calendar
day difference for continuity.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r2a/r2a_t05_ca_exit_decomposition.v1.json"
CONFIG_SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t05_ca_exit_decomposition.schema.json"

TASK_ID = "R2A-T05"
IMPLEMENTATION_VERSION = "r2a_t05_ca_exit_decomposition.v1"
RESULT_PACKAGE_SCHEMA_VERSION = "r2a_t05_result_package.v1"
REQUEST_SPEC_SCHEMA_VERSION = "r2a_t02_dynamic_request.v1"
OUTPUT_SCHEMA_VERSION = "r2a_t03_dynamic_evaluation_output.v1"
REQUEST_ORDER = ("CA_q10_k5", "CA_q15_k5", "CA_q20_k5", "CA_q25_k5")
DIMENSIONS = ("C", "A")
PRIMARY_TERMINATION_CATEGORIES = (
    "raw_false",
    "quality_or_availability_termination",
    "input_end_open_right_censored",
)
QUALITY_TERMINATION_REASONS = (
    "expected_observation_missing",
    "expected_observation_listing_pause",
    "selected_dimension_blocked",
    "selected_dimension_diagnostic_required",
    "selected_dimension_unknown",
    "selected_dimension_not_eligible",
    "selected_dimension_score_non_finite",
)
RAW_FALSE_SUBCLASSES = ("A_ONLY_FAIL", "C_ONLY_FAIL", "CA_BOTH_FAIL")
IDENTITY_CLASSES = (
    "Q10_CORE",
    "Q15_NOT_Q10_CORE",
    "Q20_NOT_Q15_ANCHOR",
    "Q25_NOT_Q20_SHELL",
)
EPSILON = 1e-12
WEAK_DELTA = 0.10
RAW_REENTRY_WINDOW = 5
CONFIRMED_REENTRY_WINDOW = 10
RAW_REENTRY_THRESHOLDS = (1, 3, 5)
CONFIRMED_REENTRY_THRESHOLDS = (5, 10)

T03_OUTPUT_TABLES = {
    "dynamic_request",
    "evaluation_scope",
    "daily_dimension_states",
    "daily_joint_states",
    "confirmed_intervals",
}
T03_OUTPUT_COLUMNS = {
    "dynamic_request": {
        "request_id",
        "request_hash",
        "request_schema_version",
        "dynamic_protocol_version",
        "evaluator_version",
        "output_schema_version",
        "score_release_id",
        "selected_dimensions",
        "q_by_dimension",
        "confirmation_k",
        "weak_delta_bp",
        "floating_comparison_epsilon",
    },
    "evaluation_scope": {
        "request_id",
        "security_scope",
        "requested_security_ids",
        "evaluated_security_count",
        "date_min",
        "date_max",
        "spine_row_count",
        "selected_dimension_count",
    },
    "daily_dimension_states": {
        "request_id",
        "security_id",
        "trading_date",
        "observation_sequence",
        "expected_observation_status",
        "observation_available_time",
        "dimension_id",
        "q_bp",
        "main_threshold",
        "weak_threshold",
        "score_dimension",
        "score_dimension_min",
        "eligible_dimension",
        "validity_status",
        "source_reason_codes",
        "dimension_ready",
        "dimension_active",
        "dimension_reason_codes",
        "available_time",
    },
    "daily_joint_states": {
        "request_id",
        "security_id",
        "trading_date",
        "observation_sequence",
        "expected_observation_status",
        "available_time",
        "joint_validity_status",
        "joint_ready",
        "joint_reason_codes",
        "raw_state",
        "raw_streak",
        "raw_streak_start_date",
        "confirmation_event",
        "confirmed_state",
        "confirmed_interval_ordinal",
    },
    "confirmed_intervals": {
        "request_id",
        "security_id",
        "interval_ordinal",
        "raw_start_date",
        "raw_start_observation_sequence",
        "confirmation_date",
        "confirmation_observation_sequence",
        "last_confirmed_end_date",
        "last_confirmed_end_observation_sequence",
        "termination_date",
        "termination_observation_sequence",
        "termination_reason",
        "termination_reason_codes",
        "right_censored",
        "selected_dimensions",
        "q_by_dimension",
        "confirmation_k",
        "confirmed_observation_count",
    },
}

SCORE_ALLOWED_TABLES = {
    "securities",
    "trading_sessions",
    "security_observation_spine",
    "dimension_definitions",
    "dimension_components",
    "daily_component_scores",
    "daily_dimension_scores",
}
SCORE_ALLOWED_COLUMNS = {
    "securities": {
        "score_release_id",
        "security_id",
        "universe_id",
        "first_expected_date",
        "last_expected_date",
        "expected_observation_count",
    },
    "trading_sessions": {
        "score_release_id",
        "trading_date",
        "session_sequence",
        "expected_security_count",
        "present_security_count",
        "available_time",
    },
    "security_observation_spine": {
        "score_release_id",
        "security_id",
        "trading_date",
        "observation_sequence",
        "expected_observation_status",
        "source_contract",
        "source_ref",
        "observation_available_time",
    },
    "dimension_definitions": {
        "score_release_id",
        "dimension_id",
        "canonical_order",
        "dimension_name",
        "component_count",
        "aggregation_method",
        "score_direction",
        "percentile_window_W",
        "definition_version",
    },
    "dimension_components": {
        "score_release_id",
        "dimension_id",
        "component_id",
        "component_order",
        "weight",
        "raw_metric_name",
        "raw_value_direction",
        "score_formula",
        "tie_method",
        "current_value_in_reference_set",
        "source_role",
        "definition_version",
    },
    "daily_component_scores": {
        "score_release_id",
        "security_id",
        "trading_date",
        "observation_sequence",
        "dimension_id",
        "component_id",
        "percentile_window_W",
        "raw_value",
        "percentile",
        "score",
        "eligible",
        "validity_status",
        "reason_codes",
        "reference_observation_count",
        "reference_window_start",
        "reference_window_end",
        "current_value_in_reference_set",
        "tie_method",
        "score_engine_version",
        "source_role",
        "source_run_id",
        "available_time",
    },
    "daily_dimension_scores": {
        "score_release_id",
        "security_id",
        "trading_date",
        "observation_sequence",
        "dimension_id",
        "percentile_window_W",
        "score_dimension",
        "score_dimension_min",
        "eligible_dimension",
        "validity_status",
        "reason_codes",
        "component_count",
        "score_engine_version",
        "source_role",
        "available_time",
    },
}


class T05Error(ValueError):
    """Fail-closed T05 error with a stable reason code."""

    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        message = reason_code if detail is None else f"{reason_code}: {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class RequestIdentity:
    logical_request_name: str
    request_id: str
    request_hash: str
    selected_dimensions: tuple[str, ...]
    q_by_dimension: dict[str, int]
    confirmation_k: int
    selection_status: str


@dataclass
class RequestSnapshot:
    identity: RequestIdentity
    joint_rows: list[dict[str, Any]]
    dimension_rows: dict[tuple[str, int, str], dict[str, Any]]
    intervals: list[dict[str, Any]]
    interval_days: dict[tuple[str, int], set[tuple[str, int]]]
    raw_keys: set[tuple[str, int]]
    confirmed_keys: set[tuple[str, int]]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise T05Error("json_input_invalid", str(path)) from error
    if not isinstance(value, dict):
        raise T05Error("json_object_required", str(path))
    return value


def load_t05_config(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the versioned T05 contract."""

    config_path = path or CONFIG_PATH
    config = _json(config_path)
    schema = _json(CONFIG_SCHEMA_PATH)
    errors = sorted(Draft202012Validator(schema).iter_errors(config), key=str)
    if errors:
        raise T05Error("t05_config_schema_invalid", errors[0].message)
    return config


def _config_request(config: Mapping[str, Any], name: str) -> RequestIdentity:
    matches = [
        item for item in config["requests"] if item["logical_request_name"] == name
    ]
    if len(matches) != 1:
        raise T05Error("request_identity_config_missing", name)
    item = matches[0]
    return RequestIdentity(
        logical_request_name=name,
        request_id=str(item["request_id"]),
        request_hash=str(item["request_hash"]),
        selected_dimensions=tuple(item["selected_dimensions"]),
        q_by_dimension={
            key: int(value) for key, value in item["q_by_dimension"].items()
        },
        confirmation_k=int(item["confirmation_k"]),
        selection_status=str(item["selection_status"]),
    )


def accepted_request_identities(
    config: Mapping[str, Any] | None = None,
) -> dict[str, RequestIdentity]:
    """Read the accepted T04 handoff and cross-check the task config."""

    loaded = dict(config or load_t05_config())
    binding = loaded["accepted_bindings"]["t04_handoff"]
    handoff_path = ROOT / binding["relative_path"]
    if not handoff_path.is_file():
        raise T05Error("accepted_t04_handoff_missing", str(handoff_path))
    if _sha256(handoff_path) != binding["sha256"]:
        raise T05Error("accepted_t04_handoff_hash_mismatch")
    handoff = _json(handoff_path)
    if (
        handoff.get("status") != "completed_accepted"
        or handoff.get("scope_id") != binding["scope_id"]
        or handoff.get("panel_id") != binding["panel_id"]
        or handoff.get("accepted_run_id") != binding["accepted_run_id"]
    ):
        raise T05Error("accepted_t04_handoff_identity_mismatch")
    handoff_items = {
        str(item["logical_request_name"]): item for item in handoff["requests"]
    }
    if set(handoff_items) != set(REQUEST_ORDER):
        raise T05Error("accepted_t04_request_set_mismatch")
    identities: dict[str, RequestIdentity] = {}
    for name in REQUEST_ORDER:
        identity = _config_request(loaded, name)
        item = handoff_items[name]
        handoff_identity = RequestIdentity(
            logical_request_name=name,
            request_id=str(item["request_id"]),
            request_hash=str(item["request_hash"]),
            selected_dimensions=tuple(item["selected_dimensions"]),
            q_by_dimension={
                key: int(value) for key, value in item["q_by_dimension"].items()
            },
            confirmation_k=int(item["confirmation_k"]),
            selection_status=str(item["selection_status"]),
        )
        if identity != handoff_identity:
            raise T05Error("accepted_t04_request_identity_mismatch", name)
        identities[name] = identity
    if (
        loaded["q_selection_status"] != "not_selected"
        or loaded["canonical_dynamic_request_selected"]
    ):
        raise T05Error("q_selection_boundary_mismatch")
    if identities["CA_q20_k5"].q_by_dimension != {"C": 2000, "A": 2000}:
        raise T05Error("research_anchor_q_mismatch")
    return identities


@contextmanager
def _connection(
    source: duckdb.DuckDBPyConnection | Path | str,
) -> Iterator[duckdb.DuckDBPyConnection]:
    if isinstance(source, duckdb.DuckDBPyConnection):
        yield source
        return
    path = Path(source)
    if not path.is_file():
        raise T05Error("input_database_missing", str(path))
    connection = duckdb.connect(str(path), read_only=True)
    try:
        yield connection
    finally:
        connection.close()


def _tables(connection: duckdb.DuckDBPyConnection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' AND table_type='BASE TABLE'"
        ).fetchall()
    }


def _columns(connection: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {str(row[1]) for row in rows}


def _validate_request_schema_connection(connection: duckdb.DuckDBPyConnection) -> None:
    request_tables = _tables(connection)
    if request_tables != T03_OUTPUT_TABLES:
        raise T05Error("evaluator_table_inventory_mismatch", sorted(request_tables))
    for table, expected in T03_OUTPUT_COLUMNS.items():
        actual = _columns(connection, table)
        if actual != expected:
            raise T05Error(
                "evaluator_schema_mismatch", f"{table}: {sorted(actual - expected)}"
            )


def validate_input_schema(
    request_source: duckdb.DuckDBPyConnection | Path | str,
    score_source: duckdb.DuckDBPyConnection | Path | str,
) -> dict[str, Any]:
    """Validate the two read-only input contracts and reject unknown fields."""

    with _connection(request_source) as request, _connection(score_source) as score:
        _validate_request_schema_connection(request)
        request_tables = _tables(request)
        score_tables = _tables(score)
        unknown_tables = score_tables - SCORE_ALLOWED_TABLES
        if unknown_tables:
            raise T05Error(
                "score_table_inventory_contains_unapproved_table",
                sorted(unknown_tables),
            )
        required_tables = {
            "security_observation_spine",
            "daily_component_scores",
            "daily_dimension_scores",
        }
        if not required_tables <= score_tables:
            raise T05Error(
                "score_required_table_missing", sorted(required_tables - score_tables)
            )
        for table, allowed in SCORE_ALLOWED_COLUMNS.items():
            if table not in score_tables:
                continue
            actual = _columns(score, table)
            if not actual <= allowed:
                raise T05Error(
                    "score_schema_contains_unapproved_field",
                    f"{table}: {sorted(actual - allowed)}",
                )
        return {
            "request_tables": sorted(request_tables),
            "score_tables": sorted(score_tables),
            "unknown_table_count": len(unknown_tables),
            "unapproved_field_count": 0,
        }


def _rows(
    connection: duckdb.DuckDBPyConnection, query: str, parameters: Sequence[Any] = ()
) -> list[dict[str, Any]]:
    cursor = connection.execute(query, list(parameters))
    names = [str(item[0]) for item in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _normal_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _request_row_identity(row: Mapping[str, Any], expected: RequestIdentity) -> None:
    q_text = str(row["q_by_dimension"])
    try:
        q_value = json.loads(q_text)
    except json.JSONDecodeError as error:
        raise T05Error(
            "evaluator_q_identity_invalid", expected.logical_request_name
        ) from error
    if not isinstance(q_value, dict):
        raise T05Error("evaluator_q_identity_invalid", expected.logical_request_name)
    actual = RequestIdentity(
        logical_request_name=expected.logical_request_name,
        request_id=str(row["request_id"]),
        request_hash=str(row["request_hash"]),
        selected_dimensions=tuple(row["selected_dimensions"]),
        q_by_dimension={key: int(value) for key, value in q_value.items()},
        confirmation_k=int(row["confirmation_k"]),
        selection_status=expected.selection_status,
    )
    if actual != expected:
        raise T05Error(
            "evaluator_request_identity_mismatch", expected.logical_request_name
        )
    if row["score_release_id"] != "pcavt-score-w120-v1-c7e04f11a2cd09aa":
        raise T05Error("evaluator_score_release_identity_mismatch")
    if row["evaluator_version"] != "r2a_t03_dynamic_evaluator.v1":
        raise T05Error("evaluator_version_mismatch")
    if row["request_schema_version"] != REQUEST_SPEC_SCHEMA_VERSION:
        raise T05Error("request_schema_version_mismatch")
    if row["output_schema_version"] != OUTPUT_SCHEMA_VERSION:
        raise T05Error("output_schema_version_mismatch")
    if row["dynamic_protocol_version"] != "pcavt_dynamic_state_protocol.v1":
        raise T05Error("dynamic_protocol_version_mismatch")
    if (
        int(row["weak_delta_bp"]) != 1000
        or abs(float(row["floating_comparison_epsilon"]) - EPSILON) > 0
    ):
        raise T05Error("evaluator_protocol_constant_mismatch")


def _load_component_map(
    connection: duckdb.DuckDBPyConnection,
    score_release_id: str,
) -> dict[tuple[str, int, str], list[dict[str, Any]]]:
    component_rows = _rows(
        connection,
        "SELECT security_id,trading_date,observation_sequence,dimension_id,"
        "component_id,score,eligible,validity_status,reason_codes "
        "FROM daily_component_scores WHERE score_release_id=? "
        "AND dimension_id IN ('C','A') "
        "ORDER BY security_id,observation_sequence,dimension_id,component_id",
        [score_release_id],
    )
    component_map: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in component_rows:
        key = (
            str(row["security_id"]),
            int(row["observation_sequence"]),
            str(row["dimension_id"]),
        )
        component_map[key].append(
            {
                "component_id": str(row["component_id"]),
                "score": _finite(row["score"]),
                "eligible": row["eligible"],
                "validity_status": row["validity_status"],
                "reason_codes": _normal_list(row["reason_codes"]),
            }
        )
    return dict(component_map)


def load_request_snapshot(
    request_source: duckdb.DuckDBPyConnection | Path | str,
    expected: RequestIdentity,
    component_map: Mapping[tuple[str, int, str], list[dict[str, Any]]],
) -> RequestSnapshot:
    """Load a single accepted T03 output without changing its interval semantics."""

    with _connection(request_source) as connection:
        _validate_request_schema_connection(connection)
        request_rows = _rows(connection, "SELECT * FROM dynamic_request")
        if len(request_rows) != 1:
            raise T05Error(
                "evaluator_dynamic_request_cardinality", expected.logical_request_name
            )
        _request_row_identity(request_rows[0], expected)
        scope_rows = _rows(connection, "SELECT * FROM evaluation_scope")
        if len(scope_rows) != 1 or scope_rows[0]["request_id"] != expected.request_id:
            raise T05Error(
                "evaluator_scope_request_id_mismatch", expected.logical_request_name
            )
        joint_rows = _rows(
            connection,
            "SELECT * FROM daily_joint_states "
            "ORDER BY security_id,observation_sequence",
        )
        dimension_rows_list = _rows(
            connection,
            "SELECT * FROM daily_dimension_states WHERE dimension_id IN ('C','A') "
            "ORDER BY security_id,observation_sequence,dimension_id",
        )
        interval_rows = _rows(
            connection,
            "SELECT * FROM confirmed_intervals ORDER BY security_id,interval_ordinal",
        )
    if any(
        row["request_id"] != expected.request_id
        for row in (*joint_rows, *dimension_rows_list)
    ):
        raise T05Error(
            "evaluator_daily_request_id_mismatch", expected.logical_request_name
        )
    dimensions: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in dimension_rows_list:
        key = (
            str(row["security_id"]),
            int(row["observation_sequence"]),
            str(row["dimension_id"]),
        )
        if key in dimensions:
            raise T05Error(
                "evaluator_dimension_key_duplicate", expected.logical_request_name
            )
        dimensions[key] = row
    intervals: list[dict[str, Any]] = []
    interval_days: dict[tuple[str, int], set[tuple[str, int]]] = {}
    for row in interval_rows:
        if str(row["request_id"]) != expected.request_id:
            raise T05Error(
                "evaluator_interval_request_id_mismatch", expected.logical_request_name
            )
        item = dict(row)
        security_id = str(item["security_id"])
        ordinal = int(item["interval_ordinal"])
        key = (security_id, ordinal)
        if key in interval_days:
            raise T05Error(
                "evaluator_interval_key_duplicate", expected.logical_request_name
            )
        days = {
            (str(joint["security_id"]), int(joint["observation_sequence"]))
            for joint in joint_rows
            if str(joint["security_id"]) == security_id
            and joint["confirmed_state"] is True
            and joint["confirmed_interval_ordinal"] is not None
            and int(joint["confirmed_interval_ordinal"]) == ordinal
        }
        if len(days) != int(item["confirmed_observation_count"]):
            raise T05Error(
                "evaluator_interval_count_mismatch", expected.logical_request_name
            )
        interval_days[key] = days
        intervals.append(item)
    raw_keys = {
        (str(row["security_id"]), int(row["observation_sequence"]))
        for row in joint_rows
        if row["raw_state"] is True
    }
    confirmed_keys = {
        (str(row["security_id"]), int(row["observation_sequence"]))
        for row in joint_rows
        if row["confirmed_state"] is True
    }
    return RequestSnapshot(
        identity=expected,
        joint_rows=joint_rows,
        dimension_rows=dimensions,
        intervals=intervals,
        interval_days=interval_days,
        raw_keys=raw_keys,
        confirmed_keys=confirmed_keys,
    )


def _state_at(
    snapshot: RequestSnapshot, security_id: str, sequence: int, dimension: str
) -> dict[str, Any] | None:
    return snapshot.dimension_rows.get((security_id, sequence, dimension))


def _gate_class(state: Mapping[str, Any] | None, q_bp: int) -> str:
    if state is None or state.get("dimension_ready") is not True:
        return "NOT_EVALUABLE"
    mean = _finite(state.get("score_dimension"))
    minimum = _finite(state.get("score_dimension_min"))
    if mean is None or minimum is None:
        return "NOT_EVALUABLE"
    main_failed = mean < (1.0 - q_bp / 10000.0) - EPSILON
    weak_failed = minimum < (1.0 - q_bp / 10000.0 - WEAK_DELTA) - EPSILON
    if main_failed and weak_failed:
        return "MAIN_AND_WEAK_FAIL"
    if main_failed:
        return "MAIN_ONLY_FAIL"
    if weak_failed:
        return "WEAK_ONLY_FAIL"
    return "NO_GATE_FAIL"


def _endpoint_metrics(
    snapshot: RequestSnapshot,
    components: Mapping[tuple[str, int, str], list[dict[str, Any]]],
    security_id: str,
    sequence: int | None,
    endpoint: str,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        state = (
            None
            if sequence is None
            else _state_at(snapshot, security_id, sequence, dimension)
        )
        q_bp = snapshot.identity.q_by_dimension[dimension]
        mean = _finite(state.get("score_dimension")) if state else None
        minimum = _finite(state.get("score_dimension_min")) if state else None
        main_threshold = 1.0 - q_bp / 10000.0
        weak_threshold = main_threshold - WEAK_DELTA
        mean_margin = None if mean is None else mean - main_threshold
        min_margin = None if minimum is None else minimum - weak_threshold
        active_margin = (
            None
            if mean_margin is None or min_margin is None
            else min(mean_margin, min_margin)
        )
        component_rows = (
            []
            if sequence is None
            else components.get((security_id, sequence, dimension), [])
        )
        if sequence is not None and len(component_rows) != 2:
            raise T05Error(
                "component_score_cardinality_mismatch",
                f"{security_id}:{sequence}:{dimension}",
            )
        output[dimension] = {
            "endpoint": endpoint,
            "dimension_id": dimension,
            "observation_sequence": sequence,
            "trading_date": _date_text(state.get("trading_date")) if state else None,
            "q_bp": q_bp,
            "main_threshold": main_threshold,
            "weak_threshold": weak_threshold,
            "score_dimension": mean,
            "score_dimension_min": minimum,
            "eligible_dimension": None
            if state is None
            else state.get("eligible_dimension"),
            "validity_status": None if state is None else state.get("validity_status"),
            "reason_codes": []
            if state is None
            else _normal_list(state.get("dimension_reason_codes")),
            "dimension_ready": None if state is None else state.get("dimension_ready"),
            "mean_margin": mean_margin,
            "min_margin": min_margin,
            "active_margin": active_margin,
            "gate_failure_class": _gate_class(state, q_bp),
            "component_scores": component_rows,
            "component_count": len(component_rows),
        }
    return output


def _primary_category(reason: str, right_censored: bool) -> str:
    if right_censored or reason == "input_end_open_right_censored":
        return "input_end_open_right_censored"
    if reason == "raw_false":
        return "raw_false"
    if reason in QUALITY_TERMINATION_REASONS:
        return "quality_or_availability_termination"
    raise T05Error("termination_reason_not_in_accepted_protocol", reason)


def _raw_false_subclass(
    snapshot: RequestSnapshot,
    security_id: str,
    sequence: int | None,
) -> tuple[str | None, bool | None, bool | None]:
    if sequence is None:
        raise T05Error("raw_false_termination_observation_missing")
    c_state = _state_at(snapshot, security_id, sequence, "C")
    a_state = _state_at(snapshot, security_id, sequence, "A")
    c_active = None if c_state is None else c_state.get("dimension_active")
    a_active = None if a_state is None else a_state.get("dimension_active")
    if c_active not in (True, False) or a_active not in (True, False):
        raise T05Error("raw_false_unclassified")
    if c_active and a_active:
        raise T05Error("raw_false_joint_active_lineage_mismatch")
    if c_active and not a_active:
        return "A_ONLY_FAIL", c_active, a_active
    if not c_active and a_active:
        return "C_ONLY_FAIL", c_active, a_active
    return "CA_BOTH_FAIL", c_active, a_active


def _quality_interruption(row: Mapping[str, Any]) -> bool:
    return (
        row["expected_observation_status"] != "present"
        or row["joint_ready"] is not True
        or row["joint_validity_status"] != "valid"
    )


def _compact_followup(
    rows: Sequence[Mapping[str, Any]],
    termination_sequence: int,
    max_lag: int,
) -> list[dict[str, Any]]:
    followup = [
        row
        for row in rows
        if 0 < int(row["observation_sequence"]) - termination_sequence <= max_lag
    ]
    followup.sort(key=lambda row: int(row["observation_sequence"]))
    return [
        {
            "observation_sequence": int(row["observation_sequence"]),
            "observation_lag": int(row["observation_sequence"]) - termination_sequence,
            "trading_date": _date_text(row["trading_date"]),
            "raw_state": row["raw_state"],
            "confirmed_state": row["confirmed_state"],
            "expected_observation_status": row["expected_observation_status"],
            "joint_ready": row["joint_ready"],
            "joint_validity_status": row["joint_validity_status"],
        }
        for row in followup
    ]


def _threshold_outcome(
    first_event_lag: int | None,
    first_quality_lag: int | None,
    max_observed_followup_lag: int | None,
    threshold: int,
) -> tuple[int | None, str]:
    if (
        first_event_lag is not None
        and first_event_lag <= threshold
        and (first_quality_lag is None or first_event_lag < first_quality_lag)
    ):
        return first_event_lag, "reentered"
    if (
        first_quality_lag is not None
        and first_quality_lag <= threshold
        and (first_event_lag is None or first_quality_lag <= first_event_lag)
    ):
        return None, "quality_interrupted"
    if max_observed_followup_lag is None or max_observed_followup_lag < threshold:
        return None, "insufficient_followup_censored"
    return None, "not_reentered_within_window"


def _followup_metrics(
    rows: Sequence[Mapping[str, Any]],
    termination_sequence: int,
    max_lag: int,
    event_field: str,
    thresholds: Sequence[int],
) -> dict[str, Any]:
    followup = [
        row
        for row in rows
        if 0 < int(row["observation_sequence"]) - termination_sequence <= max_lag
    ]
    followup.sort(key=lambda row: int(row["observation_sequence"]))
    first_event_lag = next(
        (
            int(row["observation_sequence"]) - termination_sequence
            for row in followup
            if row[event_field] is True
        ),
        None,
    )
    first_quality_lag = next(
        (
            int(row["observation_sequence"]) - termination_sequence
            for row in followup
            if _quality_interruption(row)
        ),
        None,
    )
    max_observed_followup_lag = (
        None
        if not followup
        else int(followup[-1]["observation_sequence"]) - termination_sequence
    )
    threshold_outcomes = {}
    for threshold in thresholds:
        lag, status = _threshold_outcome(
            first_event_lag,
            first_quality_lag,
            max_observed_followup_lag,
            int(threshold),
        )
        threshold_outcomes[str(threshold)] = {"lag": lag, "status": status}
    return {
        "first_event_lag": first_event_lag,
        "first_quality_lag": first_quality_lag,
        "max_observed_followup_lag": max_observed_followup_lag,
        "thresholds": threshold_outcomes,
        "compact": _compact_followup(rows, termination_sequence, max_lag),
    }


def _followup_status(
    rows: Sequence[Mapping[str, Any]],
    termination_sequence: int,
    max_lag: int,
    event_field: str,
) -> tuple[int | None, str, list[dict[str, Any]]]:
    """Compatibility wrapper for callers of the original max-window helper."""

    metrics = _followup_metrics(
        rows, termination_sequence, max_lag, event_field, (max_lag,)
    )
    outcome = metrics["thresholds"][str(max_lag)]
    return outcome["lag"], outcome["status"], metrics["compact"]


def _termination_records(
    snapshots: Mapping[str, RequestSnapshot],
    components: Mapping[tuple[str, int, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for name in REQUEST_ORDER:
        snapshot = snapshots[name]
        rows_by_security: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in snapshot.joint_rows:
            rows_by_security[str(row["security_id"])].append(row)
        for interval in snapshot.intervals:
            security_id = str(interval["security_id"])
            reason = str(interval["termination_reason"])
            right = bool(interval["right_censored"])
            primary = _primary_category(reason, right)
            if right and reason != "input_end_open_right_censored":
                raise T05Error("right_censoring_reason_mismatch")
            termination_sequence = (
                None
                if interval["termination_observation_sequence"] is None
                else int(interval["termination_observation_sequence"])
            )
            if primary == "input_end_open_right_censored" and (
                termination_sequence is not None or not right
            ):
                raise T05Error("right_censoring_semantics_mismatch")
            if primary != "input_end_open_right_censored" and right:
                raise T05Error("non_input_end_right_censoring")
            subclass = None
            c_active = None
            a_active = None
            if primary == "raw_false":
                subclass, c_active, a_active = _raw_false_subclass(
                    snapshot, security_id, termination_sequence
                )
            last_sequence = int(interval["last_confirmed_end_observation_sequence"])
            reentry = {
                "first_raw_true_lag": None,
                "first_confirmed_true_lag": None,
                "first_quality_interruption_lag": None,
                "max_observed_followup_lag": None,
                "followup_input_end_censored": None,
                "raw_thresholds": {
                    str(threshold): {
                        "lag": None,
                        "status": "not_applicable_right_censored",
                    }
                    for threshold in RAW_REENTRY_THRESHOLDS
                },
                "confirmed_thresholds": {
                    str(threshold): {
                        "lag": None,
                        "status": "not_applicable_right_censored",
                    }
                    for threshold in CONFIRMED_REENTRY_THRESHOLDS
                },
                "next_raw_true_lag": None,
                "next_raw_true_status": "not_applicable_right_censored",
                "next_confirmed_true_lag": None,
                "next_confirmed_true_status": "not_applicable_right_censored",
                "followup_observations": [],
            }
            if not right:
                raw_metrics = _followup_metrics(
                    rows_by_security[security_id],
                    termination_sequence or 0,
                    RAW_REENTRY_WINDOW,
                    "raw_state",
                    RAW_REENTRY_THRESHOLDS,
                )
                confirmed_metrics = _followup_metrics(
                    rows_by_security[security_id],
                    termination_sequence or 0,
                    CONFIRMED_REENTRY_WINDOW,
                    "confirmed_state",
                    CONFIRMED_REENTRY_THRESHOLDS,
                )
                all_followup_rows = confirmed_metrics["compact"]
                max_observed = confirmed_metrics["max_observed_followup_lag"]
                first_quality = confirmed_metrics["first_quality_lag"]
                raw_terminal = raw_metrics["thresholds"][str(RAW_REENTRY_WINDOW)]
                confirmed_terminal = confirmed_metrics["thresholds"][
                    str(CONFIRMED_REENTRY_WINDOW)
                ]
                reentry = {
                    "first_raw_true_lag": raw_metrics["first_event_lag"],
                    "first_confirmed_true_lag": confirmed_metrics["first_event_lag"],
                    "first_quality_interruption_lag": first_quality,
                    "max_observed_followup_lag": max_observed,
                    "followup_input_end_censored": (
                        first_quality is None
                        and raw_metrics["first_event_lag"] is None
                        and confirmed_metrics["first_event_lag"] is None
                        and (
                            max_observed is None
                            or max_observed < CONFIRMED_REENTRY_WINDOW
                        )
                    ),
                    "raw_thresholds": raw_metrics["thresholds"],
                    "confirmed_thresholds": confirmed_metrics["thresholds"],
                    "next_raw_true_lag": raw_terminal["lag"],
                    "next_raw_true_status": raw_terminal["status"],
                    "next_confirmed_true_lag": confirmed_terminal["lag"],
                    "next_confirmed_true_status": confirmed_terminal["status"],
                    "followup_observations": all_followup_rows,
                }
            record = {
                "logical_request_name": name,
                "request_id": snapshot.identity.request_id,
                "request_hash": snapshot.identity.request_hash,
                "q_bp": snapshot.identity.q_by_dimension["C"],
                "security_id": security_id,
                "interval_ordinal": int(interval["interval_ordinal"]),
                "raw_start_date": _date_text(interval["raw_start_date"]),
                "confirmation_date": _date_text(interval["confirmation_date"]),
                "last_confirmed_end": _date_text(interval["last_confirmed_end_date"]),
                "termination_observation_date": _date_text(
                    interval["termination_date"]
                ),
                "last_confirmed_end_observation_sequence": last_sequence,
                "termination_observation_sequence": termination_sequence,
                "primary_termination_reason": primary,
                "original_primary_termination_reason": reason,
                "right_censored": right,
                "raw_false_subclass": subclass,
                "termination_C_active": c_active,
                "termination_A_active": a_active,
                "termination_reason_codes": _normal_list(
                    interval["termination_reason_codes"]
                ),
                "confirmed_observation_count": int(
                    interval["confirmed_observation_count"]
                ),
                "last_confirmed_end_metrics": _endpoint_metrics(
                    snapshot,
                    components,
                    security_id,
                    last_sequence,
                    "last_confirmed_end",
                ),
                "termination_observation_metrics": _endpoint_metrics(
                    snapshot,
                    components,
                    security_id,
                    termination_sequence,
                    "termination_observation",
                ),
                "reentry": reentry,
                "first_raw_true_lag": reentry["first_raw_true_lag"],
                "first_confirmed_true_lag": reentry["first_confirmed_true_lag"],
                "first_quality_interruption_lag": reentry[
                    "first_quality_interruption_lag"
                ],
                "max_observed_followup_lag": reentry["max_observed_followup_lag"],
                "followup_input_end_censored": reentry["followup_input_end_censored"],
                "confirmed_day_keys": sorted(
                    snapshot.interval_days[
                        (security_id, int(interval["interval_ordinal"]))
                    ]
                ),
            }
            records.append(record)
    return records


def _mapping(
    child_name: str,
    parent_name: str,
    snapshots: Mapping[str, RequestSnapshot],
) -> dict[tuple[str, int], tuple[str, int]]:
    result: dict[tuple[str, int], tuple[str, int]] = {}
    child = snapshots[child_name]
    parent = snapshots[parent_name]
    for child_key, child_days in child.interval_days.items():
        security_id, _ = child_key
        candidates = [
            parent_key
            for parent_key, parent_days in parent.interval_days.items()
            if parent_key[0] == security_id and child_days <= parent_days
        ]
        if len(candidates) != 1:
            raise T05Error(
                "cross_q_parent_mapping_not_unique",
                f"{child_name}:{child_key}:{candidates}",
            )
        result[child_key] = candidates[0]
    return result


def _cross_q_structure(
    snapshots: Mapping[str, RequestSnapshot],
    termination_records: Sequence[Mapping[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    del termination_records
    for lower, upper in zip(REQUEST_ORDER, REQUEST_ORDER[1:]):
        if not snapshots[lower].raw_keys <= snapshots[upper].raw_keys:
            raise T05Error("cross_q_raw_subset_violation", f"{lower}->{upper}")
        if not snapshots[lower].confirmed_keys <= snapshots[upper].confirmed_keys:
            raise T05Error("cross_q_confirmed_subset_violation", f"{lower}->{upper}")
    q10_q15 = _mapping("CA_q10_k5", "CA_q15_k5", snapshots)
    q15_q20 = _mapping("CA_q15_k5", "CA_q20_k5", snapshots)
    q20_q25 = _mapping("CA_q20_k5", "CA_q25_k5", snapshots)
    q20_by_q25: dict[tuple[str, int], list[tuple[str, int]]] = defaultdict(list)
    for q20_key, q25_key in q20_q25.items():
        q20_by_q25[q25_key].append(q20_key)
    q15_by_q20: dict[tuple[str, int], list[tuple[str, int]]] = defaultdict(list)
    for q15_key, q20_key in q15_q20.items():
        q15_by_q20[q20_key].append(q15_key)
    q10_by_q20: dict[tuple[str, int], list[tuple[str, int]]] = defaultdict(list)
    for q10_key, q15_key in q10_q15.items():
        q10_by_q20[q15_q20[q15_key]].append(q10_key)
    parent_summary_rows: list[dict[str, Any]] = []
    child_summary_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    for child_name, mapping in (
        ("CA_q10_k5", q10_q15),
        ("CA_q15_k5", q15_q20),
        ("CA_q20_k5", q20_q25),
    ):
        parent_name = REQUEST_ORDER[REQUEST_ORDER.index(child_name) + 1]
        for (security_id, child_ordinal), (parent_security, parent_ordinal) in sorted(
            mapping.items()
        ):
            mappings.append(
                {
                    "child_request_name": child_name,
                    "child_security_id": security_id,
                    "child_interval_ordinal": child_ordinal,
                    "parent_request_name": parent_name,
                    "parent_security_id": parent_security,
                    "parent_interval_ordinal": parent_ordinal,
                }
            )
    q10 = snapshots["CA_q10_k5"]
    q15 = snapshots["CA_q15_k5"]
    q20 = snapshots["CA_q20_k5"]
    q25 = snapshots["CA_q25_k5"]
    q20_confirmed_global = set(q20.confirmed_keys)
    q15_confirmed_global = set(q15.confirmed_keys)
    q10_confirmed_global = set(q10.confirmed_keys)
    q25_day_parent: dict[tuple[str, int], tuple[str, int]] = {}
    for q25_key, q25_days in sorted(q25.interval_days.items()):
        for security_day in q25_days:
            if security_day in q25_day_parent:
                raise T05Error(
                    "cross_q_q25_parent_day_overlap",
                    f"{security_day}:{q25_day_parent[security_day]}:{q25_key}",
                )
            q25_day_parent[security_day] = q25_key

    q20_by_q25 = {key: sorted(value) for key, value in q20_by_q25.items()}
    for q25_key, q25_days in sorted(q25.interval_days.items()):
        security_id, q25_ordinal = q25_key
        q20_children = q20_by_q25.get(q25_key, [])
        q20_days = {
            security_day
            for child_key in q20_children
            for security_day in q20.interval_days[child_key]
        }
        q15_days = {
            security_day
            for child_key in q20_children
            for q15_key in q15_by_q20[child_key]
            for security_day in q15.interval_days[q15_key]
        }
        q10_days = {
            security_day
            for child_key in q20_children
            for q10_key in q10_by_q20[child_key]
            for security_day in q10.interval_days[q10_key]
        }
        if not q10_days <= q15_days <= q20_days <= q25_days:
            raise T05Error(
                "cross_q_interval_day_subset_violation", f"{security_id}:{q25_ordinal}"
            )
        if q20_days != (q25_days & q20_confirmed_global):
            raise T05Error(
                "cross_q_q20_parent_union_mismatch", f"{security_id}:{q25_ordinal}"
            )
        q25_only_days = q25_days - q20_days
        parent_summary_rows.append(
            {
                "logical_request_name": "CA_q25_k5",
                "request_id": q25.identity.request_id,
                "request_hash": q25.identity.request_hash,
                "security_id": security_id,
                "q25_parent_interval_ordinal": q25_ordinal,
                "q25_parent_confirmed_day_count": len(q25_days),
                "q20_confirmed_day_count_inside_parent": len(q20_days),
                "q25_only_shell_day_count": len(q25_only_days),
                "q20_child_interval_count": len(q20_children),
                "q20_fragmented_within_q25_parent": len(q20_children) > 1,
                "q20_equals_q25_parent": q20_days == q25_days,
                "q10_confirmed_day_count_inside_parent": len(q10_days),
                "q15_confirmed_day_count_inside_parent": len(q15_days),
                "q25_only_shell_identity_day_count": sum(
                    1 for day in q25_only_days if day not in q20_confirmed_global
                ),
            }
        )
        for security_day in sorted(q25_days, key=lambda item: item[1]):
            identity = (
                "Q10_CORE"
                if security_day in q10_confirmed_global
                else "Q15_NOT_Q10_CORE"
                if security_day in q15_confirmed_global
                else "Q20_NOT_Q15_ANCHOR"
                if security_day in q20_confirmed_global
                else "Q25_NOT_Q20_SHELL"
            )
            daily_rows.append(
                {
                    "security_id": security_day[0],
                    "observation_sequence": security_day[1],
                    "q25_parent_interval_ordinal": q25_ordinal,
                    "identity": identity,
                }
            )

    for q20_key, q25_key in sorted(q20_q25.items()):
        security_id, q20_ordinal = q20_key
        q25_days = q25.interval_days[q25_key]
        q20_days = q20.interval_days[q20_key]
        q20_only_shell = q25_days - q20_confirmed_global
        ordered_q25_by_sequence = {
            security_day[1]: security_day
            for security_day in sorted(q25_days, key=lambda item: item[1])
        }
        q20_sequences = [sequence for _security, sequence in q20_days]
        leading = 0
        sequence = min(q20_sequences) - 1
        while (
            sequence in ordered_q25_by_sequence
            and ordered_q25_by_sequence[sequence] in q20_only_shell
        ):
            leading += 1
            sequence -= 1
        trailing = 0
        sequence = max(q20_sequences) + 1
        while (
            sequence in ordered_q25_by_sequence
            and ordered_q25_by_sequence[sequence] in q20_only_shell
        ):
            trailing += 1
            sequence += 1
        q15_keys = q15_by_q20[q20_key]
        q10_keys = q10_by_q20[q20_key]
        q15_days = {
            security_day
            for q15_key in q15_keys
            for security_day in q15.interval_days[q15_key]
        }
        q10_days = {
            security_day
            for q10_key in q10_keys
            for security_day in q10.interval_days[q10_key]
        }
        child_summary_rows.append(
            {
                "logical_request_name": "CA_q20_k5",
                "request_id": q20.identity.request_id,
                "request_hash": q20.identity.request_hash,
                "security_id": security_id,
                "q20_interval_ordinal": q20_ordinal,
                "q25_parent_interval_ordinal": q25_key[1],
                "q10_confirmed_day_count_inside_q20": len(q10_days),
                "q15_confirmed_day_count_inside_q20": len(q15_days),
                "q20_confirmed_day_count": len(q20_days),
                "q25_parent_confirmed_day_count": len(q25_days),
                "q25_local_leading_shell_days": leading,
                "q25_local_trailing_shell_days": trailing,
                "q25_local_adjacent_shell_days": leading + trailing,
                "q10_child_interval_count": len(q10_keys),
                "q15_child_interval_count": len(q15_keys),
                "q20_sibling_count_within_q25_parent": len(q20_by_q25[q25_key]) - 1,
                "q20_open_right_censored": any(
                    bool(item["right_censored"])
                    for item in q20.intervals
                    if str(item["security_id"]) == security_id
                    and int(item["interval_ordinal"]) == q20_ordinal
                ),
            }
        )

    daily_key_counts = Counter(
        (
            row["security_id"],
            row["observation_sequence"],
            row["q25_parent_interval_ordinal"],
        )
        for row in daily_rows
    )
    if any(count != 1 for count in daily_key_counts.values()):
        raise T05Error("daily_identity_key_not_unique")
    if (
        len(daily_rows) != len(q25.confirmed_keys)
        or set((row["security_id"], row["observation_sequence"]) for row in daily_rows)
        != q25.confirmed_keys
    ):
        raise T05Error("daily_identity_row_count_or_scope_mismatch")
    identity_counts = Counter(row["identity"] for row in daily_rows)
    if not set(identity_counts) <= set(IDENTITY_CLASSES):
        raise T05Error("daily_identity_class_not_exhaustive")
    for parent in parent_summary_rows:
        parent_key = (
            parent["security_id"],
            parent["q25_parent_interval_ordinal"],
        )
        shell_count = sum(
            row["identity"] == "Q25_NOT_Q20_SHELL"
            and (row["security_id"], row["q25_parent_interval_ordinal"]) == parent_key
            for row in daily_rows
        )
        if shell_count != parent["q25_only_shell_day_count"]:
            raise T05Error("daily_identity_shell_difference_not_conserved", parent_key)
    return parent_summary_rows, child_summary_rows, daily_rows, mappings


def _summary_stats(values: Sequence[float | None]) -> dict[str, Any]:
    finite = [value for value in values if value is not None and math.isfinite(value)]
    if not finite:
        return {
            "count": len(values),
            "finite_count": 0,
            "null_count": len(values),
            "mean": None,
            "p05": None,
            "p50": None,
            "p95": None,
            "min": None,
            "max": None,
            "constant": False,
            "all_zero": False,
            "all_null": True,
        }
    ordered = sorted(finite)

    def quantile(probability: float) -> float:
        index = min(
            len(ordered) - 1, max(0, int(round((len(ordered) - 1) * probability)))
        )
        return ordered[index]

    return {
        "count": len(values),
        "finite_count": len(finite),
        "null_count": len(values) - len(finite),
        "mean": statistics.fmean(finite),
        "p05": quantile(0.05),
        "p50": quantile(0.50),
        "p95": quantile(0.95),
        "min": min(finite),
        "max": max(finite),
        "constant": len(set(finite)) == 1,
        "all_zero": all(abs(value) <= EPSILON for value in finite),
        "all_null": False,
    }


def _profiles(
    records: Sequence[Mapping[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    reason_counts = Counter(
        (
            row["logical_request_name"],
            row["primary_termination_reason"],
            row["original_primary_termination_reason"],
        )
        for row in records
    )
    reason_profile = [
        {
            "logical_request_name": name,
            "primary_termination_reason": primary,
            "original_primary_termination_reason": original,
            "interval_count": count,
        }
        for (name, primary, original), count in sorted(reason_counts.items())
    ]
    raw_counts = Counter(
        (row["logical_request_name"], row["raw_false_subclass"])
        for row in records
        if row["primary_termination_reason"] == "raw_false"
    )
    raw_profile = [
        {
            "logical_request_name": name,
            "raw_false_subclass": subclass,
            "interval_count": count,
        }
        for (name, subclass), count in sorted(raw_counts.items())
    ]
    margin_values: dict[tuple[str, str, str, str], list[float | None]] = defaultdict(
        list
    )
    gate_counts: Counter[tuple[str, str, str, str]] = Counter()
    for record in records:
        for endpoint_key in (
            "last_confirmed_end_metrics",
            "termination_observation_metrics",
        ):
            endpoint = record[endpoint_key]
            for dimension in DIMENSIONS:
                metric = endpoint[dimension]
                for margin_name in ("mean_margin", "min_margin", "active_margin"):
                    margin_values[
                        (
                            record["logical_request_name"],
                            endpoint_key,
                            dimension,
                            margin_name,
                        )
                    ].append(metric[margin_name])
                gate_counts[
                    (
                        record["logical_request_name"],
                        endpoint_key,
                        dimension,
                        metric["gate_failure_class"],
                    )
                ] += 1
    margin_profile: list[dict[str, Any]] = []
    for key, values in sorted(margin_values.items()):
        name, endpoint, dimension, margin_name = key
        margin_profile.append(
            {
                "logical_request_name": name,
                "endpoint": endpoint,
                "dimension_id": dimension,
                "margin_name": margin_name,
                **_summary_stats(values),
                "gate_failure_counts": {
                    gate: count
                    for (n, e, d, gate), count in sorted(gate_counts.items())
                    if (n, e, d) == (name, endpoint, dimension)
                },
            }
        )
    reentry_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        if record["right_censored"]:
            continue
        reentry_groups[(record["logical_request_name"], "raw")].append(record)
        reentry_groups[(record["logical_request_name"], "confirmed")].append(record)
    reentry_profile: list[dict[str, Any]] = []
    for (name, metric), group in sorted(reentry_groups.items()):
        thresholds = (
            RAW_REENTRY_THRESHOLDS if metric == "raw" else CONFIRMED_REENTRY_THRESHOLDS
        )
        threshold_field = (
            "raw_thresholds" if metric == "raw" else "confirmed_thresholds"
        )
        for threshold in thresholds:
            outcomes = [
                row["reentry"][threshold_field][str(threshold)] for row in group
            ]
            reentered = sum(outcome["status"] == "reentered" for outcome in outcomes)
            clean = sum(
                outcome["status"] == "not_reentered_within_window"
                for outcome in outcomes
            )
            insufficient = sum(
                outcome["status"] == "insufficient_followup_censored"
                for outcome in outcomes
            )
            quality = sum(
                outcome["status"] == "quality_interrupted" for outcome in outcomes
            )
            observable = reentered + clean
            reentry_profile.append(
                {
                    "logical_request_name": name,
                    "metric": metric,
                    "lag_threshold": threshold,
                    "total_non_right_censored_termination_count": len(group),
                    "observable_denominator": observable,
                    "reentered_count": reentered,
                    "clean_not_reentered_count": clean,
                    "insufficient_followup_censored_count": insufficient,
                    "quality_interrupted_count": quality,
                    "reentry_rate": (
                        None if observable == 0 else reentered / observable
                    ),
                }
            )
    years: Counter[tuple[str, int, str]] = Counter()
    securities: Counter[tuple[str, str, str]] = Counter()
    for row in records:
        if row["termination_observation_date"] is not None:
            year = int(str(row["termination_observation_date"])[:4])
        else:
            year = None
        years[
            (row["logical_request_name"], year, row["primary_termination_reason"])
        ] += 1
        securities[
            (
                row["logical_request_name"],
                row["security_id"],
                row["primary_termination_reason"],
            )
        ] += 1
    year_profile = [
        {
            "logical_request_name": name,
            "year": year,
            "primary_termination_reason": reason,
            "interval_count": count,
        }
        for (name, year, reason), count in sorted(
            years.items(), key=lambda item: (item[0][0], item[0][1] or -1, item[0][2])
        )
    ]
    security_profile = [
        {
            "logical_request_name": name,
            "security_id": security_id,
            "primary_termination_reason": reason,
            "interval_count": count,
        }
        for (name, security_id, reason), count in sorted(securities.items())
    ]
    return (
        reason_profile,
        raw_profile,
        margin_profile,
        reentry_profile,
        year_profile + security_profile,
    )


def _samples(
    records: Sequence[Mapping[str, Any]], limit: int = 20
) -> list[dict[str, Any]]:
    candidates = []
    for row in records:
        token = (
            f"{row['request_hash']}:{row['security_id']}:"
            f"{row['confirmation_date']}:{row['interval_ordinal']}"
        )
        candidates.append(
            {
                "logical_request_name": row["logical_request_name"],
                "request_hash": row["request_hash"],
                "security_id": row["security_id"],
                "confirmation_date": row["confirmation_date"],
                "interval_ordinal": row["interval_ordinal"],
                "sample_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            }
        )
    return sorted(candidates, key=lambda row: row["sample_hash"])[:limit]


def build_t05_candidate(
    request_sources: Mapping[str, duckdb.DuckDBPyConnection | Path | str],
    score_source: duckdb.DuckDBPyConnection | Path | str,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an in-memory candidate result from four synthetic T03 outputs."""

    loaded = dict(config or load_t05_config())
    identities = accepted_request_identities(loaded)
    if tuple(request_sources) != REQUEST_ORDER:
        raise T05Error("request_source_order_or_set_mismatch")
    input_checks = validate_input_schema(
        next(iter(request_sources.values())), score_source
    )
    with _connection(score_source) as score:
        expected_score_id = loaded["accepted_bindings"]["score_release"][
            "score_release_id"
        ]
        score_ids_by_table = {
            table: {
                str(row[0])
                for row in score.execute(
                    f'SELECT DISTINCT score_release_id FROM "{table}"'
                ).fetchall()
            }
            for table in sorted(_tables(score))
        }
        if any(ids != {expected_score_id} for ids in score_ids_by_table.values()):
            raise T05Error("score_table_release_identity_mismatch", score_ids_by_table)
        score_ids = {expected_score_id}
        components = _load_component_map(score, next(iter(score_ids)))
    snapshots = {
        name: load_request_snapshot(request_sources[name], identities[name], components)
        for name in REQUEST_ORDER
    }
    records = _termination_records(snapshots, components)
    (
        cross_q_summary,
        cross_q_child_summary,
        daily_identities,
        mappings,
    ) = _cross_q_structure(snapshots, records)
    reason_profile, raw_profile, margin_profile, reentry_profile, profiles = _profiles(
        records
    )
    year_profile = [row for row in profiles if "year" in row]
    security_profile = [row for row in profiles if "security_id" in row]
    reconciliation: list[dict[str, Any]] = []
    for name in REQUEST_ORDER:
        snapshot = snapshots[name]
        identity = snapshot.identity
        actual = {
            "raw_true": len(snapshot.raw_keys),
            "confirmed_true": len(snapshot.confirmed_keys),
            "intervals": len(snapshot.intervals),
            "securities_with_interval": len(
                {str(row["security_id"]) for row in snapshot.intervals}
            ),
        }
        expected = dict(loaded["accepted_t04_counts"][name])
        reconciliation.append(
            {
                "logical_request_name": name,
                "request_id": identity.request_id,
                "request_hash": identity.request_hash,
                "selected_dimensions": list(identity.selected_dimensions),
                "q_by_dimension": dict(identity.q_by_dimension),
                "confirmation_k": identity.confirmation_k,
                "selection_status": identity.selection_status,
                "expected": expected,
                "actual": actual,
                "matches_accepted_t04": actual == expected,
            }
        )
    return {
        "task_id": TASK_ID,
        "implementation_version": IMPLEMENTATION_VERSION,
        "status": "implementation_candidate",
        "research_anchor_q": loaded["research_anchor_q"],
        "research_anchor_role": loaded["research_anchor_role"],
        "q_selection_status": loaded["q_selection_status"],
        "canonical_dynamic_request_selected": loaded[
            "canonical_dynamic_request_selected"
        ],
        "formal_run_allowed": False,
        "formal_run_started": False,
        "real_score_data_read": False,
        "formal_artifacts_generated": False,
        "R2A-T05_DONE": "absent",
        "R2A-T06_started": False,
        "R2A-T06_allowed_to_start": False,
        "input_checks": input_checks,
        "request_reconciliation": reconciliation,
        "termination_records": records,
        "termination_reason_profile": reason_profile,
        "raw_false_exit_decomposition": raw_profile,
        "threshold_margin_summary": margin_profile,
        "quick_reentry_profile": reentry_profile,
        "cross_q_structure_summary": cross_q_summary,
        "cross_q_child_structure_summary": cross_q_child_summary,
        "cross_q_mapping": mappings,
        "daily_level_identities": daily_identities,
        "year_profile": year_profile,
        "security_profile": security_profile,
        "deterministic_interval_samples": _samples(records),
        "analysis_boundary": {
            "formal_run_executed": False,
            "real_score_data_read": False,
            "formal_artifacts_generated": False,
            "scientific_review_status": "not_applicable_implementation_candidate",
            "R2A_T06_allowed_to_start": False,
        },
    }


def flatten_margin_summary(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the compact margin table rows without changing signed values."""

    return [dict(row) for row in candidate["threshold_margin_summary"]]


def candidate_to_json(candidate: Mapping[str, Any]) -> str:
    """Canonical JSON rendering for synthetic review/debug output."""

    return json.dumps(
        candidate,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


__all__ = [
    "CONFIG_PATH",
    "DIMENSIONS",
    "IDENTITY_CLASSES",
    "IMPLEMENTATION_VERSION",
    "RAW_FALSE_SUBCLASSES",
    "REQUEST_ORDER",
    "RESULT_PACKAGE_SCHEMA_VERSION",
    "T05Error",
    "accepted_request_identities",
    "build_t05_candidate",
    "candidate_to_json",
    "flatten_margin_summary",
    "load_request_snapshot",
    "load_t05_config",
    "validate_input_schema",
]
