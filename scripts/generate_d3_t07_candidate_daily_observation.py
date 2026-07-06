"""Generate D3-T07 candidate daily observations from a D2-T20 candidate."""

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

DEFAULT_CONTRACT = (
    ROOT / "configs/d3/d3_t07_candidate_daily_observation_contract.v1.json"
)
OUTPUT_DUCKDB_NAME = "d3_t07_candidate_daily_observation.duckdb"
OBSERVATION_TABLE = "d3_candidate_daily_observation"
TASK_ID = "D3-T07"
SOURCE_TASK_ID = "D2-T20"
FORBIDDEN_OUTPUT_NAMES = {
    "data_version.json",
    "formal_manifest.json",
    "manifest.json",
    "labels.csv",
    "returns.csv",
    "backtest.csv",
    "portfolio.csv",
    "r0_state.csv",
}
PRE_INSERT_BLOCKER_KEYS = (
    "duplicate_observation_key_count",
    "null_ohlc_count",
    "non_positive_price_count",
    "high_low_violation_count",
    "missing_effective_adj_factor_count",
    "factor_interval_unresolved_count",
)


class D3T07GenerationError(ValueError):
    """Raised when D3-T07 candidate generation cannot proceed."""


def _utc_run_id() -> str:
    return "D3-T07-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _norm(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows_as_dicts(conn: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = conn.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def ensure_allowed_output_dir(path: Path) -> None:
    normalized = _norm(path)
    if "data/raw" in normalized or "data/external" in normalized:
        raise D3T07GenerationError("output-dir must not be under raw/external data")
    if "marketdb" in normalized or ".day" in normalized:
        raise D3T07GenerationError("output-dir must not target provider storage")
    if ".duckdb" in normalized:
        raise D3T07GenerationError("output-dir must be a directory")
    if "data/generated/d3/" not in normalized:
        raise D3T07GenerationError("output-dir must be under data/generated/d3/")


def remove_previous_outputs(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    for name in (
        OUTPUT_DUCKDB_NAME,
        "d3_t07_generation_summary.json",
        "d3_t07_quality_report.json",
        "d3_t07_handoff_candidate_report.json",
        "d3_t07_row_count_by_security.csv",
        "d3_t07_policy_usage_summary.csv",
        "d3_t07_excluded_listing_pause_rows.csv",
        "d3_t07_unresolved_rows.csv",
        "d3_t07_candidate_file_hash_summary.json",
    ):
        target = output_dir / name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()


def d2_t20_gate_passed(
    acceptance: dict[str, Any], handoff: dict[str, Any]
) -> tuple[bool, list[str]]:
    expected = {
        "d2_acceptance_decision": "accepted_for_d3_candidate_generation",
        "policy_based_acceptance": True,
        "policy_evidence_pending_hash": False,
        "formal_duckdb_write_authorized": False,
        "data_version_published": False,
        "d3_rows_generated": False,
        "r0_state_generated": False,
    }
    errors = [
        key
        for key, expected_value in expected.items()
        if acceptance.get(key) != expected_value
    ]
    if handoff.get("d3_generation_authorized") is not True:
        errors.append("d3_generation_authorized")
    if handoff.get("data_version_published") is not False:
        errors.append("handoff_data_version_published")
    if handoff.get("d3_rows_generated") is not False:
        errors.append("handoff_d3_rows_generated")
    if handoff.get("r0_state_generated") is not False:
        errors.append("handoff_r0_state_generated")
    return not errors, errors


def base_quality() -> dict[str, Any]:
    return {
        "task_id": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "input_daily_raw_row_count": 0,
        "generated_observation_row_count": 0,
        "listing_pause_excluded_count": 0,
        "null_ohlc_count": 0,
        "non_positive_price_count": 0,
        "high_low_violation_count": 0,
        "missing_effective_adj_factor_count": 0,
        "factor_interval_unresolved_count": 0,
        "duplicate_observation_key_count": 0,
        "policy_adjusted_row_count": 0,
        "neutral_factor_policy_row_count": 0,
        "factor_interval_policy_row_count": 0,
    }


def blocked_reports(
    *,
    output_dir: Path,
    run_id: str,
    reason: str,
    gate_errors: list[str] | None = None,
) -> dict[str, Any]:
    quality = base_quality()
    quality["blocking_reasons"] = gate_errors or [reason]
    summary = {
        "task_id": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "run_id": run_id,
        "d3_t07_generation_decision": reason,
        "d3_rows_generated": False,
        "data_version_published": False,
        "r0_state_generated": False,
    }
    handoff = {
        "task_id": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "d3_t07_generation_decision": reason,
        "d3_candidate_observation_generated": False,
        "d3_candidate_observation_path": "",
        "formal_data_version_published": False,
        "labels_generated": False,
        "returns_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "next_planned_task": (
            "D3-T08 PCVT input readiness and feature-base quality checks"
        ),
    }
    _write_json(output_dir / "d3_t07_generation_summary.json", summary)
    _write_json(output_dir / "d3_t07_quality_report.json", quality)
    _write_json(output_dir / "d3_t07_handoff_candidate_report.json", handoff)
    write_empty_csv_outputs(output_dir)
    write_hash_summary(output_dir)
    return summary


def filtered_daily_predicate(
    *, sample_securities: int | None, start_date: str | None, end_date: str | None
) -> str:
    predicates = ["1 = 1"]
    if start_date:
        predicates.append(f"d.trade_date >= '{start_date}'")
    if end_date:
        predicates.append(f"d.trade_date <= '{end_date}'")
    if sample_securities is not None:
        predicates.append(
            "d.ts_code IN ("
            "SELECT ts_code FROM ("
            "SELECT DISTINCT ts_code FROM d2.staging_daily_raw ORDER BY ts_code"
            f") LIMIT {int(sample_securities)})"
        )
    return " AND ".join(predicates)


def filtered_status_predicate(
    *, sample_securities: int | None, start_date: str | None, end_date: str | None
) -> str:
    predicates = ["1 = 1"]
    if start_date:
        predicates.append(f"s.trade_date >= '{start_date}'")
    if end_date:
        predicates.append(f"s.trade_date <= '{end_date}'")
    if sample_securities is not None:
        predicates.append(
            "s.ts_code IN ("
            "SELECT ts_code FROM ("
            "SELECT DISTINCT ts_code FROM d2.staging_daily_raw ORDER BY ts_code"
            f") LIMIT {int(sample_securities)})"
        )
    return " AND ".join(predicates)


def create_output_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OBSERVATION_TABLE} (
          ts_code TEXT NOT NULL,
          trade_date TEXT NOT NULL,
          open DOUBLE NOT NULL,
          high DOUBLE NOT NULL,
          low DOUBLE NOT NULL,
          close DOUBLE NOT NULL,
          vol DOUBLE,
          amount DOUBLE,
          effective_adj_factor DOUBLE NOT NULL,
          adjusted_open DOUBLE NOT NULL,
          adjusted_high DOUBLE NOT NULL,
          adjusted_low DOUBLE NOT NULL,
          adjusted_close DOUBLE NOT NULL,
          trading_status TEXT NOT NULL,
          daily_status TEXT NOT NULL,
          price_limit_status TEXT NOT NULL,
          adjustment_factor_status TEXT NOT NULL,
          up_limit DOUBLE,
          down_limit DOUBLE,
          is_limit_up BOOLEAN,
          is_limit_down BOOLEAN,
          is_listing_pause BOOLEAN NOT NULL,
          is_policy_adjusted BOOLEAN NOT NULL,
          adj_factor_policy_type TEXT,
          adj_factor_policy_source TEXT,
          policy_evidence_status TEXT,
          policy_evidence_level TEXT,
          source_task_id TEXT NOT NULL,
          d2_source_duckdb TEXT NOT NULL,
          generated_by_task TEXT NOT NULL,
          row_provenance TEXT NOT NULL,
          PRIMARY KEY (ts_code, trade_date)
        )
        """
    )


def create_candidate_view(
    conn: duckdb.DuckDBPyConnection,
    *,
    d2_source_duckdb: Path,
    sample_securities: int | None,
    start_date: str | None,
    end_date: str | None,
) -> None:
    daily_predicate = filtered_daily_predicate(
        sample_securities=sample_securities, start_date=start_date, end_date=end_date
    )
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW d3_t07_candidate_source AS
        WITH interval_match AS (
          SELECT d.ts_code,
                 d.trade_date,
                 count(p.effective_adj_factor) AS interval_match_count,
                 max(p.effective_adj_factor) AS interval_effective_adj_factor,
                 min(p.evidence_status) AS interval_evidence_status,
                 min(p.evidence_level) AS interval_evidence_level
          FROM d2.staging_daily_raw d
          LEFT JOIN d2.d2_policy_corporate_action_evidence p
            ON p.ts_code = d.ts_code
           AND d.trade_date BETWEEN p.start_date AND p.end_date
          WHERE {daily_predicate}
          GROUP BY 1, 2
        ),
        joined AS (
          SELECT d.ts_code,
                 d.trade_date,
                 d.open,
                 d.high,
                 d.low,
                 d.close,
                 d.vol,
                 d.amount,
                 s.trading_status,
                 s.daily_status,
                 s.price_limit_status,
                 f.adjustment_factor_status,
                 l.up_limit,
                 l.down_limit,
                 a.adj_factor,
                 o.policy_type AS override_policy_type,
                 o.evidence_level AS override_evidence_level,
                 im.interval_match_count,
                 im.interval_effective_adj_factor,
                 im.interval_evidence_status,
                 im.interval_evidence_level,
                 CASE
                   WHEN f.adjustment_factor_status = 'resolved' THEN a.adj_factor
                   WHEN f.adjustment_factor_status = 'neutral_factor_1_policy' THEN 1.0
                   WHEN f.adjustment_factor_status = 'factor_interval_policy'
                        AND im.interval_match_count = 1
                   THEN im.interval_effective_adj_factor
                   ELSE NULL
                 END AS effective_adj_factor
          FROM d2.staging_daily_raw d
          LEFT JOIN d2.d2_source_status s
            ON s.ts_code = d.ts_code AND s.trade_date = d.trade_date
          LEFT JOIN d2.d2_factor_evidence f
            ON f.ts_code = d.ts_code AND f.trade_date = d.trade_date
          LEFT JOIN d2.staging_stk_limit l
            ON l.ts_code = d.ts_code AND l.trade_date = d.trade_date
          LEFT JOIN d2.staging_adj_factor a
            ON a.ts_code = d.ts_code AND a.trade_date = d.trade_date
          LEFT JOIN d2.d2_policy_adj_factor_overrides o
            ON o.ts_code = d.ts_code
          LEFT JOIN interval_match im
            ON im.ts_code = d.ts_code AND im.trade_date = d.trade_date
          WHERE {daily_predicate}
        )
        SELECT *,
               CASE
                 WHEN trading_status = 'listing_pause'
                   OR daily_status = 'not_applicable_or_expected_empty'
                 THEN true ELSE false
               END AS excluded_listing_pause_or_not_applicable,
               CASE
                 WHEN adjustment_factor_status = 'factor_interval_policy'
                      AND coalesce(interval_match_count, 0) != 1
                 THEN true ELSE false
               END AS factor_interval_unresolved,
               '{str(d2_source_duckdb).replace("'", "''")}' AS d2_source_duckdb
        FROM joined
        """
    )


def compute_quality(
    conn: duckdb.DuckDBPyConnection,
    *,
    sample_securities: int | None,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, Any]:
    quality = base_quality()
    status_predicate = filtered_status_predicate(
        sample_securities=sample_securities, start_date=start_date, end_date=end_date
    )
    scalar_sql = {
        "input_daily_raw_row_count": "SELECT count(*) FROM d3_t07_candidate_source",
        "listing_pause_excluded_count": f"""
            SELECT count(*)
            FROM d2.d2_source_status s
            WHERE {status_predicate}
              AND s.trading_status = 'listing_pause'
              AND s.daily_status = 'not_applicable_or_expected_empty'
              AND s.price_limit_status = 'not_applicable_or_expected_empty'
        """,
        "null_ohlc_count": """
            SELECT count(*)
            FROM d3_t07_candidate_source
            WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
        """,
        "non_positive_price_count": """
            SELECT count(*)
            FROM d3_t07_candidate_source
            WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
        """,
        "high_low_violation_count": """
            SELECT count(*) FROM d3_t07_candidate_source WHERE high < low
        """,
        "missing_effective_adj_factor_count": """
            SELECT count(*)
            FROM d3_t07_candidate_source
            WHERE excluded_listing_pause_or_not_applicable = false
              AND open IS NOT NULL AND high IS NOT NULL
              AND low IS NOT NULL AND close IS NOT NULL
              AND open > 0 AND high > 0 AND low > 0 AND close > 0
              AND high >= low
              AND effective_adj_factor IS NULL
        """,
        "factor_interval_unresolved_count": """
            SELECT count(*)
            FROM d3_t07_candidate_source
            WHERE excluded_listing_pause_or_not_applicable = false
              AND factor_interval_unresolved = true
        """,
        "duplicate_observation_key_count": """
            SELECT count(*)
            FROM (
              SELECT ts_code, trade_date
              FROM d3_t07_candidate_source
              WHERE excluded_listing_pause_or_not_applicable = false
              GROUP BY 1, 2
              HAVING count(*) > 1
            )
        """,
    }
    for key, sql in scalar_sql.items():
        quality[key] = int(conn.execute(sql).fetchone()[0] or 0)
    return quality


def has_quality_blockers(quality: dict[str, Any]) -> bool:
    return any(int(quality.get(key, 0)) > 0 for key in PRE_INSERT_BLOCKER_KEYS)


def insert_candidate_rows(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        f"""
        INSERT INTO {OBSERVATION_TABLE}
        SELECT ts_code,
               trade_date,
               open,
               high,
               low,
               close,
               vol,
               amount,
               effective_adj_factor,
               open * effective_adj_factor AS adjusted_open,
               high * effective_adj_factor AS adjusted_high,
               low * effective_adj_factor AS adjusted_low,
               close * effective_adj_factor AS adjusted_close,
               trading_status,
               daily_status,
               price_limit_status,
               adjustment_factor_status,
               up_limit,
               down_limit,
               CASE WHEN up_limit IS NOT NULL THEN close >= up_limit ELSE NULL END,
               CASE WHEN down_limit IS NOT NULL THEN close <= down_limit ELSE NULL END,
               false AS is_listing_pause,
               adjustment_factor_status IN (
                 'neutral_factor_1_policy',
                 'factor_interval_policy'
               ) AS is_policy_adjusted,
               CASE
                 WHEN adjustment_factor_status = 'neutral_factor_1_policy'
                 THEN 'neutral_factor_1'
                 WHEN adjustment_factor_status = 'factor_interval_policy'
                 THEN 'factor_interval'
                 ELSE NULL
               END AS adj_factor_policy_type,
               CASE
                 WHEN adjustment_factor_status IN (
                   'neutral_factor_1_policy',
                   'factor_interval_policy'
                 )
                 THEN coalesce(override_evidence_level, interval_evidence_level)
                 ELSE NULL
               END AS adj_factor_policy_source,
               CASE
                 WHEN adjustment_factor_status IN (
                   'neutral_factor_1_policy',
                   'factor_interval_policy'
                 )
                 THEN coalesce(interval_evidence_status, 'hash_verified')
                 ELSE NULL
               END AS policy_evidence_status,
               CASE
                 WHEN adjustment_factor_status IN (
                   'neutral_factor_1_policy',
                   'factor_interval_policy'
                 )
                 THEN coalesce(interval_evidence_level, override_evidence_level)
                 ELSE NULL
               END AS policy_evidence_level,
               'D2-T20' AS source_task_id,
               d2_source_duckdb,
               'D3-T07' AS generated_by_task,
               (
                 'd2_t20_candidate:'
                 || ts_code || ':' || trade_date || ':'
                 || adjustment_factor_status
               ) AS row_provenance
        FROM d3_t07_candidate_source
        WHERE excluded_listing_pause_or_not_applicable = false
          AND open IS NOT NULL AND high IS NOT NULL
          AND low IS NOT NULL AND close IS NOT NULL
          AND open > 0 AND high > 0 AND low > 0 AND close > 0
          AND high >= low
          AND effective_adj_factor IS NOT NULL
          AND factor_interval_unresolved = false
        QUALIFY row_number() OVER (
          PARTITION BY ts_code, trade_date ORDER BY ts_code, trade_date
        ) = 1
        """
    )


def finalize_quality(conn: duckdb.DuckDBPyConnection, quality: dict[str, Any]) -> None:
    quality["generated_observation_row_count"] = int(
        conn.execute(f"SELECT count(*) FROM {OBSERVATION_TABLE}").fetchone()[0] or 0
    )
    quality["policy_adjusted_row_count"] = int(
        conn.execute(
            f"SELECT count(*) FROM {OBSERVATION_TABLE} WHERE is_policy_adjusted"
        ).fetchone()[0]
        or 0
    )
    quality["neutral_factor_policy_row_count"] = int(
        conn.execute(
            f"""
            SELECT count(*)
            FROM {OBSERVATION_TABLE}
            WHERE adj_factor_policy_type = 'neutral_factor_1'
            """
        ).fetchone()[0]
        or 0
    )
    quality["factor_interval_policy_row_count"] = int(
        conn.execute(
            f"""
            SELECT count(*)
            FROM {OBSERVATION_TABLE}
            WHERE adj_factor_policy_type = 'factor_interval'
            """
        ).fetchone()[0]
        or 0
    )


def write_csv_reports(
    conn: duckdb.DuckDBPyConnection,
    *,
    output_dir: Path,
) -> None:
    _write_csv(
        output_dir / "d3_t07_row_count_by_security.csv",
        _rows_as_dicts(
            conn,
            f"""
            SELECT ts_code, count(*) AS observation_row_count
            FROM {OBSERVATION_TABLE}
            GROUP BY 1
            ORDER BY 1
            """,
        ),
        ["ts_code", "observation_row_count"],
    )
    _write_csv(
        output_dir / "d3_t07_policy_usage_summary.csv",
        _rows_as_dicts(
            conn,
            f"""
            SELECT coalesce(adj_factor_policy_type, 'provider_resolved')
                     AS adj_factor_policy_type,
                   count(*) AS row_count
            FROM {OBSERVATION_TABLE}
            GROUP BY 1
            ORDER BY 1
            """,
        ),
        ["adj_factor_policy_type", "row_count"],
    )
    _write_csv(
        output_dir / "d3_t07_excluded_listing_pause_rows.csv",
        _rows_as_dicts(
            conn,
            """
            SELECT ts_code, trade_date, trading_status, daily_status,
                   price_limit_status
            FROM d2.d2_source_status
            WHERE trading_status = 'listing_pause'
              AND daily_status = 'not_applicable_or_expected_empty'
              AND price_limit_status = 'not_applicable_or_expected_empty'
            ORDER BY ts_code, trade_date
            """,
        ),
        [
            "ts_code",
            "trade_date",
            "trading_status",
            "daily_status",
            "price_limit_status",
        ],
    )
    _write_csv(
        output_dir / "d3_t07_unresolved_rows.csv",
        _rows_as_dicts(
            conn,
            """
            SELECT ts_code, trade_date, adjustment_factor_status,
                   effective_adj_factor, interval_match_count,
                   factor_interval_unresolved
            FROM d3_t07_candidate_source
            WHERE excluded_listing_pause_or_not_applicable = false
              AND (
                effective_adj_factor IS NULL
                OR factor_interval_unresolved = true
                OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                OR high < low
              )
            ORDER BY ts_code, trade_date
            """,
        ),
        [
            "ts_code",
            "trade_date",
            "adjustment_factor_status",
            "effective_adj_factor",
            "interval_match_count",
            "factor_interval_unresolved",
        ],
    )


def write_empty_csv_outputs(output_dir: Path) -> None:
    _write_csv(
        output_dir / "d3_t07_row_count_by_security.csv",
        [],
        ["ts_code", "observation_row_count"],
    )
    _write_csv(
        output_dir / "d3_t07_policy_usage_summary.csv",
        [],
        ["adj_factor_policy_type", "row_count"],
    )
    _write_csv(
        output_dir / "d3_t07_excluded_listing_pause_rows.csv",
        [],
        [
            "ts_code",
            "trade_date",
            "trading_status",
            "daily_status",
            "price_limit_status",
        ],
    )
    _write_csv(
        output_dir / "d3_t07_unresolved_rows.csv",
        [],
        [
            "ts_code",
            "trade_date",
            "adjustment_factor_status",
            "effective_adj_factor",
            "interval_match_count",
            "factor_interval_unresolved",
        ],
    )


def write_hash_summary(output_dir: Path) -> None:
    rows = []
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name != "d3_t07_candidate_file_hash_summary.json":
            rows.append(
                {
                    "file_name": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "byte_count": path.stat().st_size,
                }
            )
    _write_json(
        output_dir / "d3_t07_candidate_file_hash_summary.json",
        {"task_id": TASK_ID, "files": rows},
    )


def generate_d3_t07_candidate_daily_observation(
    *,
    d2_t20_duckdb: Path,
    d2_t20_acceptance_report: Path,
    d2_t20_handoff_report: Path,
    output_dir: Path,
    contract: Path = DEFAULT_CONTRACT,
    sample_securities: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    ensure_allowed_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    remove_previous_outputs(output_dir)
    run_id = _utc_run_id()
    _load_json(contract)
    acceptance = _load_json(d2_t20_acceptance_report)
    handoff = _load_json(d2_t20_handoff_report)
    gate_ok, gate_errors = d2_t20_gate_passed(acceptance, handoff)
    if not gate_ok:
        return blocked_reports(
            output_dir=output_dir,
            run_id=run_id,
            reason="blocked_pending_d2_t20_handoff",
            gate_errors=gate_errors,
        )

    output_duckdb = output_dir / OUTPUT_DUCKDB_NAME
    conn = duckdb.connect(str(output_duckdb))
    try:
        conn.execute(
            f"ATTACH '{str(d2_t20_duckdb).replace("'", "''")}' AS d2 (READ_ONLY)"
        )
        create_output_table(conn)
        create_candidate_view(
            conn,
            d2_source_duckdb=d2_t20_duckdb,
            sample_securities=sample_securities,
            start_date=start_date,
            end_date=end_date,
        )
        quality = compute_quality(
            conn,
            sample_securities=sample_securities,
            start_date=start_date,
            end_date=end_date,
        )
        blockers = has_quality_blockers(quality)
        if not blockers:
            insert_candidate_rows(conn)
        finalize_quality(conn, quality)
        decision = (
            "blocked_pending_factor_interval_resolution"
            if quality["factor_interval_unresolved_count"] > 0
            else "blocked_pending_quality_resolution"
            if blockers
            else "accepted_candidate_observation"
        )
        quality["d3_t07_generation_decision"] = decision
        quality["d3_candidate_observation_accepted"] = not blockers
        _write_json(output_dir / "d3_t07_quality_report.json", quality)
        write_csv_reports(conn, output_dir=output_dir)
    finally:
        conn.close()

    generated = not has_quality_blockers(quality)
    summary = {
        "task_id": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "run_id": run_id,
        "d3_t07_generation_decision": decision,
        "d3_rows_generated": generated,
        "data_version_published": False,
        "r0_state_generated": False,
        "output_duckdb": str(output_duckdb) if generated else "",
    }
    handoff_report = {
        "task_id": TASK_ID,
        "source_task_id": SOURCE_TASK_ID,
        "d3_t07_generation_decision": decision,
        "d3_candidate_observation_generated": generated,
        "d3_candidate_observation_path": str(output_duckdb) if generated else "",
        "formal_data_version_published": False,
        "labels_generated": False,
        "returns_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "next_planned_task": (
            "D3-T08 PCVT input readiness and feature-base quality checks"
        ),
    }
    _write_json(output_dir / "d3_t07_generation_summary.json", summary)
    _write_json(output_dir / "d3_t07_handoff_candidate_report.json", handoff_report)
    write_hash_summary(output_dir)
    for forbidden in FORBIDDEN_OUTPUT_NAMES:
        if (output_dir / forbidden).exists():
            raise D3T07GenerationError(f"forbidden output generated: {forbidden}")
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--d2-t20-duckdb", required=True, type=Path)
    parser.add_argument("--d2-t20-acceptance-report", required=True, type=Path)
    parser.add_argument("--d2-t20-handoff-report", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--sample-securities", type=int, default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = generate_d3_t07_candidate_daily_observation(
        d2_t20_duckdb=args.d2_t20_duckdb,
        d2_t20_acceptance_report=args.d2_t20_acceptance_report,
        d2_t20_handoff_report=args.d2_t20_handoff_report,
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
