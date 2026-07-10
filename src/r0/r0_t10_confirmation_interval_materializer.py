from __future__ import annotations

# ruff: noqa: E501
import concurrent.futures
import json
import multiprocessing
import re
import traceback
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.r0.confirmation_interval_engine import (
    CONFIRMATION_ENGINE_VERSION,
    CONFIRMATION_K_VALUES,
    STATE_FIELD_BY_NAME,
    STATE_REASON_FIELD_BY_NAME,
    STATE_VALIDITY_FIELD_BY_NAME,
)
from src.r0.daily_state_engine import Q_VALUES, WEAK_DELTA
from src.r0.formal_run_identity import FormalRunIdentityError, validate_full_git_sha
from src.r0.percentile_score_engine import PERCENTILE_WINDOWS
from src.r0.r0_t10_nested_state_materializer import NESTED_DAILY_TABLE_NAME
from src.r0.upstream_artifact_io import (
    duckdb_table_summary,
    hash_object,
    quote_ident,
    sha256_file,
    validate_manifest_shape,
    write_json_atomic,
)

MATERIALIZER_VERSION = "r0_t10_04_confirmation_interval_materializer.v1"
MANIFEST_SCHEMA_VERSION = "r0_t10_04_r0_t07_confirmation_interval_manifest.v1"
SUMMARY_SCHEMA_VERSION = "r0_t10_04_execution_summary.v1"

DEFAULT_MAX_WORKERS = 16
MAX_WORKERS_UPPER_BOUND = 16
DEFAULT_DUCKDB_THREADS = 1
DEFAULT_DUCKDB_MEMORY_LIMIT = "2GB"
DEFAULT_CHUNK_SIZE_SECURITIES = 1

DAILY_CONFIRMATION_DUCKDB_NAME = "r0_t07_daily_confirmation_results.duckdb"
CONFIRMED_INTERVAL_DUCKDB_NAME = "r0_t07_confirmed_interval_results.duckdb"
MANIFEST_NAME = "r0_t07_confirmation_interval_results_manifest.json"
SUMMARY_NAME = "r0_t07_execution_summary.json"

DAILY_CONFIRMATION_TABLE_NAME = "r0_t07_daily_confirmation_results"
CONFIRMED_INTERVAL_TABLE_NAME = "r0_t07_confirmed_interval_results"

STATE_VALUE_SQL = ", ".join(
    f"('{state_name}', {raw_field})"
    for state_name, raw_field in STATE_FIELD_BY_NAME.items()
)
K_VALUES_SQL = ", ".join(f"({k})" for k in CONFIRMATION_K_VALUES)
STATE_SPECIFIC_FIELDS = frozenset(STATE_VALIDITY_FIELD_BY_NAME.values()) | frozenset(
    STATE_REASON_FIELD_BY_NAME.values()
)


class R0T10ConfirmationIntervalMaterializationError(RuntimeError):
    pass


@dataclass(frozen=True)
class R0T06Evidence:
    path: Path
    nested_hash: str
    nested_row_count: int
    security_count: int
    date_min: str
    date_max: str
    allowed_to_start: bool


@dataclass(frozen=True)
class SourcePlan:
    evidence: R0T06Evidence
    nested_daily_state_duckdb: Path
    nested_hash: str
    nested_row_count: int
    security_count: int
    date_min: str | None
    date_max: str | None


def materialize_r0_t07_confirmation_intervals(
    *,
    r0_t06_evidence: str | Path,
    nested_daily_state_duckdb: str | Path,
    output_dir: str | Path,
    run_id: str,
    code_commit: str,
    max_workers: int = DEFAULT_MAX_WORKERS,
    duckdb_threads: int = DEFAULT_DUCKDB_THREADS,
    duckdb_memory_limit_per_worker: str = DEFAULT_DUCKDB_MEMORY_LIMIT,
    chunk_size_securities: int = DEFAULT_CHUNK_SIZE_SECURITIES,
    resume: bool = False,
) -> dict[str, Any]:
    try:
        full_code_commit = validate_full_git_sha(code_commit)
    except FormalRunIdentityError as exc:
        raise R0T10ConfirmationIntervalMaterializationError(
            "short_code_commit_forbidden"
        ) from exc
    _validate_worker_options(
        max_workers=max_workers,
        duckdb_threads=duckdb_threads,
        chunk_size_securities=chunk_size_securities,
    )
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    created_at = _utc_now()
    try:
        plan = _build_source_plan(
            Path(r0_t06_evidence), Path(nested_daily_state_duckdb)
        )
    except R0T10ConfirmationIntervalMaterializationError as exc:
        summary = _blocked_summary(
            output_dir=root,
            run_id=run_id,
            code_commit=full_code_commit,
            created_at=created_at,
            reason_codes=(str(exc),),
            max_workers=max_workers,
        )
        write_json_atomic(root / SUMMARY_NAME, summary)
        return summary

    chunk_summaries = _run_chunks(
        root=root,
        plan=plan,
        run_id=run_id,
        code_commit=full_code_commit,
        max_workers=max_workers,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit_per_worker=duckdb_memory_limit_per_worker,
        chunk_size_securities=chunk_size_securities,
        resume=resume,
    )
    planned_chunk_count = _planned_chunk_count(plan, chunk_size_securities)
    completed_chunks = [
        chunk
        for chunk in chunk_summaries
        if chunk["status"] in {"completed", "skipped"}
    ]
    failed_chunk_count = sum(
        1 for chunk in chunk_summaries if chunk["status"] == "failed"
    )
    if failed_chunk_count or len(completed_chunks) != planned_chunk_count:
        _remove_authoritative_outputs(root)
        summary = _failed_execution_summary(
            root=root,
            run_id=run_id,
            code_commit=full_code_commit,
            created_at=created_at,
            plan=plan,
            chunk_summaries=chunk_summaries,
            planned_chunk_count=planned_chunk_count,
            max_workers=max_workers,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit_per_worker=duckdb_memory_limit_per_worker,
            chunk_size_securities=chunk_size_securities,
        )
        write_json_atomic(root / SUMMARY_NAME, summary)
        return summary

    duckdb_hashes = _write_authoritative_duckdb_outputs(
        root,
        completed_chunks,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit=duckdb_memory_limit_per_worker,
    )
    duckdb_summaries = {
        "daily_confirmation": duckdb_table_summary(
            root / DAILY_CONFIRMATION_DUCKDB_NAME, DAILY_CONFIRMATION_TABLE_NAME
        ),
        "confirmed_interval": duckdb_table_summary(
            root / CONFIRMED_INTERVAL_DUCKDB_NAME, CONFIRMED_INTERVAL_TABLE_NAME
        ),
    }
    manifest = _manifest(
        root=root,
        plan=plan,
        run_id=run_id,
        code_commit=full_code_commit,
        created_at=created_at,
        max_workers=max_workers,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit_per_worker=duckdb_memory_limit_per_worker,
        chunk_size_securities=chunk_size_securities,
        chunks=completed_chunks,
        duckdb_hashes=duckdb_hashes,
        duckdb_summaries=duckdb_summaries,
    )
    validate_manifest_shape(
        manifest,
        required_fields=(
            "schema_version",
            "run_id",
            "code_commit",
            "input_nested_daily_state_duckdb_sha256",
            "daily_confirmation_row_count",
            "confirmed_interval_row_count",
            "shards",
            "output_hashes",
        ),
    )
    write_json_atomic(root / MANIFEST_NAME, manifest)
    summary = _completed_summary(
        root=root,
        run_id=run_id,
        code_commit=full_code_commit,
        created_at=created_at,
        plan=plan,
        chunk_summaries=chunk_summaries,
        manifest=manifest,
        max_workers=max_workers,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit_per_worker=duckdb_memory_limit_per_worker,
        chunk_size_securities=chunk_size_securities,
    )
    write_json_atomic(root / SUMMARY_NAME, summary)
    return summary


def _run_chunks(
    *,
    root: Path,
    plan: SourcePlan,
    run_id: str,
    code_commit: str,
    max_workers: int,
    duckdb_threads: int,
    duckdb_memory_limit_per_worker: str,
    chunk_size_securities: int,
    resume: bool,
) -> list[dict[str, Any]]:
    chunk_iter = _iter_security_chunks(plan, chunk_size_securities)
    results: list[dict[str, Any]] = []
    pending: set[concurrent.futures.Future[dict[str, Any]]] = set()
    mp_context = multiprocessing.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=max_workers, mp_context=mp_context
    ) as pool:
        while True:
            while len(pending) < max_workers:
                try:
                    securities = next(chunk_iter)
                except StopIteration:
                    break
                task = _chunk_task(
                    root=root,
                    plan=plan,
                    securities=securities,
                    run_id=run_id,
                    code_commit=code_commit,
                    duckdb_threads=duckdb_threads,
                    duckdb_memory_limit=duckdb_memory_limit_per_worker,
                )
                if resume and _should_skip_chunk(task):
                    done = _read_json_object(Path(task["done_marker_path"]))
                    done["status"] = "skipped"
                    results.append(_public_chunk_summary(done))
                    continue
                pending.add(pool.submit(_materialize_chunk_worker, task))
            if not pending:
                break
            done_futures, pending = concurrent.futures.wait(
                pending, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done_futures:
                results.append(_public_chunk_summary(future.result()))
    return sorted(results, key=lambda item: str(item["chunk_id"]))


def _materialize_chunk_worker(task: Mapping[str, Any]) -> dict[str, Any]:
    started_at = _utc_now()
    chunk_id = str(task["chunk_id"])
    daily_path = Path(str(task["daily_artifact_path"]))
    interval_path = Path(str(task["interval_artifact_path"]))
    done_marker_path = Path(str(task["done_marker_path"]))
    failed_marker_path = Path(str(task["failed_marker_path"]))
    log_path = Path(str(task["log_path"]))
    for path in (daily_path, interval_path, done_marker_path, log_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    for path in (daily_path, interval_path):
        path.with_name(path.name + ".partial").unlink(missing_ok=True)
    try:
        _write_chunk_parquet_outputs(task)
        daily_summary = _parquet_summary(daily_path, date_field="trading_date")
        interval_summary = _parquet_summary(
            interval_path, date_field="confirmation_date"
        )
        summary = {
            "schema_version": "r0_t10_04_chunk_done.v1",
            "chunk_id": chunk_id,
            "chunk_hash": task["chunk_hash"],
            "security_count": task["security_count"],
            "security_id_min": task["security_id_min"],
            "security_id_max": task["security_id_max"],
            "daily_confirmation": daily_summary,
            "confirmed_interval": interval_summary,
            "done_marker_path": str(done_marker_path),
            "started_at": started_at,
            "finished_at": _utc_now(),
            "status": "completed",
        }
        write_json_atomic(done_marker_path, summary)
        failed_marker_path.unlink(missing_ok=True)
        log_path.write_text("completed\n", encoding="utf-8")
        return summary
    except Exception as exc:  # noqa: BLE001
        failed = {
            "schema_version": "r0_t10_04_chunk_failed.v1",
            "chunk_id": chunk_id,
            "chunk_hash": task["chunk_hash"],
            "security_count": task["security_count"],
            "security_id_min": task["security_id_min"],
            "security_id_max": task["security_id_max"],
            "started_at": started_at,
            "failed_at": _utc_now(),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "status": "failed",
        }
        write_json_atomic(failed_marker_path, failed)
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        return failed


def _write_chunk_parquet_outputs(task: Mapping[str, Any]) -> None:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect()
    try:
        _configure_duckdb(
            conn,
            threads=int(task["duckdb_threads"]),
            memory_limit=str(task["duckdb_memory_limit"]),
        )
        conn.execute(
            f"ATTACH {_sql_string_literal(str(task['nested_daily_state_duckdb']))} "
            "AS nested_db (READ_ONLY)"
        )
        securities = [str(item) for item in task["securities"]]
        conn.execute("CREATE TEMP TABLE chunk_securities(security_id VARCHAR)")
        conn.executemany(
            "INSERT INTO chunk_securities VALUES (?)",
            [(security,) for security in securities],
        )
        nested_columns = _attached_nested_daily_columns(conn)
        conn.execute(
            _daily_confirmation_sql(
                has_state_specific_fields=STATE_SPECIFIC_FIELDS.issubset(nested_columns)
            )
        )
        conn.execute(_confirmed_interval_sql())
        for table_name, target in (
            ("daily_confirmation", task["daily_artifact_path"]),
            ("confirmed_interval", task["interval_artifact_path"]),
        ):
            target_path = Path(str(target))
            partial = target_path.with_name(target_path.name + ".partial")
            partial.unlink(missing_ok=True)
            conn.execute(
                f"""
                COPY (SELECT * FROM {quote_ident(table_name)} ORDER BY ALL)
                TO ? (FORMAT PARQUET, COMPRESSION ZSTD)
                """,
                [str(partial)],
            )
            partial.replace(target_path)
    finally:
        conn.close()


def _daily_confirmation_sql(*, has_state_specific_fields: bool = False) -> str:
    upstream_validity_sql = "validity_status"
    upstream_reason_sql = "reason_codes"
    if has_state_specific_fields:
        upstream_validity_sql = _state_specific_case_sql(
            STATE_VALIDITY_FIELD_BY_NAME,
            fallback_field="validity_status",
        )
        upstream_reason_sql = _state_specific_case_sql(
            STATE_REASON_FIELD_BY_NAME,
            fallback_field="reason_codes",
        )
    return f"""
    CREATE TEMP TABLE daily_confirmation AS
    WITH source_rows AS (
      SELECT n.*
      FROM nested_db.{quote_ident(NESTED_DAILY_TABLE_NAME)} n
      JOIN chunk_securities s USING (security_id)
    ), invariant_checked AS (
      SELECT
        *,
        NOT (
          (S_PCVT_raw = true AND S_PCT_raw IS DISTINCT FROM true)
          OR (S_PCT_raw = true AND S_PC_raw IS DISTINCT FROM true)
          OR (S_PC_raw = true AND S_P_raw IS DISTINCT FROM true)
        ) AS nested_invariant_ok
      FROM source_rows
    ), state_rows AS (
      SELECT
        security_id,
        trading_date,
        CAST(percentile_window_W AS INTEGER) AS percentile_window_W,
        CAST(q AS DOUBLE) AS q,
        CAST(weak_delta AS DOUBLE) AS weak_delta,
        CAST(state_name AS VARCHAR) AS state_name,
        CAST(raw_state AS BOOLEAN) AS raw_state,
        CAST(eligible_state AS BOOLEAN) AS eligible_state,
        CAST({upstream_validity_sql} AS VARCHAR) AS upstream_validity_status,
        {upstream_reason_sql} AS upstream_reason_codes,
        CAST(state_engine_version AS VARCHAR) AS state_engine_version,
        CAST(nested_invariant_ok AS BOOLEAN) AS nested_invariant_ok
      FROM invariant_checked,
      (VALUES {STATE_VALUE_SQL}) AS states(state_name, raw_state)
    ), normalized AS (
      SELECT
        *,
        CASE
          WHEN nested_invariant_ok = false THEN 'blocked'
          WHEN upstream_validity_status IN ('unknown', 'diagnostic_required', 'blocked')
          THEN upstream_validity_status
          WHEN raw_state IS NULL THEN 'unknown'
          ELSE 'valid'
        END AS computed_validity_status,
        CASE
          WHEN nested_invariant_ok = false THEN list_concat(
            ['nested_raw_state_invariant_violation'],
            COALESCE(upstream_reason_codes, [])
          )
          WHEN upstream_validity_status IN ('unknown', 'diagnostic_required', 'blocked')
          THEN COALESCE(upstream_reason_codes, ['upstream_non_ready'])
          WHEN raw_state IS NULL THEN ['raw_state_unknown']
          ELSE ['valid_no_blocker']
        END AS computed_reason_codes
      FROM state_rows
    ), segmented AS (
      SELECT
        *,
        SUM(CASE WHEN raw_state = true AND computed_validity_status = 'valid' THEN 0 ELSE 1 END)
          OVER (
            PARTITION BY security_id, percentile_window_W, q, weak_delta, state_name
            ORDER BY trading_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          ) AS raw_segment_id
      FROM normalized
    ), streaked AS (
      SELECT
        *,
        CASE
          WHEN raw_state = true AND computed_validity_status = 'valid'
          THEN SUM(
            CASE
              WHEN raw_state = true AND computed_validity_status = 'valid' THEN 1
              ELSE 0
            END
          ) OVER (
            PARTITION BY security_id, percentile_window_W, q, weak_delta, state_name, raw_segment_id
            ORDER BY trading_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
          WHEN raw_state = false AND computed_validity_status = 'valid' THEN 0
          ELSE NULL
        END AS raw_streak,
        CASE
          WHEN raw_state = true AND computed_validity_status = 'valid'
          THEN MIN(
            CASE
              WHEN raw_state = true AND computed_validity_status = 'valid' THEN trading_date
              ELSE NULL
            END
          ) OVER (
            PARTITION BY security_id, percentile_window_W, q, weak_delta, state_name, raw_segment_id
          )
          ELSE NULL
        END AS raw_streak_start_date
      FROM segmented
    ), expanded AS (
      SELECT
        streaked.*,
        CAST(k.confirmation_k AS INTEGER) AS confirmation_k
      FROM streaked
      CROSS JOIN (VALUES {K_VALUES_SQL}) AS k(confirmation_k)
    ), confirmed AS (
      SELECT
        *,
        CASE
          WHEN raw_state = true AND computed_validity_status = 'valid'
          THEN CAST(raw_streak >= confirmation_k AS BOOLEAN)
          WHEN raw_state = false AND computed_validity_status = 'valid' THEN false
          ELSE NULL
        END AS confirmed_state,
        CASE
          WHEN raw_state = true
            AND computed_validity_status = 'valid'
            AND raw_streak >= confirmation_k
          THEN raw_streak_start_date
          ELSE NULL
        END AS confirmation_start_date,
        CASE
          WHEN raw_state = true
            AND computed_validity_status = 'valid'
            AND raw_streak >= confirmation_k
          THEN MAX(CASE WHEN raw_streak = confirmation_k THEN trading_date ELSE NULL END)
            OVER (
              PARTITION BY security_id, percentile_window_W, q, weak_delta, state_name, raw_segment_id, confirmation_k
              ORDER BY trading_date
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )
          ELSE NULL
        END AS confirmation_date
      FROM expanded
    )
    SELECT
      security_id,
      trading_date,
      percentile_window_W,
      q,
      weak_delta,
      state_name,
      confirmation_k,
      raw_state,
      CAST(raw_streak AS INTEGER) AS raw_streak,
      raw_streak_start_date,
      confirmed_state,
      confirmation_start_date,
      confirmation_date,
      computed_validity_status AS validity_status,
      computed_reason_codes AS reason_codes,
      '{CONFIRMATION_ENGINE_VERSION}' AS confirmation_engine_version
    FROM confirmed
    """


def _state_specific_case_sql(
    fields_by_state: Mapping[str, str], *, fallback_field: str
) -> str:
    clauses = " ".join(
        f"WHEN '{state_name}' THEN COALESCE({field_name}, {fallback_field})"
        for state_name, field_name in fields_by_state.items()
    )
    return f"CASE states.state_name {clauses} ELSE {fallback_field} END"


def _attached_nested_daily_columns(conn: Any) -> set[str]:
    rows = conn.execute(
        f"DESCRIBE SELECT * FROM nested_db.{quote_ident(NESTED_DAILY_TABLE_NAME)}"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _confirmed_interval_sql() -> str:
    return f"""
    CREATE TEMP TABLE confirmed_interval AS
    WITH base AS (
      SELECT
        *,
        SUM(CASE WHEN raw_state = true AND validity_status = 'valid' THEN 0 ELSE 1 END)
          OVER (
            PARTITION BY security_id, percentile_window_W, q, weak_delta, state_name, confirmation_k
            ORDER BY trading_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          ) AS raw_segment_id
      FROM daily_confirmation
    ), confirmed_segments AS (
      SELECT
        security_id,
        percentile_window_W,
        q,
        weak_delta,
        state_name,
        confirmation_k,
        raw_segment_id,
        MIN(trading_date) AS raw_start_date,
        MIN(CASE WHEN confirmed_state = true THEN confirmation_date ELSE NULL END) AS confirmation_date,
        MIN(CASE WHEN confirmed_state = true THEN confirmation_date ELSE NULL END) AS confirmed_start_date,
        MAX(trading_date) AS last_true_date,
        COUNT(*) AS raw_duration_observations,
        SUM(CASE WHEN confirmed_state = true THEN 1 ELSE 0 END) AS confirmed_duration_observations,
        ROW_NUMBER() OVER (
          PARTITION BY security_id, percentile_window_W, q, weak_delta, state_name, confirmation_k
          ORDER BY MIN(trading_date)
        ) AS interval_sequence
      FROM base
      WHERE raw_state = true AND validity_status = 'valid'
      GROUP BY
        security_id,
        percentile_window_W,
        q,
        weak_delta,
        state_name,
        confirmation_k,
        raw_segment_id
      HAVING SUM(CASE WHEN confirmed_state = true THEN 1 ELSE 0 END) > 0
    ), terminated AS (
      SELECT
        s.*,
        t.trading_date AS termination_observed_date,
        t.raw_state AS termination_raw_state,
        t.validity_status AS termination_validity_status
      FROM confirmed_segments s
      LEFT JOIN LATERAL (
        SELECT trading_date, raw_state, validity_status
        FROM base b
        WHERE b.security_id = s.security_id
          AND b.percentile_window_W = s.percentile_window_W
          AND abs(b.q - s.q) < 1e-12
          AND abs(b.weak_delta - s.weak_delta) < 1e-12
          AND b.state_name = s.state_name
          AND b.confirmation_k = s.confirmation_k
          AND b.trading_date > s.last_true_date
        ORDER BY b.trading_date
        LIMIT 1
      ) t ON true
    )
    SELECT
      security_id || '|W' || percentile_window_W::VARCHAR
        || '|q' || printf('%.2f', q)
        || '|d' || printf('%.2f', weak_delta)
        || '|K' || confirmation_k::VARCHAR
        || '|' || state_name
        || '|' || confirmation_date
        || '|' || printf('%04d', interval_sequence) AS interval_id,
      security_id,
      percentile_window_W,
      q,
      weak_delta,
      state_name,
      confirmation_k,
      raw_start_date,
      confirmation_date,
      confirmed_start_date,
      CASE WHEN termination_observed_date IS NULL THEN NULL ELSE last_true_date END AS interval_end_date,
      COALESCE(termination_observed_date, last_true_date) AS last_observed_date,
      CAST(raw_duration_observations AS INTEGER) AS raw_duration_observations,
      CAST(confirmed_duration_observations AS INTEGER) AS confirmed_duration_observations,
      CAST(termination_observed_date IS NULL AS BOOLEAN) AS is_open_interval,
      CASE
        WHEN termination_observed_date IS NULL THEN 'end_of_input_open'
        WHEN termination_raw_state = false AND termination_validity_status = 'valid' THEN 'raw_state_false'
        WHEN termination_validity_status = 'blocked' THEN 'raw_state_blocked'
        WHEN termination_validity_status = 'diagnostic_required' THEN 'raw_state_diagnostic_required'
        ELSE 'raw_state_unknown'
      END AS termination_reason,
      'valid' AS validity_status,
      ['valid_no_blocker'] AS reason_codes,
      '{CONFIRMATION_ENGINE_VERSION}' AS confirmation_engine_version
    FROM terminated
    """


def _write_authoritative_duckdb_outputs(
    root: Path,
    chunks: Sequence[Mapping[str, Any]],
    *,
    duckdb_threads: int,
    duckdb_memory_limit: str,
) -> dict[str, str]:
    outputs = {
        "daily_confirmation": (
            DAILY_CONFIRMATION_DUCKDB_NAME,
            DAILY_CONFIRMATION_TABLE_NAME,
            [chunk["daily_confirmation"]["path"] for chunk in chunks],
        ),
        "confirmed_interval": (
            CONFIRMED_INTERVAL_DUCKDB_NAME,
            CONFIRMED_INTERVAL_TABLE_NAME,
            [chunk["confirmed_interval"]["path"] for chunk in chunks],
        ),
    }
    hashes: dict[str, str] = {}
    for key, (filename, table_name, shard_paths) in outputs.items():
        path = root / str(filename)
        partial = path.with_name(path.name + ".partial")
        partial.unlink(missing_ok=True)
        import duckdb  # noqa: PLC0415

        conn = duckdb.connect(str(partial))
        try:
            _configure_duckdb(
                conn, threads=duckdb_threads, memory_limit=duckdb_memory_limit
            )
            conn.execute(
                f"""
                CREATE TABLE {quote_ident(str(table_name))} AS
                SELECT *
                FROM read_parquet(?)
                """,
                [list(shard_paths)],
            )
        finally:
            conn.close()
        partial.replace(path)
        hashes[key] = sha256_file(path)
    return hashes


def _build_source_plan(
    evidence_path: Path, nested_daily_state_duckdb: Path
) -> SourcePlan:
    evidence = _parse_r0_t06_evidence(evidence_path)
    if not evidence.allowed_to_start:
        raise R0T10ConfirmationIntervalMaterializationError(
            "r0_t06_evidence_gate_not_open"
        )
    if not nested_daily_state_duckdb.is_file():
        raise R0T10ConfirmationIntervalMaterializationError(
            "r0_t06_nested_daily_duckdb_missing"
        )
    actual_hash = sha256_file(nested_daily_state_duckdb)
    if actual_hash != evidence.nested_hash:
        raise R0T10ConfirmationIntervalMaterializationError(
            "r0_t06_nested_daily_duckdb_hash_mismatch"
        )
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(nested_daily_state_duckdb), read_only=True)
    try:
        row_count, security_count, date_min, date_max = conn.execute(
            f"""
            SELECT count(*), count(DISTINCT security_id), min(trading_date), max(trading_date)
            FROM {quote_ident(NESTED_DAILY_TABLE_NAME)}
            """
        ).fetchone()
    finally:
        conn.close()
    if int(row_count) != evidence.nested_row_count:
        raise R0T10ConfirmationIntervalMaterializationError(
            "r0_t06_nested_daily_row_count_mismatch"
        )
    if int(security_count) != evidence.security_count:
        raise R0T10ConfirmationIntervalMaterializationError(
            "r0_t06_security_count_mismatch"
        )
    return SourcePlan(
        evidence=evidence,
        nested_daily_state_duckdb=nested_daily_state_duckdb,
        nested_hash=actual_hash,
        nested_row_count=int(row_count),
        security_count=int(security_count),
        date_min=None if date_min is None else str(date_min),
        date_max=None if date_max is None else str(date_max),
    )


def _parse_r0_t06_evidence(path: Path) -> R0T06Evidence:
    if not path.is_file():
        raise R0T10ConfirmationIntervalMaterializationError("r0_t06_evidence_missing")
    text = path.read_text(encoding="utf-8")
    return R0T06Evidence(
        path=path,
        nested_hash=_evidence_value(text, "nested_daily_state_duckdb_sha256"),
        nested_row_count=int(
            _evidence_value(text, "nested_daily_state_row_count").replace(",", "")
        ),
        security_count=int(_evidence_value(text, "security_count").replace(",", "")),
        date_min=_evidence_value(text, "date_min"),
        date_max=_evidence_value(text, "date_max"),
        allowed_to_start=_evidence_value(text, "R0-T07_allowed_to_start") == "true",
    )


def _evidence_value(text: str, key: str) -> str:
    match = re.search(rf"`{re.escape(key)}`:\s*`?([^`\n]+)`?", text)
    if not match:
        raise R0T10ConfirmationIntervalMaterializationError(
            f"r0_t06_evidence_missing_{key}"
        )
    return match.group(1).strip()


def _iter_security_chunks(
    plan: SourcePlan, chunk_size_securities: int
) -> Iterable[tuple[str, ...]]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(plan.nested_daily_state_duckdb), read_only=True)
    try:
        cursor = conn.execute(
            f"SELECT DISTINCT security_id FROM {quote_ident(NESTED_DAILY_TABLE_NAME)} ORDER BY 1"
        )
        while True:
            batch = cursor.fetchmany(chunk_size_securities)
            if not batch:
                break
            yield tuple(str(row[0]) for row in batch)
    finally:
        conn.close()


def _chunk_task(
    *,
    root: Path,
    plan: SourcePlan,
    securities: Sequence[str],
    run_id: str,
    code_commit: str,
    duckdb_threads: int,
    duckdb_memory_limit: str,
) -> dict[str, Any]:
    chunk_hash = hash_object(
        {
            "nested_hash": plan.nested_hash,
            "securities": list(securities),
            "confirmation_k_values": list(CONFIRMATION_K_VALUES),
            "confirmation_engine_version": CONFIRMATION_ENGINE_VERSION,
        }
    )
    chunk_id = chunk_hash[:16]
    return {
        "run_id": run_id,
        "code_commit": code_commit,
        "nested_daily_state_duckdb": str(plan.nested_daily_state_duckdb),
        "securities": tuple(securities),
        "security_count": len(securities),
        "security_id_min": min(securities),
        "security_id_max": max(securities),
        "chunk_id": chunk_id,
        "chunk_hash": chunk_hash,
        "daily_artifact_path": str(
            root / "shards" / "daily_confirmation" / f"{chunk_id}.parquet"
        ),
        "interval_artifact_path": str(
            root / "shards" / "confirmed_interval" / f"{chunk_id}.parquet"
        ),
        "done_marker_path": str(root / "status" / f"{chunk_id}.DONE.json"),
        "failed_marker_path": str(root / "status" / f"{chunk_id}.FAILED.json"),
        "log_path": str(root / "logs" / f"{chunk_id}.log"),
        "duckdb_threads": duckdb_threads,
        "duckdb_memory_limit": duckdb_memory_limit,
    }


def _should_skip_chunk(task: Mapping[str, Any]) -> bool:
    done_marker_path = Path(str(task["done_marker_path"]))
    failed_marker_path = Path(str(task["failed_marker_path"]))
    artifact_paths = [
        Path(str(task["daily_artifact_path"])),
        Path(str(task["interval_artifact_path"])),
    ]
    if failed_marker_path.exists():
        return False
    if any(path.with_name(path.name + ".partial").exists() for path in artifact_paths):
        return False
    if not done_marker_path.exists() or any(
        not path.exists() for path in artifact_paths
    ):
        return False
    try:
        done = _read_json_object(done_marker_path)
    except (OSError, json.JSONDecodeError):
        return False
    if done.get("schema_version") != "r0_t10_04_chunk_done.v1":
        return False
    if done.get("chunk_hash") != task.get("chunk_hash"):
        return False
    sections = (
        ("daily_confirmation", artifact_paths[0]),
        ("confirmed_interval", artifact_paths[1]),
    )
    return all(
        isinstance(done.get(section), Mapping)
        and done[section].get("file_sha256") == sha256_file(path)
        for section, path in sections
    )


def _manifest(
    *,
    root: Path,
    plan: SourcePlan,
    run_id: str,
    code_commit: str,
    created_at: str,
    max_workers: int,
    duckdb_threads: int,
    duckdb_memory_limit_per_worker: str,
    chunk_size_securities: int,
    chunks: Sequence[Mapping[str, Any]],
    duckdb_hashes: Mapping[str, str],
    duckdb_summaries: Mapping[str, Any],
) -> dict[str, Any]:
    daily_rows = sum(int(chunk["daily_confirmation"]["row_count"]) for chunk in chunks)
    interval_rows = sum(
        int(chunk["confirmed_interval"]["row_count"]) for chunk in chunks
    )
    dates = [
        str(value)
        for chunk in chunks
        for value in (
            chunk["daily_confirmation"].get("date_min"),
            chunk["daily_confirmation"].get("date_max"),
        )
        if value is not None
    ]
    content_hashes = {
        str(chunk["chunk_id"]): {
            "daily_confirmation": chunk["daily_confirmation"]["file_sha256"],
            "confirmed_interval": chunk["confirmed_interval"]["file_sha256"],
        }
        for chunk in chunks
    }
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "task_id": "R0-T10-04",
        "run_id": run_id,
        "created_at": created_at,
        "code_commit": code_commit,
        "confirmation_engine_version": CONFIRMATION_ENGINE_VERSION,
        "materializer_version": MATERIALIZER_VERSION,
        "input_r0_t06_evidence_path": str(plan.evidence.path),
        "input_nested_daily_state_duckdb_path": str(plan.nested_daily_state_duckdb),
        "input_nested_daily_state_duckdb_sha256": plan.nested_hash,
        "input_nested_daily_state_row_count": plan.nested_row_count,
        "input_security_count": plan.evidence.security_count,
        "input_date_min": plan.evidence.date_min,
        "input_date_max": plan.evidence.date_max,
        "daily_confirmation_row_count": daily_rows,
        "confirmed_interval_row_count": interval_rows,
        "security_count": plan.security_count,
        "date_min": min(dates) if dates else plan.date_min,
        "date_max": max(dates) if dates else plan.date_max,
        "W_coverage": list(PERCENTILE_WINDOWS),
        "q_coverage": list(Q_VALUES),
        "weak_delta": WEAK_DELTA,
        "K_coverage": list(CONFIRMATION_K_VALUES),
        "state_name_coverage": list(STATE_FIELD_BY_NAME),
        "R0-T10-05_allowed_to_start": True,
        "downstream_gate_allowed": True,
        "output_paths": {
            "daily_confirmation": str(root / DAILY_CONFIRMATION_DUCKDB_NAME),
            "confirmed_interval": str(root / CONFIRMED_INTERVAL_DUCKDB_NAME),
        },
        "output_hashes": dict(duckdb_hashes),
        "duckdb_summaries": dict(duckdb_summaries),
        "global_content_hash": hash_object(content_hashes),
        "concurrency_policy": {
            "scope": "R0-T10 formal upstream confirmation interval materialization only",
            "max_workers": max_workers,
            "allowed_max_workers": [1, MAX_WORKERS_UPPER_BOUND],
            "duckdb_threads_per_worker": duckdb_threads,
            "duckdb_memory_limit_per_worker": duckdb_memory_limit_per_worker,
            "chunk_size_securities": chunk_size_securities,
            "process_pool_context": "spawn",
        },
        "memory_boundary": {
            "parent_holds_upstream_rows": False,
            "worker_returns_rows": False,
            "parent_summary_only": True,
            "duckdb_written_by_native_bulk_read": True,
            "shards_format": "parquet",
        },
        "shards": [_manifest_shard(chunk) for chunk in chunks],
    }


def _completed_summary(
    *,
    root: Path,
    run_id: str,
    code_commit: str,
    created_at: str,
    plan: SourcePlan,
    chunk_summaries: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    max_workers: int,
    duckdb_threads: int,
    duckdb_memory_limit_per_worker: str,
    chunk_size_securities: int,
) -> dict[str, Any]:
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "task_id": "R0-T10-04",
        "status": "completed",
        "run_id": run_id,
        "created_at": created_at,
        "finished_at": _utc_now(),
        "code_commit": code_commit,
        "output_dir": str(root),
        "manifest_path": str(root / MANIFEST_NAME),
        "daily_confirmation_duckdb_path": str(root / DAILY_CONFIRMATION_DUCKDB_NAME),
        "confirmed_interval_duckdb_path": str(root / CONFIRMED_INTERVAL_DUCKDB_NAME),
        "daily_confirmation_row_count": manifest["daily_confirmation_row_count"],
        "confirmed_interval_row_count": manifest["confirmed_interval_row_count"],
        "security_count": plan.security_count,
        "date_min": manifest["date_min"],
        "date_max": manifest["date_max"],
        "chunk_count": len(chunk_summaries),
        "completed_chunk_count": sum(
            1 for chunk in chunk_summaries if chunk["status"] == "completed"
        ),
        "skipped_chunk_count": sum(
            1 for chunk in chunk_summaries if chunk["status"] == "skipped"
        ),
        "failed_chunk_count": sum(
            1 for chunk in chunk_summaries if chunk["status"] == "failed"
        ),
        "downstream_gate_allowed": True,
        "R0-T10-05_allowed_to_start": True,
        "max_workers": max_workers,
        "duckdb_threads": duckdb_threads,
        "duckdb_memory_limit_per_worker": duckdb_memory_limit_per_worker,
        "chunk_size_securities": chunk_size_securities,
        "process_pool_context": "spawn",
        "chunks": [_public_chunk_summary(chunk) for chunk in chunk_summaries],
    }


def _failed_execution_summary(
    *,
    root: Path,
    run_id: str,
    code_commit: str,
    created_at: str,
    plan: SourcePlan,
    chunk_summaries: Sequence[Mapping[str, Any]],
    planned_chunk_count: int,
    max_workers: int,
    duckdb_threads: int,
    duckdb_memory_limit_per_worker: str,
    chunk_size_securities: int,
) -> dict[str, Any]:
    completed_chunk_count = sum(
        1 for chunk in chunk_summaries if chunk["status"] == "completed"
    )
    skipped_chunk_count = sum(
        1 for chunk in chunk_summaries if chunk["status"] == "skipped"
    )
    failed_chunk_count = sum(
        1 for chunk in chunk_summaries if chunk["status"] == "failed"
    )
    completed_or_skipped_count = completed_chunk_count + skipped_chunk_count
    reasons = []
    if failed_chunk_count:
        reasons.append("failed_chunk_present")
    if completed_or_skipped_count != planned_chunk_count:
        reasons.append("completed_or_skipped_chunk_count_mismatch")
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "task_id": "R0-T10-04",
        "status": "failed",
        "run_id": run_id,
        "created_at": created_at,
        "finished_at": _utc_now(),
        "code_commit": code_commit,
        "output_dir": str(root),
        "manifest_path": None,
        "duckdb_written": False,
        "manifest_written": False,
        "downstream_gate_allowed": False,
        "R0-T10-05_allowed_to_start": False,
        "reason_codes": reasons,
        "security_count": plan.security_count,
        "chunk_count": len(chunk_summaries),
        "planned_chunk_count": planned_chunk_count,
        "completed_chunk_count": completed_chunk_count,
        "skipped_chunk_count": skipped_chunk_count,
        "failed_chunk_count": failed_chunk_count,
        "pending_chunk_count": max(
            planned_chunk_count - completed_or_skipped_count - failed_chunk_count, 0
        ),
        "max_workers": max_workers,
        "duckdb_threads": duckdb_threads,
        "duckdb_memory_limit_per_worker": duckdb_memory_limit_per_worker,
        "chunk_size_securities": chunk_size_securities,
        "process_pool_context": "spawn",
        "chunks": [_public_chunk_summary(chunk) for chunk in chunk_summaries],
    }


def _blocked_summary(
    *,
    output_dir: Path,
    run_id: str,
    code_commit: str,
    created_at: str,
    reason_codes: Sequence[str],
    max_workers: int,
) -> dict[str, Any]:
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "task_id": "R0-T10-04",
        "status": "blocked",
        "run_id": run_id,
        "created_at": created_at,
        "finished_at": _utc_now(),
        "code_commit": code_commit,
        "output_dir": str(output_dir),
        "reason_codes": list(reason_codes),
        "max_workers": max_workers,
        "duckdb_written": False,
        "manifest_written": False,
        "downstream_gate_allowed": False,
        "R0-T10-05_allowed_to_start": False,
    }


def _manifest_shard(chunk: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": chunk["chunk_id"],
        "chunk_hash": chunk["chunk_hash"],
        "status": chunk["status"],
        "security_count": chunk["security_count"],
        "security_id_min": chunk["security_id_min"],
        "security_id_max": chunk["security_id_max"],
        "done_marker_path": chunk["done_marker_path"],
        "daily_confirmation": dict(chunk["daily_confirmation"]),
        "confirmed_interval": dict(chunk["confirmed_interval"]),
    }


def _public_chunk_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "schema_version",
        "chunk_id",
        "chunk_hash",
        "security_count",
        "security_id_min",
        "security_id_max",
        "daily_confirmation",
        "confirmed_interval",
        "done_marker_path",
        "started_at",
        "finished_at",
        "status",
        "error_type",
        "error_message",
    )
    return {key: summary[key] for key in allowed if key in summary}


def _parquet_summary(path: Path, *, date_field: str) -> dict[str, Any]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect()
    try:
        row_count, date_min, date_max = conn.execute(
            f"""
            SELECT count(*), min({quote_ident(date_field)}), max({quote_ident(date_field)})
            FROM read_parquet(?)
            """,
            [str(path)],
        ).fetchone()
        schema = conn.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
        ).fetchall()
    finally:
        conn.close()
    return {
        "path": str(path),
        "row_count": int(row_count),
        "file_sha256": sha256_file(path),
        "field_names": [str(row[0]) for row in schema],
        "date_min": None if date_min is None else str(date_min),
        "date_max": None if date_max is None else str(date_max),
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise R0T10ConfirmationIntervalMaterializationError(
            f"expected JSON object: {path}"
        )
    return payload


def _planned_chunk_count(plan: SourcePlan, chunk_size_securities: int) -> int:
    return (plan.security_count + chunk_size_securities - 1) // chunk_size_securities


def _remove_authoritative_outputs(root: Path) -> None:
    for name in (DAILY_CONFIRMATION_DUCKDB_NAME, CONFIRMED_INTERVAL_DUCKDB_NAME):
        path = root / name
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".partial").unlink(missing_ok=True)
    (root / MANIFEST_NAME).unlink(missing_ok=True)


def _validate_worker_options(
    *, max_workers: int, duckdb_threads: int, chunk_size_securities: int
) -> None:
    if max_workers < 1 or max_workers > MAX_WORKERS_UPPER_BOUND:
        raise R0T10ConfirmationIntervalMaterializationError(
            "max_workers must be between 1 and 16"
        )
    if duckdb_threads < 1:
        raise R0T10ConfirmationIntervalMaterializationError(
            "duckdb_threads must be >= 1"
        )
    if chunk_size_securities < 1:
        raise R0T10ConfirmationIntervalMaterializationError(
            "chunk_size_securities must be >= 1"
        )


def _configure_duckdb(conn: Any, *, threads: int, memory_limit: str) -> None:
    conn.execute(f"SET threads = {int(threads)}")
    conn.execute("SET memory_limit = ?", [memory_limit])


def _sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _utc_now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()
