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

from src.r0.daily_state_engine import (
    DIMENSIONS,
    Q_VALUES,
    STATE_ENGINE_VERSION,
    WEAK_DELTA,
)
from src.r0.percentile_score_engine import ACTIVE_INDICATORS, PERCENTILE_WINDOWS
from src.r0.r0_t10_score_materializer import (
    DIMENSION_TABLE_NAME,
    INDICATOR_TABLE_NAME,
)
from src.r0.upstream_artifact_io import (
    duckdb_table_summary,
    hash_object,
    quote_ident,
    sha256_file,
    validate_manifest_shape,
    write_json_atomic,
)

MATERIALIZER_VERSION = "r0_t10_03_nested_state_materializer.v1"
MANIFEST_SCHEMA_VERSION = "r0_t10_03_r0_t06_nested_state_manifest.v1"
SUMMARY_SCHEMA_VERSION = "r0_t10_03_execution_summary.v1"

DEFAULT_MAX_WORKERS = 16
MAX_WORKERS_UPPER_BOUND = 16
DEFAULT_DUCKDB_THREADS = 1
DEFAULT_DUCKDB_MEMORY_LIMIT = "2GB"
DEFAULT_CHUNK_SIZE_SECURITIES = 1

INDICATOR_STATE_DUCKDB_NAME = "r0_t06_indicator_state_results.duckdb"
DIMENSION_STATE_DUCKDB_NAME = "r0_t06_dimension_state_results.duckdb"
NESTED_DAILY_DUCKDB_NAME = "r0_t06_nested_daily_state_results.duckdb"
MANIFEST_NAME = "r0_t06_nested_state_results_manifest.json"
SUMMARY_NAME = "r0_t06_execution_summary.json"

INDICATOR_STATE_TABLE_NAME = "r0_t06_indicator_state_results"
DIMENSION_STATE_TABLE_NAME = "r0_t06_dimension_state_results"
NESTED_DAILY_TABLE_NAME = "r0_t06_nested_daily_state_results"

Q_VALUES_SQL = ", ".join(f"({q:.2f})" for q in Q_VALUES)
EPSILON = 1e-12


class R0T10NestedStateMaterializationError(RuntimeError):
    pass


@dataclass(frozen=True)
class R0T05Evidence:
    path: Path
    indicator_hash: str
    dimension_hash: str
    common_hash: str
    indicator_row_count: int
    dimension_row_count: int
    common_row_count: int
    security_count: int
    date_min: str
    date_max: str
    allowed_to_start: bool


@dataclass(frozen=True)
class SourcePlan:
    evidence: R0T05Evidence
    indicator_score_duckdb: Path
    dimension_score_duckdb: Path
    common_eligible_duckdb: Path
    indicator_hash: str
    dimension_hash: str
    common_hash: str
    security_count: int
    date_min: str | None
    date_max: str | None


def materialize_r0_t06_nested_states(
    *,
    r0_t05_evidence: str | Path,
    indicator_score_duckdb: str | Path,
    dimension_score_duckdb: str | Path,
    common_eligible_duckdb: str | Path,
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
        plan = _build_source_plan(
            Path(r0_t05_evidence),
            Path(indicator_score_duckdb),
            Path(dimension_score_duckdb),
            Path(common_eligible_duckdb),
        )
    except R0T10NestedStateMaterializationError as exc:
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
        "indicator_state": duckdb_table_summary(
            root / INDICATOR_STATE_DUCKDB_NAME, INDICATOR_STATE_TABLE_NAME
        ),
        "dimension_state": duckdb_table_summary(
            root / DIMENSION_STATE_DUCKDB_NAME, DIMENSION_STATE_TABLE_NAME
        ),
        "nested_daily_state": duckdb_table_summary(
            root / NESTED_DAILY_DUCKDB_NAME, NESTED_DAILY_TABLE_NAME
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
            "input_indicator_score_duckdb_sha256",
            "indicator_state_row_count",
            "dimension_state_row_count",
            "nested_daily_state_row_count",
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
    nested_path = Path(str(task["nested_artifact_path"]))
    done_marker_path = Path(str(task["done_marker_path"]))
    failed_marker_path = Path(str(task["failed_marker_path"]))
    log_path = Path(str(task["log_path"]))
    for path in (
        indicator_path,
        dimension_path,
        nested_path,
        done_marker_path,
        log_path,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
    for path in (indicator_path, dimension_path, nested_path):
        path.with_name(path.name + ".partial").unlink(missing_ok=True)
    try:
        _write_chunk_parquet_outputs(task)
        indicator_summary = _parquet_summary(indicator_path)
        dimension_summary = _parquet_summary(dimension_path)
        nested_summary = _parquet_summary(nested_path)
        summary = {
            "schema_version": "r0_t10_03_chunk_done.v1",
            "chunk_id": chunk_id,
            "chunk_hash": task["chunk_hash"],
            "security_count": task["security_count"],
            "security_id_min": task["security_id_min"],
            "security_id_max": task["security_id_max"],
            "indicator_state": indicator_summary,
            "dimension_state": dimension_summary,
            "nested_daily_state": nested_summary,
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
            "schema_version": "r0_t10_03_chunk_failed.v1",
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
            f"ATTACH {_sql_string_literal(str(task['indicator_duckdb']))} "
            "AS indicator_db (READ_ONLY)"
        )
        conn.execute(
            f"ATTACH {_sql_string_literal(str(task['dimension_duckdb']))} "
            "AS dimension_db (READ_ONLY)"
        )
        securities = [str(item) for item in task["securities"]]
        conn.execute("CREATE TEMP TABLE chunk_securities(security_id VARCHAR)")
        conn.executemany(
            "INSERT INTO chunk_securities VALUES (?)",
            [(security,) for security in securities],
        )
        conn.execute("CREATE TEMP TABLE q_values(q DOUBLE)")
        conn.execute(f"INSERT INTO q_values VALUES {Q_VALUES_SQL}")
        conn.execute(_indicator_state_sql())
        conn.execute(_dimension_state_sql())
        conn.execute(_nested_state_sql())
        for table_name, target in (
            ("indicator_state", task["indicator_artifact_path"]),
            ("dimension_state", task["dimension_artifact_path"]),
            ("nested_daily_state", task["nested_artifact_path"]),
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


def _sql_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _indicator_state_sql() -> str:
    return f"""
    CREATE TEMP TABLE indicator_state AS
    SELECT
      i.security_id,
      i.trading_date,
      CAST(i.percentile_window_W AS INTEGER) AS percentile_window_W,
      q.q,
      i.indicator_id,
      CAST(i.score AS DOUBLE) AS score,
      CAST(i.eligible AS BOOLEAN) AS eligible,
      CASE
        WHEN i.eligible = true
          AND i.validity_status = 'valid'
          AND i.score IS NOT NULL
        THEN CAST(i.score + {EPSILON} >= 1.0 - q.q AS BOOLEAN)
        ELSE NULL
      END AS indicator_active,
      CASE
        WHEN i.eligible = true
          AND i.validity_status = 'valid'
          AND i.score IS NOT NULL
        THEN 'valid'
        WHEN i.validity_status IN ('unknown', 'diagnostic_required', 'blocked')
        THEN i.validity_status
        ELSE 'unknown'
      END AS validity_status,
      CASE
        WHEN i.eligible = true
          AND i.validity_status = 'valid'
          AND i.score IS NOT NULL
        THEN ['valid_no_blocker']
        ELSE list_distinct(
          list_concat(
            COALESCE(i.reason_codes, []),
            CASE
              WHEN i.score IS NULL THEN ['score_missing']
              WHEN i.eligible != true THEN ['indicator_not_eligible']
              ELSE []
            END
          )
        )
      END AS reason_codes,
      '{STATE_ENGINE_VERSION}' AS state_engine_version
    FROM indicator_db.{quote_ident(INDICATOR_TABLE_NAME)} i
    JOIN chunk_securities s USING (security_id)
    CROSS JOIN q_values q
    """


def _dimension_state_sql() -> str:
    return f"""
    CREATE TEMP TABLE dimension_state AS
    SELECT
      d.security_id,
      d.trading_date,
      CAST(d.percentile_window_W AS INTEGER) AS percentile_window_W,
      q.q,
      CAST({WEAK_DELTA:.2f} AS DOUBLE) AS weak_delta,
      d.dimension,
      CAST(d.score_dimension AS DOUBLE) AS score_dimension,
      CAST(d.score_dimension_min AS DOUBLE) AS score_dimension_min,
      CAST(d.eligible_dimension AS BOOLEAN) AS eligible_dimension,
      CASE
        WHEN d.eligible_dimension = true
          AND d.validity_status = 'valid'
          AND d.score_dimension IS NOT NULL
          AND d.score_dimension_min IS NOT NULL
        THEN CAST(
          d.score_dimension + {EPSILON} >= 1.0 - q.q
          AND d.score_dimension_min + {EPSILON} >= 1.0 - q.q - {WEAK_DELTA:.2f}
          AS BOOLEAN
        )
        ELSE NULL
      END AS dimension_active_weak,
      CASE
        WHEN d.eligible_dimension = true
          AND d.validity_status = 'valid'
          AND d.score_dimension IS NOT NULL
          AND d.score_dimension_min IS NOT NULL
        THEN 'valid'
        WHEN d.validity_status IN ('unknown', 'diagnostic_required', 'blocked')
        THEN d.validity_status
        ELSE 'unknown'
      END AS validity_status,
      CASE
        WHEN d.eligible_dimension = true
          AND d.validity_status = 'valid'
          AND d.score_dimension IS NOT NULL
          AND d.score_dimension_min IS NOT NULL
        THEN ['valid_no_blocker']
        ELSE list_distinct(
          list_concat(
            list_concat(
              COALESCE(d.reason_codes, []),
              CASE
                WHEN d.score_dimension IS NULL
                THEN ['score_dimension_missing']
                ELSE []
              END
            ),
            list_concat(
              CASE
                WHEN d.score_dimension_min IS NULL
                THEN ['score_dimension_min_missing']
                ELSE []
              END,
              CASE
                WHEN d.eligible_dimension != true
                THEN ['dimension_not_eligible']
                ELSE []
              END
            )
          )
        )
      END AS reason_codes,
      d.component_indicator_ids,
      '{STATE_ENGINE_VERSION}' AS state_engine_version
    FROM dimension_db.{quote_ident(DIMENSION_TABLE_NAME)} d
    JOIN chunk_securities s USING (security_id)
    CROSS JOIN q_values q
    """


def _nested_state_sql() -> str:
    return f"""
    CREATE TEMP TABLE nested_daily_state AS
    WITH pivoted AS (
      SELECT
        security_id,
        trading_date,
        percentile_window_W,
        q,
        any_value(weak_delta) AS weak_delta,
        max(CASE WHEN dimension = 'P' THEN dimension_active_weak END) AS P_raw,
        max(CASE WHEN dimension = 'C' THEN dimension_active_weak END) AS C_raw,
        max(CASE WHEN dimension = 'T' THEN dimension_active_weak END) AS T_raw,
        max(CASE WHEN dimension = 'V' THEN dimension_active_weak END) AS V_raw,
        max(CASE WHEN dimension = 'P' THEN validity_status END) AS P_status,
        max(CASE WHEN dimension = 'C' THEN validity_status END) AS C_status,
        max(CASE WHEN dimension = 'T' THEN validity_status END) AS T_status,
        max(CASE WHEN dimension = 'V' THEN validity_status END) AS V_status,
        any_value(CASE WHEN dimension = 'P' THEN reason_codes END) AS P_reasons,
        any_value(CASE WHEN dimension = 'C' THEN reason_codes END) AS C_reasons,
        any_value(CASE WHEN dimension = 'T' THEN reason_codes END) AS T_reasons,
        any_value(CASE WHEN dimension = 'V' THEN reason_codes END) AS V_reasons
      FROM dimension_state
      GROUP BY security_id, trading_date, percentile_window_W, q
    ), layered AS (
      SELECT
        *,
        P_raw AS S_P_raw,
        CASE
          WHEN P_raw = false THEN false
          WHEN P_raw IS NULL THEN NULL
          ELSE C_raw
        END AS S_PC_raw,
        CASE
          WHEN P_raw = false THEN false
          WHEN P_raw IS NULL THEN NULL
          WHEN C_raw = false THEN false
          WHEN C_raw IS NULL THEN NULL
          ELSE T_raw
        END AS S_PCT_raw,
        CASE
          WHEN P_raw = false THEN false
          WHEN P_raw IS NULL THEN NULL
          WHEN C_raw = false THEN false
          WHEN C_raw IS NULL THEN NULL
          WHEN T_raw = false THEN false
          WHEN T_raw IS NULL THEN NULL
          ELSE V_raw
        END AS S_PCVT_raw
      FROM pivoted
    )
    SELECT
      security_id,
      trading_date,
      CAST(percentile_window_W AS INTEGER) AS percentile_window_W,
      q,
      weak_delta,
      CAST(P_raw AS BOOLEAN) AS P_raw,
      CAST(C_raw AS BOOLEAN) AS C_raw,
      CAST(T_raw AS BOOLEAN) AS T_raw,
      CAST(V_raw AS BOOLEAN) AS V_raw,
      CAST(S_P_raw AS BOOLEAN) AS S_P_raw,
      CAST(S_PC_raw AS BOOLEAN) AS S_PC_raw,
      CAST(S_PCT_raw AS BOOLEAN) AS S_PCT_raw,
      CAST(S_PCVT_raw AS BOOLEAN) AS S_PCVT_raw,
      CASE
        WHEN P_raw IS NULL THEN COALESCE(P_status, 'unknown')
        ELSE 'valid'
      END AS S_P_validity_status,
      CASE
        WHEN P_raw IS NULL THEN COALESCE(P_reasons, ['missing_dimension_state'])
        ELSE ['valid_no_blocker']
      END AS S_P_reason_codes,
      CASE
        WHEN P_raw IS NULL THEN COALESCE(P_status, 'unknown')
        WHEN P_raw = false THEN 'valid'
        WHEN C_raw IS NULL THEN COALESCE(C_status, 'unknown')
        ELSE 'valid'
      END AS S_PC_validity_status,
      CASE
        WHEN P_raw IS NULL THEN COALESCE(P_reasons, ['missing_dimension_state'])
        WHEN P_raw = false THEN ['valid_no_blocker']
        WHEN C_raw IS NULL THEN COALESCE(C_reasons, ['missing_dimension_state'])
        ELSE ['valid_no_blocker']
      END AS S_PC_reason_codes,
      CASE
        WHEN P_raw IS NULL THEN COALESCE(P_status, 'unknown')
        WHEN P_raw = false THEN 'valid'
        WHEN C_raw IS NULL THEN COALESCE(C_status, 'unknown')
        WHEN C_raw = false THEN 'valid'
        WHEN T_raw IS NULL THEN COALESCE(T_status, 'unknown')
        ELSE 'valid'
      END AS S_PCT_validity_status,
      CASE
        WHEN P_raw IS NULL THEN COALESCE(P_reasons, ['missing_dimension_state'])
        WHEN P_raw = false THEN ['valid_no_blocker']
        WHEN C_raw IS NULL THEN COALESCE(C_reasons, ['missing_dimension_state'])
        WHEN C_raw = false THEN ['valid_no_blocker']
        WHEN T_raw IS NULL THEN COALESCE(T_reasons, ['missing_dimension_state'])
        ELSE ['valid_no_blocker']
      END AS S_PCT_reason_codes,
      CASE
        WHEN P_raw IS NULL THEN COALESCE(P_status, 'unknown')
        WHEN P_raw = false THEN 'valid'
        WHEN C_raw IS NULL THEN COALESCE(C_status, 'unknown')
        WHEN C_raw = false THEN 'valid'
        WHEN T_raw IS NULL THEN COALESCE(T_status, 'unknown')
        WHEN T_raw = false THEN 'valid'
        WHEN V_raw IS NULL THEN COALESCE(V_status, 'unknown')
        ELSE 'valid'
      END AS S_PCVT_validity_status,
      CASE
        WHEN P_raw IS NULL THEN COALESCE(P_reasons, ['missing_dimension_state'])
        WHEN P_raw = false THEN ['valid_no_blocker']
        WHEN C_raw IS NULL THEN COALESCE(C_reasons, ['missing_dimension_state'])
        WHEN C_raw = false THEN ['valid_no_blocker']
        WHEN T_raw IS NULL THEN COALESCE(T_reasons, ['missing_dimension_state'])
        WHEN T_raw = false THEN ['valid_no_blocker']
        WHEN V_raw IS NULL THEN COALESCE(V_reasons, ['missing_dimension_state'])
        ELSE ['valid_no_blocker']
      END AS S_PCVT_reason_codes,
      CASE
        WHEN P_raw IS NULL THEN upper(COALESCE(P_status, 'unknown'))
        WHEN P_raw = false THEN 'NONE'
        WHEN C_raw IS NULL THEN upper(COALESCE(C_status, 'unknown'))
        WHEN C_raw = false THEN 'P_ONLY'
        WHEN T_raw IS NULL THEN upper(COALESCE(T_status, 'unknown'))
        WHEN T_raw = false THEN 'PC_ONLY'
        WHEN V_raw IS NULL THEN upper(COALESCE(V_status, 'unknown'))
        WHEN V_raw = false THEN 'PCT_ONLY'
        ELSE 'PCVT'
      END AS exclusive_state_layer,
      CAST(
        CASE
          WHEN P_raw IS NULL
            OR C_raw IS NULL
            OR T_raw IS NULL
            OR V_raw IS NULL
          THEN false
          ELSE true
        END AS BOOLEAN
      ) AS eligible_state,
      CASE
        WHEN P_raw IS NULL THEN COALESCE(P_status, 'unknown')
        WHEN P_raw = false THEN 'valid'
        WHEN C_raw IS NULL THEN COALESCE(C_status, 'unknown')
        WHEN C_raw = false THEN 'valid'
        WHEN T_raw IS NULL THEN COALESCE(T_status, 'unknown')
        WHEN T_raw = false THEN 'valid'
        WHEN V_raw IS NULL THEN COALESCE(V_status, 'unknown')
        WHEN V_raw = false THEN 'valid'
        ELSE 'valid'
      END AS validity_status,
      CASE
        WHEN P_raw IS NULL THEN COALESCE(P_reasons, ['missing_dimension_state'])
        WHEN P_raw = false THEN ['valid_no_blocker']
        WHEN C_raw IS NULL THEN COALESCE(C_reasons, ['missing_dimension_state'])
        WHEN C_raw = false THEN ['valid_no_blocker']
        WHEN T_raw IS NULL THEN COALESCE(T_reasons, ['missing_dimension_state'])
        WHEN T_raw = false THEN ['valid_no_blocker']
        WHEN V_raw IS NULL THEN COALESCE(V_reasons, ['missing_dimension_state'])
        WHEN V_raw = false THEN ['valid_no_blocker']
        ELSE ['valid_no_blocker']
      END AS reason_codes,
      '{STATE_ENGINE_VERSION}' AS state_engine_version
    FROM layered
    """


def _write_authoritative_duckdb_outputs(
    root: Path,
    chunks: Sequence[Mapping[str, Any]],
    *,
    duckdb_threads: int,
    duckdb_memory_limit: str,
) -> dict[str, str]:
    outputs = {
        "indicator_state": (
            INDICATOR_STATE_DUCKDB_NAME,
            INDICATOR_STATE_TABLE_NAME,
            [chunk["indicator_state"]["path"] for chunk in chunks],
        ),
        "dimension_state": (
            DIMENSION_STATE_DUCKDB_NAME,
            DIMENSION_STATE_TABLE_NAME,
            [chunk["dimension_state"]["path"] for chunk in chunks],
        ),
        "nested_daily_state": (
            NESTED_DAILY_DUCKDB_NAME,
            NESTED_DAILY_TABLE_NAME,
            [chunk["nested_daily_state"]["path"] for chunk in chunks],
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
    evidence_path: Path,
    indicator_score_duckdb: Path,
    dimension_score_duckdb: Path,
    common_eligible_duckdb: Path,
) -> SourcePlan:
    evidence = _parse_r0_t05_evidence(evidence_path)
    if not evidence.allowed_to_start:
        raise R0T10NestedStateMaterializationError("r0_t05_evidence_gate_not_open")
    inputs = {
        "indicator": (indicator_score_duckdb, evidence.indicator_hash),
        "dimension": (dimension_score_duckdb, evidence.dimension_hash),
        "common_eligible": (common_eligible_duckdb, evidence.common_hash),
    }
    actual_hashes: dict[str, str] = {}
    for key, (path, expected_hash) in inputs.items():
        if not path.is_file():
            raise R0T10NestedStateMaterializationError(f"r0_t05_{key}_duckdb_missing")
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise R0T10NestedStateMaterializationError(
                f"r0_t05_{key}_duckdb_hash_mismatch"
            )
        actual_hashes[key] = actual_hash
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(dimension_score_duckdb), read_only=True)
    try:
        row_count, security_count, date_min, date_max = conn.execute(
            f"""
            SELECT
              count(*),
              count(DISTINCT security_id),
              min(trading_date),
              max(trading_date)
            FROM {quote_ident(DIMENSION_TABLE_NAME)}
            """
        ).fetchone()
    finally:
        conn.close()
    if int(row_count) != evidence.dimension_row_count:
        raise R0T10NestedStateMaterializationError(
            "r0_t05_dimension_row_count_mismatch"
        )
    if int(security_count) != evidence.security_count:
        raise R0T10NestedStateMaterializationError("r0_t05_security_count_mismatch")
    return SourcePlan(
        evidence=evidence,
        indicator_score_duckdb=indicator_score_duckdb,
        dimension_score_duckdb=dimension_score_duckdb,
        common_eligible_duckdb=common_eligible_duckdb,
        indicator_hash=actual_hashes["indicator"],
        dimension_hash=actual_hashes["dimension"],
        common_hash=actual_hashes["common_eligible"],
        security_count=int(security_count),
        date_min=None if date_min is None else str(date_min),
        date_max=None if date_max is None else str(date_max),
    )


def _parse_r0_t05_evidence(path: Path) -> R0T05Evidence:
    if not path.is_file():
        raise R0T10NestedStateMaterializationError("r0_t05_evidence_missing")
    text = path.read_text(encoding="utf-8")
    return R0T05Evidence(
        path=path,
        indicator_hash=_evidence_value(text, "indicator_score_duckdb_sha256"),
        dimension_hash=_evidence_value(text, "dimension_score_duckdb_sha256"),
        common_hash=_evidence_value(text, "common_eligible_duckdb_sha256"),
        indicator_row_count=int(
            _evidence_value(text, "indicator_score_row_count").replace(",", "")
        ),
        dimension_row_count=int(
            _evidence_value(text, "dimension_score_row_count").replace(",", "")
        ),
        common_row_count=int(
            _evidence_value(text, "common_eligible_row_count").replace(",", "")
        ),
        security_count=int(_evidence_value(text, "security_count").replace(",", "")),
        date_min=_evidence_value(text, "date_min"),
        date_max=_evidence_value(text, "date_max"),
        allowed_to_start=_evidence_value(text, "R0-T06_allowed_to_start") == "true",
    )


def _evidence_value(text: str, key: str) -> str:
    match = re.search(rf"`{re.escape(key)}`:\s*`?([^`\n]+)`?", text)
    if not match:
        raise R0T10NestedStateMaterializationError(f"r0_t05_evidence_missing_{key}")
    return match.group(1).strip()


def _iter_security_chunks(
    plan: SourcePlan, chunk_size_securities: int
) -> Iterable[tuple[str, ...]]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(plan.dimension_score_duckdb), read_only=True)
    try:
        cursor = conn.execute(
            "SELECT DISTINCT security_id "
            f"FROM {quote_ident(DIMENSION_TABLE_NAME)} ORDER BY 1"
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
            "indicator_hash": plan.indicator_hash,
            "dimension_hash": plan.dimension_hash,
            "common_hash": plan.common_hash,
            "securities": list(securities),
            "q_values": list(Q_VALUES),
            "weak_delta": WEAK_DELTA,
            "engine_version": STATE_ENGINE_VERSION,
        }
    )
    chunk_id = chunk_hash[:16]
    return {
        "run_id": run_id,
        "code_commit": code_commit,
        "indicator_duckdb": str(plan.indicator_score_duckdb),
        "dimension_duckdb": str(plan.dimension_score_duckdb),
        "common_duckdb": str(plan.common_eligible_duckdb),
        "securities": tuple(securities),
        "security_count": len(securities),
        "security_id_min": min(securities),
        "security_id_max": max(securities),
        "chunk_id": chunk_id,
        "chunk_hash": chunk_hash,
        "indicator_artifact_path": str(
            root / "shards" / "indicator_state" / f"{chunk_id}.parquet"
        ),
        "dimension_artifact_path": str(
            root / "shards" / "dimension_state" / f"{chunk_id}.parquet"
        ),
        "nested_artifact_path": str(
            root / "shards" / "nested_daily_state" / f"{chunk_id}.parquet"
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
        Path(str(task["indicator_artifact_path"])),
        Path(str(task["dimension_artifact_path"])),
        Path(str(task["nested_artifact_path"])),
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
    if done.get("schema_version") != "r0_t10_03_chunk_done.v1":
        return False
    if done.get("chunk_hash") != task.get("chunk_hash"):
        return False
    sections = (
        ("indicator_state", artifact_paths[0]),
        ("dimension_state", artifact_paths[1]),
        ("nested_daily_state", artifact_paths[2]),
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
    indicator_rows = sum(int(chunk["indicator_state"]["row_count"]) for chunk in chunks)
    dimension_rows = sum(int(chunk["dimension_state"]["row_count"]) for chunk in chunks)
    nested_rows = sum(int(chunk["nested_daily_state"]["row_count"]) for chunk in chunks)
    dates = [
        str(value)
        for chunk in chunks
        for section in ("indicator_state", "dimension_state", "nested_daily_state")
        for value in (chunk[section].get("date_min"), chunk[section].get("date_max"))
        if value is not None
    ]
    content_hashes = {
        str(chunk["chunk_id"]): {
            "indicator_state": chunk["indicator_state"]["file_sha256"],
            "dimension_state": chunk["dimension_state"]["file_sha256"],
            "nested_daily_state": chunk["nested_daily_state"]["file_sha256"],
        }
        for chunk in chunks
    }
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "task_id": "R0-T10-03",
        "run_id": run_id,
        "created_at": created_at,
        "code_commit_or_data_build_id": code_commit,
        "state_engine_version": STATE_ENGINE_VERSION,
        "materializer_version": MATERIALIZER_VERSION,
        "input_r0_t05_evidence_path": str(plan.evidence.path),
        "input_indicator_score_duckdb_path": str(plan.indicator_score_duckdb),
        "input_dimension_score_duckdb_path": str(plan.dimension_score_duckdb),
        "input_common_eligible_duckdb_path": str(plan.common_eligible_duckdb),
        "input_indicator_score_duckdb_sha256": plan.indicator_hash,
        "input_dimension_score_duckdb_sha256": plan.dimension_hash,
        "input_common_eligible_duckdb_sha256": plan.common_hash,
        "input_indicator_score_row_count": plan.evidence.indicator_row_count,
        "input_dimension_score_row_count": plan.evidence.dimension_row_count,
        "input_common_eligible_row_count": plan.evidence.common_row_count,
        "input_security_count": plan.evidence.security_count,
        "input_date_min": plan.evidence.date_min,
        "input_date_max": plan.evidence.date_max,
        "indicator_state_row_count": indicator_rows,
        "dimension_state_row_count": dimension_rows,
        "nested_daily_state_row_count": nested_rows,
        "security_count": plan.security_count,
        "date_min": min(dates) if dates else plan.date_min,
        "date_max": max(dates) if dates else plan.date_max,
        "W_coverage": list(PERCENTILE_WINDOWS),
        "q_coverage": list(Q_VALUES),
        "weak_delta": WEAK_DELTA,
        "indicator_coverage": list(ACTIVE_INDICATORS),
        "dimension_coverage": list(DIMENSIONS),
        "R0-T07_allowed_to_start": True,
        "downstream_gate_allowed": True,
        "output_paths": {
            "indicator_state": str(root / INDICATOR_STATE_DUCKDB_NAME),
            "dimension_state": str(root / DIMENSION_STATE_DUCKDB_NAME),
            "nested_daily_state": str(root / NESTED_DAILY_DUCKDB_NAME),
        },
        "output_hashes": dict(duckdb_hashes),
        "duckdb_summaries": dict(duckdb_summaries),
        "global_content_hash": hash_object(content_hashes),
        "concurrency_policy": {
            "scope": "R0-T10 formal upstream nested state materialization only",
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
        "task_id": "R0-T10-03",
        "status": "completed",
        "run_id": run_id,
        "created_at": created_at,
        "finished_at": _utc_now(),
        "code_commit": code_commit,
        "output_dir": str(root),
        "manifest_path": str(root / MANIFEST_NAME),
        "indicator_state_duckdb_path": str(root / INDICATOR_STATE_DUCKDB_NAME),
        "dimension_state_duckdb_path": str(root / DIMENSION_STATE_DUCKDB_NAME),
        "nested_daily_state_duckdb_path": str(root / NESTED_DAILY_DUCKDB_NAME),
        "indicator_state_row_count": manifest["indicator_state_row_count"],
        "dimension_state_row_count": manifest["dimension_state_row_count"],
        "nested_daily_state_row_count": manifest["nested_daily_state_row_count"],
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
        "R0-T07_allowed_to_start": True,
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
        "task_id": "R0-T10-03",
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
        "R0-T07_allowed_to_start": False,
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
        "task_id": "R0-T10-03",
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
        "R0-T07_allowed_to_start": False,
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
        "indicator_state": dict(chunk["indicator_state"]),
        "dimension_state": dict(chunk["dimension_state"]),
        "nested_daily_state": dict(chunk["nested_daily_state"]),
    }


def _public_chunk_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "schema_version",
        "chunk_id",
        "chunk_hash",
        "security_count",
        "security_id_min",
        "security_id_max",
        "indicator_state",
        "dimension_state",
        "nested_daily_state",
        "done_marker_path",
        "started_at",
        "finished_at",
        "status",
        "error_type",
        "error_message",
    )
    return {key: summary[key] for key in allowed if key in summary}


def _parquet_summary(path: Path) -> dict[str, Any]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect()
    try:
        row_count, date_min, date_max = conn.execute(
            """
            SELECT count(*), min(trading_date), max(trading_date)
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
        raise R0T10NestedStateMaterializationError(f"expected JSON object: {path}")
    return payload


def _planned_chunk_count(plan: SourcePlan, chunk_size_securities: int) -> int:
    return (plan.security_count + chunk_size_securities - 1) // chunk_size_securities


def _remove_authoritative_outputs(root: Path) -> None:
    for name in (
        INDICATOR_STATE_DUCKDB_NAME,
        DIMENSION_STATE_DUCKDB_NAME,
        NESTED_DAILY_DUCKDB_NAME,
    ):
        path = root / name
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".partial").unlink(missing_ok=True)
    (root / MANIFEST_NAME).unlink(missing_ok=True)


def _validate_worker_options(
    *, max_workers: int, duckdb_threads: int, chunk_size_securities: int
) -> None:
    if max_workers < 1 or max_workers > MAX_WORKERS_UPPER_BOUND:
        raise R0T10NestedStateMaterializationError(
            "max_workers must be between 1 and 16"
        )
    if duckdb_threads < 1:
        raise R0T10NestedStateMaterializationError("duckdb_threads must be >= 1")
    if chunk_size_securities < 1:
        raise R0T10NestedStateMaterializationError("chunk_size_securities must be >= 1")


def _configure_duckdb(conn: Any, *, threads: int, memory_limit: str) -> None:
    conn.execute(f"SET threads = {int(threads)}")
    conn.execute("SET memory_limit = ?", [memory_limit])


def _utc_now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()
