"""Apply D2-T20 fast coverage policy acceptance to a D2 candidate copy."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb

from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (
    build_acceptance_reports,
    compute_quality_gate,
)

FORBIDDEN_PATH_TOKENS = (
    "data/raw",
    "data\\raw",
    "data/external",
    "data\\external",
    "marketdb",
    ".day",
)
CANONICAL_DUCKDB_NAME = "d2_t15_tnskhdata_staging.duckdb"
LISTING_PAUSE_INTERVALS = (
    ("000155.SZ", "20160510", "20171217"),
    ("000629.SZ", "20170505", "20180823"),
    ("000792.SZ", "20200522", "20210809"),
)
NEUTRAL_FACTOR_TS_CODES = ("688981.SH", "689009.SH")
DELTA_METRICS = (
    "listed_open_missing_daily_count",
    "price_limit_daily_dependency_missing_count",
    "unresolved_price_limit_status_count",
    "unresolved_adjustment_factor_count",
    "daily_raw_row_count",
    "stk_limit_resolved_count",
    "adj_factor_resolved_count",
)


class D2T20PolicyError(ValueError):
    """Raised when D2-T20 policy gates or paths fail."""


@dataclass(frozen=True)
class PolicyLedgerEntry:
    run_id: str
    policy_kind: str
    ts_code: str
    start_date: str
    end_date: str
    policy_type: str
    evidence_level: str
    affected_row_count: int
    applied_by_task: str = "D2-T20"


def _utc_run_id() -> str:
    return "D2-T20-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _norm(path: Path) -> str:
    return str(path).replace("\\", "/").lower()


def _has_forbidden_token(path: Path) -> bool:
    normalized = _norm(path)
    return any(
        token.replace("\\", "/") in normalized for token in FORBIDDEN_PATH_TOKENS
    )


def guard_source_duckdb(path: Path) -> None:
    normalized = _norm(path)
    if _has_forbidden_token(path):
        raise D2T20PolicyError(f"forbidden source DuckDB path: {path}")
    if path.suffix.lower() != ".duckdb":
        raise D2T20PolicyError(f"source must be a DuckDB file: {path}")
    if path.name != CANONICAL_DUCKDB_NAME:
        raise D2T20PolicyError(f"source DuckDB must be named {CANONICAL_DUCKDB_NAME}")
    if "data/generated/d2/" not in normalized:
        raise D2T20PolicyError("source DuckDB must be under data/generated/d2/")


def guard_output_dir(path: Path) -> None:
    normalized = _norm(path)
    if _has_forbidden_token(path):
        raise D2T20PolicyError(f"forbidden output path: {path}")
    if ".duckdb" in normalized:
        raise D2T20PolicyError("output-dir must not be a DuckDB path")
    if "data/generated/d2/" not in normalized:
        raise D2T20PolicyError("output-dir must be under data/generated/d2/")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
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


def copy_source_duckdb(source_duckdb: Path, output_dir: Path) -> Path:
    guard_source_duckdb(source_duckdb)
    guard_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / CANONICAL_DUCKDB_NAME
    if source_duckdb.resolve() == target.resolve():
        raise D2T20PolicyError("output DuckDB must not be the source DuckDB")
    shutil.copy2(source_duckdb, target)
    return target


def init_policy_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS d2_policy_listing_pause_intervals (
          ts_code TEXT,
          start_date TEXT,
          end_date TEXT,
          policy_type TEXT,
          evidence_level TEXT,
          evidence_note TEXT,
          applied_by_task TEXT
        );
        CREATE TABLE IF NOT EXISTS d2_policy_adj_factor_overrides (
          ts_code TEXT,
          start_date TEXT,
          end_date TEXT,
          policy_type TEXT,
          policy_factor DOUBLE,
          evidence_level TEXT,
          evidence_note TEXT,
          applied_by_task TEXT
        );
        """
    )


def policy_plan() -> dict[str, Any]:
    return {
        "task_id": "D2-T20",
        "listing_pause_intervals": [
            {
                "ts_code": ts_code,
                "start_date": start_date,
                "end_date": end_date,
                "policy_type": "listing_pause",
                "evidence_level": "user_attested",
            }
            for ts_code, start_date, end_date in LISTING_PAUSE_INTERVALS
        ],
        "neutral_adj_factor_overrides": [
            {
                "ts_code": ts_code,
                "policy_type": "neutral_factor_1",
                "policy_factor": 1.0,
                "evidence_level": "policy_candidate_user_approved",
            }
            for ts_code in NEUTRAL_FACTOR_TS_CODES
        ],
        "formal_source_evidence": False,
        "data_version_published": False,
        "d3_rows_generated": False,
        "r0_state_generated": False,
    }


def apply_listing_pause_policy(
    conn: duckdb.DuckDBPyConnection, *, run_id: str
) -> list[PolicyLedgerEntry]:
    entries: list[PolicyLedgerEntry] = []
    for ts_code, start_date, end_date in LISTING_PAUSE_INTERVALS:
        conn.execute(
            """
            DELETE FROM d2_policy_listing_pause_intervals
            WHERE ts_code = ? AND start_date = ? AND end_date = ?
            """,
            [ts_code, start_date, end_date],
        )
        conn.execute(
            """
            INSERT INTO d2_policy_listing_pause_intervals
            VALUES (?, ?, ?, 'listing_pause', 'user_attested', ?, 'D2-T20')
            """,
            [
                ts_code,
                start_date,
                end_date,
                "User-attested listing pause interval; not official hash evidence.",
            ],
        )
        affected = int(
            conn.execute(
                """
                SELECT count(*)
                FROM d2_source_status
                WHERE ts_code = ?
                  AND trade_date BETWEEN ? AND ?
                """,
                [ts_code, start_date, end_date],
            ).fetchone()[0]
            or 0
        )
        conn.execute(
            """
            UPDATE d2_source_status
            SET trading_status = 'listing_pause',
                daily_status = 'not_applicable_or_expected_empty',
                price_limit_status = 'not_applicable_or_expected_empty'
            WHERE ts_code = ?
              AND trade_date BETWEEN ? AND ?
            """,
            [ts_code, start_date, end_date],
        )
        entries.append(
            PolicyLedgerEntry(
                run_id=run_id,
                policy_kind="listing_pause",
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
                policy_type="listing_pause",
                evidence_level="user_attested",
                affected_row_count=affected,
            )
        )
    return entries


def apply_neutral_factor_policy(
    conn: duckdb.DuckDBPyConnection, *, run_id: str
) -> list[PolicyLedgerEntry]:
    entries: list[PolicyLedgerEntry] = []
    for ts_code in NEUTRAL_FACTOR_TS_CODES:
        bounds = conn.execute(
            """
            SELECT min(trade_date), max(trade_date)
            FROM d2_factor_evidence
            WHERE ts_code = ?
              AND adjustment_factor_status = 'missing'
            """,
            [ts_code],
        ).fetchone()
        start_date = str(bounds[0] or "")
        end_date = str(bounds[1] or "")
        if not start_date or not end_date:
            start_date = ""
            end_date = ""
        conn.execute(
            """
            DELETE FROM d2_policy_adj_factor_overrides
            WHERE ts_code = ?
            """,
            [ts_code],
        )
        conn.execute(
            """
            INSERT INTO d2_policy_adj_factor_overrides
            VALUES (?, ?, ?, 'neutral_factor_1', 1.0,
                    'policy_candidate_user_approved', ?, 'D2-T20')
            """,
            [
                ts_code,
                start_date,
                end_date,
                "User-approved neutral factor policy; not provider factor evidence.",
            ],
        )
        affected = int(
            conn.execute(
                """
                SELECT count(*)
                FROM d2_factor_evidence
                WHERE ts_code = ?
                  AND adjustment_factor_status = 'missing'
                """,
                [ts_code],
            ).fetchone()[0]
            or 0
        )
        conn.execute(
            """
            UPDATE d2_factor_evidence
            SET adjustment_factor_status = 'neutral_factor_1_policy'
            WHERE ts_code = ?
              AND adjustment_factor_status = 'missing'
            """,
            [ts_code],
        )
        entries.append(
            PolicyLedgerEntry(
                run_id=run_id,
                policy_kind="neutral_adj_factor",
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
                policy_type="neutral_factor_1",
                evidence_level="policy_candidate_user_approved",
                affected_row_count=affected,
            )
        )
    return entries


def rebuild_gaps_and_summary(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    conn.execute("DELETE FROM d2_coverage_gaps")
    conn.execute("DELETE FROM d2_quality_summary")
    conn.execute(
        """
        INSERT INTO d2_coverage_gaps
        SELECT ts_code, trade_date, 'listed_open_missing_daily'
        FROM d2_source_status
        WHERE trading_status = 'listed_open_missing_daily'
        UNION ALL
        SELECT ts_code, trade_date, 'unresolved_adjustment_factor'
        FROM d2_factor_evidence
        WHERE adjustment_factor_status = 'missing'
        UNION ALL
        SELECT ts_code, trade_date, price_limit_status
        FROM d2_source_status
        WHERE price_limit_status IN ('daily_dependency_missing', 'stk_limit_missing')
        """
    )
    metric_sql = {
        "daily_raw_row_count": "SELECT count(*) FROM staging_daily_raw",
        "listed_open_missing_daily_count": """
            SELECT count(*)
            FROM d2_source_status
            WHERE trading_status = 'listed_open_missing_daily'
        """,
        "price_limit_daily_dependency_missing_count": """
            SELECT count(*)
            FROM d2_source_status
            WHERE price_limit_status = 'daily_dependency_missing'
        """,
        "unresolved_price_limit_status_count": """
            SELECT count(*)
            FROM d2_source_status
            WHERE price_limit_status = 'stk_limit_missing'
        """,
        "unresolved_adjustment_factor_count": """
            SELECT count(*)
            FROM d2_factor_evidence
            WHERE adjustment_factor_status = 'missing'
        """,
        "stk_limit_resolved_count": """
            SELECT count(*)
            FROM d2_source_status
            WHERE price_limit_status = 'resolved'
        """,
        "adj_factor_resolved_count": """
            SELECT count(*)
            FROM d2_factor_evidence
            WHERE adjustment_factor_status IN ('resolved', 'neutral_factor_1_policy')
        """,
        "provider_error_count": """
            SELECT count(*)
            FROM staging_fetch_ledger
            WHERE error_category = 'provider_error'
        """,
        "rate_limit_count": """
            SELECT count(*)
            FROM staging_fetch_ledger
            WHERE error_category = 'rate_limit'
        """,
        "timeout_count": """
            SELECT count(*)
            FROM staging_fetch_ledger
            WHERE error_category = 'timeout'
        """,
        "unmapped_security_count": """
            SELECT CASE
              WHEN (SELECT count(*) FROM staging_security_mapping_diagnostics) > 0
              THEN (
                SELECT count(*)
                FROM staging_security_mapping_diagnostics
                WHERE mapping_status != 'resolved'
              )
              ELSE 0
            END
        """,
        "duplicate_daily_key_count": """
            SELECT count(*) FROM (
              SELECT ts_code, trade_date
              FROM staging_daily_raw
              GROUP BY 1, 2
              HAVING count(*) > 1
            )
        """,
        "duplicate_adj_factor_key_count": """
            SELECT count(*) FROM (
              SELECT ts_code, trade_date
              FROM staging_adj_factor
              GROUP BY 1, 2
              HAVING count(*) > 1
            )
        """,
        "duplicate_stk_limit_key_count": """
            SELECT count(*) FROM (
              SELECT ts_code, trade_date
              FROM staging_stk_limit
              GROUP BY 1, 2
              HAVING count(*) > 1
            )
        """,
        "duplicate_suspend_key_count": """
            SELECT count(*) FROM (
              SELECT ts_code, suspend_date
              FROM staging_suspend_d
              GROUP BY 1, 2
              HAVING count(*) > 1
            )
        """,
        "null_ohlc_count": """
            SELECT count(*)
            FROM staging_daily_raw
            WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
        """,
        "non_positive_price_count": """
            SELECT count(*)
            FROM staging_daily_raw
            WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
        """,
        "high_low_violation_count": """
            SELECT count(*) FROM staging_daily_raw WHERE high < low
        """,
    }
    quality = {
        key: int(conn.execute(sql).fetchone()[0] or 0)
        for key, sql in metric_sql.items()
    }
    for key, value in quality.items():
        conn.execute("INSERT INTO d2_quality_summary VALUES (?, ?)", [key, str(value)])
    return quality


def gap_delta(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "metric": metric,
            "before_count": int(before.get(metric, 0)),
            "after_count": int(after.get(metric, 0)),
            "delta": int(after.get(metric, 0)) - int(before.get(metric, 0)),
        }
        for metric in DELTA_METRICS
    ]


def remaining_gaps(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return _rows_as_dicts(
        conn,
        """
        SELECT ts_code, trade_date, gap_type
        FROM d2_coverage_gaps
        ORDER BY gap_type, ts_code, trade_date
        """,
    )


def blocker_counts_zero(quality: dict[str, Any]) -> bool:
    return all(
        int(quality.get(key, 0)) == 0
        for key in (
            "listed_open_missing_daily_count",
            "price_limit_daily_dependency_missing_count",
            "unresolved_price_limit_status_count",
            "unresolved_adjustment_factor_count",
            "unmapped_security_count",
            "provider_error_count",
            "rate_limit_count",
            "timeout_count",
            "duplicate_daily_key_count",
            "duplicate_adj_factor_key_count",
            "duplicate_stk_limit_key_count",
            "duplicate_suspend_key_count",
            "null_ohlc_count",
            "non_positive_price_count",
            "high_low_violation_count",
        )
    )


def acceptance_report(
    quality: dict[str, Any],
    *,
    policies_authorized: bool,
) -> dict[str, Any]:
    acceptance, _handoff = build_acceptance_reports(quality)
    acceptance["task_id"] = "D2-T20"
    acceptance["policy_based_acceptance"] = False
    acceptance["policy_evidence_level"] = "none"
    if policies_authorized and blocker_counts_zero(quality):
        acceptance["d2_acceptance_decision"] = "accepted_for_d3_candidate_generation"
        acceptance["quality_blockers"] = []
        acceptance["policy_based_acceptance"] = True
        acceptance["policy_evidence_level"] = "user_attested_and_policy_candidate"
    else:
        if (
            acceptance["d2_acceptance_decision"]
            == "accepted_for_d3_candidate_generation"
        ):
            acceptance["d2_acceptance_decision"] = (
                "blocked_pending_policy_authorization"
            )
            acceptance["quality_blockers"] = ["d2_t20_policy_authorization_missing"]
    acceptance["formal_duckdb_write_authorized"] = False
    acceptance["data_version_published"] = False
    acceptance["d3_rows_generated"] = False
    acceptance["pcvt_values_generated"] = False
    acceptance["r0_state_generated"] = False
    return acceptance


def handoff_report(
    *,
    acceptance: dict[str, Any],
    output_dir: Path,
    policies_authorized: bool,
) -> dict[str, Any]:
    accepted = (
        acceptance["d2_acceptance_decision"] == "accepted_for_d3_candidate_generation"
        and policies_authorized
    )
    return {
        "task_id": "D2-T20",
        "d2_acceptance_decision": acceptance["d2_acceptance_decision"],
        "d3_handoff_decision": (
            "d3_candidate_generation_authorized"
            if accepted
            else "d3_candidate_generation_blocked"
        ),
        "d3_generation_authorized": accepted,
        "d3_source_duckdb": str(output_dir / CANONICAL_DUCKDB_NAME) if accepted else "",
        "d3_rows_generated": False,
        "data_version_published": False,
        "r0_state_generated": False,
    }


def write_risk_register(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# D2-T20 policy risk register",
                "",
                "1. The three listing_pause intervals are user-attested, "
                "not official announcement hash evidence.",
                "2. Listing-pause dates do not generate daily bars and must "
                "not participate in return calculation.",
                "3. 688981.SH / 689009.SH use neutral_factor_1 policy; a "
                "future formal version can add official factor or "
                "corporate-action verification.",
                "4. D2-T20 advances a D3 research candidate, not a formal "
                "production source.",
                "5. Formal data_version publication requires official evidence "
                "or alternative source validation.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_handoff_notes(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# D2-T20 D3 handoff notes",
                "",
                "1. D3-T07 should ignore trading_status = listing_pause dates "
                "and not generate event/return rows for them.",
                "2. For neutral_factor_1_policy securities, D3 should use "
                "effective_adj_factor = 1.0.",
                "3. D3 must not treat listing_pause dates as missing samples.",
                "4. D3 must not treat policy rows as provider raw rows.",
                "5. D3 should preserve policy flags into D3 provenance.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def apply_d2_t20_policy(
    *,
    source_duckdb: Path,
    output_dir: Path,
    allow_user_attested_listing_pause: bool = False,
    allow_neutral_adj_factor_policy: bool = False,
    authorize_d3_candidate: bool = False,
) -> dict[str, Any]:
    policies_authorized = (
        allow_user_attested_listing_pause
        and allow_neutral_adj_factor_policy
        and authorize_d3_candidate
    )
    target_duckdb = copy_source_duckdb(source_duckdb, output_dir)
    run_id = _utc_run_id()
    _write_json(output_dir / "d2_t20_policy_plan.json", policy_plan())
    conn = duckdb.connect(str(target_duckdb))
    try:
        before_quality = compute_quality_gate(conn)
        init_policy_tables(conn)
        ledger: list[PolicyLedgerEntry] = []
        if policies_authorized:
            ledger.extend(apply_listing_pause_policy(conn, run_id=run_id))
            ledger.extend(apply_neutral_factor_policy(conn, run_id=run_id))
            after_quality = rebuild_gaps_and_summary(conn)
        else:
            after_quality = before_quality
        gaps = remaining_gaps(conn)
    finally:
        conn.close()

    ledger_rows = [asdict(entry) for entry in ledger]
    delta_rows = gap_delta(before_quality, after_quality)
    acceptance = acceptance_report(
        after_quality, policies_authorized=policies_authorized
    )
    handoff = handoff_report(
        acceptance=acceptance,
        output_dir=output_dir,
        policies_authorized=policies_authorized,
    )
    _write_jsonl(output_dir / "d2_t20_policy_ledger.jsonl", ledger_rows)
    _write_json(
        output_dir / "d2_t20_post_policy_quality_report.json",
        {"task_id": "D2-T20", "quality": after_quality},
    )
    _write_json(output_dir / "d2_t20_acceptance_candidate_report.json", acceptance)
    _write_json(output_dir / "d2_t20_handoff_candidate_report.json", handoff)
    _write_csv(
        output_dir / "d2_t20_remaining_coverage_gaps.csv",
        gaps,
        ["ts_code", "trade_date", "gap_type"],
    )
    _write_csv(
        output_dir / "d2_t20_gap_delta.csv",
        delta_rows,
        ["metric", "before_count", "after_count", "delta"],
    )
    write_risk_register(output_dir / "d2_t20_policy_risk_register.md")
    write_handoff_notes(output_dir / "d2_t20_d3_handoff_notes.md")
    summary = {
        "task_id": "D2-T20",
        "run_id": run_id,
        "policies_authorized": policies_authorized,
        "d2_acceptance_decision": acceptance["d2_acceptance_decision"],
        "d3_generation_authorized": handoff["d3_generation_authorized"],
        "d3_rows_generated": False,
        "formal_duckdb_write_authorized": False,
        "data_version_published": False,
        "r0_state_generated": False,
    }
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-duckdb", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--allow-user-attested-listing-pause", action="store_true")
    parser.add_argument("--allow-neutral-adj-factor-policy", action="store_true")
    parser.add_argument("--authorize-d3-candidate", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = apply_d2_t20_policy(
        source_duckdb=args.source_duckdb,
        output_dir=args.output_dir,
        allow_user_attested_listing_pause=args.allow_user_attested_listing_pause,
        allow_neutral_adj_factor_policy=args.allow_neutral_adj_factor_policy,
        authorize_d3_candidate=args.authorize_d3_candidate,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
