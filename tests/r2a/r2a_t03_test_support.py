"""Synthetic-only support for R2A-T03 tests."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import duckdb

from src.r2a.r2a_t02_request_identity import (
    DYNAMIC_PROTOCOL_VERSION,
    REQUEST_SPEC_SCHEMA_VERSION,
    SCORE_RELEASE_ID,
    build_canonical_request,
)
from src.r2a.r2a_t03_dynamic_evaluator import (
    evaluate_dynamic_request_connections,
)

DIMENSIONS = ("P", "A", "T")


def canonical_request(
    dimensions: tuple[str, ...] = ("P", "A"),
    q_bp: int | dict[str, int] = 1500,
    confirmation_k: int = 3,
) -> dict[str, object]:
    q = {dimension: q_bp for dimension in dimensions} if isinstance(q_bp, int) else q_bp
    return build_canonical_request(
        {
            "request_schema_version": REQUEST_SPEC_SCHEMA_VERSION,
            "dynamic_protocol_version": DYNAMIC_PROTOCOL_VERSION,
            "score_release_id": SCORE_RELEASE_ID,
            "selected_dimensions": list(dimensions),
            "q_by_dimension": q,
            "confirmation_k": confirmation_k,
        }
    )


def _profile(
    security_id: str, sequence: int, dimension: str
) -> tuple[str, float | None, float | None, bool, str, list[str]]:
    status = "present"
    mean: float | None = 0.9
    minimum: float | None = 0.8
    eligible = True
    validity = "valid"
    reasons: list[str] = []
    if security_id == "S1":
        if sequence == 3:
            mean = 0.5
        elif sequence in {6, 10} and dimension == "A":
            mean = minimum = None
            eligible = False
            validity = "blocked"
            reasons = ["upstream_block"]
    elif security_id == "S2":
        if sequence == 0:
            status = "missing"
            mean = minimum = None
            eligible = False
            validity = "blocked"
        elif sequence == 1:
            status = "listing_pause"
            mean = minimum = None
            eligible = False
            validity = "blocked"
        elif dimension == "A" and sequence == 2:
            eligible = False
            reasons = ["not_ready"]
        elif dimension == "A" and sequence == 3:
            validity = "unknown"
            reasons = ["upstream_unknown"]
        elif dimension == "A" and sequence == 4:
            validity = "diagnostic_required"
        elif dimension == "A" and sequence == 5:
            validity = "blocked"
        elif dimension == "A" and sequence == 6:
            mean = None
        elif dimension == "A" and sequence == 7:
            mean = float("nan")
        elif dimension == "A" and sequence == 8:
            mean = float("inf")
        elif dimension == "A" and sequence == 9:
            minimum = float("-inf")
    elif security_id == "S3":
        mean = 0.4
        minimum = 0.3
        if sequence == 0 and dimension == "P":
            mean = 0.82
            minimum = 0.72
        elif sequence == 0 and dimension == "A":
            mean = 0.9
            minimum = 0.8
        elif sequence == 1 and dimension == "A":
            mean = 0.82
            minimum = 0.72
        elif sequence == 1 and dimension == "P":
            mean = 0.9
            minimum = 0.8
    return status, mean, minimum, eligible, validity, reasons


def create_source(
    path: str = ":memory:", *, reverse_insert_order: bool = False
) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(path)
    connection.execute(
        "CREATE TABLE security_observation_spine (score_release_id VARCHAR, "
        "security_id VARCHAR, trading_date DATE, observation_sequence BIGINT, "
        "expected_observation_status VARCHAR, "
        "observation_available_time TIMESTAMP WITH TIME ZONE)"
    )
    connection.execute(
        "CREATE TABLE daily_dimension_scores (score_release_id VARCHAR, "
        "security_id VARCHAR, trading_date DATE, observation_sequence BIGINT, "
        "dimension_id VARCHAR, score_dimension DOUBLE, score_dimension_min DOUBLE, "
        "eligible_dimension BOOLEAN, validity_status VARCHAR, reason_codes VARCHAR[], "
        "available_time TIMESTAMP WITH TIME ZONE)"
    )
    lengths = {"S1": 15, "S2": 11, "S3": 6}
    spine_rows: list[tuple[object, ...]] = []
    dimension_rows: list[tuple[object, ...]] = []
    timezone = ZoneInfo("Asia/Shanghai")
    first_date = date(2026, 1, 5)
    for security_id, length in lengths.items():
        for sequence in range(length):
            trading_date = first_date + timedelta(days=sequence)
            available = datetime.combine(trading_date, time(15), tzinfo=timezone)
            status = _profile(security_id, sequence, "P")[0]
            spine_rows.append(
                (
                    SCORE_RELEASE_ID,
                    security_id,
                    trading_date,
                    sequence,
                    status,
                    available,
                )
            )
            for dimension in DIMENSIONS:
                _, mean, minimum, eligible, validity, reasons = _profile(
                    security_id, sequence, dimension
                )
                dimension_rows.append(
                    (
                        SCORE_RELEASE_ID,
                        security_id,
                        trading_date,
                        sequence,
                        dimension,
                        mean,
                        minimum,
                        eligible,
                        validity,
                        reasons,
                        available,
                    )
                )
    if reverse_insert_order:
        spine_rows.reverse()
        dimension_rows.reverse()
    connection.executemany(
        "INSERT INTO security_observation_spine VALUES (?, ?, ?, ?, ?, ?)",
        spine_rows,
    )
    connection.executemany(
        "INSERT INTO daily_dimension_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        dimension_rows,
    )
    return connection


def evaluate(
    source: duckdb.DuckDBPyConnection,
    request: dict[str, object] | None = None,
    security_ids: list[str] | None = None,
    *,
    threads: int = 1,
) -> duckdb.DuckDBPyConnection:
    output = duckdb.connect(":memory:")
    output.execute(f"SET threads={threads}")
    evaluate_dynamic_request_connections(
        source=source,
        output=output,
        canonical_request=request or canonical_request(),
        security_ids=security_ids,
    )
    return output


def table_fingerprint(connection: duckdb.DuckDBPyConnection, table: str) -> str:
    columns = [
        row[1] for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()
    ]
    expression = ", ".join(f'"{column}"' for column in columns)
    rows = connection.execute(f"SELECT * FROM {table} ORDER BY {expression}").fetchall()
    return repr(rows)
