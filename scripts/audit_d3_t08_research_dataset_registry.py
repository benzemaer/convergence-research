"""Audit D3-T07 candidate observations as a route-agnostic research dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CONTRACT = ROOT / "configs/d3/d3_t08_research_dataset_registry_contract.v1.json"
SOURCE_TABLE = "d3_candidate_daily_observation"
OUTPUT_DUCKDB_NAME = "d3_t08_research_dataset_registry.duckdb"
TASK_ID = "D3-T08"
SOURCE_TASK_ID = "D3-T07"

TARGET_TABLES = (
    "d3_research_dataset_registry",
    "d3_research_dataset_schema_catalog",
    "d3_research_dataset_field_quality",
    "d3_research_dataset_coverage_by_security",
    "d3_research_dataset_coverage_by_date",
    "d3_research_dataset_policy_usage",
    "d3_research_dataset_window_capacity",
)
FORBIDDEN_OUTPUT_NAMES = {
    "data_version.json",
    "formal_manifest.json",
    "manifest.json",
    "labels.csv",
    "returns.csv",
    "future_outcomes.csv",
    "backtest.csv",
    "portfolio.csv",
    "r0_state.csv",
    "pcvt_values.csv",
    "pcvt_scores.csv",
    "state_labels.csv",
}
FORBIDDEN_FIELD_NAMES = {
    "pcvt_value",
    "pcvt_score",
    "pcvt_state",
    "q_threshold",
    "state",
    "label",
    "future_return",
    "breakout_direction",
    "backtest_signal",
    "portfolio_return",
}
D3_T07_QUALITY_BLOCKERS = (
    "duplicate_observation_key_count",
    "null_ohlc_count",
    "non_positive_price_count",
    "high_low_violation_count",
    "missing_effective_adj_factor_count",
    "factor_interval_unresolved_count",
)
CORE_QUALITY_BLOCKERS = (
    "duplicate_observation_key_count",
    "raw_ohlc_invalid_count",
    "raw_high_low_violation_count",
    "adjusted_ohlc_invalid_count",
    "adjusted_high_low_violation_count",
    "effective_adj_factor_invalid_count",
    "adjusted_factor_mismatch_count",
    "listing_pause_row_count",
    "is_listing_pause_true_count",
    "policy_provenance_missing_count",
    "source_task_id_invalid_count",
    "generated_by_task_invalid_count",
    "row_provenance_missing_count",
)


class D3T08AuditError(ValueError):
    """Raised when D3-T08 audit cannot proceed."""


def _utc_run_id() -> str:
    return "D3-T08-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _norm(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _rows_as_dicts(conn: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = conn.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def ensure_allowed_output_dir(path: Path) -> None:
    normalized = _norm(path)
    if "data/raw" in normalized or "data/external" in normalized:
        raise D3T08AuditError("output-dir must not be under raw/external data")
    if "marketdb" in normalized or ".day" in normalized:
        raise D3T08AuditError("output-dir must not target provider storage")
    if ".duckdb" in normalized:
        raise D3T08AuditError("output-dir must be a directory")
    if "data/generated/d3/" not in normalized:
        raise D3T08AuditError("output-dir must be under data/generated/d3/")


def _is_forbidden_input_path(path: Path) -> bool:
    normalized = _norm(path)
    return any(
        pattern in normalized
        for pattern in (
            "data/raw",
            "data/external",
            "marketdb",
            ".day",
            "data/generated/d2",
            "data/generated/d1",
        )
    )


def guard_source_d3_t07_duckdb(path: Path) -> None:
    normalized = _norm(path)
    if path.suffix.lower() != ".duckdb":
        raise D3T08AuditError("d3-t07-duckdb must be a DuckDB file")
    if path.name != "d3_t07_candidate_daily_observation.duckdb":
        raise D3T08AuditError("d3-t07-duckdb filename is not a D3-T07 candidate")
    if _is_forbidden_input_path(path):
        raise D3T08AuditError("d3-t07-duckdb path is outside the D3-T07 boundary")
    if "data/generated/d3/d3_t07_candidate_daily_observation/" not in normalized:
        raise D3T08AuditError("d3-t07-duckdb must be under D3-T07 generated output")


def guard_source_d3_t07_report(path: Path, *, expected_name: str) -> None:
    normalized = _norm(path)
    if path.name != expected_name:
        raise D3T08AuditError(f"expected D3-T07 report file {expected_name}")
    if _is_forbidden_input_path(path):
        raise D3T08AuditError("D3-T07 report path is outside the D3-T07 boundary")
    if "data/generated/d3/d3_t07_candidate_daily_observation/" not in normalized:
        raise D3T08AuditError("D3-T07 report must be under D3-T07 generated output")


def remove_previous_outputs(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    for name in (
        OUTPUT_DUCKDB_NAME,
        "d3_t08_generation_summary.json",
        "d3_t08_quality_report.json",
        "d3_t08_handoff_candidate_report.json",
        "d3_t08_schema_catalog.csv",
        "d3_t08_field_quality.csv",
        "d3_t08_coverage_by_security.csv",
        "d3_t08_coverage_by_date.csv",
        "d3_t08_policy_usage_summary.csv",
        "d3_t08_window_capacity_summary.csv",
        "d3_t08_candidate_file_hash_summary.json",
    ):
        target = output_dir / name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()


def d3_t07_gate_passed(
    quality: dict[str, Any], handoff: dict[str, Any]
) -> tuple[bool, list[str]]:
    expected = {
        "d3_t07_generation_decision": "accepted_candidate_observation",
        "d3_candidate_observation_generated": True,
        "formal_data_version_published": False,
        "labels_generated": False,
        "returns_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
    }
    errors = [
        key
        for key, expected_value in expected.items()
        if handoff.get(key) != expected_value
    ]
    for key in D3_T07_QUALITY_BLOCKERS:
        if int(quality.get(key, 0) or 0) != 0:
            errors.append(key)
    return not errors, errors


def base_quality() -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "source_row_count": 0,
        "registry_row_count": 0,
        "schema_catalog_row_count": 0,
        "field_quality_row_count": 0,
        "coverage_by_security_row_count": 0,
        "coverage_by_date_row_count": 0,
        "policy_usage_row_count": 0,
        "window_capacity_row_count": 0,
        "duplicate_observation_key_count": 0,
        "raw_ohlc_invalid_count": 0,
        "raw_high_low_violation_count": 0,
        "adjusted_ohlc_invalid_count": 0,
        "adjusted_high_low_violation_count": 0,
        "effective_adj_factor_invalid_count": 0,
        "adjusted_factor_mismatch_count": 0,
        "listing_pause_row_count": 0,
        "is_listing_pause_true_count": 0,
        "policy_provenance_missing_count": 0,
        "source_task_id_invalid_count": 0,
        "generated_by_task_invalid_count": 0,
        "row_provenance_missing_count": 0,
        "warning_count": 0,
        "warnings": [],
    }


def has_core_blockers(quality: dict[str, Any]) -> bool:
    return any(int(quality.get(key, 0) or 0) > 0 for key in CORE_QUALITY_BLOCKERS)


def output_summary(
    *,
    run_id: str,
    decision: str,
    generated: bool,
    output_duckdb: Path,
) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "run_id": run_id,
        "d3_t08_generation_decision": decision,
        "research_dataset_registry_generated": generated,
        "research_dataset_route_agnostic": True,
        "output_duckdb": str(output_duckdb) if generated else "",
        "formal_data_version_published": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
    }


def handoff_report(
    *, decision: str, generated: bool, output_duckdb: Path
) -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "d3_t08_generation_decision": decision,
        "research_dataset_registry_generated": generated,
        "research_dataset_registry_path": str(output_duckdb) if generated else "",
        "research_dataset_route_agnostic": True,
        "pcvt_indicator_definitions_frozen": False,
        "pcvt_input_readiness_generated": False,
        "pcvt_values_generated": False,
        "pcvt_scores_generated": False,
        "state_labels_generated": False,
        "labels_generated": False,
        "returns_generated": False,
        "backtest_generated": False,
        "portfolio_generated": False,
        "formal_data_version_published": False,
        "r0_state_generated": False,
        "next_planned_task": "R0-T01 PCVT candidate indicator specification",
    }


def create_output_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS d3_research_dataset_registry (
          dataset_id TEXT NOT NULL,
          source_task_id TEXT NOT NULL,
          source_duckdb TEXT NOT NULL,
          source_table TEXT NOT NULL,
          row_count INTEGER NOT NULL,
          security_count INTEGER NOT NULL,
          min_trade_date TEXT,
          max_trade_date TEXT,
          dataset_sha256 TEXT NOT NULL,
          schema_sha256 TEXT NOT NULL,
          generated_by_task TEXT NOT NULL,
          formal_data_version_published BOOLEAN NOT NULL,
          pcvt_values_generated BOOLEAN NOT NULL,
          r0_state_generated BOOLEAN NOT NULL
        );
        CREATE TABLE IF NOT EXISTS d3_research_dataset_schema_catalog (
          table_name TEXT NOT NULL,
          column_name TEXT NOT NULL,
          ordinal_position INTEGER NOT NULL,
          data_type TEXT NOT NULL,
          nullable BOOLEAN,
          semantic_role TEXT NOT NULL,
          route_agnostic BOOLEAN NOT NULL
        );
        CREATE TABLE IF NOT EXISTS d3_research_dataset_field_quality (
          column_name TEXT NOT NULL,
          null_count INTEGER NOT NULL,
          non_null_count INTEGER NOT NULL,
          distinct_count INTEGER,
          min_value_text TEXT,
          max_value_text TEXT,
          quality_status TEXT NOT NULL,
          quality_notes TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS d3_research_dataset_coverage_by_security (
          ts_code TEXT NOT NULL,
          observation_row_count INTEGER NOT NULL,
          min_trade_date TEXT,
          max_trade_date TEXT,
          policy_adjusted_row_count INTEGER NOT NULL,
          provider_resolved_row_count INTEGER NOT NULL,
          neutral_factor_policy_row_count INTEGER NOT NULL,
          factor_interval_policy_row_count INTEGER NOT NULL,
          limit_up_row_count INTEGER NOT NULL,
          limit_down_row_count INTEGER NOT NULL,
          coverage_status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS d3_research_dataset_coverage_by_date (
          trade_date TEXT NOT NULL,
          observation_row_count INTEGER NOT NULL,
          security_count INTEGER NOT NULL,
          policy_adjusted_row_count INTEGER NOT NULL,
          provider_resolved_row_count INTEGER NOT NULL,
          limit_up_row_count INTEGER NOT NULL,
          limit_down_row_count INTEGER NOT NULL,
          coverage_status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS d3_research_dataset_policy_usage (
          policy_type TEXT NOT NULL,
          row_count INTEGER NOT NULL,
          security_count INTEGER NOT NULL,
          min_trade_date TEXT,
          max_trade_date TEXT,
          policy_usage_notes TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS d3_research_dataset_window_capacity (
          ts_code TEXT NOT NULL,
          trade_date TEXT NOT NULL,
          valid_price_window_count_15 INTEGER NOT NULL,
          valid_price_window_count_20 INTEGER NOT NULL,
          valid_price_window_count_21 INTEGER NOT NULL,
          valid_price_window_count_60 INTEGER NOT NULL,
          valid_price_window_count_80 INTEGER NOT NULL,
          valid_participation_window_count_20 INTEGER NOT NULL,
          valid_participation_window_count_60 INTEGER NOT NULL,
          valid_participation_window_count_80 INTEGER NOT NULL,
          valid_trend_window_count_20 INTEGER NOT NULL,
          valid_trend_window_count_21 INTEGER NOT NULL,
          valid_trend_window_count_60 INTEGER NOT NULL,
          window_capacity_status TEXT NOT NULL
        );
        """
    )


def source_predicate(
    *, sample_securities: int | None, start_date: str | None, end_date: str | None
) -> str:
    predicates = ["1 = 1"]
    if start_date:
        predicates.append(f"o.trade_date >= {_sql_literal(start_date)}")
    if end_date:
        predicates.append(f"o.trade_date <= {_sql_literal(end_date)}")
    if sample_securities is not None:
        predicates.append(
            "o.ts_code IN ("
            "SELECT ts_code FROM ("
            f"SELECT DISTINCT ts_code FROM d3t07.{SOURCE_TABLE} ORDER BY ts_code"
            f") LIMIT {int(sample_securities)})"
        )
    return " AND ".join(predicates)


def create_source_view(
    conn: duckdb.DuckDBPyConnection,
    *,
    sample_securities: int | None,
    start_date: str | None,
    end_date: str | None,
) -> None:
    predicate = source_predicate(
        sample_securities=sample_securities, start_date=start_date, end_date=end_date
    )
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW d3_t08_source_observation AS
        SELECT *
        FROM d3t07.{SOURCE_TABLE} o
        WHERE {predicate}
        """
    )


def semantic_role(column_name: str) -> str:
    if column_name in {"ts_code", "trade_date"}:
        return "identifier"
    if column_name in {"open", "high", "low", "close"}:
        return "raw_price"
    if column_name in {"vol", "amount"}:
        return "raw_volume_amount"
    if column_name.startswith("adjusted_"):
        return "adjusted_price"
    if column_name == "effective_adj_factor":
        return "effective_factor"
    if column_name in {
        "trading_status",
        "daily_status",
        "price_limit_status",
        "adjustment_factor_status",
    }:
        return "source_status"
    if column_name in {"up_limit", "down_limit", "is_limit_up", "is_limit_down"}:
        return "trading_constraint"
    if column_name in {
        "is_policy_adjusted",
        "adj_factor_policy_type",
        "adj_factor_policy_source",
        "policy_evidence_status",
        "policy_evidence_level",
    }:
        return "policy_provenance"
    if column_name in {"source_task_id", "d2_source_duckdb", "generated_by_task"}:
        return "lineage"
    if column_name in {"is_listing_pause"}:
        return "derived_flag"
    if column_name == "row_provenance":
        return "lineage"
    return "derived_flag"


def schema_rows(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = []
    for cid, name, data_type, not_null, _default, _pk in conn.execute(
        f"PRAGMA table_info('d3t07.{SOURCE_TABLE}')"
    ).fetchall():
        rows.append(
            {
                "table_name": SOURCE_TABLE,
                "column_name": name,
                "ordinal_position": int(cid) + 1,
                "data_type": data_type,
                "nullable": not bool(not_null),
                "semantic_role": semantic_role(name),
                "route_agnostic": True,
            }
        )
    return rows


def sha256_json_rows(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dataset_sha256(conn: duckdb.DuckDBPyConnection, columns: list[str]) -> str:
    quoted = ", ".join(f'"{column}"' for column in columns)
    cursor = conn.execute(
        f"""
        SELECT {quoted}
        FROM d3_t08_source_observation
        ORDER BY ts_code, trade_date
        """
    )
    digest = hashlib.sha256()
    digest.update(("|".join(columns) + "\n").encode("utf-8"))
    while True:
        rows = cursor.fetchmany(10000)
        if not rows:
            break
        for row in rows:
            digest.update(
                (
                    json.dumps(
                        row, ensure_ascii=False, default=str, separators=(",", ":")
                    )
                    + "\n"
                ).encode("utf-8")
            )
    return digest.hexdigest()


def compute_core_quality(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    quality = base_quality()
    scalar_sql = {
        "source_row_count": "SELECT count(*) FROM d3_t08_source_observation",
        "duplicate_observation_key_count": """
            SELECT count(*)
            FROM (
              SELECT ts_code, trade_date
              FROM d3_t08_source_observation
              GROUP BY 1, 2
              HAVING count(*) > 1
            )
        """,
        "raw_ohlc_invalid_count": """
            SELECT count(*)
            FROM d3_t08_source_observation
            WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
              OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
        """,
        "raw_high_low_violation_count": """
            SELECT count(*) FROM d3_t08_source_observation WHERE high < low
        """,
        "adjusted_ohlc_invalid_count": """
            SELECT count(*)
            FROM d3_t08_source_observation
            WHERE adjusted_open IS NULL OR adjusted_high IS NULL
              OR adjusted_low IS NULL OR adjusted_close IS NULL
              OR adjusted_open <= 0 OR adjusted_high <= 0
              OR adjusted_low <= 0 OR adjusted_close <= 0
        """,
        "adjusted_high_low_violation_count": """
            SELECT count(*) FROM d3_t08_source_observation
            WHERE adjusted_high < adjusted_low
        """,
        "effective_adj_factor_invalid_count": """
            SELECT count(*) FROM d3_t08_source_observation
            WHERE effective_adj_factor IS NULL OR effective_adj_factor <= 0
        """,
        "adjusted_factor_mismatch_count": """
            SELECT count(*)
            FROM d3_t08_source_observation
            WHERE abs(adjusted_open - open * effective_adj_factor) > 1e-8
               OR abs(adjusted_high - high * effective_adj_factor) > 1e-8
               OR abs(adjusted_low - low * effective_adj_factor) > 1e-8
               OR abs(adjusted_close - close * effective_adj_factor) > 1e-8
        """,
        "listing_pause_row_count": """
            SELECT count(*) FROM d3_t08_source_observation
            WHERE trading_status = 'listing_pause'
               OR daily_status = 'not_applicable_or_expected_empty'
        """,
        "is_listing_pause_true_count": """
            SELECT count(*) FROM d3_t08_source_observation
            WHERE is_listing_pause IS NOT false
        """,
        "policy_provenance_missing_count": """
            SELECT count(*) FROM d3_t08_source_observation
            WHERE is_policy_adjusted
              AND (
                adj_factor_policy_type IS NULL
                OR policy_evidence_status IS NULL
                OR policy_evidence_level IS NULL
              )
        """,
        "source_task_id_invalid_count": """
            SELECT count(*) FROM d3_t08_source_observation
            WHERE source_task_id IS NULL OR source_task_id != 'D2-T20'
        """,
        "generated_by_task_invalid_count": """
            SELECT count(*) FROM d3_t08_source_observation
            WHERE generated_by_task IS NULL OR generated_by_task != 'D3-T07'
        """,
        "row_provenance_missing_count": """
            SELECT count(*) FROM d3_t08_source_observation
            WHERE row_provenance IS NULL OR row_provenance = ''
        """,
    }
    for key, sql in scalar_sql.items():
        quality[key] = int(conn.execute(sql).fetchone()[0] or 0)
    warnings = ["amount_volume_unit_contract_not_declared_in_d3_t07_dataset"]
    quality["warnings"] = warnings
    quality["warning_count"] = len(warnings)
    return quality


def populate_schema_catalog(
    conn: duckdb.DuckDBPyConnection, rows: list[dict[str, Any]]
) -> None:
    conn.executemany(
        """
        INSERT INTO d3_research_dataset_schema_catalog
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["table_name"],
                row["column_name"],
                row["ordinal_position"],
                row["data_type"],
                row["nullable"],
                row["semantic_role"],
                row["route_agnostic"],
            )
            for row in rows
        ],
    )


def populate_registry(
    conn: duckdb.DuckDBPyConnection,
    *,
    source_duckdb: Path,
    schema_hash: str,
    dataset_hash: str,
) -> None:
    conn.execute(
        """
        INSERT INTO d3_research_dataset_registry
        SELECT 'D3_T08_RESEARCH_DATASET_FROM_D3_T07_CANDIDATE' AS dataset_id,
               'D3-T07' AS source_task_id,
               ? AS source_duckdb,
               ? AS source_table,
               count(*) AS row_count,
               count(DISTINCT ts_code) AS security_count,
               min(trade_date) AS min_trade_date,
               max(trade_date) AS max_trade_date,
               ? AS dataset_sha256,
               ? AS schema_sha256,
               'D3-T08' AS generated_by_task,
               false AS formal_data_version_published,
               false AS pcvt_values_generated,
               false AS r0_state_generated
        FROM d3_t08_source_observation
        """,
        [str(source_duckdb), SOURCE_TABLE, dataset_hash, schema_hash],
    )


def populate_field_quality(
    conn: duckdb.DuckDBPyConnection, columns: list[str], required: set[str]
) -> None:
    rows = []
    total = int(
        conn.execute("SELECT count(*) FROM d3_t08_source_observation").fetchone()[0]
        or 0
    )
    for column in columns:
        quoted = f'"{column}"'
        null_count = int(
            conn.execute(
                f"SELECT count(*) FROM d3_t08_source_observation WHERE {quoted} IS NULL"
            ).fetchone()[0]
            or 0
        )
        distinct_count = int(
            conn.execute(
                f"SELECT count(DISTINCT {quoted}) FROM d3_t08_source_observation"
            ).fetchone()[0]
            or 0
        )
        min_value, max_value = conn.execute(
            f"""
            SELECT min(CAST({quoted} AS VARCHAR)), max(CAST({quoted} AS VARCHAR))
            FROM d3_t08_source_observation
            """
        ).fetchone()
        if column in required and null_count > 0:
            status = "blocked_required_null"
            notes = "required field contains null"
        elif column in {"vol", "amount"} and null_count > 0:
            status = "warning_optional_null"
            notes = "participation proxy has null values"
        else:
            status = "ok"
            notes = "route-agnostic base field quality checked"
        rows.append(
            (
                column,
                null_count,
                total - null_count,
                distinct_count,
                min_value,
                max_value,
                status,
                notes,
            )
        )
    conn.executemany(
        """
        INSERT INTO d3_research_dataset_field_quality
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def populate_coverage_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        INSERT INTO d3_research_dataset_coverage_by_security
        SELECT ts_code,
               count(*) AS observation_row_count,
               min(trade_date) AS min_trade_date,
               max(trade_date) AS max_trade_date,
               sum(CASE WHEN is_policy_adjusted THEN 1 ELSE 0 END)::INTEGER,
               sum(CASE WHEN NOT is_policy_adjusted THEN 1 ELSE 0 END)::INTEGER,
               sum(CASE WHEN adj_factor_policy_type = 'neutral_factor_1'
                        THEN 1 ELSE 0 END)::INTEGER,
               sum(CASE WHEN adj_factor_policy_type = 'factor_interval'
                        THEN 1 ELSE 0 END)::INTEGER,
               sum(CASE WHEN is_limit_up THEN 1 ELSE 0 END)::INTEGER,
               sum(CASE WHEN is_limit_down THEN 1 ELSE 0 END)::INTEGER,
               'ok' AS coverage_status
        FROM d3_t08_source_observation
        GROUP BY 1
        ORDER BY 1
        """
    )
    conn.execute(
        """
        INSERT INTO d3_research_dataset_coverage_by_date
        SELECT trade_date,
               count(*) AS observation_row_count,
               count(DISTINCT ts_code) AS security_count,
               sum(CASE WHEN is_policy_adjusted THEN 1 ELSE 0 END)::INTEGER,
               sum(CASE WHEN NOT is_policy_adjusted THEN 1 ELSE 0 END)::INTEGER,
               sum(CASE WHEN is_limit_up THEN 1 ELSE 0 END)::INTEGER,
               sum(CASE WHEN is_limit_down THEN 1 ELSE 0 END)::INTEGER,
               'ok' AS coverage_status
        FROM d3_t08_source_observation
        GROUP BY 1
        ORDER BY 1
        """
    )


def populate_policy_usage(
    conn: duckdb.DuckDBPyConnection, *, listing_pause_excluded_count: int
) -> None:
    rows = _rows_as_dicts(
        conn,
        """
        SELECT coalesce(adj_factor_policy_type, 'provider_resolved') AS policy_type,
               count(*) AS row_count,
               count(DISTINCT ts_code) AS security_count,
               min(trade_date) AS min_trade_date,
               max(trade_date) AS max_trade_date,
               'observed in D3-T07 candidate rows' AS policy_usage_notes
        FROM d3_t08_source_observation
        GROUP BY 1
        """,
    )
    present = {row["policy_type"] for row in rows}
    for policy_type in ("provider_resolved", "neutral_factor_1", "factor_interval"):
        if policy_type not in present:
            rows.append(
                {
                    "policy_type": policy_type,
                    "row_count": 0,
                    "security_count": 0,
                    "min_trade_date": None,
                    "max_trade_date": None,
                    "policy_usage_notes": "not observed in filtered D3-T07 rows",
                }
            )
    rows.append(
        {
            "policy_type": "listing_pause_excluded",
            "row_count": int(listing_pause_excluded_count),
            "security_count": 0,
            "min_trade_date": None,
            "max_trade_date": None,
            "policy_usage_notes": "excluded upstream by D3-T07; no observation rows",
        }
    )
    conn.executemany(
        """
        INSERT INTO d3_research_dataset_policy_usage
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["policy_type"],
                int(row["row_count"] or 0),
                int(row["security_count"] or 0),
                row["min_trade_date"],
                row["max_trade_date"],
                row["policy_usage_notes"],
            )
            for row in sorted(rows, key=lambda item: item["policy_type"])
        ],
    )


def populate_window_capacity(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        INSERT INTO d3_research_dataset_window_capacity
        WITH flags AS (
          SELECT *,
                 CASE
                   WHEN adjusted_open > 0 AND adjusted_high > 0
                    AND adjusted_low > 0 AND adjusted_close > 0
                    AND adjusted_high >= adjusted_low
                   THEN 1 ELSE 0
                 END AS valid_price_flag,
                 CASE
                   WHEN vol IS NOT NULL AND amount IS NOT NULL
                    AND vol >= 0 AND amount >= 0
                   THEN 1 ELSE 0
                 END AS valid_participation_flag,
                 CASE WHEN adjusted_close > 0 THEN 1 ELSE 0 END AS valid_trend_flag
          FROM d3_t08_source_observation
        ),
        windows AS (
          SELECT ts_code,
                 trade_date,
                 sum(valid_price_flag) OVER (
                   PARTITION BY ts_code ORDER BY trade_date
                   ROWS BETWEEN 14 PRECEDING AND CURRENT ROW
                 )::INTEGER AS valid_price_window_count_15,
                 sum(valid_price_flag) OVER (
                   PARTITION BY ts_code ORDER BY trade_date
                   ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                 )::INTEGER AS valid_price_window_count_20,
                 sum(valid_price_flag) OVER (
                   PARTITION BY ts_code ORDER BY trade_date
                   ROWS BETWEEN 20 PRECEDING AND CURRENT ROW
                 )::INTEGER AS valid_price_window_count_21,
                 sum(valid_price_flag) OVER (
                   PARTITION BY ts_code ORDER BY trade_date
                   ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                 )::INTEGER AS valid_price_window_count_60,
                 sum(valid_price_flag) OVER (
                   PARTITION BY ts_code ORDER BY trade_date
                   ROWS BETWEEN 79 PRECEDING AND CURRENT ROW
                 )::INTEGER AS valid_price_window_count_80,
                 sum(valid_participation_flag) OVER (
                   PARTITION BY ts_code ORDER BY trade_date
                   ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                 )::INTEGER AS valid_participation_window_count_20,
                 sum(valid_participation_flag) OVER (
                   PARTITION BY ts_code ORDER BY trade_date
                   ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                 )::INTEGER AS valid_participation_window_count_60,
                 sum(valid_participation_flag) OVER (
                   PARTITION BY ts_code ORDER BY trade_date
                   ROWS BETWEEN 79 PRECEDING AND CURRENT ROW
                 )::INTEGER AS valid_participation_window_count_80,
                 sum(valid_trend_flag) OVER (
                   PARTITION BY ts_code ORDER BY trade_date
                   ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                 )::INTEGER AS valid_trend_window_count_20,
                 sum(valid_trend_flag) OVER (
                   PARTITION BY ts_code ORDER BY trade_date
                   ROWS BETWEEN 20 PRECEDING AND CURRENT ROW
                 )::INTEGER AS valid_trend_window_count_21,
                 sum(valid_trend_flag) OVER (
                   PARTITION BY ts_code ORDER BY trade_date
                   ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
                 )::INTEGER AS valid_trend_window_count_60
          FROM flags
        )
        SELECT *,
               CASE
                 WHEN valid_price_window_count_80 >= 80
                  AND valid_participation_window_count_80 >= 80
                  AND valid_trend_window_count_60 >= 60
                 THEN 'full_route_agnostic_window_capacity'
                 ELSE 'insufficient_history_for_long_windows'
               END AS window_capacity_status
        FROM windows
        ORDER BY ts_code, trade_date
        """
    )


def populate_audit_tables(
    conn: duckdb.DuckDBPyConnection,
    *,
    source_duckdb: Path,
    d3_t07_quality: dict[str, Any],
) -> None:
    schema_catalog_rows = schema_rows(conn)
    schema_hash = sha256_json_rows(schema_catalog_rows)
    columns = [row["column_name"] for row in schema_catalog_rows]
    data_hash = dataset_sha256(conn, columns)
    populate_schema_catalog(conn, schema_catalog_rows)
    populate_registry(
        conn,
        source_duckdb=source_duckdb,
        schema_hash=schema_hash,
        dataset_hash=data_hash,
    )
    required_columns = {
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "effective_adj_factor",
        "adjusted_open",
        "adjusted_high",
        "adjusted_low",
        "adjusted_close",
        "trading_status",
        "daily_status",
        "price_limit_status",
        "adjustment_factor_status",
        "is_listing_pause",
        "is_policy_adjusted",
        "source_task_id",
        "d2_source_duckdb",
        "generated_by_task",
        "row_provenance",
    }
    populate_field_quality(conn, columns, required_columns)
    populate_coverage_tables(conn)
    populate_policy_usage(
        conn,
        listing_pause_excluded_count=int(
            d3_t07_quality.get("listing_pause_excluded_count", 0) or 0
        ),
    )
    populate_window_capacity(conn)


def finalize_quality(conn: duckdb.DuckDBPyConnection, quality: dict[str, Any]) -> None:
    for key, table in (
        ("registry_row_count", "d3_research_dataset_registry"),
        ("schema_catalog_row_count", "d3_research_dataset_schema_catalog"),
        ("field_quality_row_count", "d3_research_dataset_field_quality"),
        ("coverage_by_security_row_count", "d3_research_dataset_coverage_by_security"),
        ("coverage_by_date_row_count", "d3_research_dataset_coverage_by_date"),
        ("policy_usage_row_count", "d3_research_dataset_policy_usage"),
        ("window_capacity_row_count", "d3_research_dataset_window_capacity"),
    ):
        quality[key] = int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def write_csv_reports(conn: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    outputs = (
        (
            "d3_t08_schema_catalog.csv",
            "d3_research_dataset_schema_catalog",
            [
                "table_name",
                "column_name",
                "ordinal_position",
                "data_type",
                "nullable",
                "semantic_role",
                "route_agnostic",
            ],
        ),
        (
            "d3_t08_field_quality.csv",
            "d3_research_dataset_field_quality",
            [
                "column_name",
                "null_count",
                "non_null_count",
                "distinct_count",
                "min_value_text",
                "max_value_text",
                "quality_status",
                "quality_notes",
            ],
        ),
        (
            "d3_t08_coverage_by_security.csv",
            "d3_research_dataset_coverage_by_security",
            [
                "ts_code",
                "observation_row_count",
                "min_trade_date",
                "max_trade_date",
                "policy_adjusted_row_count",
                "provider_resolved_row_count",
                "neutral_factor_policy_row_count",
                "factor_interval_policy_row_count",
                "limit_up_row_count",
                "limit_down_row_count",
                "coverage_status",
            ],
        ),
        (
            "d3_t08_coverage_by_date.csv",
            "d3_research_dataset_coverage_by_date",
            [
                "trade_date",
                "observation_row_count",
                "security_count",
                "policy_adjusted_row_count",
                "provider_resolved_row_count",
                "limit_up_row_count",
                "limit_down_row_count",
                "coverage_status",
            ],
        ),
        (
            "d3_t08_policy_usage_summary.csv",
            "d3_research_dataset_policy_usage",
            [
                "policy_type",
                "row_count",
                "security_count",
                "min_trade_date",
                "max_trade_date",
                "policy_usage_notes",
            ],
        ),
        (
            "d3_t08_window_capacity_summary.csv",
            "d3_research_dataset_window_capacity",
            [
                "ts_code",
                "trade_date",
                "valid_price_window_count_15",
                "valid_price_window_count_20",
                "valid_price_window_count_21",
                "valid_price_window_count_60",
                "valid_price_window_count_80",
                "valid_participation_window_count_20",
                "valid_participation_window_count_60",
                "valid_participation_window_count_80",
                "valid_trend_window_count_20",
                "valid_trend_window_count_21",
                "valid_trend_window_count_60",
                "window_capacity_status",
            ],
        ),
    )
    for file_name, table, columns in outputs:
        _write_csv(
            output_dir / file_name,
            _rows_as_dicts(conn, f"SELECT * FROM {table}"),
            columns,
        )


def write_empty_csv_outputs(output_dir: Path) -> None:
    empty_outputs = {
        "d3_t08_schema_catalog.csv": [
            "table_name",
            "column_name",
            "ordinal_position",
            "data_type",
            "nullable",
            "semantic_role",
            "route_agnostic",
        ],
        "d3_t08_field_quality.csv": [
            "column_name",
            "null_count",
            "non_null_count",
            "distinct_count",
            "min_value_text",
            "max_value_text",
            "quality_status",
            "quality_notes",
        ],
        "d3_t08_coverage_by_security.csv": [
            "ts_code",
            "observation_row_count",
            "min_trade_date",
            "max_trade_date",
            "policy_adjusted_row_count",
            "provider_resolved_row_count",
            "neutral_factor_policy_row_count",
            "factor_interval_policy_row_count",
            "limit_up_row_count",
            "limit_down_row_count",
            "coverage_status",
        ],
        "d3_t08_coverage_by_date.csv": [
            "trade_date",
            "observation_row_count",
            "security_count",
            "policy_adjusted_row_count",
            "provider_resolved_row_count",
            "limit_up_row_count",
            "limit_down_row_count",
            "coverage_status",
        ],
        "d3_t08_policy_usage_summary.csv": [
            "policy_type",
            "row_count",
            "security_count",
            "min_trade_date",
            "max_trade_date",
            "policy_usage_notes",
        ],
        "d3_t08_window_capacity_summary.csv": [
            "ts_code",
            "trade_date",
            "valid_price_window_count_15",
            "valid_price_window_count_20",
            "valid_price_window_count_21",
            "valid_price_window_count_60",
            "valid_price_window_count_80",
            "valid_participation_window_count_20",
            "valid_participation_window_count_60",
            "valid_participation_window_count_80",
            "valid_trend_window_count_20",
            "valid_trend_window_count_21",
            "valid_trend_window_count_60",
            "window_capacity_status",
        ],
    }
    for file_name, columns in empty_outputs.items():
        _write_csv(output_dir / file_name, [], columns)


def write_hash_summary(output_dir: Path) -> None:
    rows = []
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name != "d3_t08_candidate_file_hash_summary.json":
            rows.append(
                {
                    "file_name": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "byte_count": path.stat().st_size,
                }
            )
    _write_json(
        output_dir / "d3_t08_candidate_file_hash_summary.json",
        {"task_id": TASK_ID, "files": rows},
    )


def write_reports(
    *,
    output_dir: Path,
    run_id: str,
    output_duckdb: Path,
    quality: dict[str, Any],
    decision: str,
    generated: bool,
) -> dict[str, Any]:
    quality["d3_t08_generation_decision"] = decision
    quality["research_dataset_registry_generated"] = generated
    summary = output_summary(
        run_id=run_id,
        decision=decision,
        generated=generated,
        output_duckdb=output_duckdb,
    )
    _write_json(output_dir / "d3_t08_quality_report.json", quality)
    _write_json(output_dir / "d3_t08_generation_summary.json", summary)
    _write_json(
        output_dir / "d3_t08_handoff_candidate_report.json",
        handoff_report(
            decision=decision, generated=generated, output_duckdb=output_duckdb
        ),
    )
    write_hash_summary(output_dir)
    return summary


def blocked_reports(
    *,
    output_dir: Path,
    run_id: str,
    output_duckdb: Path,
    reason: str,
    gate_errors: list[str],
) -> dict[str, Any]:
    quality = base_quality()
    quality["blocking_reasons"] = gate_errors or [reason]
    write_empty_csv_outputs(output_dir)
    return write_reports(
        output_dir=output_dir,
        run_id=run_id,
        output_duckdb=output_duckdb,
        quality=quality,
        decision=reason,
        generated=False,
    )


def audit_d3_t08_research_dataset_registry(
    *,
    d3_t07_duckdb: Path,
    d3_t07_quality_report: Path,
    d3_t07_handoff_report: Path,
    output_dir: Path,
    contract: Path = DEFAULT_CONTRACT,
    sample_securities: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    guard_source_d3_t07_duckdb(d3_t07_duckdb)
    guard_source_d3_t07_report(
        d3_t07_quality_report, expected_name="d3_t07_quality_report.json"
    )
    guard_source_d3_t07_report(
        d3_t07_handoff_report, expected_name="d3_t07_handoff_candidate_report.json"
    )
    ensure_allowed_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    remove_previous_outputs(output_dir)
    run_id = _utc_run_id()
    _load_json(contract)
    d3_t07_quality = _load_json(d3_t07_quality_report)
    d3_t07_handoff = _load_json(d3_t07_handoff_report)
    output_duckdb = output_dir / OUTPUT_DUCKDB_NAME
    gate_ok, gate_errors = d3_t07_gate_passed(d3_t07_quality, d3_t07_handoff)
    if not gate_ok:
        return blocked_reports(
            output_dir=output_dir,
            run_id=run_id,
            output_duckdb=output_duckdb,
            reason="blocked_pending_d3_t07_candidate_observation",
            gate_errors=gate_errors,
        )

    conn = duckdb.connect(str(output_duckdb))
    try:
        conn.execute(
            f"ATTACH '{str(d3_t07_duckdb).replace("'", "''")}' AS d3t07 (READ_ONLY)"
        )
        create_output_tables(conn)
        create_source_view(
            conn,
            sample_securities=sample_securities,
            start_date=start_date,
            end_date=end_date,
        )
        quality = compute_core_quality(conn)
        blockers = has_core_blockers(quality)
        if not blockers:
            populate_audit_tables(
                conn,
                source_duckdb=d3_t07_duckdb,
                d3_t07_quality=d3_t07_quality,
            )
        finalize_quality(conn, quality)
        if blockers:
            decision = "blocked_pending_research_dataset_quality"
            generated = False
        elif quality["warning_count"] > 0:
            decision = "accepted_research_dataset_registry_with_warnings"
            generated = True
        else:
            decision = "accepted_research_dataset_registry"
            generated = True
        _write_json(output_dir / "d3_t08_quality_report.json", quality)
        write_csv_reports(conn, output_dir)
    finally:
        conn.close()

    summary = write_reports(
        output_dir=output_dir,
        run_id=run_id,
        output_duckdb=output_duckdb,
        quality=quality,
        decision=decision,
        generated=generated,
    )
    for forbidden in FORBIDDEN_OUTPUT_NAMES:
        if (output_dir / forbidden).exists():
            raise D3T08AuditError(f"forbidden output generated: {forbidden}")
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--d3-t07-duckdb", required=True, type=Path)
    parser.add_argument("--d3-t07-quality-report", required=True, type=Path)
    parser.add_argument("--d3-t07-handoff-report", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--sample-securities", type=int, default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = audit_d3_t08_research_dataset_registry(
        d3_t07_duckdb=args.d3_t07_duckdb,
        d3_t07_quality_report=args.d3_t07_quality_report,
        d3_t07_handoff_report=args.d3_t07_handoff_report,
        output_dir=args.output_dir,
        contract=args.contract,
        sample_securities=args.sample_securities,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
