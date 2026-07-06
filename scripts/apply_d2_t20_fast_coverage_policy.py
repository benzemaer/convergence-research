"""Apply D2-T20 fast coverage policy acceptance to a D2 candidate copy."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.materialize_d2_tnskhdata_security_major_duckdb_candidate import (  # noqa: E402
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


@dataclass(frozen=True)
class EvidenceGateResult:
    passed: bool
    pending_hash: bool
    blocker: str | None
    evidence_level: str
    target_policy_ts_codes: tuple[str, ...]


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


def load_policy_evidence_manifest(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


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
        CREATE TABLE IF NOT EXISTS d2_policy_evidence_documents (
          evidence_id TEXT,
          policy_kind TEXT,
          ts_code TEXT,
          document_role TEXT,
          source TEXT,
          title TEXT,
          announcement_date TEXT,
          url TEXT,
          sha256 TEXT,
          evidence_status TEXT,
          note TEXT,
          applied_by_task TEXT
        );
        CREATE TABLE IF NOT EXISTS d2_policy_corporate_action_evidence (
          ts_code TEXT,
          company_name TEXT,
          policy_type TEXT,
          start_date TEXT,
          end_date TEXT,
          effective_adj_factor DOUBLE,
          evidence_level TEXT,
          evidence_status TEXT,
          source TEXT,
          sha256 TEXT,
          note TEXT,
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


def _evidence_status(sha256: str, allow_pending_hash: bool) -> str:
    if sha256:
        return "hash_verified"
    return "pending_hash" if allow_pending_hash else "missing_hash"


def _manifest_listing_map(manifest: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not manifest:
        return {}
    return {
        str(row["ts_code"]): row for row in manifest.get("listing_pause_intervals", [])
    }


def _manifest_adj_map(manifest: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not manifest:
        return {}
    return {
        str(row["ts_code"]): row
        for row in manifest.get("adj_factor_policy_evidence", [])
    }


def write_listing_evidence_documents(
    conn: duckdb.DuckDBPyConnection,
    *,
    manifest: dict[str, Any] | None,
    allow_pending_hash: bool,
) -> None:
    conn.execute("DELETE FROM d2_policy_evidence_documents")
    listing_map = _manifest_listing_map(manifest)
    for ts_code, _start_date, _end_date in LISTING_PAUSE_INTERVALS:
        row = listing_map.get(ts_code, {})
        for document in row.get("evidence_documents", []):
            role = str(document.get("document_role", ""))
            sha256 = str(document.get("sha256", ""))
            status = _evidence_status(sha256, allow_pending_hash)
            conn.execute(
                """
                INSERT INTO d2_policy_evidence_documents
                VALUES (?, 'listing_pause', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'D2-T20')
                """,
                [
                    f"listing_pause:{ts_code}:{role}",
                    ts_code,
                    role,
                    document.get("source", ""),
                    document.get("title", ""),
                    document.get("announcement_date", ""),
                    document.get("url", ""),
                    sha256,
                    status,
                    document.get("note", ""),
                ],
            )


def write_corporate_action_evidence(
    conn: duckdb.DuckDBPyConnection,
    *,
    manifest: dict[str, Any] | None,
    allow_pending_hash: bool,
) -> None:
    conn.execute("DELETE FROM d2_policy_corporate_action_evidence")
    adj_map = _manifest_adj_map(manifest)
    for ts_code in NEUTRAL_FACTOR_TS_CODES:
        row = adj_map.get(ts_code, {})
        intervals = row.get("factor_intervals", [])
        if not intervals:
            conn.execute(
                """
                INSERT INTO d2_policy_corporate_action_evidence
                VALUES (?, ?, ?, '', '', NULL, ?, 'pending_evidence',
                        '', '', ?, 'D2-T20')
                """,
                [
                    ts_code,
                    row.get("company_name", ""),
                    row.get("policy_type", "neutral_or_factor_interval_policy"),
                    row.get("evidence_level", "corporate_action_checked"),
                    row.get("notes", "Pending corporate action evidence."),
                ],
            )
            continue
        for interval in intervals:
            sha256 = str(interval.get("sha256", ""))
            status = _evidence_status(sha256, allow_pending_hash)
            conn.execute(
                """
                INSERT INTO d2_policy_corporate_action_evidence
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'D2-T20')
                """,
                [
                    ts_code,
                    row.get("company_name", ""),
                    row.get("policy_type", ""),
                    interval.get("start_date", ""),
                    interval.get("end_date", ""),
                    interval.get("effective_adj_factor"),
                    row.get("evidence_level", ""),
                    status,
                    interval.get("source", ""),
                    sha256,
                    interval.get("note", ""),
                ],
            )


def policy_candidate_ts_codes(conn: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    rows = conn.execute(
        """
        SELECT DISTINCT ts_code
        FROM d2_factor_evidence
        WHERE adjustment_factor_status = 'missing'
        ORDER BY ts_code
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def evaluate_evidence_gate(
    conn: duckdb.DuckDBPyConnection,
    *,
    manifest: dict[str, Any] | None,
    require_policy_evidence: bool,
    allow_pending_hash: bool,
) -> EvidenceGateResult:
    targets = policy_candidate_ts_codes(conn)
    if not require_policy_evidence:
        return EvidenceGateResult(True, False, None, "not_required", targets)
    if manifest is None:
        return EvidenceGateResult(
            False,
            False,
            "d2_t20_policy_evidence_manifest_missing",
            "missing",
            targets,
        )
    listing_map = _manifest_listing_map(manifest)
    for ts_code, _start_date, _end_date in LISTING_PAUSE_INTERVALS:
        documents = listing_map.get(ts_code, {}).get("evidence_documents", [])
        roles = {str(document.get("document_role", "")) for document in documents}
        if not {"pause_listing_announcement", "resume_listing_announcement"} <= roles:
            return EvidenceGateResult(
                False,
                False,
                "d2_t20_listing_pause_evidence_missing",
                "incomplete",
                targets,
            )
    adj_map = _manifest_adj_map(manifest)
    manifest_targets = tuple(sorted(adj_map))
    if manifest_targets != targets:
        return EvidenceGateResult(
            False,
            False,
            "d2_t20_policy_evidence_target_mismatch",
            "target_mismatch",
            targets,
        )
    supplementary = {
        str(row.get("ts_code", ""))
        for row in manifest.get("supplementary_factor_observations", [])
    }
    if supplementary & set(targets):
        return EvidenceGateResult(
            False,
            False,
            "d2_t20_supplementary_evidence_overlaps_policy_target",
            "target_mismatch",
            targets,
        )
    pending_hash = False
    for row in listing_map.values():
        for document in row.get("evidence_documents", []):
            if not str(document.get("sha256", "")):
                pending_hash = True
    for row in adj_map.values():
        intervals = row.get("factor_intervals", [])
        for interval in intervals:
            if not str(interval.get("sha256", "")):
                pending_hash = True
            factor = interval.get("effective_adj_factor")
            if factor is not None and float(factor) != 1.0:
                return EvidenceGateResult(
                    False,
                    pending_hash,
                    "d2_t20_non_neutral_factor_interval_requires_policy_change",
                    "factor_interval_policy_candidate",
                    targets,
                )
    if pending_hash and not allow_pending_hash:
        return EvidenceGateResult(
            False,
            True,
            "d2_t20_policy_evidence_hash_missing",
            "pending_hash_blocked",
            targets,
        )
    level = (
        "official_announcement_pending_hash_and_policy_candidate"
        if pending_hash
        else "official_announcement_hash_backed_and_corporate_action_checked"
    )
    return EvidenceGateResult(True, pending_hash, None, level, targets)


def apply_listing_pause_policy(
    conn: duckdb.DuckDBPyConnection,
    *,
    run_id: str,
    manifest: dict[str, Any] | None,
    allow_pending_hash: bool,
) -> list[PolicyLedgerEntry]:
    entries: list[PolicyLedgerEntry] = []
    listing_map = _manifest_listing_map(manifest)
    for ts_code, start_date, end_date in LISTING_PAUSE_INTERVALS:
        documents = listing_map.get(ts_code, {}).get("evidence_documents", [])
        has_pending = any(not str(document.get("sha256", "")) for document in documents)
        evidence_level = (
            "official_announcement_pending_hash"
            if has_pending and allow_pending_hash
            else "official_announcement_hash_backed"
            if documents
            else "user_attested"
        )
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
            VALUES (?, ?, ?, 'listing_pause', ?, ?, 'D2-T20')
            """,
            [
                ts_code,
                start_date,
                end_date,
                evidence_level,
                "Listing pause policy backed by D2-T20 evidence manifest.",
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
                evidence_level=evidence_level,
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
    evidence_gate: EvidenceGateResult,
) -> dict[str, Any]:
    acceptance, _handoff = build_acceptance_reports(quality)
    acceptance["task_id"] = "D2-T20"
    acceptance["policy_based_acceptance"] = False
    acceptance["policy_evidence_level"] = evidence_gate.evidence_level
    acceptance["policy_evidence_pending_hash"] = evidence_gate.pending_hash
    acceptance["policy_evidence_blocker"] = evidence_gate.blocker or ""
    acceptance["policy_evidence_target_ts_codes"] = list(
        evidence_gate.target_policy_ts_codes
    )
    if policies_authorized and blocker_counts_zero(quality) and evidence_gate.passed:
        acceptance["d2_acceptance_decision"] = "accepted_for_d3_candidate_generation"
        acceptance["quality_blockers"] = []
        acceptance["policy_based_acceptance"] = True
        if evidence_gate.evidence_level == "not_required":
            acceptance["policy_evidence_level"] = "user_attested_and_policy_candidate"
    else:
        if (
            policies_authorized
            and blocker_counts_zero(quality)
            and not evidence_gate.passed
        ):
            acceptance["d2_acceptance_decision"] = "blocked_pending_policy_evidence"
            acceptance["quality_blockers"] = [
                "d2_t20_policy_evidence_incomplete_or_mismatch"
            ]
        elif (
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


def write_risk_register(
    path: Path,
    *,
    evidence_gate: EvidenceGateResult,
    manifest: dict[str, Any] | None,
) -> None:
    pending_note = (
        "pending hash accepted by explicit D2-T20 flag"
        if evidence_gate.pending_hash
        else "hash-backed evidence required before formal release"
    )
    manifest_note = (
        f"manifest_id={manifest.get('manifest_id', '')}"
        if manifest
        else "manifest absent"
    )
    path.write_text(
        "\n".join(
            [
                "# D2-T20 policy risk register",
                "",
                "1. The three listing_pause intervals must remain tied to "
                f"policy evidence provenance ({manifest_note}); current status: "
                f"{pending_note}.",
                "2. Listing-pause dates do not generate daily bars and must "
                "not participate in return calculation.",
                "3. 688981.SH / 689009.SH are the D2-T20 adjustment-factor "
                "policy targets for neutral_factor_1; 688728.SH is supplementary "
                "observation only and must not replace 688981.SH.",
                "4. D2-T20 advances a D3 research candidate, not a formal "
                "production source or formal source promotion.",
                "5. Formal data_version publication requires official evidence "
                "hashes or alternative source validation.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_handoff_notes(path: Path, *, evidence_gate: EvidenceGateResult) -> None:
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
                "6. D3 notes must preserve policy_evidence_status, "
                "policy_evidence_provenance, factor_interval/effective_adj_factor, "
                "and neutral factor policy flags.",
                f"7. Current policy_evidence_status: {evidence_gate.evidence_level}; "
                f"pending_hash={str(evidence_gate.pending_hash).lower()}.",
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
    policy_evidence_manifest: Path | None = None,
    require_policy_evidence: bool = False,
    allow_pending_evidence_hash: bool = False,
) -> dict[str, Any]:
    policies_authorized = (
        allow_user_attested_listing_pause
        and allow_neutral_adj_factor_policy
        and authorize_d3_candidate
    )
    manifest = load_policy_evidence_manifest(policy_evidence_manifest)
    target_duckdb = copy_source_duckdb(source_duckdb, output_dir)
    run_id = _utc_run_id()
    _write_json(output_dir / "d2_t20_policy_plan.json", policy_plan())
    conn = duckdb.connect(str(target_duckdb))
    try:
        before_quality = compute_quality_gate(conn)
        init_policy_tables(conn)
        write_listing_evidence_documents(
            conn, manifest=manifest, allow_pending_hash=allow_pending_evidence_hash
        )
        write_corporate_action_evidence(
            conn, manifest=manifest, allow_pending_hash=allow_pending_evidence_hash
        )
        evidence_gate = evaluate_evidence_gate(
            conn,
            manifest=manifest,
            require_policy_evidence=require_policy_evidence,
            allow_pending_hash=allow_pending_evidence_hash,
        )
        ledger: list[PolicyLedgerEntry] = []
        if policies_authorized:
            ledger.extend(
                apply_listing_pause_policy(
                    conn,
                    run_id=run_id,
                    manifest=manifest,
                    allow_pending_hash=allow_pending_evidence_hash,
                )
            )
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
        after_quality,
        policies_authorized=policies_authorized,
        evidence_gate=evidence_gate,
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
    write_risk_register(
        output_dir / "d2_t20_policy_risk_register.md",
        evidence_gate=evidence_gate,
        manifest=manifest,
    )
    write_handoff_notes(
        output_dir / "d2_t20_d3_handoff_notes.md", evidence_gate=evidence_gate
    )
    summary = {
        "task_id": "D2-T20",
        "run_id": run_id,
        "policies_authorized": policies_authorized,
        "policy_evidence_gate_passed": evidence_gate.passed,
        "policy_evidence_pending_hash": evidence_gate.pending_hash,
        "policy_evidence_level": evidence_gate.evidence_level,
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
    parser.add_argument(
        "--policy-evidence-manifest",
        type=Path,
        default=None,
        help=("Optional D2-T20 policy evidence manifest. Default: no evidence gate."),
    )
    parser.add_argument("--require-policy-evidence", action="store_true")
    parser.add_argument("--allow-pending-evidence-hash", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = apply_d2_t20_policy(
        source_duckdb=args.source_duckdb,
        output_dir=args.output_dir,
        allow_user_attested_listing_pause=args.allow_user_attested_listing_pause,
        allow_neutral_adj_factor_policy=args.allow_neutral_adj_factor_policy,
        authorize_d3_candidate=args.authorize_d3_candidate,
        policy_evidence_manifest=args.policy_evidence_manifest,
        require_policy_evidence=args.require_policy_evidence,
        allow_pending_evidence_hash=args.allow_pending_evidence_hash,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
