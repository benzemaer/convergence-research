"""Set-based DuckDB materialization for the EXP-A01 formal package.

The Python implementation in :mod:`exp_a01_price_ma_attachment` remains the
small synthetic oracle.  This module deliberately has no dependency on that
oracle: formal materialization is performed by DuckDB window expressions over
the authorized dense observation sequence.  Only compact aggregates are
returned to Python; the raw metric rows stay in the output DuckDB.
"""

# SQL templates intentionally preserve readable set-based expressions.
# ruff: noqa: E501

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

TASK_ID = "EXP-A01"
METRIC_ENGINE_VERSION = "exp_a01_price_ma_attachment.v1"
A1_ID = "A1_LogBodyCenterToMACloudCenter_5_60"
A2_ID = "A2_BodyCenterOutsideMACloudRate20_5_60"
A2B_ID = "A2b_BodyToMACloudGapMean20_5_60"
INDICATOR_IDS = (A1_ID, A2_ID, A2B_ID)
RAW_METRIC_NAMES = {
    A1_ID: "LogBodyCenterToMACloudCenter_5_60",
    A2_ID: "BodyCenterOutsideMACloudRate20_5_60",
    A2B_ID: "BodyToMACloudGapMean20_5_60",
}
REQUIRED_OBSERVATIONS = {A1_ID: 60, A2_ID: 79, A2B_ID: 79}
MA_WINDOWS = (5, 10, 20, 30, 60)
REASON_CODES = (
    "valid_no_blocker",
    "window_insufficient",
    "missing_adjusted_open",
    "missing_adjusted_close",
    "missing_required_history",
    "nonpositive_adjusted_open",
    "nonpositive_adjusted_close",
    "nonpositive_MA",
    "adjustment_failure",
    "suspension_in_required_window",
    "listing_pause_in_required_window",
    "invalid_trading_status",
    "reopen_after_suspension",
)
RAW_TABLE_COLUMNS = (
    "run_id",
    "security_id",
    "trading_date",
    "observation_sequence",
    "expected_observation_status",
    "indicator_id",
    "raw_metric_name",
    "raw_value",
    "validity_status",
    "reason_codes_json",
    "input_window_start",
    "input_window_end",
    "required_observation_count",
    "actual_valid_observation_count",
    "metric_engine_version",
    "source_ref",
)
CSV_FILES = (
    "exp_a01_metric_profile.csv",
    "exp_a01_validity_profile.csv",
    "exp_a01_year_coverage.csv",
    "exp_a01_security_coverage.csv",
)

_VALID_TRADING_STATUSES = {
    "normal_trading",
    "limit_up",
    "limit_down",
    "one_price_limit_up",
    "one_price_limit_down",
}
_VALID_DAILY_STATUSES = {"resolved"}
_VALID_ADJUSTMENT_STATUSES = {
    "resolved",
    "not_applicable_or_carry_forward",
    "neutral_factor_1_policy",
    "factor_interval_policy",
}
DEFAULT_DUCKDB_THREADS = 12
MAX_DUCKDB_THREADS = 12
DEFAULT_MEMORY_LIMIT = "12GB"


def materialize_raw_metrics(
    *,
    candidate_path: Path,
    candidate_table: str,
    index_path: Path,
    index_table: str,
    output_path: Path,
    run_id: str,
    duckdb_threads: int = DEFAULT_DUCKDB_THREADS,
    memory_limit: str = DEFAULT_MEMORY_LIMIT,
) -> dict[str, Any]:
    """Materialize the three raw metrics with one DuckDB connection."""

    _require_identifier(candidate_table)
    _require_identifier(index_table)
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("duckdb is required for formal materialization") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(output_path))
    try:
        _configure_duckdb_connection(
            connection, duckdb_threads=duckdb_threads, memory_limit=memory_limit
        )
        connection.execute("PRAGMA preserve_insertion_order=false")
        connection.execute(
            f"ATTACH '{_sql_literal(str(candidate_path))}' AS candidate (READ_ONLY)"
        )
        connection.execute(
            f"ATTACH '{_sql_literal(str(index_path))}' AS expected (READ_ONLY)"
        )
        sql = _raw_metric_sql(
            candidate_table=candidate_table,
            index_table=index_table,
            run_id=run_id,
        )
        connection.execute(f"CREATE TABLE exp_a01_raw_metrics AS {sql}")
        row_count = int(
            connection.execute("SELECT COUNT(*) FROM exp_a01_raw_metrics").fetchone()[0]
        )
        schema = [
            {"name": str(row[1]), "type": str(row[2])}
            for row in connection.execute(
                "PRAGMA table_info('exp_a01_raw_metrics')"
            ).fetchall()
        ]
        expected_count = int(
            connection.execute(
                f"SELECT COUNT(*) FROM expected.{index_table}"
            ).fetchone()[0]
        )
        return {
            "table": "exp_a01_raw_metrics",
            "row_count": row_count,
            "expected_index_row_count": expected_count,
            "schema": schema,
            "expected_row_count": expected_count * 3,
        }
    finally:
        connection.close()


def write_compact_csvs(
    *,
    output_dir: Path,
    raw_duckdb: Path,
    duckdb_threads: int = DEFAULT_DUCKDB_THREADS,
    memory_limit: str = DEFAULT_MEMORY_LIMIT,
) -> dict[str, dict[str, Any]]:
    """Write the four compact profiles from the persisted raw table."""

    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for formal profiles") from exc

    connection = duckdb.connect(str(raw_duckdb), read_only=True)
    try:
        _configure_duckdb_connection(
            connection, duckdb_threads=duckdb_threads, memory_limit=memory_limit
        )
        specs = (
            (
                "exp_a01_metric_profile.csv",
                _metric_profile_query(),
                _METRIC_PROFILE_FIELDS,
            ),
            (
                "exp_a01_validity_profile.csv",
                _validity_profile_query(),
                _VALIDITY_PROFILE_FIELDS,
            ),
            ("exp_a01_year_coverage.csv", _year_profile_query(), _YEAR_PROFILE_FIELDS),
            (
                "exp_a01_security_coverage.csv",
                _security_profile_query(),
                _SECURITY_PROFILE_FIELDS,
            ),
        )
        results: dict[str, dict[str, Any]] = {}
        for filename, query, fields in specs:
            rows = connection.execute(query).fetchall()
            path = output_dir / filename
            _write_csv(path, fields, rows)
            results[filename] = {
                "path": str(path),
                "row_count": len(rows),
                "columns": list(fields),
            }
        return results
    finally:
        connection.close()


def _raw_metric_sql(*, candidate_table: str, index_table: str, run_id: str) -> str:
    candidate_date = _canonical_date("m.trade_date")
    index_date = _canonical_date("i.trading_date")
    run_literal = _sql_literal(run_id)
    row_reason = _row_reason_expression()
    flags = _window_reason_flags()
    a1_reasons = _metric_reason_expression("a1", 60, "cloud_valid")
    a2_reasons = _metric_reason_expression("a2", 79, "a2_points_valid_count = 20")
    return f"""
WITH dense AS (
  SELECT
    i.security_id,
    {index_date} AS trading_date,
    CAST(i.observation_sequence AS BIGINT) AS observation_sequence,
    i.expected_observation_status,
    CASE WHEN i.expected_observation_status = 'present' THEN m.adjusted_open END AS adjusted_open,
    CASE WHEN i.expected_observation_status = 'present' THEN m.adjusted_close END AS adjusted_close,
    CASE WHEN i.expected_observation_status = 'present' THEN m.trading_status
         ELSE i.expected_observation_status END AS trading_status,
    CASE WHEN i.expected_observation_status = 'present' THEN m.daily_status
         ELSE i.expected_observation_status END AS daily_status,
    CASE WHEN i.expected_observation_status = 'present' THEN m.effective_adj_factor END AS effective_adj_factor,
    CASE WHEN i.expected_observation_status = 'present' THEN m.adjustment_factor_status END AS adjustment_factor_status,
    CASE WHEN i.expected_observation_status = 'present' THEN m.is_listing_pause
         ELSE i.expected_observation_status = 'listing_pause' END AS is_listing_pause,
    CASE WHEN i.expected_observation_status = 'present' THEN m.row_provenance
         ELSE i.source_ref END AS row_provenance,
    i.source_contract,
    i.source_ref
  FROM expected.{index_table} AS i
  LEFT JOIN candidate.{candidate_table} AS m
    ON i.expected_observation_status = 'present'
   AND m.ts_code = i.security_id
   AND {candidate_date} = {index_date}
), row_flags AS (
  SELECT
    d.*,
    {row_reason} AS row_reasons,
    LEN({row_reason}) = 0 AS row_is_valid
  FROM dense AS d
), windows AS (
  SELECT
    r.*,
    COUNT(*) OVER p60 AS a1_window_count,
    SUM(CASE WHEN r.row_is_valid THEN 1 ELSE 0 END) OVER p60 AS a1_valid_count,
    FIRST_VALUE(r.trading_date) OVER p60 AS a1_window_start,
    COUNT(*) OVER p79 AS a2_window_count,
    SUM(CASE WHEN r.row_is_valid THEN 1 ELSE 0 END) OVER p79 AS a2_valid_count,
    FIRST_VALUE(r.trading_date) OVER p79 AS a2_window_start,
    AVG(CASE WHEN r.row_is_valid THEN r.adjusted_close END) OVER p5 AS ma5,
    AVG(CASE WHEN r.row_is_valid THEN r.adjusted_close END) OVER p10 AS ma10,
    AVG(CASE WHEN r.row_is_valid THEN r.adjusted_close END) OVER p20 AS ma20,
    AVG(CASE WHEN r.row_is_valid THEN r.adjusted_close END) OVER p30 AS ma30,
    AVG(CASE WHEN r.row_is_valid THEN r.adjusted_close END) OVER p60 AS ma60,
    SUM(CASE WHEN r.row_is_valid THEN 1 ELSE 0 END) OVER p5 AS valid5,
    SUM(CASE WHEN r.row_is_valid THEN 1 ELSE 0 END) OVER p10 AS valid10,
    SUM(CASE WHEN r.row_is_valid THEN 1 ELSE 0 END) OVER p20 AS valid20,
    SUM(CASE WHEN r.row_is_valid THEN 1 ELSE 0 END) OVER p30 AS valid30,
    SUM(CASE WHEN r.row_is_valid THEN 1 ELSE 0 END) OVER p60 AS valid60,
    COUNT(*) OVER p20 AS a2_points_count
    {flags}
  FROM row_flags AS r
  WINDOW
    p5 AS (PARTITION BY security_id ORDER BY observation_sequence ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
    p10 AS (PARTITION BY security_id ORDER BY observation_sequence ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
    p20 AS (PARTITION BY security_id ORDER BY observation_sequence ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
    p30 AS (PARTITION BY security_id ORDER BY observation_sequence ROWS BETWEEN 29 PRECEDING AND CURRENT ROW),
    p60 AS (PARTITION BY security_id ORDER BY observation_sequence ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
    p79 AS (PARTITION BY security_id ORDER BY observation_sequence ROWS BETWEEN 78 PRECEDING AND CURRENT ROW)
), cloud AS (
  SELECT
    w.*,
    CASE WHEN w.row_is_valid THEN
      (LN(w.adjusted_open) + LN(w.adjusted_close)) / 2.0 END AS body,
    CASE WHEN w.row_is_valid AND w.valid5 = 5 AND w.ma5 > 0 AND isfinite(w.ma5)
      THEN LN(w.ma5) END AS log_ma5,
    CASE WHEN w.row_is_valid AND w.valid10 = 10 AND w.ma10 > 0 AND isfinite(w.ma10)
      THEN LN(w.ma10) END AS log_ma10,
    CASE WHEN w.row_is_valid AND w.valid20 = 20 AND w.ma20 > 0 AND isfinite(w.ma20)
      THEN LN(w.ma20) END AS log_ma20,
    CASE WHEN w.row_is_valid AND w.valid30 = 30 AND w.ma30 > 0 AND isfinite(w.ma30)
      THEN LN(w.ma30) END AS log_ma30,
    CASE WHEN w.row_is_valid AND w.valid60 = 60 AND w.ma60 > 0 AND isfinite(w.ma60)
      THEN LN(w.ma60) END AS log_ma60
  FROM windows AS w
), cloud_values AS (
  SELECT
    c.*,
    CASE WHEN c.body IS NOT NULL AND c.log_ma5 IS NOT NULL AND c.log_ma10 IS NOT NULL
          AND c.log_ma20 IS NOT NULL AND c.log_ma30 IS NOT NULL AND c.log_ma60 IS NOT NULL
      THEN LEAST(c.log_ma5, c.log_ma10, c.log_ma20, c.log_ma30, c.log_ma60) END AS cloud_low,
    CASE WHEN c.body IS NOT NULL AND c.log_ma5 IS NOT NULL AND c.log_ma10 IS NOT NULL
          AND c.log_ma20 IS NOT NULL AND c.log_ma30 IS NOT NULL AND c.log_ma60 IS NOT NULL
      THEN GREATEST(c.log_ma5, c.log_ma10, c.log_ma20, c.log_ma30, c.log_ma60) END AS cloud_high,
    CASE WHEN c.body IS NOT NULL AND c.log_ma5 IS NOT NULL AND c.log_ma10 IS NOT NULL
          AND c.log_ma20 IS NOT NULL AND c.log_ma30 IS NOT NULL AND c.log_ma60 IS NOT NULL
      THEN (c.log_ma5 + c.log_ma10 + c.log_ma20 + c.log_ma30 + c.log_ma60) / 5.0 END AS cloud_center,
    c.body IS NOT NULL AND c.log_ma5 IS NOT NULL AND c.log_ma10 IS NOT NULL
      AND c.log_ma20 IS NOT NULL AND c.log_ma30 IS NOT NULL AND c.log_ma60 IS NOT NULL
      AS cloud_valid
  FROM cloud AS c
), point_windows AS (
  SELECT
    p.*,
    SUM(CASE WHEN p.cloud_valid THEN 1 ELSE 0 END) OVER p20 AS a2_points_valid_count,
    SUM(CASE WHEN p.cloud_valid AND (p.body < p.cloud_low OR p.body > p.cloud_high)
      THEN 1 ELSE 0 END) OVER p20 AS a2_outside_count,
    SUM(CASE WHEN p.cloud_valid THEN
      CASE
        WHEN GREATEST(LN(p.adjusted_open), LN(p.adjusted_close)) < p.cloud_low
          THEN p.cloud_low - GREATEST(LN(p.adjusted_open), LN(p.adjusted_close))
        WHEN LEAST(LN(p.adjusted_open), LN(p.adjusted_close)) > p.cloud_high
          THEN LEAST(LN(p.adjusted_open), LN(p.adjusted_close)) - p.cloud_high
        ELSE 0.0
      END
      ELSE 0.0 END) OVER p20 AS a2_gap_sum
  FROM cloud_values AS p
  WINDOW p20 AS (PARTITION BY security_id ORDER BY observation_sequence ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
), metric_reasons AS (
  SELECT
    p.*,
    {a1_reasons} AS a1_reasons,
    {a2_reasons} AS a2_reasons
  FROM point_windows AS p
), metric_values AS (
  SELECT
    m.*,
    CASE WHEN list_contains(m.a1_reasons, 'valid_no_blocker')
      THEN ABS(m.body - m.cloud_center) END AS a1_value,
    CASE WHEN list_contains(m.a2_reasons, 'valid_no_blocker')
      THEN m.a2_outside_count / 20.0 END AS a2_value,
    CASE WHEN list_contains(m.a2_reasons, 'valid_no_blocker')
      THEN m.a2_gap_sum / 20.0 END AS a2b_value
  FROM metric_reasons AS m
), output_rows AS (
  SELECT
    '{run_literal}'::VARCHAR AS run_id,
    security_id, trading_date, observation_sequence, expected_observation_status,
    '{A1_ID}'::VARCHAR AS indicator_id,
    '{RAW_METRIC_NAMES[A1_ID]}'::VARCHAR AS raw_metric_name,
    CAST(a1_value AS DOUBLE) AS raw_value,
    {_status_expression("a1_reasons")} AS validity_status,
    CAST(TO_JSON(a1_reasons) AS VARCHAR) AS reason_codes_json,
    a1_window_start AS input_window_start,
    trading_date AS input_window_end,
    60::INTEGER AS required_observation_count,
    CAST(a1_valid_count AS INTEGER) AS actual_valid_observation_count,
    '{METRIC_ENGINE_VERSION}'::VARCHAR AS metric_engine_version,
    source_ref
  FROM metric_values
  UNION ALL
  SELECT
    '{run_literal}'::VARCHAR,
    security_id, trading_date, observation_sequence, expected_observation_status,
    '{A2_ID}'::VARCHAR,
    '{RAW_METRIC_NAMES[A2_ID]}',
    CAST(a2_value AS DOUBLE),
    {_status_expression("a2_reasons")},
    CAST(TO_JSON(a2_reasons) AS VARCHAR),
    a2_window_start,
    trading_date,
    79::INTEGER,
    CAST(a2_valid_count AS INTEGER),
    '{METRIC_ENGINE_VERSION}',
    source_ref
  FROM metric_values
  UNION ALL
  SELECT
    '{run_literal}'::VARCHAR,
    security_id, trading_date, observation_sequence, expected_observation_status,
    '{A2B_ID}'::VARCHAR,
    '{RAW_METRIC_NAMES[A2B_ID]}',
    CAST(a2b_value AS DOUBLE),
    {_status_expression("a2_reasons")},
    CAST(TO_JSON(a2_reasons) AS VARCHAR),
    a2_window_start,
    trading_date,
    79::INTEGER,
    CAST(a2_valid_count AS INTEGER),
    '{METRIC_ENGINE_VERSION}',
    source_ref
  FROM metric_values
)
SELECT
  run_id, security_id, trading_date, observation_sequence, expected_observation_status,
  indicator_id, raw_metric_name, raw_value, validity_status, reason_codes_json,
  input_window_start, input_window_end, required_observation_count,
  actual_valid_observation_count, metric_engine_version, source_ref
FROM output_rows
ORDER BY security_id, observation_sequence,
  CASE indicator_id WHEN '{A1_ID}' THEN 0 WHEN '{A2_ID}' THEN 1 ELSE 2 END
"""


def _row_reason_expression() -> str:
    return """list_filter([
      CASE WHEN adjusted_open IS NULL OR NOT isfinite(adjusted_open) THEN 'missing_adjusted_open' END,
      CASE WHEN adjusted_close IS NULL OR NOT isfinite(adjusted_close) THEN 'missing_adjusted_close' END,
      CASE WHEN expected_observation_status = 'missing'
             OR (daily_status IS NULL OR lower(trim(CAST(daily_status AS VARCHAR))) NOT IN ('resolved'))
           THEN 'missing_required_history' END,
      CASE WHEN adjusted_open IS NOT NULL AND isfinite(adjusted_open) AND adjusted_open <= 0
           THEN 'nonpositive_adjusted_open' END,
      CASE WHEN adjusted_close IS NOT NULL AND isfinite(adjusted_close) AND adjusted_close <= 0
           THEN 'nonpositive_adjusted_close' END,
      CASE WHEN effective_adj_factor IS NULL OR NOT isfinite(effective_adj_factor)
             OR effective_adj_factor <= 0
             OR adjustment_factor_status IS NULL
             OR lower(trim(CAST(adjustment_factor_status AS VARCHAR))) NOT IN
               ('resolved', 'not_applicable_or_carry_forward', 'neutral_factor_1_policy', 'factor_interval_policy')
           THEN 'adjustment_failure' END,
      CASE WHEN COALESCE(lower(trim(CAST(trading_status AS VARCHAR))), '') = 'suspended'
           THEN 'suspension_in_required_window' END,
      CASE WHEN expected_observation_status = 'listing_pause'
             OR is_listing_pause IS DISTINCT FROM FALSE
           THEN 'listing_pause_in_required_window' END,
      CASE WHEN COALESCE(lower(trim(CAST(trading_status AS VARCHAR))), '') NOT IN
             ('normal_trading', 'limit_up', 'limit_down', 'one_price_limit_up', 'one_price_limit_down',
              'suspended', 'reopen_after_suspension')
           THEN 'invalid_trading_status' END,
      CASE WHEN COALESCE(lower(trim(CAST(trading_status AS VARCHAR))), '') = 'reopen_after_suspension'
           THEN 'reopen_after_suspension' END
    ], x -> x IS NOT NULL)"""


def _window_reason_flags() -> str:
    parts: list[str] = []
    for reason in REASON_CODES[2:]:
        escaped = reason.replace("'", "''")
        parts.append(
            f",\n    MAX(CASE WHEN list_contains(r.row_reasons, '{escaped}') THEN 1 ELSE 0 END)"
            f" OVER p60 AS a1_has_{reason}"
        )
        parts.append(
            f",\n    MAX(CASE WHEN list_contains(r.row_reasons, '{escaped}') THEN 1 ELSE 0 END)"
            f" OVER p79 AS a2_has_{reason}"
        )
    return "".join(parts)


def _metric_reason_expression(prefix: str, required: int, valid_expression: str) -> str:
    base_reasons = [
        f"CASE WHEN {prefix}_window_count < {required} THEN 'window_insufficient' END",
        f"CASE WHEN {prefix}_has_missing_adjusted_open = 1 THEN 'missing_adjusted_open' END",
        f"CASE WHEN {prefix}_has_missing_adjusted_close = 1 THEN 'missing_adjusted_close' END",
        (
            f"CASE WHEN {prefix}_window_count < {required}"
            f" OR {prefix}_has_missing_required_history = 1"
            " THEN 'missing_required_history' END"
        ),
        f"CASE WHEN {prefix}_has_nonpositive_adjusted_open = 1 THEN 'nonpositive_adjusted_open' END",
        f"CASE WHEN {prefix}_has_nonpositive_adjusted_close = 1 THEN 'nonpositive_adjusted_close' END",
        f"CASE WHEN {prefix}_has_adjustment_failure = 1 THEN 'adjustment_failure' END",
        f"CASE WHEN {prefix}_has_suspension_in_required_window = 1 THEN 'suspension_in_required_window' END",
        f"CASE WHEN {prefix}_has_listing_pause_in_required_window = 1 THEN 'listing_pause_in_required_window' END",
        f"CASE WHEN {prefix}_has_invalid_trading_status = 1 THEN 'invalid_trading_status' END",
        f"CASE WHEN {prefix}_has_reopen_after_suspension = 1 THEN 'reopen_after_suspension' END",
    ]
    base_expression = f"list_filter([{', '.join(base_reasons)}], x -> x IS NOT NULL)"
    expression = (
        "CASE WHEN LEN("
        + base_expression
        + f") = 0 AND NOT ({valid_expression}) THEN ['nonpositive_MA'] "
        + "ELSE "
        + base_expression
        + " END"
    )
    return (
        "CASE WHEN LEN("
        + base_expression
        + ") = 0 AND ("
        + valid_expression
        + ") THEN ['valid_no_blocker'] ELSE "
        + expression
        + " END"
    )


def _status_expression(reason_column: str) -> str:
    return (
        f"CASE WHEN list_contains({reason_column}, 'valid_no_blocker') THEN 'valid' "
        f"WHEN list_contains({reason_column}, 'adjustment_failure') "
        f" OR list_contains({reason_column}, 'invalid_trading_status') "
        f" OR list_contains({reason_column}, 'nonpositive_adjusted_open') "
        f" OR list_contains({reason_column}, 'nonpositive_adjusted_close') "
        f" OR list_contains({reason_column}, 'nonpositive_MA') "
        f" OR list_contains({reason_column}, 'suspension_in_required_window') "
        f" OR list_contains({reason_column}, 'listing_pause_in_required_window') THEN 'blocked' "
        f"WHEN list_contains({reason_column}, 'reopen_after_suspension') THEN 'diagnostic_required' "
        "ELSE 'unknown' END"
    )


def _canonical_date(column: str) -> str:
    return (
        "CAST(COALESCE("
        f"try_strptime(CAST({column} AS VARCHAR), '%Y-%m-%d'), "
        f"try_strptime(CAST({column} AS VARCHAR), '%Y%m%d')"
        ") AS DATE)"
    )


def _require_identifier(value: str) -> None:
    if not value or not all(part.isidentifier() for part in value.split(".")):
        raise ValueError(f"unsafe SQL identifier: {value!r}")


def _configure_duckdb_connection(
    connection: Any, *, duckdb_threads: int, memory_limit: str
) -> None:
    """Apply the governed single-process DuckDB resource profile."""

    if isinstance(duckdb_threads, bool) or not isinstance(duckdb_threads, int):
        raise ValueError("duckdb_threads must be an integer")
    if not 1 <= duckdb_threads <= MAX_DUCKDB_THREADS:
        raise ValueError(f"duckdb_threads must be between 1 and {MAX_DUCKDB_THREADS}")
    if not isinstance(memory_limit, str) or not memory_limit.strip():
        raise ValueError("memory_limit must be a non-empty string")
    connection.execute(f"PRAGMA threads={duckdb_threads}")
    connection.execute(f"PRAGMA memory_limit='{_sql_literal(memory_limit)}'")


def _sql_literal(value: str) -> str:
    return str(value).replace("'", "''")


def _write_csv(
    path: Path, fields: Sequence[str], rows: Iterable[Sequence[Any]]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(fields)
        for row in rows:
            writer.writerow([_csv_value(value) for value in row])


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite value cannot be serialized")
        return repr(value)
    return value


_METRIC_PROFILE_FIELDS = (
    "indicator_id",
    "required_observation_count",
    "total_row_count",
    "valid_count",
    "unknown_count",
    "blocked_count",
    "diagnostic_required_count",
    "valid_rate",
    "zero_count",
    "zero_rate_among_valid",
    "positive_count",
    "unique_value_count",
    "min_value",
    "mean_value",
    "stddev_pop_value",
    "q01_value",
    "q05_value",
    "q25_value",
    "median_value",
    "q75_value",
    "q95_value",
    "q99_value",
    "max_value",
    "first_valid_date",
    "last_valid_date",
    "unique_security_count",
    "valid_security_count",
    "nonzero_year_count",
    "max_year_valid_share",
    "max_security_valid_share",
)


def _metric_profile_query() -> str:
    order = _indicator_order_sql("indicator_id")
    return f"""
WITH years AS (
  SELECT indicator_id, YEAR(trading_date) AS calendar_year,
         COUNT(*) FILTER (WHERE validity_status = 'valid') AS valid_count
  FROM exp_a01_raw_metrics GROUP BY indicator_id, calendar_year
), securities AS (
  SELECT indicator_id, security_id,
         COUNT(*) FILTER (WHERE validity_status = 'valid') AS valid_count
  FROM exp_a01_raw_metrics GROUP BY indicator_id, security_id
), base AS (
  SELECT indicator_id,
         CASE indicator_id WHEN '{A1_ID}' THEN 60 ELSE 79 END AS required_observation_count,
         COUNT(*) AS total_row_count,
         COUNT(*) FILTER (WHERE validity_status = 'valid') AS valid_count,
         COUNT(*) FILTER (WHERE validity_status = 'unknown') AS unknown_count,
         COUNT(*) FILTER (WHERE validity_status = 'blocked') AS blocked_count,
         COUNT(*) FILTER (WHERE validity_status = 'diagnostic_required') AS diagnostic_required_count,
         COUNT(*) FILTER (WHERE validity_status = 'valid')::DOUBLE / NULLIF(COUNT(*), 0) AS valid_rate,
         COUNT(*) FILTER (WHERE validity_status = 'valid' AND raw_value = 0) AS zero_count,
         COUNT(*) FILTER (WHERE validity_status = 'valid' AND raw_value = 0)::DOUBLE
           / NULLIF(COUNT(*) FILTER (WHERE validity_status = 'valid'), 0) AS zero_rate_among_valid,
         COUNT(*) FILTER (WHERE validity_status = 'valid' AND raw_value > 0) AS positive_count,
         COUNT(DISTINCT raw_value) FILTER (WHERE validity_status = 'valid') AS unique_value_count,
         MIN(raw_value) FILTER (WHERE validity_status = 'valid') AS min_value,
         AVG(raw_value) FILTER (WHERE validity_status = 'valid') AS mean_value,
         STDDEV_POP(raw_value) FILTER (WHERE validity_status = 'valid') AS stddev_pop_value,
         QUANTILE_CONT(raw_value, 0.01) FILTER (WHERE validity_status = 'valid') AS q01_value,
         QUANTILE_CONT(raw_value, 0.05) FILTER (WHERE validity_status = 'valid') AS q05_value,
         QUANTILE_CONT(raw_value, 0.25) FILTER (WHERE validity_status = 'valid') AS q25_value,
         QUANTILE_CONT(raw_value, 0.50) FILTER (WHERE validity_status = 'valid') AS median_value,
         QUANTILE_CONT(raw_value, 0.75) FILTER (WHERE validity_status = 'valid') AS q75_value,
         QUANTILE_CONT(raw_value, 0.95) FILTER (WHERE validity_status = 'valid') AS q95_value,
         QUANTILE_CONT(raw_value, 0.99) FILTER (WHERE validity_status = 'valid') AS q99_value,
         MAX(raw_value) FILTER (WHERE validity_status = 'valid') AS max_value,
         MIN(trading_date) FILTER (WHERE validity_status = 'valid') AS first_valid_date,
         MAX(trading_date) FILTER (WHERE validity_status = 'valid') AS last_valid_date,
         COUNT(DISTINCT security_id) AS unique_security_count,
         COUNT(DISTINCT security_id) FILTER (WHERE validity_status = 'valid') AS valid_security_count
  FROM exp_a01_raw_metrics GROUP BY indicator_id
), year_shares AS (
  SELECT y.indicator_id,
         COUNT(*) FILTER (WHERE y.valid_count > 0) AS nonzero_year_count,
         MAX(y.valid_count::DOUBLE / NULLIF(b.valid_count, 0)) AS max_year_valid_share
  FROM years y JOIN base b USING (indicator_id) GROUP BY y.indicator_id
), security_shares AS (
  SELECT s.indicator_id,
         MAX(s.valid_count::DOUBLE / NULLIF(b.valid_count, 0)) AS max_security_valid_share
  FROM securities s JOIN base b USING (indicator_id) GROUP BY s.indicator_id
)
SELECT b.indicator_id, b.required_observation_count, b.total_row_count, b.valid_count,
       b.unknown_count, b.blocked_count, b.diagnostic_required_count, b.valid_rate,
       b.zero_count, b.zero_rate_among_valid, b.positive_count, b.unique_value_count,
       b.min_value, b.mean_value, b.stddev_pop_value, b.q01_value, b.q05_value,
       b.q25_value, b.median_value, b.q75_value, b.q95_value, b.q99_value, b.max_value,
       b.first_valid_date, b.last_valid_date, b.unique_security_count,
       b.valid_security_count, y.nonzero_year_count, y.max_year_valid_share,
       s.max_security_valid_share
FROM base b JOIN year_shares y USING (indicator_id) JOIN security_shares s USING (indicator_id)
ORDER BY {order}
"""


_VALIDITY_PROFILE_FIELDS = (
    "indicator_id",
    "profile_dimension",
    "profile_value",
    "row_count",
    "denominator_count",
    "row_share",
)


def _validity_profile_query() -> str:
    order = _indicator_order_sql("indicator_id")
    return f"""
WITH totals AS (
  SELECT indicator_id, COUNT(*) AS denominator_count
  FROM exp_a01_raw_metrics GROUP BY indicator_id
), rows AS (
  SELECT r.indicator_id, 'validity_status' AS profile_dimension,
         r.validity_status AS profile_value, COUNT(*) AS row_count,
         t.denominator_count
  FROM exp_a01_raw_metrics r JOIN totals t USING (indicator_id)
  GROUP BY r.indicator_id, r.validity_status, t.denominator_count
  UNION ALL
  SELECT r.indicator_id, 'reason_code', json_extract_string(j.value, '$'),
         COUNT(*), t.denominator_count
  FROM exp_a01_raw_metrics r JOIN totals t USING (indicator_id),
       LATERAL json_each(r.reason_codes_json) j
  GROUP BY r.indicator_id, json_extract_string(j.value, '$'), t.denominator_count
  UNION ALL
  SELECT r.indicator_id, 'current_expected_observation_status',
         r.expected_observation_status, COUNT(*), t.denominator_count
  FROM exp_a01_raw_metrics r JOIN totals t USING (indicator_id)
  GROUP BY r.indicator_id, r.expected_observation_status, t.denominator_count
)
SELECT indicator_id, profile_dimension, profile_value, row_count, denominator_count,
       row_count::DOUBLE / NULLIF(denominator_count, 0) AS row_share
FROM rows
ORDER BY {order}, profile_dimension, profile_value
"""


_YEAR_PROFILE_FIELDS = (
    "calendar_year",
    "indicator_id",
    "row_count",
    "valid_count",
    "valid_rate",
    "zero_count",
    "zero_rate_among_valid",
    "min_value",
    "q05_value",
    "median_value",
    "q95_value",
    "max_value",
    "unique_security_count",
    "valid_security_count",
)


def _year_profile_query() -> str:
    return f"""
SELECT YEAR(trading_date) AS calendar_year, indicator_id, COUNT(*) AS row_count,
       COUNT(*) FILTER (WHERE validity_status = 'valid') AS valid_count,
       COUNT(*) FILTER (WHERE validity_status = 'valid')::DOUBLE / NULLIF(COUNT(*), 0) AS valid_rate,
       COUNT(*) FILTER (WHERE validity_status = 'valid' AND raw_value = 0) AS zero_count,
       COUNT(*) FILTER (WHERE validity_status = 'valid' AND raw_value = 0)::DOUBLE
         / NULLIF(COUNT(*) FILTER (WHERE validity_status = 'valid'), 0) AS zero_rate_among_valid,
       MIN(raw_value) FILTER (WHERE validity_status = 'valid') AS min_value,
       QUANTILE_CONT(raw_value, 0.05) FILTER (WHERE validity_status = 'valid') AS q05_value,
       QUANTILE_CONT(raw_value, 0.50) FILTER (WHERE validity_status = 'valid') AS median_value,
       QUANTILE_CONT(raw_value, 0.95) FILTER (WHERE validity_status = 'valid') AS q95_value,
       MAX(raw_value) FILTER (WHERE validity_status = 'valid') AS max_value,
       COUNT(DISTINCT security_id) AS unique_security_count,
       COUNT(DISTINCT security_id) FILTER (WHERE validity_status = 'valid') AS valid_security_count
FROM exp_a01_raw_metrics
GROUP BY calendar_year, indicator_id
ORDER BY calendar_year, CASE indicator_id WHEN '{A1_ID}' THEN 0 WHEN '{A2_ID}' THEN 1 ELSE 2 END
"""


_SECURITY_PROFILE_FIELDS = (
    "security_id",
    "indicator_id",
    "row_count",
    "valid_count",
    "valid_rate",
    "zero_count",
    "zero_rate_among_valid",
    "first_date",
    "last_date",
    "first_valid_date",
    "last_valid_date",
    "min_value",
    "median_value",
    "max_value",
)


def _security_profile_query() -> str:
    return f"""
SELECT security_id, indicator_id, COUNT(*) AS row_count,
       COUNT(*) FILTER (WHERE validity_status = 'valid') AS valid_count,
       COUNT(*) FILTER (WHERE validity_status = 'valid')::DOUBLE / NULLIF(COUNT(*), 0) AS valid_rate,
       COUNT(*) FILTER (WHERE validity_status = 'valid' AND raw_value = 0) AS zero_count,
       COUNT(*) FILTER (WHERE validity_status = 'valid' AND raw_value = 0)::DOUBLE
         / NULLIF(COUNT(*) FILTER (WHERE validity_status = 'valid'), 0) AS zero_rate_among_valid,
       MIN(trading_date) AS first_date, MAX(trading_date) AS last_date,
       MIN(trading_date) FILTER (WHERE validity_status = 'valid') AS first_valid_date,
       MAX(trading_date) FILTER (WHERE validity_status = 'valid') AS last_valid_date,
       MIN(raw_value) FILTER (WHERE validity_status = 'valid') AS min_value,
       QUANTILE_CONT(raw_value, 0.50) FILTER (WHERE validity_status = 'valid') AS median_value,
       MAX(raw_value) FILTER (WHERE validity_status = 'valid') AS max_value
FROM exp_a01_raw_metrics
GROUP BY security_id, indicator_id
ORDER BY security_id, CASE indicator_id WHEN '{A1_ID}' THEN 0 WHEN '{A2_ID}' THEN 1 ELSE 2 END
"""


def _indicator_order_sql(column: str) -> str:
    return (
        f"CASE {column} WHEN '{A1_ID}' THEN 0 WHEN '{A2_ID}' THEN 1 "
        f"WHEN '{A2B_ID}' THEN 2 ELSE 99 END, {column}"
    )
