# ruff: noqa: E501

"""Set-based EXP-A02 raw-domain and availability aggregation.

EXP-A02 consumes only the accepted EXP-A01 raw artifact.  The implementation
stage exposes this module for synthetic fixtures; it never opens the approved
large local-only artifact and never creates a new DuckDB database.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

TASK_ID = "EXP-A02"
PROGRAM_ID = "EXP-A"
A01_RUN_ID = "EXP-A01-20260717T040145984Z"
A01_IMPLEMENTATION_SHA = "c9a52dc29f7d41c85ab416e99bb9ef8cc6411b9d"
A01_RESULT_COMMIT = "b7be2577233c045e507efe05d20601a20d373c9b"
RAW_TABLE = "exp_a01_raw_metrics"
GRID_RESIDUAL_TOLERANCE = 1e-12
EXTREME_TAIL_SIZE = 20

A1_ID = "A1_LogBodyCenterToMACloudCenter_5_60"
A2_ID = "A2_BodyCenterOutsideMACloudRate20_5_60"
A2B_ID = "A2b_BodyToMACloudGapMean20_5_60"
INDICATOR_IDS = (A1_ID, A2_ID, A2B_ID)
INDICATOR_ORDER = {
    indicator_id: index for index, indicator_id in enumerate(INDICATOR_IDS)
}

VALIDITY_STATUSES = ("valid", "unknown", "blocked", "diagnostic_required")
EXPECTED_OBSERVATION_STATUSES = ("present", "listing_pause", "missing", "unresolved")
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

RAW_COLUMNS = (
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

OUTPUT_FILES = {
    "raw_domain_profile": "exp_a02_raw_domain_profile.csv",
    "indicator_availability": "exp_a02_indicator_availability.csv",
    "common_valid_availability": "exp_a02_common_valid_availability.csv",
    "validity_status_profile": "exp_a02_validity_status_profile.csv",
    "reason_code_profile": "exp_a02_reason_code_profile.csv",
    "reason_combination_profile": "exp_a02_reason_combination_profile.csv",
    "year_availability": "exp_a02_year_availability.csv",
    "security_availability": "exp_a02_security_availability.csv",
    "extreme_value_sample": "exp_a02_extreme_value_sample.csv",
    "manifest": "exp_a02_manifest.json",
    "validator_result": "exp_a02_validator_result.json",
    "anomaly_scan": "exp_a02_anomaly_scan.json",
    "result_analysis": "exp_a02_result_analysis.md",
}

CSV_FIELDS = {
    "raw_domain_profile": (
        "indicator_id",
        "total_row_count",
        "valid_count",
        "unknown_count",
        "blocked_count",
        "diagnostic_required_count",
        "valid_rate",
        "valid_raw_null_count",
        "nonvalid_raw_nonnull_count",
        "nonfinite_valid_count",
        "domain_violation_count",
        "min_value",
        "q01_value",
        "q05_value",
        "q25_value",
        "median_value",
        "q75_value",
        "q95_value",
        "q99_value",
        "max_value",
        "mean_value",
        "stddev_pop_value",
        "zero_count",
        "zero_rate_among_valid",
        "positive_count",
        "unique_value_count",
        "discrete_grid_step",
        "grid_violation_count",
        "grid_residual_max",
        "first_valid_date",
        "last_valid_date",
    ),
    "indicator_availability": (
        "indicator_id",
        "expected_row_count",
        "present_row_count",
        "native_valid_count",
        "native_valid_rate_expected",
        "native_valid_rate_present",
        "unknown_count",
        "blocked_count",
        "diagnostic_required_count",
        "total_security_count",
        "valid_security_count",
        "total_year_count",
        "valid_year_count",
        "first_valid_date",
        "last_valid_date",
        "max_year_valid_share",
        "max_security_valid_share",
    ),
    "common_valid_availability": (
        "set_id",
        "member_indicator_ids_json",
        "expected_key_count",
        "all_member_rows_present_count",
        "common_valid_count",
        "common_valid_rate_expected",
        "union_valid_count",
        "union_valid_rate_expected",
    ),
    "validity_status_profile": (
        "indicator_id",
        "validity_status",
        "row_count",
        "denominator_count",
        "row_share",
    ),
    "reason_code_profile": (
        "indicator_id",
        "reason_code",
        "row_count",
        "denominator_count",
        "row_share",
    ),
    "reason_combination_profile": (
        "indicator_id",
        "reason_codes_json",
        "row_count",
        "denominator_count",
        "row_share",
    ),
    "year_availability": (
        "calendar_year",
        "indicator_id",
        "row_count",
        "present_count",
        "valid_count",
        "valid_rate_expected",
        "valid_rate_present",
        "unknown_count",
        "blocked_count",
        "diagnostic_required_count",
        "unique_security_count",
        "valid_security_count",
    ),
    "security_availability": (
        "security_id",
        "indicator_id",
        "row_count",
        "present_count",
        "valid_count",
        "valid_rate_expected",
        "valid_rate_present",
        "unknown_count",
        "blocked_count",
        "diagnostic_required_count",
        "first_date",
        "last_date",
        "first_valid_date",
        "last_valid_date",
    ),
    "extreme_value_sample": (
        "indicator_id",
        "tail",
        "rank",
        "security_id",
        "trading_date",
        "observation_sequence",
        "raw_value",
    ),
}

FORBIDDEN_OUTPUT_FIELD_NAMES = (
    "percentile",
    "score",
    "threshold",
    "q",
    "state",
    "active",
    "Jaccard",
    "correlation",
    "redundancy",
    "winner",
    "selected_indicator",
    "replacement",
    "A_layer_approved",
    "PCATV",
    "future_return",
    "future_volatility",
    "future_direction",
    "backtest",
    "portfolio",
    "transaction_cost",
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value}")
    return value


def _indicator_order_sql(column: str) -> str:
    _safe_identifier(column)
    return (
        f"CASE {column} WHEN '{A1_ID}' THEN 0 WHEN '{A2_ID}' THEN 1 "
        f"WHEN '{A2B_ID}' THEN 2 ELSE 99 END, {column}"
    )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _rows(cursor: Any, fields: Sequence[str]) -> list[dict[str, Any]]:
    return [dict(zip(fields, row, strict=True)) for row in cursor.fetchall()]


def _csv_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return repr(value)
    return value


def write_profiles(
    output_root: Path, profiles: Mapping[str, Sequence[Mapping[str, Any]]]
) -> None:
    """Write the nine compact CSVs using canonical UTF-8/LF text."""

    output_root.mkdir(parents=True, exist_ok=True)
    for profile_name, filename in OUTPUT_FILES.items():
        if profile_name not in CSV_FIELDS:
            continue
        rows = profiles.get(profile_name, ())
        fields = CSV_FIELDS[profile_name]
        with (output_root / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fields, extrasaction="raise", lineterminator="\n"
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {field: _csv_scalar(row.get(field)) for field in fields}
                )


def build_profiles(
    connection: Any,
    *,
    expected_row_count: int | None = None,
    raw_table: str = RAW_TABLE,
) -> dict[str, list[dict[str, Any]]]:
    """Build all A02 aggregates with DuckDB set-based SQL.

    The SQL here is the producer implementation.  The validator intentionally
    defines independent aggregate queries instead of importing these queries.
    """

    table = _safe_identifier(raw_table)
    if expected_row_count is None:
        expected_row_count = int(
            connection.execute(
                f"""SELECT COUNT(*) FROM (
                    SELECT DISTINCT security_id, trading_date, observation_sequence
                    FROM {table}
                )"""
            ).fetchone()[0]
        )
    if expected_row_count < 0:
        raise ValueError("expected_row_count must be nonnegative")

    profiles = {
        "raw_domain_profile": _raw_domain_profile(connection, table),
        "indicator_availability": _indicator_availability(
            connection, table, expected_row_count
        ),
        "common_valid_availability": _common_valid_availability(
            connection, table, expected_row_count
        ),
        "validity_status_profile": _validity_status_profile(connection, table),
        "reason_code_profile": _reason_code_profile(connection, table),
        "reason_combination_profile": _reason_combination_profile(connection, table),
        "year_availability": _year_availability(connection, table, expected_row_count),
        "security_availability": _security_availability(
            connection, table, expected_row_count
        ),
        "extreme_value_sample": _extreme_value_sample(connection, table),
    }
    return profiles


def _raw_domain_profile(connection: Any, table: str) -> list[dict[str, Any]]:
    indicators = ", ".join(
        f"({_sql_literal(indicator_id)}, {index})"
        for index, indicator_id in enumerate(INDICATOR_IDS)
    )
    query = f"""
WITH indicator_list(indicator_id, indicator_order) AS (VALUES {indicators}),
aggregates AS (
  SELECT indicator_id,
    COUNT(*) AS total_row_count,
    COUNT(*) FILTER (WHERE validity_status='valid') AS valid_count,
    COUNT(*) FILTER (WHERE validity_status='unknown') AS unknown_count,
    COUNT(*) FILTER (WHERE validity_status='blocked') AS blocked_count,
    COUNT(*) FILTER (WHERE validity_status='diagnostic_required') AS diagnostic_required_count,
    COUNT(*) FILTER (WHERE validity_status='valid' AND raw_value IS NULL) AS valid_raw_null_count,
    COUNT(*) FILTER (WHERE validity_status<>'valid' AND raw_value IS NOT NULL) AS nonvalid_raw_nonnull_count,
    COUNT(*) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND NOT isfinite(raw_value)) AS nonfinite_valid_count,
    COUNT(*) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)
      AND ((indicator_id IN ({_sql_literal(A1_ID)}, {_sql_literal(A2B_ID)}) AND raw_value < 0)
        OR (indicator_id={_sql_literal(A2_ID)} AND (raw_value < 0 OR raw_value > 1)))) AS domain_violation_count,
    COUNT(*) FILTER (WHERE validity_status='valid')::DOUBLE / NULLIF(COUNT(*), 0) AS valid_rate,
    MIN(raw_value) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS min_value,
    QUANTILE_CONT(raw_value, 0.01) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS q01_value,
    QUANTILE_CONT(raw_value, 0.05) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS q05_value,
    QUANTILE_CONT(raw_value, 0.25) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS q25_value,
    QUANTILE_CONT(raw_value, 0.50) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS median_value,
    QUANTILE_CONT(raw_value, 0.75) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS q75_value,
    QUANTILE_CONT(raw_value, 0.95) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS q95_value,
    QUANTILE_CONT(raw_value, 0.99) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS q99_value,
    MAX(raw_value) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS max_value,
    AVG(raw_value) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS mean_value,
    STDDEV_POP(raw_value) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS stddev_pop_value,
    COUNT(*) FILTER (WHERE validity_status='valid' AND raw_value=0) AS zero_count,
    COUNT(*) FILTER (WHERE validity_status='valid' AND raw_value=0)::DOUBLE / NULLIF(COUNT(*) FILTER (WHERE validity_status='valid'),0) AS zero_rate_among_valid,
    COUNT(*) FILTER (WHERE validity_status='valid' AND raw_value>0) AS positive_count,
    COUNT(DISTINCT raw_value) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS unique_value_count,
    MIN(trading_date) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS first_valid_date,
    MAX(trading_date) FILTER (WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS last_valid_date,
    MAX(ABS(raw_value * 20.0 - ROUND(raw_value * 20.0))) FILTER (WHERE indicator_id={_sql_literal(A2_ID)} AND validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)) AS grid_residual_max,
    COUNT(*) FILTER (WHERE indicator_id={_sql_literal(A2_ID)} AND validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)
      AND ABS(raw_value * 20.0 - ROUND(raw_value * 20.0)) > {GRID_RESIDUAL_TOLERANCE}) AS grid_violation_count
  FROM {table}
  GROUP BY indicator_id
)
SELECT i.indicator_id,
  COALESCE(a.total_row_count,0) AS total_row_count,
  COALESCE(a.valid_count,0) AS valid_count,
  COALESCE(a.unknown_count,0) AS unknown_count,
  COALESCE(a.blocked_count,0) AS blocked_count,
  COALESCE(a.diagnostic_required_count,0) AS diagnostic_required_count,
  COALESCE(a.valid_rate,0.0) AS valid_rate,
  COALESCE(a.valid_raw_null_count,0) AS valid_raw_null_count,
  COALESCE(a.nonvalid_raw_nonnull_count,0) AS nonvalid_raw_nonnull_count,
  COALESCE(a.nonfinite_valid_count,0) AS nonfinite_valid_count,
  COALESCE(a.domain_violation_count,0) AS domain_violation_count,
  a.min_value,a.q01_value,a.q05_value,a.q25_value,a.median_value,a.q75_value,
  a.q95_value,a.q99_value,a.max_value,a.mean_value,a.stddev_pop_value,
  COALESCE(a.zero_count,0) AS zero_count,COALESCE(a.zero_rate_among_valid,0.0) AS zero_rate_among_valid,
  COALESCE(a.positive_count,0) AS positive_count,COALESCE(a.unique_value_count,0) AS unique_value_count,
  CASE WHEN i.indicator_id={_sql_literal(A2_ID)} THEN 0.05 ELSE NULL END AS discrete_grid_step,
  CASE WHEN i.indicator_id={_sql_literal(A2_ID)} THEN COALESCE(a.grid_violation_count,0) ELSE 0 END AS grid_violation_count,
  CASE WHEN i.indicator_id={_sql_literal(A2_ID)} THEN a.grid_residual_max ELSE NULL END AS grid_residual_max,
  a.first_valid_date,a.last_valid_date
FROM indicator_list i LEFT JOIN aggregates a USING (indicator_id)
ORDER BY i.indicator_order
"""
    return _rows(connection.execute(query), CSV_FIELDS["raw_domain_profile"])


def _indicator_availability(
    connection: Any, table: str, expected_row_count: int
) -> list[dict[str, Any]]:
    indicators = ", ".join(
        f"({_sql_literal(indicator_id)}, {index})"
        for index, indicator_id in enumerate(INDICATOR_IDS)
    )
    query = f"""
WITH indicator_list(indicator_id, indicator_order) AS (VALUES {indicators}),
key_rows AS (
  SELECT security_id,trading_date,observation_sequence,
    MAX(CASE WHEN expected_observation_status='present' THEN 1 ELSE 0 END) AS is_present
  FROM {table} GROUP BY 1,2,3
),
base AS (
  SELECT indicator_id,
    COUNT(*) FILTER (WHERE validity_status='valid') AS native_valid_count,
    COUNT(*) FILTER (WHERE validity_status='unknown') AS unknown_count,
    COUNT(*) FILTER (WHERE validity_status='blocked') AS blocked_count,
    COUNT(*) FILTER (WHERE validity_status='diagnostic_required') AS diagnostic_required_count,
    COUNT(DISTINCT security_id) AS total_security_count,
    COUNT(DISTINCT security_id) FILTER (WHERE validity_status='valid') AS valid_security_count,
    COUNT(DISTINCT YEAR(trading_date)) AS total_year_count,
    COUNT(DISTINCT YEAR(trading_date)) FILTER (WHERE validity_status='valid') AS valid_year_count,
    MIN(trading_date) FILTER (WHERE validity_status='valid') AS first_valid_date,
    MAX(trading_date) FILTER (WHERE validity_status='valid') AS last_valid_date
  FROM {table} GROUP BY indicator_id
),
years AS (
  SELECT indicator_id,YEAR(trading_date) AS calendar_year,
    COUNT(*) FILTER (WHERE validity_status='valid') AS valid_count
  FROM {table} GROUP BY 1,2
),
securities AS (
  SELECT indicator_id,security_id,COUNT(*) FILTER (WHERE validity_status='valid') AS valid_count
  FROM {table} GROUP BY 1,2
),
year_share AS (
  SELECT y.indicator_id,MAX(y.valid_count::DOUBLE / NULLIF(b.native_valid_count,0)) AS max_year_valid_share
  FROM years y JOIN base b USING (indicator_id) GROUP BY y.indicator_id
),
security_share AS (
  SELECT s.indicator_id,MAX(s.valid_count::DOUBLE / NULLIF(b.native_valid_count,0)) AS max_security_valid_share
  FROM securities s JOIN base b USING (indicator_id) GROUP BY s.indicator_id
),
present AS (SELECT COUNT(*) FILTER (WHERE is_present=1) AS present_row_count FROM key_rows)
SELECT i.indicator_id,{expected_row_count} AS expected_row_count,
  COALESCE(p.present_row_count,0) AS present_row_count,
  COALESCE(b.native_valid_count,0) AS native_valid_count,
  COALESCE(b.native_valid_count::DOUBLE / NULLIF({expected_row_count},0),0.0) AS native_valid_rate_expected,
  COALESCE(b.native_valid_count::DOUBLE / NULLIF(p.present_row_count,0),0.0) AS native_valid_rate_present,
  COALESCE(b.unknown_count,0) AS unknown_count,COALESCE(b.blocked_count,0) AS blocked_count,
  COALESCE(b.diagnostic_required_count,0) AS diagnostic_required_count,
  COALESCE(b.total_security_count,0) AS total_security_count,COALESCE(b.valid_security_count,0) AS valid_security_count,
  COALESCE(b.total_year_count,0) AS total_year_count,COALESCE(b.valid_year_count,0) AS valid_year_count,
  b.first_valid_date,b.last_valid_date,COALESCE(y.max_year_valid_share,0.0) AS max_year_valid_share,
  COALESCE(s.max_security_valid_share,0.0) AS max_security_valid_share
FROM indicator_list i LEFT JOIN base b USING (indicator_id)
CROSS JOIN present p LEFT JOIN year_share y USING (indicator_id) LEFT JOIN security_share s USING (indicator_id)
ORDER BY i.indicator_order
"""
    return _rows(connection.execute(query), CSV_FIELDS["indicator_availability"])


def _common_valid_availability(
    connection: Any, table: str, expected_row_count: int
) -> list[dict[str, Any]]:
    groups = (
        ("A1_A2", (A1_ID, A2_ID)),
        ("A1_A2b", (A1_ID, A2B_ID)),
        ("A2_A2b", (A2_ID, A2B_ID)),
        ("A1_A2_A2b", INDICATOR_IDS),
    )
    rows: list[dict[str, Any]] = []
    for set_id, members in groups:
        member_sql = ", ".join(_sql_literal(value) for value in members)
        valid_flags = ", ".join(
            f"MAX(CASE WHEN indicator_id={_sql_literal(value)} AND validity_status='valid' THEN 1 ELSE 0 END) AS v{index}"
            for index, value in enumerate(members)
        )
        common_expr = " + ".join(f"v{index}" for index in range(len(members)))
        query = f"""
WITH key_rows AS (
  SELECT security_id,trading_date,observation_sequence,
    COUNT(DISTINCT indicator_id) FILTER (WHERE indicator_id IN ({member_sql})) AS member_row_count,
    {valid_flags}
  FROM {table} GROUP BY 1,2,3
)
SELECT {_sql_literal(set_id)} AS set_id,
  {_sql_literal(json.dumps(list(members), separators=(",", ":")))} AS member_indicator_ids_json,
  {expected_row_count} AS expected_key_count,
  COUNT(*) FILTER (WHERE member_row_count={len(members)}) AS all_member_rows_present_count,
  COUNT(*) FILTER (WHERE member_row_count={len(members)} AND {common_expr}={len(members)}) AS common_valid_count,
  COUNT(*) FILTER (WHERE member_row_count={len(members)} AND {common_expr}={len(members)})::DOUBLE / NULLIF({expected_row_count},0) AS common_valid_rate_expected,
  COUNT(*) FILTER (WHERE member_row_count={len(members)} AND {common_expr}>0) AS union_valid_count,
  COUNT(*) FILTER (WHERE member_row_count={len(members)} AND {common_expr}>0)::DOUBLE / NULLIF({expected_row_count},0) AS union_valid_rate_expected
FROM key_rows
"""
        rows.extend(
            _rows(connection.execute(query), CSV_FIELDS["common_valid_availability"])
        )
    return rows


def _validity_status_profile(connection: Any, table: str) -> list[dict[str, Any]]:
    indicators = ", ".join(
        f"({_sql_literal(indicator_id)}, {index})"
        for index, indicator_id in enumerate(INDICATOR_IDS)
    )
    statuses = ", ".join(
        f"({_sql_literal(status)}, {index})"
        for index, status in enumerate(VALIDITY_STATUSES)
    )
    query = f"""
WITH indicator_list(indicator_id,indicator_order) AS (VALUES {indicators}),
status_list(validity_status,status_order) AS (VALUES {statuses}),
totals AS (SELECT indicator_id,COUNT(*) AS denominator_count FROM {table} GROUP BY 1)
SELECT i.indicator_id,s.validity_status,
  COUNT(r.indicator_id) AS row_count,COALESCE(t.denominator_count,0) AS denominator_count,
  COUNT(r.indicator_id)::DOUBLE / NULLIF(t.denominator_count,0) AS row_share
FROM indicator_list i CROSS JOIN status_list s
LEFT JOIN {table} r ON r.indicator_id=i.indicator_id AND r.validity_status=s.validity_status
LEFT JOIN totals t ON t.indicator_id=i.indicator_id
GROUP BY i.indicator_order,i.indicator_id,s.status_order,s.validity_status,t.denominator_count
ORDER BY i.indicator_order,s.status_order
"""
    return _rows(connection.execute(query), CSV_FIELDS["validity_status_profile"])


def _reason_code_profile(connection: Any, table: str) -> list[dict[str, Any]]:
    indicators = ", ".join(
        f"({_sql_literal(indicator_id)}, {index})"
        for index, indicator_id in enumerate(INDICATOR_IDS)
    )
    reasons = ", ".join(
        f"({_sql_literal(reason)}, {index})"
        for index, reason in enumerate(REASON_CODES)
    )
    query = f"""
WITH indicator_list(indicator_id,indicator_order) AS (VALUES {indicators}),
reason_list(reason_code,reason_order) AS (VALUES {reasons}),
totals AS (SELECT indicator_id,COUNT(*) AS denominator_count FROM {table} GROUP BY 1),
reason_rows AS (
  SELECT r.indicator_id,json_extract_string(j.value,'$') AS reason_code
  FROM {table} r,LATERAL json_each(CASE WHEN json_valid(r.reason_codes_json) THEN r.reason_codes_json ELSE '[]' END) j
)
SELECT i.indicator_id,rc.reason_code,COUNT(rr.reason_code) AS row_count,
  COALESCE(t.denominator_count,0) AS denominator_count,
  COUNT(rr.reason_code)::DOUBLE / NULLIF(t.denominator_count,0) AS row_share
FROM indicator_list i CROSS JOIN reason_list rc
LEFT JOIN reason_rows rr ON rr.indicator_id=i.indicator_id AND rr.reason_code=rc.reason_code
LEFT JOIN totals t ON t.indicator_id=i.indicator_id
GROUP BY i.indicator_order,i.indicator_id,rc.reason_order,rc.reason_code,t.denominator_count
ORDER BY i.indicator_order,rc.reason_order
"""
    return _rows(connection.execute(query), CSV_FIELDS["reason_code_profile"])


def _reason_combination_profile(connection: Any, table: str) -> list[dict[str, Any]]:
    query = f"""
WITH totals AS (SELECT indicator_id,COUNT(*) AS denominator_count FROM {table} GROUP BY 1)
SELECT r.indicator_id,r.reason_codes_json,COUNT(*) AS row_count,t.denominator_count,
  COUNT(*)::DOUBLE / NULLIF(t.denominator_count,0) AS row_share
FROM {table} r JOIN totals t USING (indicator_id)
GROUP BY r.indicator_id,r.reason_codes_json,t.denominator_count
ORDER BY {_indicator_order_sql("indicator_id")},r.reason_codes_json
"""
    return _rows(connection.execute(query), CSV_FIELDS["reason_combination_profile"])


def _year_availability(
    connection: Any, table: str, expected_row_count: int
) -> list[dict[str, Any]]:
    query = f"""
SELECT YEAR(trading_date) AS calendar_year,indicator_id,COUNT(*) AS row_count,
  COUNT(*) FILTER (WHERE expected_observation_status='present') AS present_count,
  COUNT(*) FILTER (WHERE validity_status='valid') AS valid_count,
  COUNT(*) FILTER (WHERE validity_status='valid')::DOUBLE / NULLIF(COUNT(*),0) AS valid_rate_expected,
  COUNT(*) FILTER (WHERE validity_status='valid')::DOUBLE / NULLIF(COUNT(*) FILTER (WHERE expected_observation_status='present'),0) AS valid_rate_present,
  COUNT(*) FILTER (WHERE validity_status='unknown') AS unknown_count,
  COUNT(*) FILTER (WHERE validity_status='blocked') AS blocked_count,
  COUNT(*) FILTER (WHERE validity_status='diagnostic_required') AS diagnostic_required_count,
  COUNT(DISTINCT security_id) AS unique_security_count,
  COUNT(DISTINCT security_id) FILTER (WHERE validity_status='valid') AS valid_security_count
FROM {table}
GROUP BY calendar_year,indicator_id
ORDER BY calendar_year,{_indicator_order_sql("indicator_id")}
"""
    return _rows(connection.execute(query), CSV_FIELDS["year_availability"])


def _security_availability(
    connection: Any, table: str, expected_row_count: int
) -> list[dict[str, Any]]:
    query = f"""
SELECT security_id,indicator_id,COUNT(*) AS row_count,
  COUNT(*) FILTER (WHERE expected_observation_status='present') AS present_count,
  COUNT(*) FILTER (WHERE validity_status='valid') AS valid_count,
  COUNT(*) FILTER (WHERE validity_status='valid')::DOUBLE / NULLIF(COUNT(*),0) AS valid_rate_expected,
  COUNT(*) FILTER (WHERE validity_status='valid')::DOUBLE / NULLIF(COUNT(*) FILTER (WHERE expected_observation_status='present'),0) AS valid_rate_present,
  COUNT(*) FILTER (WHERE validity_status='unknown') AS unknown_count,
  COUNT(*) FILTER (WHERE validity_status='blocked') AS blocked_count,
  COUNT(*) FILTER (WHERE validity_status='diagnostic_required') AS diagnostic_required_count,
  MIN(trading_date) AS first_date,MAX(trading_date) AS last_date,
  MIN(trading_date) FILTER (WHERE validity_status='valid') AS first_valid_date,
  MAX(trading_date) FILTER (WHERE validity_status='valid') AS last_valid_date
FROM {table}
GROUP BY security_id,indicator_id
ORDER BY security_id,{_indicator_order_sql("indicator_id")}
"""
    return _rows(connection.execute(query), CSV_FIELDS["security_availability"])


def _extreme_value_sample(connection: Any, table: str) -> list[dict[str, Any]]:
    query = f"""
WITH valid_rows AS (
  SELECT indicator_id,security_id,trading_date,observation_sequence,raw_value,
    ROW_NUMBER() OVER (PARTITION BY indicator_id ORDER BY raw_value ASC,security_id ASC,observation_sequence ASC) AS lower_rank,
    ROW_NUMBER() OVER (PARTITION BY indicator_id ORDER BY raw_value DESC,security_id ASC,observation_sequence ASC) AS upper_rank
  FROM {table}
  WHERE validity_status='valid' AND raw_value IS NOT NULL AND isfinite(raw_value)
), tails AS (
  SELECT indicator_id,'lower' AS tail,lower_rank AS rank,security_id,trading_date,observation_sequence,raw_value
  FROM valid_rows WHERE lower_rank <= {EXTREME_TAIL_SIZE}
  UNION ALL
  SELECT indicator_id,'upper' AS tail,upper_rank AS rank,security_id,trading_date,observation_sequence,raw_value
  FROM valid_rows WHERE upper_rank <= {EXTREME_TAIL_SIZE}
)
SELECT indicator_id,tail,rank,security_id,trading_date,observation_sequence,raw_value
FROM tails
ORDER BY {_indicator_order_sql("indicator_id")},CASE tail WHEN 'lower' THEN 0 ELSE 1 END,rank
"""
    return _rows(connection.execute(query), CSV_FIELDS["extreme_value_sample"])


def build_anomaly_scan(
    profiles: Mapping[str, Sequence[Mapping[str, Any]]],
    validator_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the small anomaly artifact from aggregate-level observations."""

    blocking: list[str] = []
    investigations: list[str] = []
    if validator_result is not None and validator_result.get("status") != "passed":
        blocking.append("aggregate_validator_failed")
    for row in profiles.get("indicator_availability", ()):
        indicator = str(row["indicator_id"])
        if float(row.get("native_valid_rate_expected") or 0.0) < 0.80:
            investigations.append(f"native_valid_rate_expected_below_0_80:{indicator}")
        if float(row.get("max_year_valid_share") or 0.0) > 0.50:
            investigations.append(f"max_year_valid_share_above_0_50:{indicator}")
        if float(row.get("max_security_valid_share") or 0.0) > 0.10:
            investigations.append(f"max_security_valid_share_above_0_10:{indicator}")
    for row in profiles.get("raw_domain_profile", ()):
        indicator = str(row["indicator_id"])
        if int(row.get("valid_count") or 0) > 0 and int(
            row.get("zero_count") or 0
        ) == int(row["valid_count"]):
            investigations.append(f"valid_values_all_zero:{indicator}")
        if (
            int(row.get("unique_value_count") or 0) == 1
            and int(row.get("valid_count") or 0) > 0
        ):
            investigations.append(f"valid_values_single_value:{indicator}")
        if (
            indicator == A2_ID
            and int(row.get("grid_violation_count") or 0) == 0
            and int(row.get("unique_value_count") or 0) <= 2
        ):
            investigations.append("a2_grid_levels_at_most_2")
    for row in profiles.get("year_availability", ()):
        if int(row.get("valid_count") or 0) == 0:
            investigations.append(
                f"year_without_valid_rows:{row['calendar_year']}:{row['indicator_id']}"
            )
    for row in profiles.get("security_availability", ()):
        if int(row.get("valid_count") or 0) == 0:
            investigations.append(
                f"security_without_valid_rows:{row['security_id']}:{row['indicator_id']}"
            )
    status = (
        "failed"
        if blocking
        else ("passed_with_investigation_items" if investigations else "passed")
    )
    return {
        "task_id": TASK_ID,
        "status": status,
        "blocking_anomalies": sorted(set(blocking)),
        "blocking_anomaly_count": len(set(blocking)),
        "investigation_items": sorted(set(investigations)),
        "investigation_item_count": len(set(investigations)),
    }


def build_result_analysis(
    *,
    run_id: str,
    reviewed_implementation_sha: str,
    handoff: Mapping[str, Any],
    input_bindings: Mapping[str, Any],
    profiles: Mapping[str, Sequence[Mapping[str, Any]]],
    validator_result: Mapping[str, Any],
    anomaly_scan: Mapping[str, Any],
    synthetic_fixture: bool,
) -> str:
    """Build the fixed-section implementation/formal-result analysis text."""

    availability = list(profiles.get("indicator_availability", ()))
    raw_domain = list(profiles.get("raw_domain_profile", ()))
    common = list(profiles.get("common_valid_availability", ()))
    lines = [
        "# EXP-A02 raw domain, availability and validity analysis",
        "",
        "## 1. Actual run / reviewed SHA",
        f"run_id: {run_id}",
        f"reviewed_implementation_sha: {reviewed_implementation_sha or '(implementation review pending)'}",
        f"execution_mode: {'synthetic_fixture_only' if synthetic_fixture else 'formal_not_authorized'}",
        "",
        "## 2. Accepted EXP-A01 handoff",
        f"accepted_run_id: {handoff.get('accepted_run_id')}",
        f"accepted_status: {handoff.get('status')}",
        f"formal_result_review_status: {handoff.get('formal_result_review_status')}",
        "",
        "## 3. Input artifact and hash bindings",
        f"input_artifact_count: {len(input_bindings)}",
        "upstream_consumption: accepted_EXP_A01_artifact_only",
        "",
        "## 4. Raw-table cardinality",
        f"raw_row_count: {sum(int(row.get('total_row_count') or 0) for row in raw_domain)}",
        f"indicator_count: {len(raw_domain)}",
        "",
        "## 5. Raw domains",
        "The three registered raw domains are checked from finite valid values; the rate-valued candidate is checked on the fixed twenty-point grid.",
        "",
        "## 6. Indicator availability",
        *[
            f"{row['indicator_id']}: native_valid_count={row['native_valid_count']}; native_valid_rate_expected={row['native_valid_rate_expected']}"
            for row in availability
        ],
        "",
        "## 7. Common-valid availability",
        *[
            f"{row['set_id']}: common_valid_count={row['common_valid_count']}; union_valid_count={row['union_valid_count']}"
            for row in common
        ],
        "",
        "## 8. Validity-status distribution",
        "The compact status profile uses the complete expected-row denominator for each indicator.",
        "",
        "## 9. Reason-code distribution",
        "Reason-code counts are overlapping evidence counts and are not a mutually exclusive partition.",
        "",
        "## 10. Reason-combination distribution",
        "Canonical reason-code arrays are retained as complete combinations.",
        "",
        "## 11. Year availability",
        "Year-level availability is reported without using future outcomes or selection criteria.",
        "",
        "## 12. Security availability",
        "Security-level availability is reported for every security present in the input artifact.",
        "",
        "## 13. Deterministic extreme-value sample",
        "Each indicator uses deterministic lower and upper tails ordered by value, security, and observation sequence.",
        "",
        "## 14. Full invariant validation",
        f"status: {validator_result.get('status')}; mismatch_count: {sum(int(value or 0) for value in validator_result.get('mismatch_counts', {}).values())}",
        "",
        "## 15. Independent aggregate recomputation",
        "The validator defines independent set-based aggregate SQL and compares every persisted compact field.",
        "",
        "## 16. Validator result",
        f"status: {validator_result.get('status')}; valid: {validator_result.get('valid')}",
        "",
        "## 17. Anomaly scan",
        f"status: {anomaly_scan.get('status')}; blocking_anomaly_count: {anomaly_scan.get('blocking_anomaly_count')}; investigation_item_count: {anomaly_scan.get('investigation_item_count')}",
        "",
        "## 18. Supported conclusions",
        "This implementation package supports only raw-domain, availability, validity, reason-code, and compact aggregate integrity checks.",
        "",
        "## 19. Unsupported conclusions",
        "Candidate identity comparisons, downstream selection, predictive outcomes, and state-machine decisions are outside EXP-A02.",
        "",
        "## 20. Readiness for user Formal-result review",
        (
            "needs_investigation_before_user_review"
            if synthetic_fixture
            else "ready_for_user_formal_result_review"
        ),
        "",
    ]
    return "\n".join(lines)
