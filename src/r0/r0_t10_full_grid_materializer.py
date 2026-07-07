from __future__ import annotations

import concurrent.futures
import json
import multiprocessing
import traceback
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.r0.candidate_artifact_engine import (
    CANDIDATE_ARTIFACT_ENGINE_VERSION,
    build_candidate_configs,
)
from src.r0.formal_run_identity import FormalRunIdentityError, validate_full_git_sha
from src.r0.r0_t10_authorized_input_manifest_builder import (
    BASELINE_CONFIG_ID,
    load_authorized_manifest,
    sha256_file,
)
from src.r0.upstream_artifact_io import quote_ident, write_json_atomic

MATERIALIZER_VERSION = "r0_t10_05_artifact_backed_full_grid_materializer.v1"
MANIFEST_SCHEMA_VERSION = "r0_t10_05_full_grid_manifest.v1"
SUMMARY_SCHEMA_VERSION = "r0_t10_05_execution_summary.v1"
VALIDATION_RESULT_NAME = "r0_t10_05_validation_result.json"
GLOBAL_MANIFEST_NAME = "r0_t10_05_full_grid_manifest.json"
SUMMARY_NAME = "r0_t10_05_execution_summary.json"
DEFAULT_MAX_WORKERS = 16
MAX_WORKERS_UPPER_BOUND = 16
DEFAULT_DUCKDB_THREADS = 1
DEFAULT_DUCKDB_MEMORY_LIMIT = "2GB"

DAILY_TABLE = "candidate_daily_state"
INTERVAL_TABLE = "candidate_confirmed_interval"


class R0T10FullGridMaterializationError(RuntimeError):
    pass


def materialize_full_grid(
    *,
    authorized_input_manifest: str | Path,
    output_dir: str | Path,
    run_id: str,
    code_commit: str,
    max_workers: int = DEFAULT_MAX_WORKERS,
    duckdb_threads: int = DEFAULT_DUCKDB_THREADS,
    duckdb_memory_limit_per_worker: str = DEFAULT_DUCKDB_MEMORY_LIMIT,
    resume: bool = False,
) -> dict[str, Any]:
    try:
        full_code_commit = validate_full_git_sha(code_commit)
    except FormalRunIdentityError as exc:
        raise R0T10FullGridMaterializationError("short_code_commit_forbidden") from exc
    if max_workers < 1 or max_workers > MAX_WORKERS_UPPER_BOUND:
        raise R0T10FullGridMaterializationError("max_workers must be between 1 and 16")
    if duckdb_threads < 1:
        raise R0T10FullGridMaterializationError("duckdb_threads must be >= 1")

    manifest_path = Path(authorized_input_manifest)
    manifest = load_authorized_manifest(manifest_path)
    if manifest.get("code_commit") != full_code_commit:
        raise R0T10FullGridMaterializationError("code_commit_mismatch")
    manifest_hash = sha256_file(manifest_path)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    _ensure_dirs(root)
    configs = [config.as_dict() for config in build_candidate_configs()]
    tasks = [
        {
            "config": config,
            "authorized_input_manifest_path": str(manifest_path),
            "authorized_input_manifest_hash": manifest_hash,
            "authorized_input_manifest": manifest,
            "output_dir": str(root),
            "run_id": run_id,
            "code_commit": full_code_commit,
            "duckdb_threads": duckdb_threads,
            "duckdb_memory_limit_per_worker": duckdb_memory_limit_per_worker,
            "resume": resume,
        }
        for config in configs
    ]

    results: list[dict[str, Any]] = []
    if max_workers == 1:
        for task in tasks:
            results.append(_run_one_config(task))
            _write_progress_summary(
                root,
                run_id,
                full_code_commit,
                manifest_path,
                manifest_hash,
                configs,
                results,
            )
    else:
        context = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=max_workers, mp_context=context
        ) as pool:
            futures = [pool.submit(_run_one_config, task) for task in tasks]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
                _write_progress_summary(
                    root,
                    run_id,
                    full_code_commit,
                    manifest_path,
                    manifest_hash,
                    configs,
                    results,
                )

    selected_count = len(configs)
    completed = [r for r in results if r.get("status") in {"completed", "skipped"}]
    failed = [r for r in results if r.get("status") == "failed"]
    if failed or len(completed) != selected_count:
        (root / GLOBAL_MANIFEST_NAME).unlink(missing_ok=True)
        summary = _summary(
            root=root,
            run_id=run_id,
            code_commit=full_code_commit,
            manifest_path=manifest_path,
            manifest_hash=manifest_hash,
            configs=configs,
            results=results,
            status="failed",
            max_workers=max_workers,
            duckdb_threads=duckdb_threads,
            duckdb_memory_limit_per_worker=duckdb_memory_limit_per_worker,
        )
        write_json_atomic(root / SUMMARY_NAME, summary)
        return summary

    global_manifest = _global_manifest(
        root=root,
        run_id=run_id,
        code_commit=full_code_commit,
        manifest_path=manifest_path,
        manifest_hash=manifest_hash,
        source_manifest=manifest,
        configs=configs,
        results=results,
        max_workers=max_workers,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit_per_worker=duckdb_memory_limit_per_worker,
    )
    write_json_atomic(root / GLOBAL_MANIFEST_NAME, global_manifest)
    summary = _summary(
        root=root,
        run_id=run_id,
        code_commit=full_code_commit,
        manifest_path=manifest_path,
        manifest_hash=manifest_hash,
        configs=configs,
        results=results,
        status="completed",
        max_workers=max_workers,
        duckdb_threads=duckdb_threads,
        duckdb_memory_limit_per_worker=duckdb_memory_limit_per_worker,
    )
    summary["global_manifest_path"] = str(root / GLOBAL_MANIFEST_NAME)
    summary["global_manifest_sha256"] = sha256_file(root / GLOBAL_MANIFEST_NAME)
    summary["downstream_gate_allowed"] = True
    summary["R0-T11_allowed_to_start"] = True
    write_json_atomic(root / SUMMARY_NAME, summary)
    return summary


def _run_one_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    config = dict(payload["config"])
    config_id = str(config["candidate_config_id"])
    root = Path(str(payload["output_dir"]))
    paths = _paths_for_config(root, config_id)
    started_at = _utc_now()
    try:
        if payload.get("resume") is True and _can_skip_config(
            paths=paths,
            config=config,
            input_manifest_hash=str(payload["authorized_input_manifest_hash"]),
            code_commit=str(payload["code_commit"]),
        ):
            done = _load_json(paths["done"])
            done["status"] = "skipped"
            return done
        _clear_partials(paths)
        paths["failed"].unlink(missing_ok=True)
        paths["config_dir"].mkdir(parents=True, exist_ok=True)
        _write_config_snapshot(paths["config"], config)
        _write_config_artifacts(
            paths=paths,
            config=config,
            manifest=dict(payload["authorized_input_manifest"]),
            run_id=str(payload["run_id"]),
            code_commit=str(payload["code_commit"]),
            duckdb_threads=int(payload["duckdb_threads"]),
            duckdb_memory_limit=str(payload["duckdb_memory_limit_per_worker"]),
        )
        result = _config_result(
            paths=paths,
            config=config,
            input_manifest_hash=str(payload["authorized_input_manifest_hash"]),
            run_id=str(payload["run_id"]),
            code_commit=str(payload["code_commit"]),
            started_at=started_at,
        )
        write_json_atomic(paths["done"], result)
        paths["log"].write_text("completed\n", encoding="utf-8")
        return result
    except Exception as exc:  # noqa: BLE001
        failed = {
            "candidate_config_id": config_id,
            "config_hash": config.get("config_hash"),
            "input_manifest_hash": payload.get("authorized_input_manifest_hash"),
            "started_at": started_at,
            "failed_at": _utc_now(),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback_log_path": str(paths["log"]),
            "retry_command": (
                "python -m src.r0.r0_t10_full_grid_materializer_cli "
                "--authorized-input-manifest "
                f"{payload['authorized_input_manifest_path']} "
                f"--output-dir {root} --run-id {payload['run_id']} "
                f"--code-commit {payload['code_commit']} --resume"
            ),
            "status": "failed",
        }
        paths["log"].write_text(traceback.format_exc(), encoding="utf-8")
        write_json_atomic(paths["failed"], failed)
        return failed


def _write_config_artifacts(
    *,
    paths: Mapping[str, Path],
    config: Mapping[str, Any],
    manifest: Mapping[str, Any],
    run_id: str,
    code_commit: str,
    duckdb_threads: int,
    duckdb_memory_limit: str,
) -> None:
    import duckdb  # noqa: PLC0415

    daily_artifact = manifest["input_artifacts"]["r0_t07_daily_confirmation"]
    interval_artifact = manifest["input_artifacts"]["r0_t07_confirmed_interval"]
    daily_source = Path(str(daily_artifact["path"]))
    interval_source = Path(str(interval_artifact["path"]))
    daily_source_hash = sha256_file(daily_source)
    interval_source_hash = sha256_file(interval_source)
    if daily_source_hash != daily_artifact["sha256"]:
        raise R0T10FullGridMaterializationError("r0_t07_daily_hash_mismatch")
    if interval_source_hash != interval_artifact["sha256"]:
        raise R0T10FullGridMaterializationError("r0_t07_interval_hash_mismatch")

    w = int(config["percentile_window_W"])
    q = float(config["low_quantile_q"])
    k = int(config["confirmation_days_K"])
    daily_partial = paths["daily_duckdb_partial"]
    interval_partial = paths["interval_duckdb_partial"]
    daily_parquet_partial = paths["daily_parquet_partial"]
    interval_parquet_partial = paths["interval_parquet_partial"]
    for path in (
        daily_partial,
        interval_partial,
        daily_parquet_partial,
        interval_parquet_partial,
    ):
        path.unlink(missing_ok=True)

    conn = duckdb.connect(str(daily_partial))
    try:
        _configure_duckdb(conn, duckdb_threads, duckdb_memory_limit)
        conn.execute(
            f"ATTACH {_sql_literal(str(daily_source))} AS source_db (READ_ONLY)"
        )
        conn.execute(
            f"""
            CREATE TABLE {DAILY_TABLE} AS
            SELECT
              security_id,
              trading_date,
              ? AS candidate_config_id,
              ? AS config_hash,
              ? AS run_id,
              ? AS code_commit,
              ? AS input_manifest_hash,
              percentile_window_W,
              q AS low_quantile_q,
              weak_delta,
              confirmation_k AS confirmation_days_K,
              'weak' AS dimension_rule,
              state_name,
              raw_state,
              raw_streak,
              raw_streak_start_date,
              confirmed_state,
              confirmation_start_date,
              confirmation_date,
              validity_status,
              reason_codes,
              confirmation_engine_version,
              ? AS artifact_engine_version
            FROM source_db.{quote_ident(str(daily_artifact["table"]))}
            WHERE percentile_window_W = ?
              AND abs(q - ?) < 0.0000000001
              AND confirmation_k = ?
              AND abs(weak_delta - 0.10) < 0.0000000001
            ORDER BY security_id, trading_date, state_name
            """,
            [
                config["candidate_config_id"],
                config["config_hash"],
                run_id,
                code_commit,
                manifest["run_id"],
                CANDIDATE_ARTIFACT_ENGINE_VERSION,
                w,
                q,
                k,
            ],
        )
        conn.execute(
            f"COPY {DAILY_TABLE} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(daily_parquet_partial)],
        )
    finally:
        conn.close()

    conn = duckdb.connect(str(interval_partial))
    try:
        _configure_duckdb(conn, duckdb_threads, duckdb_memory_limit)
        conn.execute(
            f"ATTACH {_sql_literal(str(interval_source))} AS source_db (READ_ONLY)"
        )
        conn.execute(
            f"""
            CREATE TABLE {INTERVAL_TABLE} AS
            SELECT
              security_id,
              state_name AS state_level,
              ? AS candidate_config_id,
              ? AS config_hash,
              ? AS run_id,
              ? AS code_commit,
              ? AS input_manifest_hash,
              interval_id AS confirmed_interval_id,
              percentile_window_W,
              q AS low_quantile_q,
              weak_delta,
              confirmation_k AS confirmation_days_K,
              'weak' AS dimension_rule,
              raw_start_date,
              confirmation_date AS confirmation_time,
              confirmed_start_date,
              interval_end_date,
              last_observed_date,
              raw_duration_observations AS raw_length,
              confirmed_duration_observations AS confirmed_length,
              is_open_interval,
              termination_reason AS termination_type,
              validity_status,
              reason_codes,
              confirmation_engine_version,
              ? AS artifact_engine_version
            FROM source_db.{quote_ident(str(interval_artifact["table"]))}
            WHERE percentile_window_W = ?
              AND abs(q - ?) < 0.0000000001
              AND confirmation_k = ?
              AND abs(weak_delta - 0.10) < 0.0000000001
            ORDER BY security_id, confirmed_interval_id
            """,
            [
                config["candidate_config_id"],
                config["config_hash"],
                run_id,
                code_commit,
                manifest["run_id"],
                CANDIDATE_ARTIFACT_ENGINE_VERSION,
                w,
                q,
                k,
            ],
        )
        conn.execute(
            f"COPY {INTERVAL_TABLE} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(interval_parquet_partial)],
        )
    finally:
        conn.close()

    daily_partial.replace(paths["daily_duckdb"])
    interval_partial.replace(paths["interval_duckdb"])
    daily_parquet_partial.replace(paths["daily_parquet"])
    interval_parquet_partial.replace(paths["interval_parquet"])


def _config_result(
    *,
    paths: Mapping[str, Path],
    config: Mapping[str, Any],
    input_manifest_hash: str,
    run_id: str,
    code_commit: str,
    started_at: str,
) -> dict[str, Any]:
    daily_count = _duckdb_count(paths["daily_duckdb"], DAILY_TABLE)
    interval_count = _duckdb_count(paths["interval_duckdb"], INTERVAL_TABLE)
    true_count = _duckdb_count_where(
        paths["daily_duckdb"], DAILY_TABLE, "confirmed_state = true"
    )
    raw_true_max = _max_raw_streak(paths["daily_duckdb"], DAILY_TABLE)
    finished_at = _utc_now()
    return {
        "candidate_config_id": config["candidate_config_id"],
        "config_hash": config["config_hash"],
        "input_manifest_hash": input_manifest_hash,
        "run_id": run_id,
        "code_commit": code_commit,
        "daily_artifact_duckdb_path": str(paths["daily_duckdb"]),
        "daily_artifact_parquet_path": str(paths["daily_parquet"]),
        "interval_artifact_duckdb_path": str(paths["interval_duckdb"]),
        "interval_artifact_parquet_path": str(paths["interval_parquet"]),
        "daily_row_count": daily_count,
        "interval_row_count": interval_count,
        "daily_confirmed_true_count": true_count,
        "max_raw_streak_by_state": raw_true_max,
        "zero_interval_reason": (
            "no_confirmed_segments_in_r0_t07_input"
            if interval_count == 0 and true_count == 0
            else None
        ),
        "daily_duckdb_hash": sha256_file(paths["daily_duckdb"]),
        "daily_parquet_hash": sha256_file(paths["daily_parquet"]),
        "interval_duckdb_hash": sha256_file(paths["interval_duckdb"]),
        "interval_parquet_hash": sha256_file(paths["interval_parquet"]),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": _duration_seconds(started_at, finished_at),
        "status": "completed",
    }


def _can_skip_config(
    *,
    paths: Mapping[str, Path],
    config: Mapping[str, Any],
    input_manifest_hash: str,
    code_commit: str,
) -> bool:
    if any(path.exists() for path in paths["partials"]):
        return False
    if paths["failed"].exists():
        return False
    required = (
        paths["done"],
        paths["config"],
        paths["daily_duckdb"],
        paths["daily_parquet"],
        paths["interval_duckdb"],
        paths["interval_parquet"],
    )
    if not all(path.exists() for path in required):
        return False
    try:
        done = _load_json(paths["done"])
    except (OSError, json.JSONDecodeError):
        return False
    return (
        done.get("config_hash") == config.get("config_hash")
        and done.get("input_manifest_hash") == input_manifest_hash
        and done.get("code_commit") == code_commit
        and done.get("daily_duckdb_hash") == sha256_file(paths["daily_duckdb"])
        and done.get("daily_parquet_hash") == sha256_file(paths["daily_parquet"])
        and done.get("interval_duckdb_hash") == sha256_file(paths["interval_duckdb"])
        and done.get("interval_parquet_hash") == sha256_file(paths["interval_parquet"])
    )


def _global_manifest(
    *,
    root: Path,
    run_id: str,
    code_commit: str,
    manifest_path: Path,
    manifest_hash: str,
    source_manifest: Mapping[str, Any],
    configs: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    max_workers: int,
    duckdb_threads: int,
    duckdb_memory_limit_per_worker: str,
) -> dict[str, Any]:
    result_by_id = {str(r["candidate_config_id"]): dict(r) for r in results}
    config_ids = [str(config["candidate_config_id"]) for config in configs]
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_type": "r0_t10_05_full_grid_manifest",
        "task_id": "R0-T10-05",
        "run_id": run_id,
        "code_commit": code_commit,
        "created_at": _utc_now(),
        "repository": "benzemaer/convergence-research",
        "authorized_input_manifest_path": str(manifest_path),
        "authorized_input_manifest_sha256": manifest_hash,
        "authorized_input_manifest_run_id": source_manifest["run_id"],
        "row_payload_embedded": False,
        "selected_config_count": len(config_ids),
        "selected_config_ids": config_ids,
        "baseline_config_id": BASELINE_CONFIG_ID,
        "candidate_configs": list(configs),
        "completed_config_count": len(results),
        "failed_config_count": 0,
        "skipped_config_count": sum(1 for r in results if r.get("status") == "skipped"),
        "daily_candidate_row_count_total": sum(
            int(r["daily_row_count"]) for r in results
        ),
        "confirmed_interval_row_count_total": sum(
            int(r["interval_row_count"]) for r in results
        ),
        "daily_confirmed_true_count_total": sum(
            int(r["daily_confirmed_true_count"]) for r in results
        ),
        "confirmed_interval_zero_config_count": sum(
            1 for r in results if int(r["interval_row_count"]) == 0
        ),
        "confirmed_interval_row_count_by_config": {
            cid: int(result_by_id[cid]["interval_row_count"]) for cid in config_ids
        },
        "daily_confirmed_true_count_by_config": {
            cid: int(result_by_id[cid]["daily_confirmed_true_count"])
            for cid in config_ids
        },
        "daily_row_count_by_config": {
            cid: int(result_by_id[cid]["daily_row_count"]) for cid in config_ids
        },
        "artifacts_by_config": {
            cid: {
                "status": result_by_id[cid]["status"],
                "config_snapshot_path": str(_paths_for_config(root, cid)["config"]),
                "DONE_path": str(_paths_for_config(root, cid)["done"]),
                "daily_duckdb_path": result_by_id[cid]["daily_artifact_duckdb_path"],
                "daily_duckdb_sha256": result_by_id[cid]["daily_duckdb_hash"],
                "daily_parquet_path": result_by_id[cid]["daily_artifact_parquet_path"],
                "daily_parquet_sha256": result_by_id[cid]["daily_parquet_hash"],
                "interval_duckdb_path": result_by_id[cid][
                    "interval_artifact_duckdb_path"
                ],
                "interval_duckdb_sha256": result_by_id[cid]["interval_duckdb_hash"],
                "interval_parquet_path": result_by_id[cid][
                    "interval_artifact_parquet_path"
                ],
                "interval_parquet_sha256": result_by_id[cid]["interval_parquet_hash"],
            }
            for cid in config_ids
        },
        "max_raw_streak_summary": {
            cid: result_by_id[cid]["max_raw_streak_by_state"] for cid in config_ids
        },
        "zero_interval_reason": (
            "no_confirmed_segments_in_r0_t07_input"
            if all(
                int(result_by_id[cid]["interval_row_count"]) == 0 for cid in config_ids
            )
            else None
        ),
        "concurrency_policy": {
            "max_workers": max_workers,
            "duckdb_threads": duckdb_threads,
            "duckdb_memory_limit_per_worker": duckdb_memory_limit_per_worker,
            "process_pool_context": "spawn",
            "artifact_backed_streaming_input": True,
            "monolithic_json_payload_mode": False,
            "parent_receives_row_payload": False,
        },
        "status": "completed",
        "downstream_gate_allowed": True,
        "R0-T11_allowed_to_start": True,
    }


def _summary(
    *,
    root: Path,
    run_id: str,
    code_commit: str,
    manifest_path: Path,
    manifest_hash: str,
    configs: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    status: str,
    max_workers: int,
    duckdb_threads: int,
    duckdb_memory_limit_per_worker: str,
) -> dict[str, Any]:
    completed = [r for r in results if r.get("status") in {"completed", "skipped"}]
    failed = [r for r in results if r.get("status") == "failed"]
    pending = len(configs) - len(completed) - len(failed)
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "task_id": "R0-T10-05",
        "run_id": run_id,
        "code_commit": code_commit,
        "updated_at": _utc_now(),
        "output_dir": str(root),
        "authorized_input_manifest_path": str(manifest_path),
        "authorized_input_manifest_sha256": manifest_hash,
        "selected_config_count": len(configs),
        "completed_config_count": len(
            [r for r in results if r.get("status") == "completed"]
        ),
        "skipped_config_count": len(
            [r for r in results if r.get("status") == "skipped"]
        ),
        "failed_config_count": len(failed),
        "pending_config_count": pending,
        "DONE_marker_count": len(list((root / "configs").glob("*/DONE.json"))),
        "FAILED_marker_count": len(list((root / "configs").glob("*/FAILED.json"))),
        "daily_candidate_row_count_total": sum(
            int(r.get("daily_row_count", 0)) for r in completed
        ),
        "confirmed_interval_row_count_total": sum(
            int(r.get("interval_row_count", 0)) for r in completed
        ),
        "daily_confirmed_true_count_total": sum(
            int(r.get("daily_confirmed_true_count", 0)) for r in completed
        ),
        "confirmed_interval_zero_config_count": sum(
            1 for r in completed if int(r.get("interval_row_count", 0)) == 0
        ),
        "max_workers": max_workers,
        "duckdb_threads": duckdb_threads,
        "duckdb_memory_limit_per_worker": duckdb_memory_limit_per_worker,
        "process_pool_context": "spawn",
        "row_payload_embedded": False,
        "partial_artifact_used_as_completed": False,
        "status": status,
        "downstream_gate_allowed": status == "completed",
        "R0-T11_allowed_to_start": status == "completed",
    }


def _write_progress_summary(
    root: Path,
    run_id: str,
    code_commit: str,
    manifest_path: Path,
    manifest_hash: str,
    configs: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
) -> None:
    summary = _summary(
        root=root,
        run_id=run_id,
        code_commit=code_commit,
        manifest_path=manifest_path,
        manifest_hash=manifest_hash,
        configs=configs,
        results=results,
        status="in_progress",
        max_workers=0,
        duckdb_threads=0,
        duckdb_memory_limit_per_worker="",
    )
    summary["retry_command"] = (
        "python -m src.r0.r0_t10_full_grid_materializer_cli "
        f"--authorized-input-manifest {manifest_path} --output-dir {root} "
        f"--run-id {run_id} --code-commit {code_commit} --resume"
    )
    write_json_atomic(root / SUMMARY_NAME, summary)


def _paths_for_config(root: Path, config_id: str) -> dict[str, Any]:
    config_dir = root / "configs" / config_id
    return {
        "config_dir": config_dir,
        "config": config_dir / "candidate_config_snapshot.json",
        "daily_duckdb": config_dir / "candidate_daily_state.duckdb",
        "daily_duckdb_partial": config_dir / "candidate_daily_state.partial.duckdb",
        "daily_parquet": config_dir / "candidate_daily_state.parquet",
        "daily_parquet_partial": config_dir / "candidate_daily_state.partial.parquet",
        "interval_duckdb": config_dir / "candidate_confirmed_interval.duckdb",
        "interval_duckdb_partial": config_dir
        / "candidate_confirmed_interval.partial.duckdb",
        "interval_parquet": config_dir / "candidate_confirmed_interval.parquet",
        "interval_parquet_partial": config_dir
        / "candidate_confirmed_interval.partial.parquet",
        "done": config_dir / "DONE.json",
        "failed": config_dir / "FAILED.json",
        "log": config_dir / "logs" / f"{config_id}.log",
        "partials": [
            config_dir / "candidate_daily_state.partial.duckdb",
            config_dir / "candidate_daily_state.partial.parquet",
            config_dir / "candidate_confirmed_interval.partial.duckdb",
            config_dir / "candidate_confirmed_interval.partial.parquet",
            config_dir / "DONE.partial.json",
            config_dir / "FAILED.partial.json",
        ],
    }


def _ensure_dirs(root: Path) -> None:
    (root / "configs").mkdir(parents=True, exist_ok=True)


def _clear_partials(paths: Mapping[str, Any]) -> None:
    for path in paths["partials"]:
        path.unlink(missing_ok=True)
    paths["log"].parent.mkdir(parents=True, exist_ok=True)


def _write_config_snapshot(path: Path, config: Mapping[str, Any]) -> None:
    write_json_atomic(
        path,
        {"schema_version": "r0_t10_05_candidate_config_snapshot.v1", **dict(config)},
    )


def _configure_duckdb(conn: Any, threads: int, memory_limit: str) -> None:
    conn.execute(f"PRAGMA threads={int(threads)}")
    conn.execute(f"PRAGMA memory_limit='{memory_limit}'")


def _duckdb_count(path: Path, table: str) -> int:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        return int(
            conn.execute(f"SELECT count(*) FROM {quote_ident(table)}").fetchone()[0]
        )
    finally:
        conn.close()


def _duckdb_count_where(path: Path, table: str, where: str) -> int:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        return int(
            conn.execute(
                f"SELECT count(*) FROM {quote_ident(table)} WHERE {where}"
            ).fetchone()[0]
        )
    finally:
        conn.close()


def _max_raw_streak(path: Path, table: str) -> dict[str, int]:
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(path), read_only=True)
    try:
        rows = conn.execute(
            f"""
            SELECT state_name, coalesce(max(raw_streak), 0)
            FROM {quote_ident(table)}
            GROUP BY state_name
            ORDER BY state_name
            """
        ).fetchall()
        return {str(state): int(value) for state, value in rows}
    finally:
        conn.close()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise R0T10FullGridMaterializationError(f"expected JSON object: {path}")
    return payload


def _duration_seconds(started_at: str, finished_at: str) -> float:
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    return (finish - start).total_seconds()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
