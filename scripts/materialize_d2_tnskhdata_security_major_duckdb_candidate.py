"""D2-T15 security-major tnskhdata DuckDB candidate materialization."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.resolve_security_provider_codes import resolve_security_provider_codes  # noqa: E402,I001

DEFAULT_SECURITY_UNIVERSE = (
    ROOT / "configs/d2/csi800_static_2026_06_membership_alignment.v1.json"
)
DEFAULT_CONTRACT = (
    ROOT / "configs/d2/tnskhdata_full_materialization_acceptance_contract.v1.json"
)
DEFAULT_OUTPUT_DIR = (
    ROOT / "data/generated/d2/d2_t15_tnskhdata_security_major_candidate"
)
DEFAULT_START_DATE = "20160101"
DEFAULT_END_DATE = "20260630"
ENDPOINTS = ("daily", "adj_factor", "stock_st", "suspend_d", "stk_limit")
COMPLETED_LEDGER_STATUSES = {
    "succeeded",
    "empty_resolved",
    "unsupported_param_variant",
}
FORBIDDEN_OUTPUT_TOKENS = (
    "data/raw",
    "data/external",
    "marketdb",
    ".day",
)


class D2T15MaterializationError(ValueError):
    """Raised when D2-T15 candidate materialization gates fail."""


@dataclass(frozen=True)
class SecurityMajorFetchTask:
    task_id: str
    endpoint: str
    ts_code: str
    start_date: str
    end_date: str
    param_variant: str
    task_hash: str


@dataclass(frozen=True)
class SecurityUniverseLoadResult:
    securities: list[dict[str, str]]
    mapping_diagnostics: list[dict[str, Any]]
    metrics: dict[str, int]


@dataclass
class FetchLedgerEntry:
    task_id: str
    endpoint: str
    ts_code: str
    start_date: str
    end_date: str
    param_variant: str
    task_hash: str
    status: str
    attempt_count: int
    row_count: int
    accepted_row_count: int
    error_category: str | None
    error_message_redacted: str | None
    started_at: str
    completed_at: str
    elapsed_seconds: float


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _date_yyyymmdd(value: Any) -> str:
    return str(value or "").strip()[:10].replace("-", "")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _row_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _task_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _redact_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    for key in ("TNSKHDATA_TOKEN", "TUSHARE_TOKEN", "token", "secret"):
        text = (
            text.replace(os.environ.get(key, ""), "***")
            if os.environ.get(key)
            else text
        )
    return text[:300]


def _classify_error(exc: Exception) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if "rate" in text or "limit" in text or "频" in text:
        return "rate_limit"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if any(
        token in text for token in ("argument", "parameter", "unexpected", "schema")
    ):
        return "unsupported_param_variant"
    return "provider_error"


def _frame_records(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if hasattr(payload, "to_dict"):
        records = payload.to_dict("records")
    elif isinstance(payload, list):
        records = payload
    else:
        records = list(payload)
    return [dict(row) for row in records]


def ensure_allowed_output_dir(path: Path) -> None:
    normalized = str(path).replace("\\", "/").lower()
    if any(token in normalized for token in FORBIDDEN_OUTPUT_TOKENS):
        raise D2T15MaterializationError(f"forbidden output path: {path}")
    if ".duckdb" in normalized and not normalized.endswith(
        "d2_t15_tnskhdata_staging.duckdb"
    ):
        raise D2T15MaterializationError(f"forbidden DuckDB output path: {path}")


def load_security_universe(
    path: Path, limit: int | None = None
) -> SecurityUniverseLoadResult:
    payload = _load_json(path)
    rows = payload.get("rows", [])
    selected_rows = rows[:limit] if limit is not None else rows
    securities: list[dict[str, str]] = []
    diagnostics: list[dict[str, Any]] = []
    for row in selected_rows:
        mapping = resolve_security_provider_codes(str(row["security_id"]))
        diagnostics.append(
            {
                "security_id": str(row["security_id"]),
                "ts_code": mapping.tnskhdata_ts_code or "",
                "mapping_status": mapping.mapping_status,
                "mapping_blocking_reasons": mapping.mapping_blocking_reasons,
            }
        )
        if mapping.mapping_status != "resolved" or not mapping.tnskhdata_ts_code:
            continue
        securities.append(
            {
                "security_id": str(row["security_id"]),
                "ts_code": mapping.tnskhdata_ts_code,
                "universe_id": str(row.get("universe_id", "")),
                "time_segment_id": str(row.get("time_segment_id", "")),
            }
        )
    return SecurityUniverseLoadResult(
        securities=securities,
        mapping_diagnostics=diagnostics,
        metrics={
            "configured_security_count": len(selected_rows),
            "mapped_security_count": len(securities),
            "unmapped_security_count": len(selected_rows) - len(securities),
        },
    )


def make_date_chunks(
    start_date: str, end_date: str, chunk_policy: str
) -> list[tuple[str, str]]:
    start_date = _date_yyyymmdd(start_date)
    end_date = _date_yyyymmdd(end_date)
    if chunk_policy == "full-range":
        return [(start_date, end_date)]
    start_year = int(start_date[:4])
    end_year = int(end_date[:4])
    chunks: list[tuple[str, str]] = []
    if chunk_policy == "year":
        for year in range(start_year, end_year + 1):
            chunk_start = max(start_date, f"{year}0101")
            chunk_end = min(end_date, f"{year}1231")
            chunks.append((chunk_start, chunk_end))
        return chunks
    if chunk_policy == "month":
        year = start_year
        month = int(start_date[4:6])
        while year < end_year or (year == end_year and month <= int(end_date[4:6])):
            chunk_start = max(start_date, f"{year}{month:02d}01")
            if month == 12:
                next_year, next_month = year + 1, 1
            else:
                next_year, next_month = year, month + 1
            next_month_start = datetime(next_year, next_month, 1)
            month_end = datetime.fromtimestamp(next_month_start.timestamp() - 86400)
            chunk_end = min(end_date, month_end.strftime("%Y%m%d"))
            chunks.append((chunk_start, chunk_end))
            year, month = next_year, next_month
        return chunks
    raise D2T15MaterializationError(f"unsupported chunk policy: {chunk_policy}")


def build_security_major_fetch_plan(
    securities: list[dict[str, str]],
    *,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    chunk_policy: str = "year",
) -> list[SecurityMajorFetchTask]:
    tasks: list[SecurityMajorFetchTask] = []
    for security in securities:
        ts_code = security["ts_code"]
        for endpoint in ENDPOINTS:
            for chunk_start, chunk_end in make_date_chunks(
                start_date, end_date, chunk_policy
            ):
                param_variant = "ts_code_start_end"
                payload = {
                    "endpoint": endpoint,
                    "ts_code": ts_code,
                    "start_date": chunk_start,
                    "end_date": chunk_end,
                    "param_variant": param_variant,
                }
                digest = _task_hash(payload)
                tasks.append(
                    SecurityMajorFetchTask(
                        task_id=f"{endpoint}:{ts_code}:{chunk_start}:{chunk_end}:{digest[:8]}",
                        endpoint=endpoint,
                        ts_code=ts_code,
                        start_date=chunk_start,
                        end_date=chunk_end,
                        param_variant=param_variant,
                        task_hash=digest,
                    )
                )
    return tasks


def load_resume_ledger(path: Path) -> dict[str, dict[str, Any]]:
    completed: dict[str, dict[str, Any]] = {}
    for entry in _read_jsonl(path):
        if entry.get("status") in COMPLETED_LEDGER_STATUSES and entry.get("task_hash"):
            completed[str(entry["task_id"])] = entry
    return completed


def filter_tasks_for_resume(
    tasks: list[SecurityMajorFetchTask], ledger_path: Path, *, resume: bool
) -> list[SecurityMajorFetchTask]:
    if not resume:
        return tasks
    completed = load_resume_ledger(ledger_path)
    return [
        task
        for task in tasks
        if completed.get(task.task_id, {}).get("task_hash") != task.task_hash
    ]


class DuckDBStagingWriter:
    """Single-connection writer for D2-T15 DuckDB candidate staging."""

    def __init__(self, path: Path) -> None:
        ensure_allowed_output_dir(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = duckdb.connect(str(path))
        self.init_schema()

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS staging_security_universe (
              security_id TEXT,
              ts_code TEXT,
              universe_id TEXT,
              time_segment_id TEXT
            );
            CREATE TABLE IF NOT EXISTS staging_security_mapping_diagnostics (
              security_id TEXT,
              ts_code TEXT,
              mapping_status TEXT,
              mapping_blocking_reasons TEXT
            );
            CREATE TABLE IF NOT EXISTS staging_stock_basic (
              ts_code TEXT,
              list_date TEXT,
              delist_date TEXT
            );
            CREATE TABLE IF NOT EXISTS staging_trade_calendar (
              cal_date TEXT,
              is_open TEXT
            );
            CREATE TABLE IF NOT EXISTS staging_daily_raw (
              ts_code TEXT,
              trade_date TEXT,
              open DOUBLE,
              high DOUBLE,
              low DOUBLE,
              close DOUBLE,
              pre_close DOUBLE,
              vol DOUBLE,
              amount DOUBLE,
              source_registry_id TEXT,
              endpoint TEXT,
              fetch_scope TEXT,
              source_snapshot_id TEXT,
              provider_row_hash TEXT,
              ingested_at TEXT
            );
            CREATE TABLE IF NOT EXISTS staging_adj_factor (
              ts_code TEXT,
              trade_date TEXT,
              adj_factor DOUBLE,
              source_snapshot_id TEXT,
              provider_row_hash TEXT,
              ingested_at TEXT
            );
            CREATE TABLE IF NOT EXISTS staging_stock_st (
              ts_code TEXT,
              trade_date TEXT,
              st_status TEXT,
              source_snapshot_id TEXT,
              provider_row_hash TEXT,
              ingested_at TEXT
            );
            CREATE TABLE IF NOT EXISTS staging_suspend_d (
              ts_code TEXT,
              suspend_date TEXT,
              suspend_type TEXT,
              source_snapshot_id TEXT,
              provider_row_hash TEXT,
              ingested_at TEXT
            );
            CREATE TABLE IF NOT EXISTS staging_stk_limit (
              ts_code TEXT,
              trade_date TEXT,
              up_limit DOUBLE,
              down_limit DOUBLE,
              pre_close DOUBLE,
              source_snapshot_id TEXT,
              provider_row_hash TEXT,
              ingested_at TEXT
            );
            CREATE TABLE IF NOT EXISTS staging_fetch_ledger (
              task_id TEXT,
              endpoint TEXT,
              ts_code TEXT,
              start_date TEXT,
              end_date TEXT,
              param_variant TEXT,
              task_hash TEXT,
              status TEXT,
              attempt_count INTEGER,
              row_count INTEGER,
              accepted_row_count INTEGER,
              error_category TEXT,
              error_message_redacted TEXT,
              started_at TEXT,
              completed_at TEXT,
              elapsed_seconds DOUBLE
            );
            CREATE TABLE IF NOT EXISTS staging_provider_errors (
              task_id TEXT,
              endpoint TEXT,
              ts_code TEXT,
              error_category TEXT,
              error_message_redacted TEXT
            );
            CREATE TABLE IF NOT EXISTS d2_expected_security_dates (
              ts_code TEXT,
              trade_date TEXT
            );
            CREATE TABLE IF NOT EXISTS d2_source_status (
              ts_code TEXT,
              trade_date TEXT,
              trading_status TEXT,
              daily_status TEXT,
              price_limit_status TEXT
            );
            CREATE TABLE IF NOT EXISTS d2_factor_evidence (
              ts_code TEXT,
              trade_date TEXT,
              adjustment_factor_status TEXT
            );
            CREATE TABLE IF NOT EXISTS d2_adjusted_price (
              ts_code TEXT,
              trade_date TEXT,
              adj_close DOUBLE
            );
            CREATE TABLE IF NOT EXISTS d2_coverage_gaps (
              ts_code TEXT,
              trade_date TEXT,
              gap_type TEXT
            );
            CREATE TABLE IF NOT EXISTS d2_quality_summary (
              metric TEXT,
              value TEXT
            );
            """
        )

    def write_security_universe(self, rows: list[dict[str, Any]]) -> None:
        payload = [
            (
                row.get("security_id"),
                row.get("ts_code"),
                row.get("universe_id"),
                row.get("time_segment_id"),
            )
            for row in rows
        ]
        self.conn.executemany(
            "INSERT INTO staging_security_universe VALUES (?, ?, ?, ?)", payload
        )

    def write_security_mapping_diagnostics(self, rows: list[dict[str, Any]]) -> None:
        payload = [
            (
                row.get("security_id"),
                row.get("ts_code"),
                row.get("mapping_status"),
                json.dumps(
                    row.get("mapping_blocking_reasons", []),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
            for row in rows
        ]
        self.conn.executemany(
            "INSERT INTO staging_security_mapping_diagnostics VALUES (?, ?, ?, ?)",
            payload,
        )

    def write_trade_calendar(self, rows: list[dict[str, Any]]) -> None:
        payload = [
            (_date_yyyymmdd(row.get("cal_date")), str(row.get("is_open")))
            for row in rows
        ]
        self.conn.executemany(
            "INSERT INTO staging_trade_calendar VALUES (?, ?)", payload
        )

    def write_stock_basic(self, rows: list[dict[str, Any]]) -> None:
        payload = [
            (
                row.get("ts_code"),
                _date_yyyymmdd(row.get("list_date")),
                _date_yyyymmdd(row.get("delist_date")),
            )
            for row in rows
        ]
        self.conn.executemany(
            "INSERT INTO staging_stock_basic VALUES (?, ?, ?)", payload
        )

    def write_endpoint_rows(self, endpoint: str, rows: list[dict[str, Any]]) -> int:
        ingested_at = _utc_now()
        if endpoint == "daily":
            payload = [
                (
                    row.get("ts_code"),
                    _date_yyyymmdd(row.get("trade_date")),
                    row.get("open"),
                    row.get("high"),
                    row.get("low"),
                    row.get("close"),
                    row.get("pre_close"),
                    row.get("vol"),
                    row.get("amount"),
                    "TNSKHDATA",
                    "daily",
                    "security_major",
                    row.get("source_snapshot_id", "D2_T15_TNSKHDATA_SECURITY_MAJOR"),
                    _row_hash(row),
                    ingested_at,
                )
                for row in rows
            ]
            self.conn.executemany(
                "INSERT INTO staging_daily_raw VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                payload,
            )
            return len(payload)
        if endpoint == "adj_factor":
            payload = [
                (
                    row.get("ts_code"),
                    _date_yyyymmdd(row.get("trade_date")),
                    row.get("adj_factor"),
                    row.get("source_snapshot_id", "D2_T15_TNSKHDATA_SECURITY_MAJOR"),
                    _row_hash(row),
                    ingested_at,
                )
                for row in rows
            ]
            self.conn.executemany(
                "INSERT INTO staging_adj_factor VALUES (?, ?, ?, ?, ?, ?)", payload
            )
            return len(payload)
        if endpoint == "stock_st":
            payload = [
                (
                    row.get("ts_code"),
                    _date_yyyymmdd(row.get("trade_date") or row.get("ann_date")),
                    str(row.get("st_status") or row.get("name_type") or ""),
                    row.get("source_snapshot_id", "D2_T15_TNSKHDATA_SECURITY_MAJOR"),
                    _row_hash(row),
                    ingested_at,
                )
                for row in rows
            ]
            self.conn.executemany(
                "INSERT INTO staging_stock_st VALUES (?, ?, ?, ?, ?, ?)", payload
            )
            return len(payload)
        if endpoint == "suspend_d":
            payload = [
                (
                    row.get("ts_code"),
                    _date_yyyymmdd(row.get("suspend_date") or row.get("trade_date")),
                    str(row.get("suspend_type") or ""),
                    row.get("source_snapshot_id", "D2_T15_TNSKHDATA_SECURITY_MAJOR"),
                    _row_hash(row),
                    ingested_at,
                )
                for row in rows
            ]
            self.conn.executemany(
                "INSERT INTO staging_suspend_d VALUES (?, ?, ?, ?, ?, ?)", payload
            )
            return len(payload)
        if endpoint == "stk_limit":
            payload = [
                (
                    row.get("ts_code"),
                    _date_yyyymmdd(row.get("trade_date")),
                    row.get("up_limit"),
                    row.get("down_limit"),
                    row.get("pre_close"),
                    row.get("source_snapshot_id", "D2_T15_TNSKHDATA_SECURITY_MAJOR"),
                    _row_hash(row),
                    ingested_at,
                )
                for row in rows
            ]
            self.conn.executemany(
                "INSERT INTO staging_stk_limit VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                payload,
            )
            return len(payload)
        raise D2T15MaterializationError(f"unsupported endpoint: {endpoint}")

    def write_ledger(self, entries: list[FetchLedgerEntry]) -> None:
        self.conn.executemany(
            "INSERT INTO staging_fetch_ledger VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    entry.task_id,
                    entry.endpoint,
                    entry.ts_code,
                    entry.start_date,
                    entry.end_date,
                    entry.param_variant,
                    entry.task_hash,
                    entry.status,
                    entry.attempt_count,
                    entry.row_count,
                    entry.accepted_row_count,
                    entry.error_category,
                    entry.error_message_redacted,
                    entry.started_at,
                    entry.completed_at,
                    entry.elapsed_seconds,
                )
                for entry in entries
            ],
        )


def fetch_task_with_provider(
    client: Any, task: SecurityMajorFetchTask
) -> tuple[list[dict[str, Any]], FetchLedgerEntry]:
    started = _utc_now()
    started_monotonic = time.monotonic()
    attempt_count = 0
    method = getattr(client, task.endpoint)
    variants = [
        {
            "variant": task.param_variant,
            "params": {
                "ts_code": task.ts_code,
                "start_date": task.start_date,
                "end_date": task.end_date,
            },
        }
    ]
    if task.endpoint == "stk_limit":
        variants.append(
            {
                "variant": "date_range_fallback",
                "params": {"start_date": task.start_date, "end_date": task.end_date},
            }
        )
    unsupported_seen = False
    last_error: Exception | None = None
    for variant in variants:
        attempt_count += 1
        try:
            rows = _frame_records(method(**variant["params"]))
            accepted = [
                row
                for row in rows
                if str(row.get("ts_code")) == task.ts_code
                and task.start_date
                <= _date_yyyymmdd(row.get("trade_date") or row.get("suspend_date"))
                <= task.end_date
            ]
            status = "succeeded" if accepted else "empty_resolved"
            if unsupported_seen and accepted:
                status = "succeeded_after_fallback"
            completed = _utc_now()
            return accepted, FetchLedgerEntry(
                task_id=task.task_id,
                endpoint=task.endpoint,
                ts_code=task.ts_code,
                start_date=task.start_date,
                end_date=task.end_date,
                param_variant=str(variant["variant"]),
                task_hash=task.task_hash,
                status=status,
                attempt_count=attempt_count,
                row_count=len(rows),
                accepted_row_count=len(accepted),
                error_category=None,
                error_message_redacted=None,
                started_at=started,
                completed_at=completed,
                elapsed_seconds=round(time.monotonic() - started_monotonic, 3),
            )
        except Exception as exc:
            last_error = exc
            if (
                _classify_error(exc) == "unsupported_param_variant"
                and len(variants) > attempt_count
            ):
                unsupported_seen = True
                continue
            break
    completed = _utc_now()
    category = _classify_error(last_error) if last_error else "provider_error"
    return [], FetchLedgerEntry(
        task_id=task.task_id,
        endpoint=task.endpoint,
        ts_code=task.ts_code,
        start_date=task.start_date,
        end_date=task.end_date,
        param_variant=task.param_variant,
        task_hash=task.task_hash,
        status=category,
        attempt_count=attempt_count,
        row_count=0,
        accepted_row_count=0,
        error_category=category,
        error_message_redacted=_redact_error(last_error) if last_error else None,
        started_at=started,
        completed_at=completed,
        elapsed_seconds=round(time.monotonic() - started_monotonic, 3),
    )


def compute_quality_gate(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    conn.execute("DELETE FROM d2_expected_security_dates")
    conn.execute("DELETE FROM d2_source_status")
    conn.execute("DELETE FROM d2_factor_evidence")
    conn.execute("DELETE FROM d2_coverage_gaps")
    conn.execute("DELETE FROM d2_quality_summary")
    conn.execute(
        """
        INSERT INTO d2_expected_security_dates
        SELECT DISTINCT u.ts_code, c.cal_date
        FROM staging_security_universe u
        JOIN staging_trade_calendar c ON c.is_open = '1'
        LEFT JOIN staging_stock_basic b ON b.ts_code = u.ts_code
        WHERE c.cal_date >= COALESCE(NULLIF(b.list_date, ''), '00000000')
          AND (
            COALESCE(NULLIF(b.delist_date, ''), '99999999') = '99999999'
            OR c.cal_date <= b.delist_date
          )
        """
    )
    conn.execute(
        """
        INSERT INTO d2_source_status
        SELECT e.ts_code,
               e.trade_date,
               CASE
                 WHEN d.ts_code IS NOT NULL THEN 'listed_open_resolved_daily'
                 WHEN s.suspend_type = 'S' THEN 'suspended'
                 ELSE 'listed_open_missing_daily'
               END AS trading_status,
               CASE
                 WHEN d.ts_code IS NOT NULL THEN 'resolved'
                 WHEN s.suspend_type = 'S' THEN 'not_applicable_or_expected_empty'
                 ELSE 'missing'
               END AS daily_status,
               CASE
                 WHEN s.suspend_type = 'S' THEN 'not_applicable_or_expected_empty'
                 WHEN d.ts_code IS NULL THEN 'daily_dependency_missing'
                 WHEN l.ts_code IS NULL THEN 'stk_limit_missing'
                 ELSE 'resolved'
               END AS price_limit_status
        FROM d2_expected_security_dates e
        LEFT JOIN staging_daily_raw d
          ON d.ts_code = e.ts_code AND d.trade_date = e.trade_date
        LEFT JOIN staging_suspend_d s
          ON s.ts_code = e.ts_code AND s.suspend_date = e.trade_date
        LEFT JOIN staging_stk_limit l
          ON l.ts_code = e.ts_code AND l.trade_date = e.trade_date
        """
    )
    conn.execute(
        """
        INSERT INTO d2_factor_evidence
        SELECT e.ts_code,
               e.trade_date,
               CASE
                 WHEN s.suspend_type = 'S' THEN 'not_applicable_or_carry_forward'
                 WHEN a.ts_code IS NULL THEN 'missing'
                 ELSE 'resolved'
               END AS adjustment_factor_status
        FROM d2_expected_security_dates e
        LEFT JOIN staging_suspend_d s
          ON s.ts_code = e.ts_code AND s.suspend_date = e.trade_date
        LEFT JOIN staging_adj_factor a
          ON a.ts_code = e.ts_code AND a.trade_date = e.trade_date
        """
    )
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
        "configured_security_count": """
            SELECT CASE
              WHEN (SELECT count(*) FROM staging_security_mapping_diagnostics) > 0
              THEN (SELECT count(*) FROM staging_security_mapping_diagnostics)
              ELSE (SELECT count(*) FROM staging_security_universe)
            END
        """,
        "mapped_security_count": """
            SELECT CASE
              WHEN (SELECT count(*) FROM staging_security_mapping_diagnostics) > 0
              THEN (
                SELECT count(*)
                FROM staging_security_mapping_diagnostics
                WHERE mapping_status = 'resolved'
              )
              ELSE (SELECT count(*) FROM staging_security_universe)
            END
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
        "candidate_universe_row_count": """
            SELECT count(*) FROM staging_security_universe
        """,
        "security_count": """
            SELECT count(DISTINCT ts_code) FROM staging_security_universe
        """,
        "trade_cal_open_date_count": """
            SELECT count(*) FROM staging_trade_calendar WHERE is_open = '1'
        """,
        "expected_listed_open_security_date_count": """
            SELECT count(*) FROM d2_expected_security_dates
        """,
        "daily_raw_row_count": "SELECT count(*) FROM staging_daily_raw",
        "daily_resolved_security_date_count": """
            SELECT count(*) FROM d2_source_status WHERE daily_status = 'resolved'
        """,
        "listed_open_missing_daily_count": """
            SELECT count(*)
            FROM d2_source_status
            WHERE trading_status = 'listed_open_missing_daily'
        """,
        "suspended_security_date_count": """
            SELECT count(*)
            FROM d2_source_status
            WHERE trading_status = 'suspended'
        """,
        "adj_factor_resolved_count": """
            SELECT count(*)
            FROM d2_factor_evidence
            WHERE adjustment_factor_status = 'resolved'
        """,
        "unresolved_adjustment_factor_count": """
            SELECT count(*)
            FROM d2_factor_evidence
            WHERE adjustment_factor_status = 'missing'
        """,
        "adj_factor_carry_forward_required_count": """
            SELECT count(*)
            FROM d2_factor_evidence
            WHERE adjustment_factor_status = 'not_applicable_or_carry_forward'
        """,
        "stk_limit_resolved_count": """
            SELECT count(*)
            FROM d2_source_status
            WHERE price_limit_status = 'resolved'
        """,
        "unresolved_price_limit_status_count": """
            SELECT count(*)
            FROM d2_source_status
            WHERE price_limit_status = 'stk_limit_missing'
        """,
        "price_limit_daily_dependency_missing_count": """
            SELECT count(*)
            FROM d2_source_status
            WHERE price_limit_status = 'daily_dependency_missing'
        """,
        "duplicate_daily_key_count": """
            SELECT count(*)
            FROM (
              SELECT ts_code, trade_date
              FROM staging_daily_raw
              GROUP BY 1, 2
              HAVING count(*) > 1
            )
        """,
        "duplicate_adj_factor_key_count": """
            SELECT count(*)
            FROM (
              SELECT ts_code, trade_date
              FROM staging_adj_factor
              GROUP BY 1, 2
              HAVING count(*) > 1
            )
        """,
        "duplicate_stk_limit_key_count": """
            SELECT count(*)
            FROM (
              SELECT ts_code, trade_date
              FROM staging_stk_limit
              GROUP BY 1, 2
              HAVING count(*) > 1
            )
        """,
        "duplicate_suspend_key_count": """
            SELECT count(*)
            FROM (
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
    }
    quality = {
        key: int(conn.execute(sql).fetchone()[0] or 0)
        for key, sql in metric_sql.items()
    }
    for key, value in quality.items():
        conn.execute("INSERT INTO d2_quality_summary VALUES (?, ?)", [key, str(value)])
    return quality


def d2_acceptance_decision(quality: dict[str, Any]) -> str:
    provider_blockers = [
        "listed_open_missing_daily_count",
        "unresolved_adjustment_factor_count",
        "unresolved_price_limit_status_count",
        "unmapped_security_count",
        "provider_error_count",
        "rate_limit_count",
        "timeout_count",
    ]
    quality_blockers = [
        "duplicate_daily_key_count",
        "duplicate_adj_factor_key_count",
        "duplicate_stk_limit_key_count",
        "duplicate_suspend_key_count",
        "null_ohlc_count",
        "non_positive_price_count",
        "high_low_violation_count",
    ]
    if any(quality.get(key, 0) for key in provider_blockers):
        return "blocked_pending_provider_coverage"
    if any(quality.get(key, 0) for key in quality_blockers):
        return "blocked_pending_quality_resolution"
    return "accepted_for_d3_candidate_generation"


def d2_acceptance_blocker_keys(quality: dict[str, Any]) -> list[str]:
    blocker_keys = [
        "listed_open_missing_daily_count",
        "unresolved_adjustment_factor_count",
        "unresolved_price_limit_status_count",
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
    ]
    return [key for key in blocker_keys if quality.get(key, 0)]


def build_acceptance_reports(
    quality: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    decision = d2_acceptance_decision(quality)
    d3_decision = (
        "d3_candidate_generation_allowed"
        if decision == "accepted_for_d3_candidate_generation"
        else "d3_candidate_generation_blocked"
    )
    acceptance = {
        "task_id": "D2-T15",
        "d2_acceptance_decision": decision,
        "quality_report_source": "d2_t15_tnskhdata_staging.duckdb",
        "formal_duckdb_write_authorized": False,
        "candidate_duckdb_staging_written": True,
        "data_version_published": False,
        "d3_rows_generated": False,
        "pcvt_values_generated": False,
        "r0_state_generated": False,
        "quality_blockers": d2_acceptance_blocker_keys(quality),
    }
    handoff = {
        "task_id": "D2-T15",
        "d3_handoff_decision": d3_decision,
        "d2_acceptance_decision": decision,
        "d3_generation_authorized": False,
        "d3_rows_generated": False,
        "data_version_published": False,
        "r0_state_generated": False,
    }
    return acceptance, handoff


def write_gap_reports(conn: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    for name, group_sql in {
        "d2_t15_coverage_gaps_by_ts_code.csv": "ts_code",
        "d2_t15_coverage_gaps_by_trade_date.csv": "trade_date",
        "d2_t15_coverage_gaps_by_month.csv": "substr(trade_date, 1, 6)",
    }.items():
        rows = conn.execute(
            f"""
            SELECT {group_sql} AS key, gap_type, count(*) AS gap_count
            FROM d2_coverage_gaps
            GROUP BY 1, 2
            ORDER BY 1, 2
            """
        ).fetchall()
        with (output_dir / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["key", "gap_type", "gap_count"])
            writer.writerows(rows)


def write_hash_summary(output_dir: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for path in sorted(output_dir.iterdir()):
        if path.name == "d2_t15_candidate_file_hash_summary.json":
            continue
        if path.is_file():
            summary[path.name] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
    _write_json(output_dir / "d2_t15_candidate_file_hash_summary.json", summary)
    return summary


def run_quality_reports(output_dir: Path, db_path: Path) -> dict[str, Any]:
    writer = DuckDBStagingWriter(db_path)
    try:
        quality = compute_quality_gate(writer.conn)
        acceptance, handoff = build_acceptance_reports(quality)
        _write_json(output_dir / "d2_t15_duckdb_quality_report.json", quality)
        _write_json(
            output_dir / "d2_t15_d2_acceptance_candidate_report.json", acceptance
        )
        _write_json(output_dir / "d2_t15_d3_handoff_candidate_report.json", handoff)
        write_gap_reports(writer.conn, output_dir)
        return {
            "quality": quality,
            "acceptance": acceptance,
            "handoff": handoff,
            "duckdb_written": True,
            "formal_duckdb_write_authorized": False,
            "d3_rows_generated": False,
            "r0_state_generated": False,
        }
    finally:
        writer.close()
        write_hash_summary(output_dir)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT, type=Path)
    parser.add_argument(
        "--security-universe", default=DEFAULT_SECURITY_UNIVERSE, type=Path
    )
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, type=Path)
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Future remote runner parameter; not used by current scaffold.",
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument(
        "--max-workers",
        default=4,
        type=int,
        help="Future remote runner parameter; current PR does not fetch remotely.",
    )
    parser.add_argument(
        "--chunk-policy",
        default="year",
        choices=("full-range", "year", "month"),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Future remote runner parameter; current scaffold only defines "
            "ledger semantics."
        ),
    )
    parser.add_argument("--dry-run-plan", action="store_true")
    parser.add_argument("--no-remote-fetch", action="store_true")
    parser.add_argument("--export-compatible-jsonl", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--sample-securities", type=int)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    ensure_allowed_output_dir(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    universe = load_security_universe(
        args.security_universe, limit=args.sample_securities
    )
    tasks = build_security_major_fetch_plan(
        universe.securities,
        start_date=args.start_date,
        end_date=args.end_date,
        chunk_policy=args.chunk_policy,
    )
    if args.dry_run_plan:
        _write_jsonl(
            args.output_dir / "d2_t15_fetch_plan.jsonl",
            [asdict(task) for task in tasks],
        )
        print(
            json.dumps(
                {
                    "task_count": len(tasks),
                    "remote_provider_called": False,
                    "configured_security_count": universe.metrics[
                        "configured_security_count"
                    ],
                    "mapped_security_count": universe.metrics["mapped_security_count"],
                    "unmapped_security_count": universe.metrics[
                        "unmapped_security_count"
                    ],
                    "future_remote_runner_parameters": [
                        "--env-file",
                        "--max-workers",
                        "--resume",
                    ],
                },
                sort_keys=True,
            )
        )
        return 0
    db_path = args.output_dir / "d2_t15_tnskhdata_staging.duckdb"
    if args.no_remote_fetch:
        result = run_quality_reports(args.output_dir, db_path)
        print(json.dumps(result["acceptance"], ensure_ascii=False, sort_keys=True))
        return 0
    raise D2T15MaterializationError(
        "remote security-major fetch is implemented for injected fake-client tests; "
        "CLI remote execution requires a separately reviewed provider runner"
    )


if __name__ == "__main__":
    raise SystemExit(main())
