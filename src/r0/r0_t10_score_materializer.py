from __future__ import annotations

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

from src.r0.percentile_score_engine import (
    ACTIVE_INDICATORS,
    DIMENSION_COMPONENTS,
    PERCENTILE_WINDOWS,
    SCORE_ENGINE_VERSION,
    compute_common_eligible_samples,
    compute_dimension_scores,
    compute_indicator_scores,
)
from src.r0.upstream_artifact_io import (
    duckdb_table_summary,
    hash_object,
    quote_ident,
    sha256_file,
    validate_manifest_shape,
    write_json_atomic,
    write_jsonl_gz_atomic,
)

MATERIALIZER_VERSION = "r0_t10_02_score_materializer.v1"
MANIFEST_SCHEMA_VERSION = "r0_t10_02_r0_t05_score_manifest.v1"
SUMMARY_SCHEMA_VERSION = "r0_t10_02_execution_summary.v1"

DEFAULT_MAX_WORKERS = 16
MAX_WORKERS_UPPER_BOUND = 16
DEFAULT_DUCKDB_THREADS = 1
DEFAULT_DUCKDB_MEMORY_LIMIT = "2GB"
DEFAULT_CHUNK_SIZE_SECURITIES = 1

R0_T04_TABLE_NAME = "r0_t04_raw_metric_results"
INDICATOR_DUCKDB_NAME = "r0_t05_indicator_score_results.duckdb"
DIMENSION_DUCKDB_NAME = "r0_t05_dimension_score_results.duckdb"
COMMON_DUCKDB_NAME = "r0_t05_common_eligible_sample_results.duckdb"
MANIFEST_NAME = "r0_t05_score_results_manifest.json"
SUMMARY_NAME = "r0_t05_execution_summary.json"
INDICATOR_TABLE_NAME = "r0_t05_indicator_score_results"
DIMENSION_TABLE_NAME = "r0_t05_dimension_score_results"
COMMON_TABLE_NAME = "r0_t05_common_eligible_sample_results"


class R0T10ScoreMaterializationError(RuntimeError):
    pass


@dataclass(frozen=True)
class R0T04Evidence:
    path: Path
    output_duckdb_sha256: str
    row_count: int
    security_count: int
    date_min: str
    date_max: str
    allowed_to_start: bool


@dataclass(frozen=True)
class SourcePlan:
    r0_t04_duckdb: Path
    evidence: R0T04Evidence
    input_duckdb_hash: str
    source_row_count: int
    source_security_count: int
    date_min: str | None
    date_max: str | None


def materialize_r0_t05_scores(
    *,
    r0_t04_evidence: str | Path,
    r0_t04_duckdb: str | Path,
    output_dir: str | Path,
    run_id: str,
    code_commit: str,
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
        plan = _build_source_plan(Path(r0_t04_evidence), Path(r0_t04_duckdb))
    except R0T10ScoreMaterializationError as exc:
        summary = _blocked_summary(
            output_dir=root,
            run_id=run_id,
            code_commit=code_commit,
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
        write_json_atomic(root / SUMMARY_NAME, summary)
        return summary

    duckdb_hashes = _write_authoritative_duckdb_outputs(
        root,
        completed_chunks,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit=duckdb_memory_limit_per_worker,
    )
    duckdb_summaries = {
        "indicator": duckdb_table_summary(
            root / INDICATOR_DUCKDB_NAME, INDICATOR_TABLE_NAME
        ),
        "dimension": duckdb_table_summary(
            root / DIMENSION_DUCKDB_NAME, DIMENSION_TABLE_NAME
        ),
        "common_eligible": duckdb_table_summary(
            root / COMMON_DUCKDB_NAME, COMMON_TABLE_NAME
        ),
    }
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
        duckdb_hashes=duckdb_hashes,
        duckdb_summaries=duckdb_summaries,
    )
    validate_manifest_shape(
        manifest,
        required_fields=(
            "schema_version",
            "run_id",
            "input_r0_t04_duckdb_sha256",
            "indicator_score_row_count",
            "dimension_score_row_count",
            "common_eligible_row_count",
            "shards",
            "output_hashes",
        ),
    )
    write_json_atomic(root / MANIFEST_NAME, manifest)
    summary = _completed_summary(
        root=root,
        run_id=run_id,
        code_commit=code_commit,
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
                    resume=resume,
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
    indicator_path = Path(str(task["indicator_artifact_path"]))
    dimension_path = Path(str(task["dimension_artifact_path"]))
    common_path = Path(str(task["common_artifact_path"]))
    done_marker_path = Path(str(task["done_marker_path"]))
    failed_marker_path = Path(str(task["failed_marker_path"]))
    log_path = Path(str(task["log_path"]))
    for path in (
        indicator_path,
        dimension_path,
        common_path,
        done_marker_path,
        log_path,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
    for path in (indicator_path, dimension_path, common_path):
        path.with_name(path.name + ".partial").unlink(missing_ok=True)
    try:
        raw_rows = tuple(_read_raw_rows_for_securities(task))
        indicator_scores = compute_indicator_scores(raw_rows)
        dimension_scores = compute_dimension_scores(indicator_scores)
        common_samples = compute_common_eligible_samples(indicator_scores)
        indicator_write = write_jsonl_gz_atomic(
            indicator_path, (item.as_dict() for item in indicator_scores)
        )
        dimension_write = write_jsonl_gz_atomic(
            dimension_path, (item.as_dict() for item in dimension_scores)
        )
        common_write = write_jsonl_gz_atomic(
            common_path, (item.as_dict() for item in common_samples)
        )
        summary = {
            "schema_version": "r0_t10_02_chunk_done.v1",
            "chunk_id": chunk_id,
            "chunk_hash": task["chunk_hash"],
            "security_count": task["security_count"],
            "security_id_min": task["security_id_min"],
            "security_id_max": task["security_id_max"],
            "indicator_score": _write_summary(indicator_write),
            "dimension_score": _write_summary(dimension_write),
            "common_eligible": _write_summary(common_write),
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
            "schema_version": "r0_t10_02_chunk_failed.v1",
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


def _read_raw_rows_for_securities(task: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(task["r0_t04_duckdb"]), read_only=True)
    try:
        _configure_duckdb(
            conn,
            threads=int(task["duckdb_threads"]),
            memory_limit=str(task["duckdb_memory_limit"]),
        )
        securities = tuple(str(item) for item in task["securities"])
        placeholders = ",".join("?" for _ in securities)
        sql = (
            f"SELECT * FROM {quote_ident(R0_T04_TABLE_NAME)} "
            f"WHERE security_id IN ({placeholders}) "
            "ORDER BY security_id, indicator_id, trading_date"
        )
        cursor = conn.execute(sql, list(securities))
        columns = [str(desc[0]) for desc in cursor.description]
        while True:
            batch = cursor.fetchmany(4096)
            if not batch:
                break
            for values in batch:
                yield dict(zip(columns, values, strict=True))
    finally:
        conn.close()


def _write_authoritative_duckdb_outputs(
    root: Path,
    chunks: Sequence[Mapping[str, Any]],
    *,
    duckdb_threads: int,
    duckdb_memory_limit: str,
) -> dict[str, str]:
    outputs = {
        "indicator": (
            INDICATOR_DUCKDB_NAME,
            INDICATOR_TABLE_NAME,
            [chunk["indicator_score"]["path"] for chunk in chunks],
        ),
        "dimension": (
            DIMENSION_DUCKDB_NAME,
            DIMENSION_TABLE_NAME,
            [chunk["dimension_score"]["path"] for chunk in chunks],
        ),
        "common_eligible": (
            COMMON_DUCKDB_NAME,
            COMMON_TABLE_NAME,
            [chunk["common_eligible"]["path"] for chunk in chunks],
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
                FROM read_json_auto(?, format='newline_delimited')
                """,
                [list(shard_paths)],
            )
        finally:
            conn.close()
        partial.replace(path)
        hashes[key] = sha256_file(path)
    return hashes


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
    indicator_rows = sum(int(chunk["indicator_score"]["row_count"]) for chunk in chunks)
    dimension_rows = sum(int(chunk["dimension_score"]["row_count"]) for chunk in chunks)
    common_rows = sum(int(chunk["common_eligible"]["row_count"]) for chunk in chunks)
    dates = [
        str(value)
        for chunk in chunks
        for section in ("indicator_score", "dimension_score", "common_eligible")
        for value in (chunk[section].get("date_min"), chunk[section].get("date_max"))
        if value is not None
    ]
    content_hashes = {
        str(chunk["chunk_id"]): {
            "indicator": chunk["indicator_score"]["content_sha256"],
            "dimension": chunk["dimension_score"]["content_sha256"],
            "common_eligible": chunk["common_eligible"]["content_sha256"],
        }
        for chunk in chunks
    }
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "task_id": "R0-T10-02",
        "run_id": run_id,
        "created_at": created_at,
        "code_commit_or_data_build_id": code_commit,
        "score_engine_version": SCORE_ENGINE_VERSION,
        "materializer_version": MATERIALIZER_VERSION,
        "input_r0_t04_evidence_path": str(plan.evidence.path),
        "input_r0_t04_duckdb_path": str(plan.r0_t04_duckdb),
        "input_r0_t04_duckdb_sha256": plan.input_duckdb_hash,
        "input_r0_t04_row_count": plan.source_row_count,
        "input_security_count": plan.source_security_count,
        "input_date_min": plan.date_min,
        "input_date_max": plan.date_max,
        "indicator_score_row_count": indicator_rows,
        "dimension_score_row_count": dimension_rows,
        "common_eligible_row_count": common_rows,
        "security_count": plan.source_security_count,
        "date_min": min(dates) if dates else plan.date_min,
        "date_max": max(dates) if dates else plan.date_max,
        "W_coverage": list(PERCENTILE_WINDOWS),
        "indicator_coverage": list(ACTIVE_INDICATORS),
        "dimension_coverage": list(DIMENSION_COMPONENTS),
        "output_paths": {
            "indicator": str(root / INDICATOR_DUCKDB_NAME),
            "dimension": str(root / DIMENSION_DUCKDB_NAME),
            "common_eligible": str(root / COMMON_DUCKDB_NAME),
        },
        "output_hashes": dict(duckdb_hashes),
        "duckdb_summaries": dict(duckdb_summaries),
        "global_content_hash": hash_object(content_hashes),
        "concurrency_policy": {
            "scope": "R0-T10 formal upstream score materialization only",
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
        "task_id": "R0-T10-02",
        "status": "completed",
        "run_id": run_id,
        "created_at": created_at,
        "finished_at": _utc_now(),
        "code_commit": code_commit,
        "output_dir": str(root),
        "manifest_path": str(root / MANIFEST_NAME),
        "indicator_score_duckdb_path": str(root / INDICATOR_DUCKDB_NAME),
        "dimension_score_duckdb_path": str(root / DIMENSION_DUCKDB_NAME),
        "common_eligible_duckdb_path": str(root / COMMON_DUCKDB_NAME),
        "input_r0_t04_duckdb_sha256": plan.input_duckdb_hash,
        "indicator_score_row_count": manifest["indicator_score_row_count"],
        "dimension_score_row_count": manifest["dimension_score_row_count"],
        "common_eligible_row_count": manifest["common_eligible_row_count"],
        "security_count": plan.source_security_count,
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
        "max_workers": max_workers,
        "duckdb_threads": duckdb_threads,
        "duckdb_memory_limit_per_worker": duckdb_memory_limit_per_worker,
        "chunk_size_securities": chunk_size_securities,
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
        "task_id": "R0-T10-02",
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
        "reason_codes": reasons,
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
        "chunks": [_public_chunk_summary(chunk) for chunk in chunk_summaries],
    }


def _build_source_plan(evidence_path: Path, r0_t04_duckdb: Path) -> SourcePlan:
    evidence = _parse_r0_t04_evidence(evidence_path)
    if not evidence.allowed_to_start:
        raise R0T10ScoreMaterializationError("r0_t04_evidence_gate_not_open")
    if not r0_t04_duckdb.is_file():
        raise R0T10ScoreMaterializationError("r0_t04_duckdb_missing")
    actual_hash = sha256_file(r0_t04_duckdb)
    if actual_hash != evidence.output_duckdb_sha256:
        raise R0T10ScoreMaterializationError("r0_t04_duckdb_hash_mismatch")
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(r0_t04_duckdb), read_only=True)
    try:
        table_exists = (
            conn.execute(
                """
                SELECT count(*)
                FROM information_schema.tables
                WHERE table_schema = 'main' AND table_name = ?
                """,
                [R0_T04_TABLE_NAME],
            ).fetchone()[0]
            == 1
        )
        if not table_exists:
            raise R0T10ScoreMaterializationError("r0_t04_table_missing")
        row_count, security_count, date_min, date_max = conn.execute(
            f"""
            SELECT
              count(*),
              count(DISTINCT security_id),
              min(trading_date),
              max(trading_date)
            FROM {quote_ident(R0_T04_TABLE_NAME)}
            """
        ).fetchone()
    finally:
        conn.close()
    if int(row_count) != evidence.row_count:
        raise R0T10ScoreMaterializationError("r0_t04_row_count_mismatch")
    return SourcePlan(
        r0_t04_duckdb=r0_t04_duckdb,
        evidence=evidence,
        input_duckdb_hash=actual_hash,
        source_row_count=int(row_count),
        source_security_count=int(security_count),
        date_min=None if date_min is None else str(date_min),
        date_max=None if date_max is None else str(date_max),
    )


def _parse_r0_t04_evidence(path: Path) -> R0T04Evidence:
    if not path.is_file():
        raise R0T10ScoreMaterializationError("r0_t04_evidence_missing")
    text = path.read_text(encoding="utf-8")
    return R0T04Evidence(
        path=path,
        output_duckdb_sha256=_evidence_value(text, "output_duckdb_sha256"),
        row_count=int(_evidence_value(text, "row_count").replace(",", "")),
        security_count=int(_evidence_value(text, "security_count").replace(",", "")),
        date_min=_evidence_value(text, "date_min"),
        date_max=_evidence_value(text, "date_max"),
        allowed_to_start=_evidence_value(text, "R0-T05_allowed_to_start") == "true",
    )


def _evidence_value(text: str, key: str) -> str:
    match = re.search(rf"`{re.escape(key)}`:\s*`?([^`\n]+)`?", text)
    if not match:
        raise R0T10ScoreMaterializationError(f"r0_t04_evidence_missing_{key}")
    return match.group(1).strip()


def _iter_security_chunks(
    plan: SourcePlan, chunk_size_securities: int
) -> Iterable[tuple[str, ...]]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(plan.r0_t04_duckdb), read_only=True)
    try:
        cursor = conn.execute(
            "SELECT DISTINCT security_id "
            f"FROM {quote_ident(R0_T04_TABLE_NAME)} ORDER BY 1"
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
            "source_hash": plan.input_duckdb_hash,
            "securities": list(securities),
            "windows": list(PERCENTILE_WINDOWS),
            "engine_version": SCORE_ENGINE_VERSION,
        }
    )
    chunk_id = chunk_hash[:16]
    return {
        "run_id": run_id,
        "code_commit": code_commit,
        "r0_t04_duckdb": str(plan.r0_t04_duckdb),
        "securities": tuple(securities),
        "security_count": len(securities),
        "security_id_min": min(securities),
        "security_id_max": max(securities),
        "chunk_id": chunk_id,
        "chunk_hash": chunk_hash,
        "indicator_artifact_path": str(
            root / "shards" / "indicator_score" / f"{chunk_id}.jsonl.gz"
        ),
        "dimension_artifact_path": str(
            root / "shards" / "dimension_score" / f"{chunk_id}.jsonl.gz"
        ),
        "common_artifact_path": str(
            root / "shards" / "common_eligible" / f"{chunk_id}.jsonl.gz"
        ),
        "done_marker_path": str(root / "status" / f"{chunk_id}.DONE.json"),
        "failed_marker_path": str(root / "status" / f"{chunk_id}.FAILED.json"),
        "log_path": str(root / "logs" / f"{chunk_id}.log"),
        "duckdb_threads": duckdb_threads,
        "duckdb_memory_limit": duckdb_memory_limit,
        "resume": resume,
    }


def _should_skip_chunk(task: Mapping[str, Any]) -> bool:
    done_marker_path = Path(str(task["done_marker_path"]))
    failed_marker_path = Path(str(task["failed_marker_path"]))
    artifact_paths = [
        Path(str(task["indicator_artifact_path"])),
        Path(str(task["dimension_artifact_path"])),
        Path(str(task["common_artifact_path"])),
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
    if done.get("schema_version") != "r0_t10_02_chunk_done.v1":
        return False
    if done.get("chunk_hash") != task.get("chunk_hash"):
        return False
    sections = (
        ("indicator_score", artifact_paths[0]),
        ("dimension_score", artifact_paths[1]),
        ("common_eligible", artifact_paths[2]),
    )
    return all(
        isinstance(done.get(section), Mapping)
        and done[section].get("file_sha256") == sha256_file(path)
        for section, path in sections
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise R0T10ScoreMaterializationError(f"expected JSON object: {path}")
    return payload


def _planned_chunk_count(plan: SourcePlan, chunk_size_securities: int) -> int:
    return (
        plan.source_security_count + chunk_size_securities - 1
    ) // chunk_size_securities


def _remove_authoritative_outputs(root: Path) -> None:
    for name in (INDICATOR_DUCKDB_NAME, DIMENSION_DUCKDB_NAME, COMMON_DUCKDB_NAME):
        path = root / name
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".partial").unlink(missing_ok=True)
    (root / MANIFEST_NAME).unlink(missing_ok=True)


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
        "task_id": "R0-T10-02",
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
    }


def _write_summary(summary: Any) -> dict[str, Any]:
    return {
        "path": str(summary.path),
        "row_count": summary.row_count,
        "content_sha256": summary.content_sha256,
        "file_sha256": summary.file_sha256,
        "field_names": list(summary.field_names),
        "date_min": summary.date_min,
        "date_max": summary.date_max,
    }


def _manifest_shard(chunk: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": chunk["chunk_id"],
        "chunk_hash": chunk["chunk_hash"],
        "status": chunk["status"],
        "security_count": chunk["security_count"],
        "security_id_min": chunk["security_id_min"],
        "security_id_max": chunk["security_id_max"],
        "indicator_score": dict(chunk["indicator_score"]),
        "dimension_score": dict(chunk["dimension_score"]),
        "common_eligible": dict(chunk["common_eligible"]),
    }


def _public_chunk_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "schema_version",
        "chunk_id",
        "chunk_hash",
        "security_count",
        "security_id_min",
        "security_id_max",
        "indicator_score",
        "dimension_score",
        "common_eligible",
        "done_marker_path",
        "started_at",
        "finished_at",
        "status",
        "error_type",
        "error_message",
    )
    return {key: summary[key] for key in allowed if key in summary}


def _validate_worker_options(
    *, max_workers: int, duckdb_threads: int, chunk_size_securities: int
) -> None:
    if max_workers < 1 or max_workers > MAX_WORKERS_UPPER_BOUND:
        raise R0T10ScoreMaterializationError("max_workers must be between 1 and 16")
    if duckdb_threads < 1:
        raise R0T10ScoreMaterializationError("duckdb_threads must be >= 1")
    if chunk_size_securities < 1:
        raise R0T10ScoreMaterializationError("chunk_size_securities must be >= 1")


def _configure_duckdb(conn: Any, *, threads: int, memory_limit: str) -> None:
    conn.execute(f"SET threads = {int(threads)}")
    conn.execute("SET memory_limit = ?", [memory_limit])


def _utc_now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()
