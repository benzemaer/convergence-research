from __future__ import annotations

import concurrent.futures
import json
import traceback
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.r0.raw_metric_engine import METRIC_ENGINE_VERSION, compute_raw_metrics
from src.r0.upstream_artifact_io import (
    duckdb_table_summary,
    hash_object,
    quote_ident,
    sha256_file,
    validate_manifest_shape,
    write_json_atomic,
    write_jsonl_gz_atomic,
)

MATERIALIZER_VERSION = "r0_t10_01_raw_metric_materializer.v1"
MANIFEST_SCHEMA_VERSION = "r0_t10_01_r0_t04_raw_metric_manifest.v1"
SUMMARY_SCHEMA_VERSION = "r0_t10_01_execution_summary.v1"
DEFAULT_SOURCE_TABLE = "d3_candidate_daily_observation"
DEFAULT_MAX_WORKERS = 6
MAX_WORKERS_UPPER_BOUND = 8
DEFAULT_DUCKDB_THREADS = 1
DEFAULT_DUCKDB_MEMORY_LIMIT = "2GB"
DEFAULT_CHUNK_SIZE_SECURITIES = 1
OUTPUT_DUCKDB_NAME = "r0_t04_raw_metric_results.duckdb"
OUTPUT_MANIFEST_NAME = "r0_t04_raw_metric_results_manifest.json"
OUTPUT_SUMMARY_NAME = "r0_t04_execution_summary.json"
OUTPUT_TABLE_NAME = "r0_t04_raw_metric_results"


class R0T10MaterializationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourcePlan:
    d3_duckdb: Path
    source_table: str
    security_column: str
    date_column: str
    source_columns: tuple[str, ...]
    input_artifact_hash: str
    source_row_count: int
    source_security_count: int
    date_min: str | None
    date_max: str | None


def materialize_r0_t04_raw_metrics(
    *,
    d3_duckdb: str | Path,
    output_dir: str | Path,
    run_id: str,
    code_commit: str,
    source_table: str = DEFAULT_SOURCE_TABLE,
    max_workers: int = DEFAULT_MAX_WORKERS,
    duckdb_threads: int = DEFAULT_DUCKDB_THREADS,
    duckdb_memory_limit_per_worker: str = DEFAULT_DUCKDB_MEMORY_LIMIT,
    chunk_size_securities: int = DEFAULT_CHUNK_SIZE_SECURITIES,
    resume: bool = False,
) -> dict[str, Any]:
    _validate_worker_options(
        max_workers=max_workers,
        duckdb_threads=duckdb_threads,
        chunk_size_securities=chunk_size_securities,
    )
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    created_at = _utc_now()

    try:
        plan = _build_source_plan(Path(d3_duckdb), source_table)
    except R0T10MaterializationError as exc:
        summary = _blocked_summary(
            output_dir=root,
            run_id=run_id,
            code_commit=code_commit,
            created_at=created_at,
            reason_codes=(str(exc),),
            max_workers=max_workers,
        )
        write_json_atomic(root / OUTPUT_SUMMARY_NAME, summary)
        return summary

    chunk_summaries = _run_chunks(
        root=root,
        plan=plan,
        run_id=run_id,
        code_commit=code_commit,
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
            code_commit=code_commit,
            created_at=created_at,
            plan=plan,
            chunk_summaries=chunk_summaries,
            planned_chunk_count=planned_chunk_count,
            max_workers=max_workers,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit_per_worker=duckdb_memory_limit_per_worker,
            chunk_size_securities=chunk_size_securities,
        )
        write_json_atomic(root / OUTPUT_SUMMARY_NAME, summary)
        return summary

    status = "completed"
    duckdb_path = root / OUTPUT_DUCKDB_NAME
    _write_authoritative_duckdb(
        duckdb_path,
        completed_chunks,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit=duckdb_memory_limit_per_worker,
    )
    output_duckdb_hash = sha256_file(duckdb_path)
    duckdb_summary = duckdb_table_summary(duckdb_path, OUTPUT_TABLE_NAME)
    row_count = sum(int(chunk["row_count"]) for chunk in completed_chunks)
    manifest = _manifest(
        root=root,
        plan=plan,
        run_id=run_id,
        code_commit=code_commit,
        created_at=created_at,
        max_workers=max_workers,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit_per_worker=duckdb_memory_limit_per_worker,
        chunk_size_securities=chunk_size_securities,
        chunks=completed_chunks,
        duckdb_hash=output_duckdb_hash,
        duckdb_summary=duckdb_summary,
    )
    validate_manifest_shape(
        manifest,
        required_fields=(
            "schema_version",
            "run_id",
            "row_count",
            "security_count",
            "input_artifact_hash",
            "output_artifact_hash",
            "shards",
            "global_content_hash",
        ),
    )
    write_json_atomic(root / OUTPUT_MANIFEST_NAME, manifest)
    summary = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "task_id": "R0-T10-01",
        "status": status,
        "run_id": run_id,
        "created_at": created_at,
        "finished_at": _utc_now(),
        "code_commit": code_commit,
        "output_dir": str(root),
        "manifest_path": str(root / OUTPUT_MANIFEST_NAME),
        "duckdb_path": str(duckdb_path),
        "row_count": row_count,
        "security_count": plan.source_security_count,
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
        "max_workers": max_workers,
        "duckdb_threads": duckdb_threads,
        "duckdb_memory_limit_per_worker": duckdb_memory_limit_per_worker,
        "chunk_size_securities": chunk_size_securities,
        "memory_boundary": {
            "parent_receives_rows": False,
            "worker_returns_row_payload": False,
            "parent_summary_fields": [
                "chunk_id",
                "status",
                "row_count",
                "content_sha256",
                "file_sha256",
                "artifact_path",
                "done_marker_path",
            ],
        },
        "chunks": [_public_chunk_summary(chunk) for chunk in chunk_summaries],
    }
    write_json_atomic(root / OUTPUT_SUMMARY_NAME, summary)
    return summary


def _planned_chunk_count(plan: SourcePlan, chunk_size_securities: int) -> int:
    return (
        plan.source_security_count + chunk_size_securities - 1
    ) // chunk_size_securities


def _remove_authoritative_outputs(root: Path) -> None:
    for path in (
        root / OUTPUT_DUCKDB_NAME,
        root / f"{OUTPUT_DUCKDB_NAME}.partial",
        root / OUTPUT_MANIFEST_NAME,
    ):
        path.unlink(missing_ok=True)


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
    reason_codes = []
    if failed_chunk_count:
        reason_codes.append("failed_chunk_present")
    if completed_or_skipped_count != planned_chunk_count:
        reason_codes.append("completed_or_skipped_chunk_count_mismatch")
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "task_id": "R0-T10-01",
        "status": "failed",
        "run_id": run_id,
        "created_at": created_at,
        "finished_at": _utc_now(),
        "code_commit": code_commit,
        "output_dir": str(root),
        "manifest_path": None,
        "duckdb_path": None,
        "manifest_written": False,
        "duckdb_written": False,
        "downstream_gate_allowed": False,
        "reason_codes": reason_codes,
        "row_count": sum(
            int(chunk.get("row_count", 0))
            for chunk in chunk_summaries
            if chunk["status"] in {"completed", "skipped"}
        ),
        "security_count": plan.source_security_count,
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
        "memory_boundary": {
            "parent_receives_rows": False,
            "worker_returns_row_payload": False,
            "parent_summary_fields": [
                "chunk_id",
                "status",
                "row_count",
                "content_sha256",
                "file_sha256",
                "artifact_path",
                "done_marker_path",
            ],
        },
        "chunks": [_public_chunk_summary(chunk) for chunk in chunk_summaries],
    }


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
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as pool:
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
                    resume=resume,
                )
                if resume and _should_skip_chunk(task):
                    done = _read_done_marker(Path(task["done_marker_path"]))
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
    artifact_path = Path(str(task["artifact_path"]))
    done_marker_path = Path(str(task["done_marker_path"]))
    failed_marker_path = Path(str(task["failed_marker_path"]))
    log_path = Path(str(task["log_path"]))
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    done_marker_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = artifact_path.with_name(artifact_path.name + ".partial")
    partial_path.unlink(missing_ok=True)
    try:
        rows = _compute_chunk_rows(task)
        write_summary = write_jsonl_gz_atomic(artifact_path, rows)
        finished_at = _utc_now()
        summary = {
            "schema_version": "r0_t10_01_chunk_done.v1",
            "chunk_id": task["chunk_id"],
            "chunk_hash": task["chunk_hash"],
            "security_count": task["security_count"],
            "security_id_min": task["security_id_min"],
            "security_id_max": task["security_id_max"],
            "row_count": write_summary.row_count,
            "content_sha256": write_summary.content_sha256,
            "file_sha256": write_summary.file_sha256,
            "field_names": list(write_summary.field_names),
            "date_min": write_summary.date_min,
            "date_max": write_summary.date_max,
            "artifact_path": str(artifact_path),
            "done_marker_path": str(done_marker_path),
            "started_at": started_at,
            "finished_at": finished_at,
            "status": "completed",
        }
        write_json_atomic(done_marker_path, summary)
        failed_marker_path.unlink(missing_ok=True)
        log_path.write_text("completed\n", encoding="utf-8")
        return summary
    except Exception as exc:  # noqa: BLE001 - marker must capture worker failure.
        failed = {
            "schema_version": "r0_t10_01_chunk_failed.v1",
            "chunk_id": task["chunk_id"],
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


def _compute_chunk_rows(task: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(task["d3_duckdb"]), read_only=True)
    try:
        _configure_duckdb(
            conn,
            threads=int(task["duckdb_threads"]),
            memory_limit=str(task["duckdb_memory_limit"]),
        )
        for security_rows in _read_rows_for_securities(
            conn=conn,
            source_table=str(task["source_table"]),
            security_column=str(task["security_column"]),
            date_column=str(task["date_column"]),
            securities=tuple(str(item) for item in task["securities"]),
        ):
            for result in compute_raw_metrics(security_rows):
                yield result.as_dict()
    finally:
        conn.close()


def _read_rows_for_securities(
    *,
    conn: Any,
    source_table: str,
    security_column: str,
    date_column: str,
    securities: Sequence[str],
) -> Iterable[list[dict[str, Any]]]:
    placeholders = ",".join("?" for _ in securities)
    sql = (
        f"SELECT * FROM {quote_ident(source_table)} "
        f"WHERE {quote_ident(security_column)} IN ({placeholders}) "
        f"ORDER BY {quote_ident(security_column)}, {quote_ident(date_column)}"
    )
    cursor = conn.execute(sql, list(securities))
    columns = [str(desc[0]) for desc in cursor.description]
    current_security: str | None = None
    current_rows: list[dict[str, Any]] = []
    while True:
        batch = cursor.fetchmany(2048)
        if not batch:
            break
        for values in batch:
            raw = dict(zip(columns, values, strict=True))
            normalized = _normalise_observation_row(raw)
            security_id = str(normalized["security_id"])
            if current_security is not None and security_id != current_security:
                yield current_rows
                current_rows = []
            current_security = security_id
            current_rows.append(normalized)
    if current_rows:
        yield current_rows


def _write_authoritative_duckdb(
    path: Path,
    chunks: Sequence[Mapping[str, Any]],
    *,
    duckdb_threads: int,
    duckdb_memory_limit: str,
) -> None:
    import duckdb  # noqa: PLC0415

    partial = path.with_name(path.name + ".partial")
    partial.unlink(missing_ok=True)
    conn = duckdb.connect(str(partial))
    try:
        _configure_duckdb(
            conn, threads=duckdb_threads, memory_limit=duckdb_memory_limit
        )
        shard_paths = [str(chunk["artifact_path"]) for chunk in chunks]
        if shard_paths:
            conn.execute(
                f"""
                CREATE TABLE {quote_ident(OUTPUT_TABLE_NAME)} AS
                SELECT *
                FROM read_json_auto(?, format='newline_delimited')
                """,
                [shard_paths],
            )
        else:
            conn.execute(
                f"""
                CREATE TABLE {quote_ident(OUTPUT_TABLE_NAME)} (
                  security_id TEXT,
                  trading_date TEXT,
                  indicator_id TEXT,
                  raw_metric_name TEXT,
                  raw_value DOUBLE,
                  validity_status TEXT,
                  reason_codes TEXT[],
                  input_window_start TEXT,
                  input_window_end TEXT,
                  required_observation_count INTEGER,
                  actual_valid_observation_count INTEGER,
                  source_field_names TEXT[],
                  metric_engine_version TEXT
                )
                """
            )
    finally:
        conn.close()
    partial.replace(path)


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
    duckdb_hash: str,
    duckdb_summary: Mapping[str, Any],
) -> dict[str, Any]:
    row_count = sum(int(chunk["row_count"]) for chunk in chunks)
    content_hashes = {
        str(chunk["chunk_id"]): str(chunk["content_sha256"]) for chunk in chunks
    }
    fields = sorted(
        {field for chunk in chunks for field in chunk.get("field_names", ())}
    )
    dates = [
        str(value)
        for chunk in chunks
        for value in (chunk.get("date_min"), chunk.get("date_max"))
        if value is not None
    ]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "task_id": "R0-T10-01",
        "artifact_id": hash_object(
            {
                "run_id": run_id,
                "input_artifact_hash": plan.input_artifact_hash,
                "content_hashes": content_hashes,
            }
        ),
        "run_id": run_id,
        "created_at": created_at,
        "code_commit_or_data_build_id": code_commit,
        "engine_version": METRIC_ENGINE_VERSION,
        "materializer_version": MATERIALIZER_VERSION,
        "row_count": row_count,
        "security_count": plan.source_security_count,
        "date_min": min(dates) if dates else plan.date_min,
        "date_max": max(dates) if dates else plan.date_max,
        "source_lineage": {
            "source_task": "D3",
            "source_duckdb": str(plan.d3_duckdb),
            "source_table": plan.source_table,
            "source_row_count": plan.source_row_count,
            "source_security_count": plan.source_security_count,
        },
        "input_artifact_hash": plan.input_artifact_hash,
        "output_artifact_path": str(root / OUTPUT_DUCKDB_NAME),
        "output_artifact_hash": duckdb_hash,
        "global_content_hash": hash_object(content_hashes),
        "field_names": fields,
        "duckdb_summary": dict(duckdb_summary),
        "concurrency_policy": {
            "scope": "R0-T10 formal upstream materialization only",
            "max_workers": max_workers,
            "allowed_max_workers": [1, MAX_WORKERS_UPPER_BOUND],
            "duckdb_threads_per_worker": duckdb_threads,
            "duckdb_memory_limit_per_worker": duckdb_memory_limit_per_worker,
            "chunk_size_securities": chunk_size_securities,
            "r0_t09_runner_worker_policy_unchanged": True,
        },
        "memory_boundary": {
            "parent_holds_all_securities": False,
            "parent_holds_all_dates": False,
            "parent_holds_upstream_rows": False,
            "worker_returns_rows": False,
            "duckdb_written_by_stream_append": True,
        },
        "exchange_artifact_format": "sharded_jsonl_gz",
        "shards": [
            {
                "chunk_id": chunk["chunk_id"],
                "path": chunk["artifact_path"],
                "row_count": chunk["row_count"],
                "content_sha256": chunk["content_sha256"],
                "file_sha256": chunk["file_sha256"],
                "status": chunk["status"],
                "security_count": chunk["security_count"],
                "security_id_min": chunk["security_id_min"],
                "security_id_max": chunk["security_id_max"],
            }
            for chunk in chunks
        ],
    }


def _build_source_plan(d3_duckdb: Path, source_table: str) -> SourcePlan:
    if not d3_duckdb.is_file():
        raise R0T10MaterializationError("d3_source_duckdb_missing")
    _guard_d3_source_path(d3_duckdb)
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(d3_duckdb), read_only=True)
    try:
        rows = conn.execute(f"PRAGMA table_info('{source_table}')").fetchall()
        if not rows:
            raise R0T10MaterializationError("d3_source_table_missing")
        columns = tuple(str(row[1]) for row in rows)
        security_column = _first_available(columns, ("security_id", "ts_code"))
        date_column = _first_available(columns, ("trading_date", "trade_date"))
        if security_column is None or date_column is None:
            raise R0T10MaterializationError("d3_source_key_columns_missing")
        required = {
            "adjusted_high",
            "adjusted_low",
            "adjusted_close",
            "daily_vwap",
            "volume_shares",
            "turnover_float",
            "amount_yuan",
            "float_share_shares",
        }
        available_after_alias = {
            *_alias_available(columns),
            "security_id",
            "trading_date",
        }
        missing = sorted(required - available_after_alias)
        if missing:
            raise R0T10MaterializationError(
                "d3_source_r0_t04_required_fields_missing:" + ",".join(missing)
            )
        quoted_table = quote_ident(source_table)
        quoted_security = quote_ident(security_column)
        quoted_date = quote_ident(date_column)
        source_row_count = int(
            conn.execute(f"SELECT count(*) FROM {quoted_table}").fetchone()[0]
        )
        source_security_count = int(
            conn.execute(
                f"SELECT count(DISTINCT {quoted_security}) FROM {quoted_table}"
            ).fetchone()[0]
        )
        date_min, date_max = conn.execute(
            f"SELECT min({quoted_date}), max({quoted_date}) FROM {quoted_table}"
        ).fetchone()
    finally:
        conn.close()
    return SourcePlan(
        d3_duckdb=d3_duckdb.resolve(),
        source_table=source_table,
        security_column=security_column,
        date_column=date_column,
        source_columns=columns,
        input_artifact_hash=sha256_file(d3_duckdb),
        source_row_count=source_row_count,
        source_security_count=source_security_count,
        date_min=None if date_min is None else str(date_min),
        date_max=None if date_max is None else str(date_max),
    )


def _iter_security_chunks(
    plan: SourcePlan, chunk_size_securities: int
) -> Iterable[tuple[str, ...]]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(plan.d3_duckdb), read_only=True)
    try:
        cursor = conn.execute(
            "SELECT DISTINCT "
            f"{quote_ident(plan.security_column)} AS security_id "
            f"FROM {quote_ident(plan.source_table)} ORDER BY 1"
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
    resume: bool,
) -> dict[str, Any]:
    chunk_hash = hash_object(
        {
            "source_hash": plan.input_artifact_hash,
            "source_table": plan.source_table,
            "securities": list(securities),
            "engine_version": METRIC_ENGINE_VERSION,
        }
    )
    chunk_id = chunk_hash[:16]
    shard_dir = root / "shards"
    status_dir = root / "status"
    log_dir = root / "logs"
    return {
        "run_id": run_id,
        "code_commit": code_commit,
        "d3_duckdb": str(plan.d3_duckdb),
        "source_table": plan.source_table,
        "security_column": plan.security_column,
        "date_column": plan.date_column,
        "input_artifact_hash": plan.input_artifact_hash,
        "securities": tuple(securities),
        "security_count": len(securities),
        "security_id_min": min(securities),
        "security_id_max": max(securities),
        "chunk_id": chunk_id,
        "chunk_hash": chunk_hash,
        "artifact_path": str(shard_dir / f"{chunk_id}.r0_t04_raw_metrics.jsonl.gz"),
        "done_marker_path": str(status_dir / f"{chunk_id}.DONE.json"),
        "failed_marker_path": str(status_dir / f"{chunk_id}.FAILED.json"),
        "log_path": str(log_dir / f"{chunk_id}.log"),
        "duckdb_threads": duckdb_threads,
        "duckdb_memory_limit": duckdb_memory_limit,
        "resume": resume,
    }


def _should_skip_chunk(task: Mapping[str, Any]) -> bool:
    artifact_path = Path(str(task["artifact_path"]))
    done_marker_path = Path(str(task["done_marker_path"]))
    failed_marker_path = Path(str(task["failed_marker_path"]))
    partial_path = artifact_path.with_name(artifact_path.name + ".partial")
    if partial_path.exists() or failed_marker_path.exists():
        return False
    if not artifact_path.exists() or not done_marker_path.exists():
        return False
    try:
        done = _read_done_marker(done_marker_path)
    except (OSError, json.JSONDecodeError, R0T10MaterializationError):
        return False
    return (
        done.get("schema_version") == "r0_t10_01_chunk_done.v1"
        and done.get("chunk_hash") == task.get("chunk_hash")
        and done.get("file_sha256") == sha256_file(artifact_path)
        and int(done.get("row_count", -1)) >= 0
        and isinstance(done.get("field_names"), list)
    )


def _read_done_marker(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise R0T10MaterializationError("chunk DONE marker must be JSON object")
    return payload


def _public_chunk_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "schema_version",
        "chunk_id",
        "chunk_hash",
        "security_count",
        "security_id_min",
        "security_id_max",
        "row_count",
        "content_sha256",
        "file_sha256",
        "field_names",
        "date_min",
        "date_max",
        "artifact_path",
        "done_marker_path",
        "started_at",
        "finished_at",
        "status",
        "error_type",
        "error_message",
    )
    return {key: summary[key] for key in allowed if key in summary}


def _normalise_observation_row(row: Mapping[str, Any]) -> dict[str, Any]:
    close = _pick(row, "adjusted_close", "adj_close", "close")
    high = _pick(row, "adjusted_high", "adj_high", "high")
    low = _pick(row, "adjusted_low", "adj_low", "low")
    volume = _pick(row, "volume_shares", "vol", "volume")
    amount = _pick(row, "amount_yuan", "amount")
    daily_vwap = _pick(row, "daily_vwap")
    if daily_vwap is None and _positive(volume) and _positive(amount):
        daily_vwap = float(amount) / float(volume)
    normalized = dict(row)
    normalized.update(
        {
            "security_id": str(_pick(row, "security_id", "ts_code")),
            "trading_date": str(_pick(row, "trading_date", "trade_date")),
            "adjusted_open": _pick(row, "adjusted_open", "adj_open", "open", "close"),
            "adjusted_high": high,
            "adjusted_low": low,
            "adjusted_close": close,
            "daily_vwap": daily_vwap,
            "volume_shares": volume,
            "amount_yuan": amount,
            "amount_unit": row.get("amount_unit", "yuan"),
            "amount_volume_unit_status": row.get("amount_volume_unit_status", "valid"),
            "daily_vwap_range_status": row.get("daily_vwap_range_status", "valid"),
            "turnover_float": _pick(row, "turnover_float"),
            "turnover_field_status": row.get("turnover_field_status", "valid"),
            "share_field_status": row.get("share_field_status", "valid"),
            "provider_turnover_crosscheck_status": row.get(
                "provider_turnover_crosscheck_status", "valid"
            ),
            "float_share_shares": _pick(row, "float_share_shares"),
            "trading_status": row.get("trading_status", "normal"),
            "corporate_action_flag": row.get("corporate_action_flag", False),
            "suspension_flag": row.get(
                "suspension_flag", row.get("is_listing_pause", False)
            ),
            "corporate_action_types_in_window": row.get(
                "corporate_action_types_in_window", []
            ),
            "share_comparability_corporate_action_in_window": row.get(
                "share_comparability_corporate_action_in_window", False
            ),
            "common_share_basis_policy": row.get("common_share_basis_policy", "same"),
            "volume_comparability_policy": row.get(
                "volume_comparability_policy", "same"
            ),
            "adjustment_status": row.get("adjustment_status", "valid"),
            "zero_amount_flag": row.get("zero_amount_flag", False),
        }
    )
    return normalized


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
        "task_id": "R0-T10-01",
        "status": "blocked",
        "run_id": run_id,
        "created_at": created_at,
        "code_commit": code_commit,
        "output_dir": str(output_dir),
        "row_count": 0,
        "security_count": 0,
        "max_workers": max_workers,
        "reason_codes": list(reason_codes),
        "artifacts_written": False,
    }


def _validate_worker_options(
    *, max_workers: int, duckdb_threads: int, chunk_size_securities: int
) -> None:
    if max_workers < 1 or max_workers > MAX_WORKERS_UPPER_BOUND:
        raise R0T10MaterializationError("max_workers must be between 1 and 8")
    if duckdb_threads < 1:
        raise R0T10MaterializationError("duckdb_threads must be >= 1")
    if chunk_size_securities < 1:
        raise R0T10MaterializationError("chunk_size_securities must be >= 1")


def _configure_duckdb(conn: Any, *, threads: int, memory_limit: str) -> None:
    conn.execute(f"SET threads TO {int(threads)}")
    safe_limit = memory_limit.replace("'", "''")
    conn.execute(f"SET memory_limit = '{safe_limit}'")


def _guard_d3_source_path(path: Path) -> None:
    normalized = str(path).replace("\\", "/").lower()
    if any(
        token in normalized
        for token in ("data/raw", "data/external", "marketdb", ".day")
    ):
        raise R0T10MaterializationError("d3_source_path_forbidden")
    if "data/generated/d3/" not in normalized:
        raise R0T10MaterializationError("d3_source_must_be_generated_d3_artifact")


def _first_available(columns: Sequence[str], candidates: Sequence[str]) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _alias_available(columns: Sequence[str]) -> set[str]:
    available = set(columns)
    aliases = {
        "security_id": ("ts_code",),
        "trading_date": ("trade_date",),
        "adjusted_open": ("adj_open", "open"),
        "adjusted_high": ("adj_high", "high"),
        "adjusted_low": ("adj_low", "low"),
        "adjusted_close": ("adj_close", "close"),
        "volume_shares": ("vol", "volume"),
        "amount_yuan": ("amount",),
    }
    for canonical, alias_names in aliases.items():
        if canonical in available or any(alias in available for alias in alias_names):
            available.add(canonical)
    return available


def _pick(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _positive(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
