"""Score-only formal audit harness for R2A-T04."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb

from src.r2a.r2a_t03_output_contract import (
    DynamicEvaluationSummary,
    validate_dynamic_evaluation_output,
)
from src.r2a.r2a_t04_audit_validator import validate_review_bundle
from src.r2a.r2a_t04_real_data_audit import (
    R2AT04AuditError,
    canonical_table_profiles,
    free_disk_gate,
    record_score_structure,
    request_metrics,
    sha256_file,
    termination_metrics,
    verify_file_identity,
    write_csv_records,
    year_metrics,
)
from src.r2a.r2a_t04_set_based_evaluator import (
    evaluate_request_set_based_with_threads,
)

SCOPE_ID = "r2a_t04_ca_q15_q25_k5_response_audit.v1"
FORMAL_AUTHORIZATION_ID = "R2A-T04-CA-Q-AUDIT-AUTH-20260720-R5"
PANEL_ID = "r2a_t04_ca_q15_q25_k5_panel.v1"
EXPECTED_REQUEST_COUNT = 2
REVIEW_FILES = (
    "request_metrics.csv",
    "year_metrics.csv",
    "termination_metrics.csv",
    "response_checks.csv",
    "interval_structure_summary.csv",
    "interval_samples.csv",
    "score_dimension_endpoint_summary.csv",
    "score_component_endpoint_summary.csv",
    "request_output_profiles.json",
    "request_panel.json",
    "score_source_identity.json",
    "validation_receipt.json",
    "result_analysis.md",
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _attach_read_only(
    connection: duckdb.DuckDBPyConnection, path: Path, alias: str
) -> None:
    escaped = str(path.resolve()).replace("'", "''")
    connection.execute(f"ATTACH '{escaped}' AS {alias} (READ_ONLY)")


def _detach(connection: duckdb.DuckDBPyConnection, alias: str) -> None:
    connection.execute(f"DETACH {alias}")


def initialize_score_audit_database(audit: duckdb.DuckDBPyConnection) -> None:
    """Create the active Score-only audit database without external-source tables."""

    audit.execute(
        "CREATE TABLE request_metrics_records("
        "logical_request_name VARCHAR PRIMARY KEY,request_id VARCHAR,"
        "request_hash VARCHAR,validator_status VARCHAR,metrics_json VARCHAR,"
        "output_tables_json VARCHAR,wall_seconds DOUBLE,peak_rss_bytes BIGINT,"
        "temporary_output_bytes BIGINT)"
    )
    audit.execute(
        "CREATE TABLE year_metrics_records(logical_request_name VARCHAR,"
        "year INTEGER,metrics_json VARCHAR,PRIMARY KEY(logical_request_name,year))"
    )
    audit.execute(
        "CREATE TABLE termination_metrics_records(logical_request_name VARCHAR,"
        "termination_reason VARCHAR,count BIGINT,rate DOUBLE,"
        "PRIMARY KEY(logical_request_name,termination_reason))"
    )
    audit.execute(
        "CREATE TABLE response_daily(logical_request_name VARCHAR,"
        "security_id VARCHAR,trading_date DATE,joint_ready BOOLEAN,"
        "raw_state BOOLEAN,confirmed_state BOOLEAN,raw_streak_start_date DATE,"
        "confirmation_event BOOLEAN,PRIMARY KEY(logical_request_name,"
        "security_id,trading_date))"
    )
    audit.execute(
        "CREATE TABLE response_checks(check_id VARCHAR,comparison VARCHAR,"
        "violation_count BIGINT,strict_change BOOLEAN,passed BOOLEAN,detail VARCHAR)"
    )
    audit.execute(
        "CREATE TABLE interval_inventory(logical_request_name VARCHAR,"
        "request_id VARCHAR,request_hash VARCHAR,security_id VARCHAR,"
        "interval_ordinal BIGINT,raw_start_date DATE,confirmation_date DATE,"
        "last_confirmed_end_date DATE,termination_date DATE,"
        "termination_reason VARCHAR,confirmed_observation_count BIGINT,"
        "right_censored BOOLEAN,PRIMARY KEY(logical_request_name,request_id,"
        "security_id,interval_ordinal))"
    )
    audit.execute(
        "CREATE TABLE score_dimension_structure(logical_request_name VARCHAR,"
        "request_id VARCHAR,security_id VARCHAR,interval_ordinal BIGINT,"
        "anchor_type VARCHAR,anchor_date DATE,dimension_id VARCHAR,"
        "score_dimension DOUBLE,score_dimension_min DOUBLE,"
        "eligible_dimension BOOLEAN,validity_status VARCHAR,reason_codes VARCHAR[])"
    )
    audit.execute(
        "CREATE TABLE score_component_structure(logical_request_name VARCHAR,"
        "request_id VARCHAR,security_id VARCHAR,interval_ordinal BIGINT,"
        "anchor_type VARCHAR,anchor_date DATE,dimension_id VARCHAR,"
        "component_id VARCHAR,raw_value DOUBLE,percentile DOUBLE,score DOUBLE,"
        "eligible BOOLEAN,validity_status VARCHAR,reason_codes VARCHAR[])"
    )


def run_ca_q_response_checks_sql(audit: duckdb.DuckDBPyConnection) -> None:
    """Record only the frozen CA q=1500 versus q=2500 response relations."""

    comparison = "CA_q15_k5 -> CA_q25_k5"
    left_name = "CA_q15_k5"
    right_name = "CA_q25_k5"
    joint_mismatch = int(
        audit.execute(
            "SELECT count(*) FROM (SELECT security_id,trading_date,joint_ready FROM "
            "response_daily WHERE logical_request_name=?) l FULL OUTER JOIN (SELECT "
            "security_id,trading_date,joint_ready FROM response_daily WHERE "
            "logical_request_name=?) r USING(security_id,trading_date) WHERE "
            "l.security_id IS NULL OR r.security_id IS NULL OR "
            "l.joint_ready IS DISTINCT FROM r.joint_ready",
            [left_name, right_name],
        ).fetchone()[0]
    )

    def subset_counts(field: str) -> tuple[int, int, int, int]:
        left_count = int(
            audit.execute(
                f"SELECT count(*) FROM response_daily WHERE logical_request_name=? "
                f"AND {field}=true",
                [left_name],
            ).fetchone()[0]
        )
        right_count = int(
            audit.execute(
                f"SELECT count(*) FROM response_daily WHERE logical_request_name=? "
                f"AND {field}=true",
                [right_name],
            ).fetchone()[0]
        )
        violation = int(
            audit.execute(
                f"SELECT count(*) FROM response_daily l ANTI JOIN response_daily r "
                "ON l.security_id=r.security_id AND l.trading_date=r.trading_date "
                f"AND r.logical_request_name=? AND r.{field}=true "
                f"WHERE l.logical_request_name=? AND l.{field}=true",
                [right_name, left_name],
            ).fetchone()[0]
        )
        right_only = int(
            audit.execute(
                f"SELECT count(*) FROM response_daily r ANTI JOIN response_daily l "
                "ON l.security_id=r.security_id AND l.trading_date=r.trading_date "
                f"AND l.logical_request_name=? AND l.{field}=true "
                f"WHERE r.logical_request_name=? AND r.{field}=true",
                [left_name, right_name],
            ).fetchone()[0]
        )
        return left_count, right_count, violation, right_only

    raw_left, raw_right, raw_violation, raw_right_only = subset_counts("raw_state")
    confirmed_left, confirmed_right, confirmed_violation, confirmed_right_only = (
        subset_counts("confirmed_state")
    )
    raw_strict = raw_right_only > 0
    confirmed_strict = confirmed_right_only > 0
    non_degenerate = raw_strict or confirmed_strict
    rows = [
        (
            "ca_q_joint_ready_equality",
            comparison,
            joint_mismatch,
            False,
            joint_mismatch == 0,
            json.dumps({"mismatch_count": joint_mismatch}, sort_keys=True),
        ),
        (
            "ca_q_raw_subset",
            comparison,
            raw_violation,
            raw_strict,
            raw_violation == 0,
            json.dumps(
                {
                    "left_count": raw_left,
                    "right_count": raw_right,
                    "right_only_count": raw_right_only,
                },
                sort_keys=True,
            ),
        ),
        (
            "ca_q_confirmed_subset",
            comparison,
            confirmed_violation,
            confirmed_strict,
            confirmed_violation == 0,
            json.dumps(
                {
                    "left_count": confirmed_left,
                    "right_count": confirmed_right,
                    "right_only_count": confirmed_right_only,
                },
                sort_keys=True,
            ),
        ),
        (
            "ca_q_response_non_degenerate",
            comparison,
            0 if non_degenerate else 1,
            non_degenerate,
            non_degenerate,
            json.dumps(
                {
                    "raw_strict_change": raw_strict,
                    "confirmed_strict_change": confirmed_strict,
                },
                sort_keys=True,
            ),
        ),
    ]
    audit.executemany("INSERT INTO response_checks VALUES (?,?,?,?,?,?)", rows)


def record_score_request_result(
    audit: duckdb.DuckDBPyConnection,
    *,
    logical_name: str,
    result_database: Path,
    score_database: Path,
    summary: DynamicEvaluationSummary,
    profiles: Mapping[str, Any],
    wall_seconds: float,
    peak_rss_bytes: int,
    temporary_output_bytes: int,
) -> None:
    """Record one validated request without any non-Score join."""

    _attach_read_only(audit, result_database, "dyn")
    try:
        with duckdb.connect(str(result_database), read_only=True) as result:
            metrics = request_metrics(result)
            metrics["evaluated_security_count"] = int(
                result.execute(
                    "SELECT evaluated_security_count FROM evaluation_scope"
                ).fetchone()[0]
            )
            years = year_metrics(result)
            terminations = termination_metrics(result)
        audit.execute(
            "INSERT INTO request_metrics_records VALUES (?,?,?,?,?,?,?,?,?)",
            [
                logical_name,
                summary.request_id,
                summary.request_hash,
                "passed",
                json.dumps(metrics, sort_keys=True),
                json.dumps(profiles, sort_keys=True),
                wall_seconds,
                peak_rss_bytes,
                temporary_output_bytes,
            ],
        )
        audit.executemany(
            "INSERT INTO year_metrics_records VALUES (?,?,?)",
            [
                (logical_name, row["year"], json.dumps(row, sort_keys=True))
                for row in years
            ],
        )
        if terminations:
            audit.executemany(
                "INSERT INTO termination_metrics_records VALUES (?,?,?,?)",
                [
                    (
                        logical_name,
                        row["termination_reason"],
                        row["count"],
                        row["rate"],
                    )
                    for row in terminations
                ],
            )
        escaped = logical_name.replace("'", "''")
        audit.execute(
            f"INSERT INTO response_daily SELECT '{escaped}',security_id,"
            "trading_date,joint_ready,raw_state,confirmed_state,"
            "raw_streak_start_date,confirmation_event "
            "FROM dyn.daily_joint_states"
        )
        audit.execute(
            f"INSERT INTO interval_inventory SELECT '{escaped}',i.request_id,"
            "r.request_hash,i.security_id,i.interval_ordinal,i.raw_start_date,"
            "i.confirmation_date,i.last_confirmed_end_date,i.termination_date,"
            "i.termination_reason,i.confirmed_observation_count,i.right_censored "
            "FROM dyn.confirmed_intervals i JOIN dyn.dynamic_request r "
            "USING(request_id)"
        )
    finally:
        _detach(audit, "dyn")
    record_score_structure(
        audit,
        logical_name=logical_name,
        result_database=result_database,
        score_database=score_database,
    )


def _arrow_rows(
    connection: duckdb.DuckDBPyConnection, query: str
) -> list[dict[str, Any]]:
    return connection.execute(query).fetch_arrow_table().to_pylist()


def build_interval_structure_outputs(
    audit: duckdb.DuckDBPyConnection,
    *,
    formal_root: Path,
    review_directory: Path,
) -> dict[str, int]:
    """Build request-level and security-level interval structure outputs."""

    summary_rows = _arrow_rows(
        audit,
        """
        WITH security_counts AS (
          SELECT logical_request_name,security_id,count(*) interval_count,
            sum(confirmed_observation_count) confirmed_observation_total,
            count(*) FILTER(WHERE right_censored) right_censored_interval_count,
            max(confirmed_observation_count) max_interval_duration
          FROM interval_inventory GROUP BY 1,2
        ), request_security AS (
          SELECT logical_request_name,
            quantile_cont(interval_count,0.50) per_security_interval_count_p50,
            quantile_cont(interval_count,0.90) per_security_interval_count_p90,
            quantile_cont(interval_count,0.99) per_security_interval_count_p99,
            max(interval_count) per_security_interval_count_max
          FROM security_counts GROUP BY 1
        )
        SELECT r.logical_request_name,r.request_id,r.request_hash,
          count(i.interval_ordinal) interval_count,
          count(DISTINCT i.security_id) security_with_interval_count,
          count(DISTINCT i.security_id)::DOUBLE/
            max(CAST(json_extract(r.metrics_json,
              '$.evaluated_security_count') AS BIGINT))
            security_breadth_rate,
          max(CAST(json_extract(r.metrics_json,
            '$.evaluated_security_count') AS BIGINT))-
            count(DISTINCT i.security_id) zero_interval_security_count,
          count(i.interval_ordinal) FILTER(WHERE i.right_censored)
            right_censored_count,
          count(i.interval_ordinal) FILTER(WHERE i.right_censored)::DOUBLE/
            nullif(count(i.interval_ordinal),0) right_censored_rate,
          min(i.confirmed_observation_count) duration_min,
          quantile_cont(i.confirmed_observation_count,0.10) duration_p10,
          quantile_cont(i.confirmed_observation_count,0.25) duration_p25,
          quantile_cont(i.confirmed_observation_count,0.50) duration_p50,
          quantile_cont(i.confirmed_observation_count,0.75) duration_p75,
          quantile_cont(i.confirmed_observation_count,0.90) duration_p90,
          quantile_cont(i.confirmed_observation_count,0.99) duration_p99,
          max(i.confirmed_observation_count) duration_max,
          s.per_security_interval_count_p50,s.per_security_interval_count_p90,
          s.per_security_interval_count_p99,s.per_security_interval_count_max,
          coalesce(sum(i.confirmed_observation_count),0) confirmed_observation_total
        FROM request_metrics_records r LEFT JOIN interval_inventory i USING(
          logical_request_name,request_id,request_hash)
        LEFT JOIN request_security s USING(logical_request_name)
        GROUP BY ALL ORDER BY r.logical_request_name
        """,
    )
    security_rows = _arrow_rows(
        audit,
        """
        SELECT logical_request_name,security_id,count(*) interval_count,
          sum(confirmed_observation_count) confirmed_observation_total,
          count(*) FILTER(WHERE right_censored) right_censored_interval_count,
          max(confirmed_observation_count) max_interval_duration
        FROM interval_inventory GROUP BY 1,2 ORDER BY 1,2
        """,
    )
    write_csv_records(review_directory / "interval_structure_summary.csv", summary_rows)
    write_csv_records(formal_root / "interval_security_distribution.csv", security_rows)
    escaped = (formal_root / "interval_inventory.parquet").as_posix().replace("'", "''")
    audit.execute(
        f"COPY (SELECT * FROM interval_inventory ORDER BY ALL) TO '{escaped}' "
        "(FORMAT PARQUET,COMPRESSION ZSTD)"
    )
    return {
        "interval_structure_row_count": len(summary_rows),
        "interval_security_row_count": len(security_rows),
    }


def build_score_endpoint_outputs(
    audit: duckdb.DuckDBPyConnection, *, review_directory: Path
) -> dict[str, int]:
    """Aggregate Score endpoint structure entirely inside DuckDB."""

    dimension_rows = _arrow_rows(
        audit,
        """
        SELECT logical_request_name,anchor_type,dimension_id,count(*) row_count,
          count(*) FILTER(WHERE eligible_dimension) eligible_count,
          avg(eligible_dimension::INT) eligible_rate,
          count(*) FILTER(WHERE validity_status='valid') valid_count,
          avg((validity_status='valid')::INT) valid_rate,
          quantile_cont(score_dimension,0.10) score_dimension_p10,
          quantile_cont(score_dimension,0.25) score_dimension_p25,
          quantile_cont(score_dimension,0.50) score_dimension_p50,
          quantile_cont(score_dimension,0.75) score_dimension_p75,
          quantile_cont(score_dimension,0.90) score_dimension_p90,
          quantile_cont(score_dimension_min,0.10) score_dimension_min_p10,
          quantile_cont(score_dimension_min,0.25) score_dimension_min_p25,
          quantile_cont(score_dimension_min,0.50) score_dimension_min_p50,
          quantile_cont(score_dimension_min,0.75) score_dimension_min_p75,
          quantile_cont(score_dimension_min,0.90) score_dimension_min_p90
        FROM score_dimension_structure GROUP BY 1,2,3 ORDER BY 1,2,3
        """,
    )
    component_rows = _arrow_rows(
        audit,
        """
        SELECT logical_request_name,anchor_type,dimension_id,component_id,
          count(*) row_count,count(*) FILTER(WHERE eligible) eligible_count,
          avg(eligible::INT) eligible_rate,
          count(*) FILTER(WHERE validity_status='valid') valid_count,
          avg((validity_status='valid')::INT) valid_rate,
          quantile_cont(raw_value,0.10) raw_value_p10,
          quantile_cont(raw_value,0.25) raw_value_p25,
          quantile_cont(raw_value,0.50) raw_value_p50,
          quantile_cont(raw_value,0.75) raw_value_p75,
          quantile_cont(raw_value,0.90) raw_value_p90,
          quantile_cont(percentile,0.10) percentile_p10,
          quantile_cont(percentile,0.25) percentile_p25,
          quantile_cont(percentile,0.50) percentile_p50,
          quantile_cont(percentile,0.75) percentile_p75,
          quantile_cont(percentile,0.90) percentile_p90,
          quantile_cont(score,0.10) score_p10,
          quantile_cont(score,0.25) score_p25,
          quantile_cont(score,0.50) score_p50,
          quantile_cont(score,0.75) score_p75,
          quantile_cont(score,0.90) score_p90
        FROM score_component_structure GROUP BY 1,2,3,4 ORDER BY 1,2,3,4
        """,
    )
    write_csv_records(
        review_directory / "score_dimension_endpoint_summary.csv", dimension_rows
    )
    write_csv_records(
        review_directory / "score_component_endpoint_summary.csv", component_rows
    )
    return {
        "dimension_endpoint_summary_row_count": len(dimension_rows),
        "component_endpoint_summary_row_count": len(component_rows),
    }


def deterministic_interval_samples(
    audit: duckdb.DuckDBPyConnection,
    *,
    review_directory: Path,
    per_request_limit: int = 20,
) -> list[dict[str, Any]]:
    """Select deterministic interval samples without outcome-based filtering."""

    if per_request_limit < 1 or per_request_limit > 20:
        raise R2AT04AuditError("interval_sample_limit_invalid")
    rows = _arrow_rows(
        audit,
        f"""
        WITH ranked AS (
          SELECT *,sha256(request_hash||':'||security_id||':'||
            CAST(confirmation_date AS VARCHAR)||':'||
            CAST(interval_ordinal AS VARCHAR)) sample_hash,
            row_number() OVER(PARTITION BY logical_request_name ORDER BY
              sha256(request_hash||':'||security_id||':'||
                CAST(confirmation_date AS VARCHAR)||':'||
                CAST(interval_ordinal AS VARCHAR)),security_id,interval_ordinal) n
          FROM interval_inventory
        )
        SELECT logical_request_name,request_id,request_hash,security_id,
          interval_ordinal,raw_start_date,confirmation_date,
          last_confirmed_end_date,termination_date,termination_reason,
          confirmed_observation_count,right_censored,sample_hash
        FROM ranked WHERE n<={int(per_request_limit)} ORDER BY 1,sample_hash
        """,
    )
    write_csv_records(review_directory / "interval_samples.csv", rows)
    return rows


def _validate_reconciliations(
    audit: duckdb.DuckDBPyConnection,
    *,
    expected_security_count: int,
) -> dict[str, int]:
    request_count, validator_failures, scope_mismatches = audit.execute(
        "SELECT count(*),count(*) FILTER(WHERE validator_status<>'passed'),"
        "count(*) FILTER(WHERE CAST(json_extract(metrics_json,"
        "'$.evaluated_security_count') AS BIGINT)<>? OR "
        "CAST(json_extract(metrics_json,'$.spine_observation_count') AS BIGINT)<=0 "
        "OR CAST(json_extract(metrics_json,'$.security_with_interval_count') "
        "AS BIGINT)>?) FROM request_metrics_records",
        [expected_security_count, expected_security_count],
    ).fetchone()
    if int(request_count) != EXPECTED_REQUEST_COUNT:
        raise R2AT04AuditError("formal_request_count_mismatch")
    interval_failures = audit.execute(
        "SELECT count(*) FROM request_metrics_records r LEFT JOIN ("
        "SELECT logical_request_name,count(*) n FROM interval_inventory GROUP BY 1) i "
        "USING(logical_request_name) WHERE CAST(json_extract(r.metrics_json,"
        "'$.confirmed_interval_count') AS BIGINT)<>coalesce(i.n,0)"
    ).fetchone()[0]
    endpoint_failures = audit.execute(
        "WITH expected AS (SELECT logical_request_name,"
        "sum((raw_start_date IS NOT NULL)::INT+(confirmation_date IS NOT NULL)::INT+"
        "(last_confirmed_end_date IS NOT NULL)::INT+"
        "(termination_date IS NOT NULL)::INT) n FROM interval_inventory GROUP BY 1),"
        "d AS (SELECT logical_request_name,count(*) n FROM score_dimension_structure "
        "GROUP BY 1),c AS (SELECT logical_request_name,count(*) n FROM "
        "score_component_structure GROUP BY 1) SELECT count(*) FROM expected e "
        "LEFT JOIN d USING(logical_request_name) "
        "LEFT JOIN c USING(logical_request_name) "
        "WHERE coalesce(d.n,0)<>e.n*5 OR coalesce(c.n,0)<>e.n*10"
    ).fetchone()[0]
    duplicate_failures = audit.execute(
        "SELECT (SELECT count(*) FROM (SELECT logical_request_name,request_id,"
        "security_id,interval_ordinal,count(*) n FROM interval_inventory GROUP BY "
        "1,2,3,4 HAVING n<>1))+(SELECT count(*) FROM (SELECT logical_request_name,"
        "request_id,security_id,interval_ordinal,anchor_type,dimension_id,count(*) n "
        "FROM score_dimension_structure GROUP BY 1,2,3,4,5,6 HAVING n<>1))+"
        "(SELECT count(*) FROM (SELECT logical_request_name,request_id,security_id,"
        "interval_ordinal,anchor_type,dimension_id,component_id,count(*) n FROM "
        "score_component_structure GROUP BY 1,2,3,4,5,6,7 HAVING n<>1))"
    ).fetchone()[0]
    total_raw, total_intervals = audit.execute(
        "SELECT sum(CAST(json_extract(metrics_json,'$.raw_true_count') AS BIGINT)),"
        "sum(CAST(json_extract(metrics_json,'$.confirmed_interval_count') AS BIGINT)) "
        "FROM request_metrics_records"
    ).fetchone()
    response_count, response_failures, non_degenerate_passed = audit.execute(
        "SELECT count(*),count(*) FILTER(WHERE passed=false),"
        "count(*) FILTER(WHERE check_id='ca_q_response_non_degenerate' "
        "AND strict_change=true AND passed=true) FROM response_checks"
    ).fetchone()
    failures = {
        "request_validator_failure_count": int(validator_failures),
        "scope_security_count_mismatch_count": int(scope_mismatches),
        "interval_reconciliation_failure_count": int(interval_failures),
        "score_endpoint_reconciliation_failure_count": int(
            endpoint_failures + duplicate_failures
        ),
    }
    if any(failures.values()):
        raise R2AT04AuditError("score_audit_reconciliation_failed")
    if (
        int(response_count) != 4
        or int(response_failures)
        or int(non_degenerate_passed) != 1
    ):
        raise R2AT04AuditError("score_audit_response_checks_failed")
    if not total_raw or not total_intervals:
        raise R2AT04AuditError("score_audit_response_degenerate")
    return failures


def _file_identity(path: Path, root: Path) -> dict[str, Any]:
    return {
        "relative_path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "byte_size": path.stat().st_size,
    }


def _analysis(
    *, formal_run_id: str, score_identity: Mapping[str, Any], recommendation: str
) -> str:
    sections = (
        (
            "Score input identity",
            f"Run `{formal_run_id}` used accepted Score "
            f"`{score_identity['sha256']}` "
            f"({score_identity['byte_size']} bytes).",
        ),
        (
            "Frozen CA two-request panel",
            "The frozen panel contains only CA_q15_k5 and CA_q25_k5.",
        ),
        (
            "Accepted output validator status",
            "Every recorded request passed the accepted persisted-output validator.",
        ),
        (
            "Joint evaluability",
            "Joint readiness must be identical because q changes activity, not "
            "readiness.",
        ),
        (
            "CA q=1500 vs q=2500 raw-state response",
            "The q=1500 raw-state key set must be a subset of q=2500.",
        ),
        (
            "CA q=1500 vs q=2500 confirmed-state response",
            "The q=1500 confirmed-state key set must be a subset of q=2500.",
        ),
        (
            "Interval count and duration comparison",
            "Counts, duration quantiles, censoring, and confirmed totals are compared.",
        ),
        (
            "Security breadth and concentration",
            "Breadth, zero-interval counts, and per-security concentration are "
            "reported.",
        ),
        (
            "Year stability",
            "Year metrics retain evaluability, state, interval, and breadth structure.",
        ),
        (
            "Termination distribution",
            "Termination reason counts and rates are reported by request.",
        ),
        (
            "Score endpoint structure",
            "Five dimensions and ten components are diagnostic context at four "
            "anchors.",
        ),
        (
            "Limitations",
            "This audit does not select q, register a canonical state, create trading "
            "signals, use future returns, backtest, or construct a portfolio.",
        ),
        (
            "Automated recommendation",
            f"Automated recommendation: `{recommendation}`. Owner result review "
            "remains `pending`.",
        ),
    )
    lines = ["# R2A-T04 Score-only result analysis", ""]
    for ordinal, (title, body) in enumerate(sections, start=1):
        lines.extend((f"## {ordinal}. {title}", "", body, ""))
    return "\n".join(lines)


def finalize_score_review_bundle(
    *,
    audit_database: Path,
    review_directory: Path,
    formal_run_id: str,
    score_identity: Mapping[str, Any],
    panel: Sequence[Mapping[str, Any]],
    validation: Mapping[str, Any],
    blocking_anomalies: Sequence[str] = (),
    max_bytes: int = 62_914_560,
    interval_sample_per_request: int = 20,
) -> dict[str, Any]:
    """Export and validate the exact compact Score-only review bundle."""

    review_directory.mkdir(parents=True, exist_ok=False)
    with duckdb.connect(str(audit_database), read_only=True) as audit:
        request_rows = [
            {
                "logical_request_name": row[0],
                "request_id": row[1],
                "request_hash": row[2],
                "validator_status": row[3],
                **json.loads(row[4]),
            }
            for row in audit.execute(
                "SELECT logical_request_name,request_id,request_hash,"
                "validator_status,metrics_json FROM request_metrics_records ORDER BY 1"
            ).fetchall()
        ]
        year_rows = [
            {"logical_request_name": row[0], **json.loads(row[1])}
            for row in audit.execute(
                "SELECT logical_request_name,metrics_json FROM year_metrics_records "
                "ORDER BY logical_request_name,year"
            ).fetchall()
        ]
        termination_rows = _arrow_rows(
            audit,
            "SELECT logical_request_name,termination_reason,count,rate FROM "
            "termination_metrics_records ORDER BY 1,2",
        )
        response_rows = _arrow_rows(
            audit, "SELECT * FROM response_checks ORDER BY check_id,comparison"
        )
        profiles = {
            row[0]: json.loads(row[1])
            for row in audit.execute(
                "SELECT logical_request_name,output_tables_json FROM "
                "request_metrics_records ORDER BY 1"
            ).fetchall()
        }
        write_csv_records(review_directory / "request_metrics.csv", request_rows)
        write_csv_records(review_directory / "year_metrics.csv", year_rows)
        write_csv_records(
            review_directory / "termination_metrics.csv", termination_rows
        )
        write_csv_records(review_directory / "response_checks.csv", response_rows)
        build_interval_structure_outputs(
            audit,
            formal_root=audit_database.parent,
            review_directory=review_directory,
        )
        build_score_endpoint_outputs(audit, review_directory=review_directory)
        deterministic_interval_samples(
            audit,
            review_directory=review_directory,
            per_request_limit=interval_sample_per_request,
        )
    _write_json(review_directory / "request_output_profiles.json", profiles)
    _write_json(review_directory / "request_panel.json", list(panel))
    score_public = {
        "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
        "sha256": score_identity["sha256"],
        "byte_size": score_identity["byte_size"],
    }
    _write_json(review_directory / "score_source_identity.json", score_public)
    recommendation = (
        "continue_to_owner_result_review"
        if not blocking_anomalies
        else "blocked_evaluator_or_response_degeneracy"
    )
    validation_record = {
        **validation,
        "blocking_anomaly_count": len(blocking_anomalies),
        "status": "passed" if not blocking_anomalies else "failed",
    }
    _write_json(review_directory / "validation_receipt.json", validation_record)
    (review_directory / "result_analysis.md").write_text(
        _analysis(
            formal_run_id=formal_run_id,
            score_identity=score_identity,
            recommendation=recommendation,
        ),
        encoding="utf-8",
        newline="\n",
    )
    missing = [name for name in REVIEW_FILES if not (review_directory / name).is_file()]
    if missing:
        raise R2AT04AuditError("score_review_bundle_file_missing", ",".join(missing))
    files = [
        _file_identity(review_directory / name, review_directory)
        for name in REVIEW_FILES
    ]
    summary = {
        "task_id": "R2A-T04",
        "bundle_mode": "formal_review",
        "scope_id": SCOPE_ID,
        "status": (
            "score_audit_completed_pending_result_review"
            if not blocking_anomalies
            else "formal_run_blocked"
        ),
        "formal_run_id": formal_run_id,
        "formal_authorization_id": FORMAL_AUTHORIZATION_ID,
        "authorization_revision": 5,
        "panel_id": PANEL_ID,
        "request_count": EXPECTED_REQUEST_COUNT,
        "score_source": score_public,
        "execution": {
            "full_universe_request_concurrency": 1,
            "duckdb_thread_count": 4,
            "formal_run_consumed": True,
        },
        "validation": validation_record,
        "review_boundary": {
            "automated_recommendation": recommendation,
            "owner_result_review": "pending",
            "R2A_T04_DONE": "absent",
            "R2A_T05_allowed_to_start": False,
        },
        "files": files,
    }
    _write_json(review_directory / "run_summary.json", summary)
    total_bytes = sum(path.stat().st_size for path in review_directory.iterdir())
    if total_bytes > max_bytes:
        raise R2AT04AuditError("score_review_bundle_exceeds_size_gate")
    validate_review_bundle(review_directory)
    return summary


def _assert_no_consumed_authorization(parent: Path, authorization_id: str) -> None:
    for authorization_path in parent.glob("*/authorization.json"):
        value = json.loads(authorization_path.read_text(encoding="utf-8"))
        if (
            value.get("formal_authorization_id") == authorization_id
            and value.get("formal_run_consumed") is True
        ):
            raise R2AT04AuditError("formal_authorization_already_consumed")


def run_score_formal_audit(
    *,
    config: Mapping[str, Any],
    panel: Sequence[Mapping[str, Any]],
    score_database: Path,
    output_root: Path,
    review_output: Path,
    execution_gate: Mapping[str, Any],
    evaluator: Callable[..., tuple[DynamicEvaluationSummary, float, int, int]] = (
        evaluate_request_set_based_with_threads
    ),
    output_validator: Callable[[duckdb.DuckDBPyConnection], Any] = (
        validate_dynamic_evaluation_output
    ),
) -> dict[str, Any]:
    """Run the frozen CA two-request Score audit strictly serially and once."""

    if execution_gate.get("status") != "passed":
        raise R2AT04AuditError("formal_execution_gate_not_passed")
    if (
        config.get("status") != "authorized_not_started"
        or config.get("authorization_revision") != 5
        or config.get("formal_run_authorized") is not True
        or config.get("formal_run_started") is not False
        or config.get("formal_run_consumed") is not False
    ):
        raise R2AT04AuditError("formal_authorization_metadata_invalid")
    if (
        len(panel) != EXPECTED_REQUEST_COUNT
        or config.get("full_universe_request_concurrency") != 1
    ):
        raise R2AT04AuditError("formal_concurrency_or_panel_gate_failed")
    if output_root.exists() or review_output.exists():
        raise R2AT04AuditError("formal_output_already_exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_consumed_authorization(
        output_root.parent, str(config["formal_authorization_id"])
    )
    free_bytes = free_disk_gate(
        output_root.parent,
        int(config["score_release"]["byte_size"]),
        int(config["minimum_free_disk_score_db_multiple"]),
    )
    score_identity = verify_file_identity(
        score_database,
        expected_sha256=str(config["score_release"]["sha256"]),
        expected_byte_size=int(config["score_release"]["byte_size"]),
    )
    output_root.mkdir()
    for child in ("requests", "request-results", "logs"):
        (output_root / child).mkdir()
    authorization = {
        "formal_authorization_id": config["formal_authorization_id"],
        "authorization_revision": 5,
        "formal_run_consumed": True,
        "scope_id": SCOPE_ID,
        "full_universe_request_concurrency": 1,
        "duckdb_thread_count": 4,
        "thread_benchmark_fingerprint": config["thread_preflight"][
            "thread_benchmark_fingerprint"
        ],
    }
    _write_json(output_root / "authorization.json", authorization)
    _write_json(
        output_root / "score_source_identity.json",
        {
            "score_release_id": config["score_release"]["score_release_id"],
            **score_identity,
        },
    )
    _write_json(output_root / "request_panel.json", list(panel))
    for item in panel:
        _write_json(
            output_root / "requests" / f"{item['logical_request_name']}.json",
            {
                key: item[key]
                for key in (
                    "request_schema_version",
                    "request_id",
                    "request_hash",
                    "spec",
                )
            },
        )
    audit_path = output_root / "audit_metrics.duckdb"
    log_path = output_root / "logs" / "formal_run.jsonl"
    request_summaries: list[dict[str, Any]] = []
    started = time.perf_counter()
    with duckdb.connect(str(audit_path)) as audit:
        audit.execute("SET threads=4")
        initialize_score_audit_database(audit)
        for ordinal, item in enumerate(panel, start=1):
            logical_name = str(item["logical_request_name"])
            result_path = output_root / "request-results" / f"{logical_name}.duckdb"
            summary, wall, peak, temporary_bytes = evaluator(
                score_database=score_database,
                canonical_request={
                    key: item[key]
                    for key in (
                        "request_schema_version",
                        "request_id",
                        "request_hash",
                        "spec",
                    )
                },
                output_database=result_path,
                duckdb_thread_count=4,
                security_ids=None,
            )
            with duckdb.connect(str(result_path), read_only=True) as result:
                output_validator(result)
                profiles = canonical_table_profiles(result)
                evaluated_security_count = int(
                    result.execute(
                        "SELECT evaluated_security_count FROM evaluation_scope"
                    ).fetchone()[0]
                )
            if evaluated_security_count != int(
                config["score_release"]["security_count"]
            ):
                raise R2AT04AuditError("formal_scope_security_count_mismatch")
            record_score_request_result(
                audit,
                logical_name=logical_name,
                result_database=result_path,
                score_database=score_database,
                summary=summary,
                profiles=profiles,
                wall_seconds=wall,
                peak_rss_bytes=peak,
                temporary_output_bytes=temporary_bytes,
            )
            request_summary = {
                "ordinal": ordinal,
                "logical_request_name": logical_name,
                "request_id": summary.request_id,
                "validator_status": "passed",
                "wall_seconds": wall,
                "peak_rss_bytes": peak,
                "temporary_output_bytes": temporary_bytes,
                "output_tables": profiles,
            }
            request_summaries.append(request_summary)
            with log_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(request_summary, sort_keys=True) + "\n")
            result_path.unlink()
        run_ca_q_response_checks_sql(audit)
        validation = _validate_reconciliations(
            audit,
            expected_security_count=int(config["score_release"]["security_count"]),
        )
        response_violation_count = int(
            audit.execute(
                "SELECT coalesce(sum(violation_count),0) FROM response_checks"
            ).fetchone()[0]
        )
        validation["response_violation_count"] = response_violation_count
        audit.execute("CHECKPOINT")
    formal_run_id = output_root.name
    summary = finalize_score_review_bundle(
        audit_database=audit_path,
        review_directory=review_output,
        formal_run_id=formal_run_id,
        score_identity=score_identity,
        panel=panel,
        validation=validation,
        max_bytes=int(config["review_bundle_max_bytes"]),
        interval_sample_per_request=int(config["interval_sample_per_request"]),
    )
    run_manifest = {
        "formal_run_id": formal_run_id,
        "formal_authorization_id": config["formal_authorization_id"],
        "authorization_revision": 5,
        "scope_id": SCOPE_ID,
        "formal_run_consumed": True,
        "request_count": EXPECTED_REQUEST_COUNT,
        "request_execution": "strictly_serial",
        "duckdb_thread_count": 4,
        "free_bytes_before_run": free_bytes,
        "elapsed_seconds": time.perf_counter() - started,
        "review_bundle_status": summary["validation"]["status"],
        "request_summaries": request_summaries,
    }
    _write_json(output_root / "run_manifest.json", run_manifest)
    _write_json(output_root / "validation_receipt.json", summary["validation"])
    (output_root / "result_analysis.md").write_text(
        (review_output / "result_analysis.md").read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    return {
        "formal_run_id": formal_run_id,
        "scope_id": SCOPE_ID,
        "status": summary["status"],
        "score_identity": score_identity,
        "request_count": EXPECTED_REQUEST_COUNT,
        "elapsed_seconds": run_manifest["elapsed_seconds"],
        "automated_recommendation": summary["review_boundary"][
            "automated_recommendation"
        ],
    }
