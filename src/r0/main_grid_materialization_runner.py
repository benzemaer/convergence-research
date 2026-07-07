from __future__ import annotations

import concurrent.futures
import csv
import gzip
import hashlib
import json
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.r0.candidate_artifact_engine import (
    BLOCKED,
    CANDIDATE_ARTIFACT_ENGINE_VERSION,
    LEGACY_V1_FIELD_NAMES,
    assemble_candidate_daily_rows,
    assemble_confirmed_interval_rows,
    assert_no_forbidden_candidate_outputs,
    build_candidate_configs,
    check_candidate_lineage,
)

MATERIALIZATION_RUNNER_VERSION = "r0_t09_main_grid_materialization_runner.v1"
MAX_WORKERS_DEFAULT = 6
MAX_WORKERS_UPPER_BOUND = 6
BASELINE_CANDIDATE_CONFIG_ID = "R0_W250_Q20_K3_WEAK_D010"
REQUIRED_MANIFEST_FIELDS = (
    "input_data_version",
    "input_schema_version",
    "input_content_hash",
    "input_row_counts",
    "source_lineage",
    "authorized_r0_input",
    "code_commit_or_data_build_id",
    "input_payload_path",
)
FORBIDDEN_MANIFEST_FIELDS = {
    "future_return",
    "future_volatility",
    "future_direction",
    "win_rate",
    "pnl",
    "alpha",
    "backtest",
    "portfolio",
    "trade_signal",
    "buy_signal",
    "sell_signal",
}
CONTRACT_IDS = (
    "R0_T04_RAW_METRIC_ENGINE_CONTRACT_V1",
    "R0_T05_STRICT_PAST_PERCENTILE_SCORE_CONTRACT_V1",
    "R0_T06_WEAK_DIMENSION_NESTED_STATE_CONTRACT_V1",
    "R0_T07_CONFIRMATION_STREAK_INTERVAL_CONTRACT_V1",
    "R0_T08_MAIN_GRID_CANDIDATE_ARTIFACT_CONTRACT_V1",
    "R0_T09_MAIN_GRID_MATERIALIZATION_CONTRACT_V1",
)
SCHEMA_VERSIONS = {
    "materialization_manifest": "r0_t09_materialization_manifest.v1",
    "done_marker": "r0_t09_done_marker.v1",
    "failed_marker": "r0_t09_failed_marker.v1",
    "candidate_daily_state": "r0_t08_candidate_daily_state.v1",
    "confirmed_interval": "r0_t08_confirmed_interval.v1",
}


class R0T09MaterializationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthorizedInput:
    manifest_path: Path
    manifest: dict[str, Any]
    manifest_hash: str
    payload_path: Path
    payload: dict[str, Any]


def run_main_grid_materialization(
    *,
    input_manifest: str | Path,
    output_dir: str | Path,
    max_workers: int = MAX_WORKERS_DEFAULT,
    resume: bool = False,
    only_config: str | None = None,
    dry_run: bool = False,
    run_id: str | None = None,
    code_commit: str | None = None,
    repository: str = "benzemaer/convergence-research",
) -> dict[str, Any]:
    if max_workers < 1 or max_workers > MAX_WORKERS_UPPER_BOUND:
        raise R0T09MaterializationError("max_workers must be between 1 and 6")

    authorized = load_authorized_input(input_manifest)
    configs = [config.as_dict() for config in build_candidate_configs()]
    if only_config is not None and only_config not in {
        str(config["candidate_config_id"]) for config in configs
    }:
        raise R0T09MaterializationError(f"unknown candidate_config_id: {only_config}")
    selected_configs = [
        config
        for config in configs
        if only_config is None or config["candidate_config_id"] == only_config
    ]
    if run_id is None:
        run_id = "R0-T09-" + _utc_now().replace("-", "").replace(":", "")
    if code_commit is None:
        code_commit = str(
            authorized.manifest.get("code_commit_or_data_build_id", "unknown")
        )

    if dry_run:
        return {
            "task_id": "R0-T09",
            "status": "dry_run",
            "run_id": run_id,
            "candidate_config_count": len(configs),
            "selected_config_count": len(selected_configs),
            "max_workers": max_workers,
            "resume": resume,
            "artifacts_written": False,
            "tasks": [config["candidate_config_id"] for config in selected_configs],
        }

    root = Path(output_dir)
    _ensure_output_dirs(root)
    task_payloads = [
        {
            "config": config,
            "output_dir": str(root),
            "input_manifest_path": str(authorized.manifest_path),
            "input_manifest_hash": authorized.manifest_hash,
            "input_manifest": authorized.manifest,
            "input_payload": authorized.payload,
            "run_id": run_id,
            "code_commit": code_commit,
            "repository": repository,
            "resume": resume,
        }
        for config in selected_configs
    ]

    results: list[dict[str, Any]] = []
    if max_workers == 1 or len(task_payloads) <= 1:
        for payload in task_payloads:
            results.append(_run_one_config(payload))
            _write_global_manifest(
                root=root,
                run_id=run_id,
                code_commit=code_commit,
                repository=repository,
                authorized=authorized,
                configs=configs,
                results=results,
                selected_config_ids=[
                    str(config["candidate_config_id"]) for config in selected_configs
                ],
                finished=False,
            )
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(_run_one_config, payload) for payload in task_payloads
            ]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
                _write_global_manifest(
                    root=root,
                    run_id=run_id,
                    code_commit=code_commit,
                    repository=repository,
                    authorized=authorized,
                    configs=configs,
                    results=results,
                    selected_config_ids=[
                        str(config["candidate_config_id"])
                        for config in selected_configs
                    ],
                    finished=False,
                )

    return _write_global_manifest(
        root=root,
        run_id=run_id,
        code_commit=code_commit,
        repository=repository,
        authorized=authorized,
        configs=configs,
        results=results,
        selected_config_ids=[
            str(config["candidate_config_id"]) for config in selected_configs
        ],
        finished=True,
    )


def load_authorized_input(input_manifest: str | Path) -> AuthorizedInput:
    manifest_path = Path(input_manifest).resolve()
    manifest = _load_json(manifest_path)
    missing = [field for field in REQUIRED_MANIFEST_FIELDS if field not in manifest]
    if missing:
        raise R0T09MaterializationError(f"input manifest missing fields: {missing}")
    if manifest.get("authorized_r0_input") is not True:
        raise R0T09MaterializationError("input manifest is not authorized for R0")
    if _contains_forbidden_key(manifest):
        raise R0T09MaterializationError(
            "input manifest contains forbidden output fields"
        )
    lineage_guard = check_candidate_lineage(manifest.get("source_lineage", ()))
    if lineage_guard.validity_status == BLOCKED:
        raise R0T09MaterializationError("input manifest lineage is blocked")

    payload_path = Path(str(manifest["input_payload_path"]))
    if not payload_path.is_absolute():
        payload_path = manifest_path.parent / payload_path
    payload_path = payload_path.resolve()
    _guard_payload_path(payload_path)
    payload_hash = sha256_file(payload_path)
    if payload_hash != manifest["input_content_hash"]:
        raise R0T09MaterializationError("input payload hash mismatch")
    payload = _load_json(payload_path)
    forbidden_guard = assert_no_forbidden_candidate_outputs(payload)
    if forbidden_guard.validity_status == BLOCKED:
        raise R0T09MaterializationError("input payload contains forbidden fields")
    return AuthorizedInput(
        manifest_path=manifest_path,
        manifest=manifest,
        manifest_hash=sha256_file(manifest_path),
        payload_path=payload_path,
        payload=payload,
    )


def should_skip_config(
    *,
    config: Mapping[str, Any],
    output_dir: str | Path,
    input_manifest_hash: str,
) -> bool:
    paths = _paths_for_config(Path(output_dir), str(config["candidate_config_id"]))
    if any(path.exists() for path in paths["partials"]):
        return False
    if paths["failed"].exists() and not paths["done"].exists():
        return False
    required = (
        paths["done"],
        paths["daily_duckdb"],
        paths["daily_csv"],
        paths["interval_duckdb"],
        paths["interval_csv"],
    )
    if not all(path.exists() for path in required):
        return False
    try:
        done = _load_json(paths["done"])
    except (OSError, json.JSONDecodeError):
        return False
    if done.get("config_hash") != config.get("config_hash"):
        return False
    if done.get("input_manifest_hash") != input_manifest_hash:
        return False
    return done.get("daily_content_hash") == sha256_file(
        paths["daily_csv"]
    ) and done.get("interval_content_hash") == sha256_file(paths["interval_csv"])


def _run_one_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    config = dict(payload["config"])
    root = Path(str(payload["output_dir"]))
    config_id = str(config["candidate_config_id"])
    paths = _paths_for_config(root, config_id)
    started_at = _utc_now()
    if payload.get("resume") is True and should_skip_config(
        config=config,
        output_dir=root,
        input_manifest_hash=str(payload["input_manifest_hash"]),
    ):
        done = _load_json(paths["done"])
        done["status"] = "skipped"
        return done

    log_path = paths["log"]
    try:
        for path in paths["partials"]:
            path.unlink(missing_ok=True)
        input_payload = dict(payload["input_payload"])
        source_lineage = tuple(payload["input_manifest"].get("source_lineage", ()))
        daily_all = assemble_candidate_daily_rows(
            raw_metric_results=input_payload.get("raw_metric_results", ()),
            indicator_score_results=input_payload.get("indicator_score_results", ()),
            dimension_score_results=input_payload.get("dimension_score_results", ()),
            nested_daily_state_results=input_payload.get(
                "nested_daily_state_results", ()
            ),
            daily_confirmation_results=input_payload.get(
                "daily_confirmation_results", ()
            ),
            run_id=str(payload["run_id"]),
            code_commit=str(payload["code_commit"]),
            input_data_version=str(payload["input_manifest"]["input_data_version"]),
            source_lineage=source_lineage,
        )
        interval_all = assemble_confirmed_interval_rows(
            confirmed_interval_results=input_payload.get(
                "confirmed_interval_results", ()
            ),
            run_id=str(payload["run_id"]),
            code_commit=str(payload["code_commit"]),
            input_data_version=str(payload["input_manifest"]["input_data_version"]),
            source_lineage=source_lineage,
        )
        daily_rows = [
            row for row in daily_all if row["candidate_config_id"] == config_id
        ]
        interval_rows = [
            row for row in interval_all if row["candidate_config_id"] == config_id
        ]
        guard = assert_no_forbidden_candidate_outputs(
            {"daily_rows": daily_rows, "interval_rows": interval_rows}
        )
        if guard.validity_status == BLOCKED:
            raise R0T09MaterializationError("forbidden output guard blocked config")
        _write_json_atomic(paths["config"], config)
        _write_csv_gz_atomic(paths["daily_csv"], daily_rows)
        _write_csv_gz_atomic(paths["interval_csv"], interval_rows)
        _write_duckdb_atomic(paths["daily_duckdb"], "candidate_daily_rows", daily_rows)
        _write_duckdb_atomic(
            paths["interval_duckdb"], "confirmed_interval_rows", interval_rows
        )
        finished_at = _utc_now()
        done = {
            "candidate_config_id": config_id,
            "config_hash": config["config_hash"],
            "input_manifest_hash": payload["input_manifest_hash"],
            "input_data_version": payload["input_manifest"]["input_data_version"],
            "daily_artifact_duckdb_path": str(paths["daily_duckdb"]),
            "daily_artifact_csv_path": str(paths["daily_csv"]),
            "interval_artifact_duckdb_path": str(paths["interval_duckdb"]),
            "interval_artifact_csv_path": str(paths["interval_csv"]),
            "daily_row_count": len(daily_rows),
            "interval_row_count": len(interval_rows),
            "daily_content_hash": sha256_file(paths["daily_csv"]),
            "interval_content_hash": sha256_file(paths["interval_csv"]),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": _duration_seconds(started_at, finished_at),
            "code_commit": payload["code_commit"],
            "engine_versions": _engine_versions(),
            "status": "completed",
        }
        _write_json_atomic(paths["done"], done)
        paths["failed"].unlink(missing_ok=True)
        log_path.write_text("completed\n", encoding="utf-8")
        return done
    except Exception as exc:  # noqa: BLE001 - FAILED marker must capture all failures.
        failed_at = _utc_now()
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        failed = {
            "candidate_config_id": config_id,
            "config_hash": config.get("config_hash"),
            "input_manifest_hash": payload["input_manifest_hash"],
            "started_at": started_at,
            "failed_at": failed_at,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback_log_path": str(log_path),
            "retry_command": (
                "python scripts/r0/run_r0_t09_main_grid.py "
                f"--input-manifest {payload['input_manifest_path']} "
                f"--output-dir {root} --only-config {config_id} --resume"
            ),
            "status": "failed",
        }
        _write_json_atomic(paths["failed"], failed)
        return failed


def _write_global_manifest(
    *,
    root: Path,
    run_id: str,
    code_commit: str,
    repository: str,
    authorized: AuthorizedInput,
    configs: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    selected_config_ids: Sequence[str],
    finished: bool,
) -> dict[str, Any]:
    result_by_id = {
        str(result["candidate_config_id"]): dict(result) for result in results
    }
    completed = {
        config_id
        for config_id, result in result_by_id.items()
        if result.get("status") == "completed"
    }
    skipped = {
        config_id
        for config_id, result in result_by_id.items()
        if result.get("status") == "skipped"
    }
    failed = {
        config_id
        for config_id, result in result_by_id.items()
        if result.get("status") == "failed"
    }
    selected = set(selected_config_ids)
    pending = selected - completed - skipped - failed
    status = "completed" if not failed and not pending else "incomplete"
    if not finished and pending:
        status = "incomplete"

    row_count_by_config = {
        str(config["candidate_config_id"]): int(
            result_by_id.get(str(config["candidate_config_id"]), {}).get(
                "daily_row_count", 0
            )
        )
        for config in configs
    }
    interval_count_by_config = {
        str(config["candidate_config_id"]): int(
            result_by_id.get(str(config["candidate_config_id"]), {}).get(
                "interval_row_count", 0
            )
        )
        for config in configs
    }
    daily_hashes = {
        config_id: result["daily_content_hash"]
        for config_id, result in result_by_id.items()
        if result.get("status") in {"completed", "skipped"}
    }
    interval_hashes = {
        config_id: result["interval_content_hash"]
        for config_id, result in result_by_id.items()
        if result.get("status") in {"completed", "skipped"}
    }
    manifest = {
        "manifest_id": _hash_object(
            {
                "task_id": "R0-T09",
                "run_id": run_id,
                "input_manifest_hash": authorized.manifest_hash,
                "daily_hashes": daily_hashes,
                "interval_hashes": interval_hashes,
            }
        ),
        "task_id": "R0-T09",
        "run_id": run_id,
        "status": status,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "finished_at": _utc_now() if finished else None,
        "code_commit": code_commit,
        "repository": repository,
        "input_manifest_path": str(authorized.manifest_path),
        "input_manifest_hash": authorized.manifest_hash,
        "input_data_version": authorized.manifest["input_data_version"],
        "candidate_config_count": len(configs),
        "completed_config_count": len(completed),
        "failed_config_count": len(failed),
        "skipped_config_count": len(skipped),
        "pending_config_count": len(pending),
        "baseline_candidate_config_id": BASELINE_CANDIDATE_CONFIG_ID,
        "candidate_configs": list(configs),
        "per_config_status": {
            config_id: result_by_id.get(config_id, {"status": "pending"})
            for config_id in sorted(selected)
        },
        "daily_artifacts": _artifact_paths(
            root, configs, "daily_states", "daily_states"
        ),
        "interval_artifacts": _artifact_paths(
            root, configs, "confirmed_intervals", "confirmed_intervals"
        ),
        "status_files": {
            str(config["candidate_config_id"]): str(
                root / "status" / f"{config['candidate_config_id']}.DONE.json"
            )
            for config in configs
        },
        "logs": {
            str(config["candidate_config_id"]): str(
                root / "logs" / f"{config['candidate_config_id']}.log"
            )
            for config in configs
        },
        "row_count_by_config": row_count_by_config,
        "interval_count_by_config": interval_count_by_config,
        "daily_content_hash_by_config": daily_hashes,
        "interval_content_hash_by_config": interval_hashes,
        "global_daily_content_hash": _hash_object(daily_hashes),
        "global_interval_content_hash": _hash_object(interval_hashes),
        "engine_versions": _engine_versions(),
        "contract_ids": list(CONTRACT_IDS),
        "schema_versions": dict(SCHEMA_VERSIONS),
        "lineage_guard": check_candidate_lineage(
            authorized.manifest.get("source_lineage", ())
        ).as_dict(),
        "forbidden_output_guard": assert_no_forbidden_candidate_outputs(
            {
                "per_config_status": list(result_by_id.values()),
                "candidate_configs": list(configs),
            }
        ).as_dict(),
    }
    if manifest["forbidden_output_guard"]["validity_status"] == BLOCKED:
        manifest["status"] = "blocked"
    _write_json_atomic(root / "manifest.json", manifest)
    return manifest


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_csv_gz_atomic(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    partial = path.with_name(path.name.replace(".csv.gz", ".partial.csv.gz"))
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with gzip.open(partial, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
    partial.replace(path)


def _write_duckdb_atomic(
    path: Path, table_name: str, rows: Sequence[Mapping[str, Any]]
) -> None:
    partial = path.with_name(path.name.replace(".duckdb", ".partial.duckdb"))
    partial.unlink(missing_ok=True)
    import duckdb  # noqa: PLC0415

    conn = duckdb.connect(str(partial))
    try:
        conn.execute(f"CREATE TABLE {table_name} (row_json TEXT)")
        conn.executemany(
            f"INSERT INTO {table_name} VALUES (?)",
            [(_canonical_json(row),) for row in rows],
        )
    finally:
        conn.close()
    partial.replace(path)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    partial = path.with_name(path.name.replace(".json", ".partial.json"))
    partial.write_text(_canonical_json(payload) + "\n", encoding="utf-8")
    partial.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise R0T09MaterializationError(f"expected object JSON: {path}")
    return payload


def _paths_for_config(root: Path, config_id: str) -> dict[str, Any]:
    daily_stem = f"{config_id}.daily_states"
    interval_stem = f"{config_id}.confirmed_intervals"
    partials = [
        root / "daily_states" / f"{daily_stem}.partial.duckdb",
        root / "daily_states" / f"{daily_stem}.partial.csv.gz",
        root / "confirmed_intervals" / f"{interval_stem}.partial.duckdb",
        root / "confirmed_intervals" / f"{interval_stem}.partial.csv.gz",
        root / "configs" / f"{config_id}.config.partial.json",
        root / "status" / f"{config_id}.DONE.partial.json",
        root / "status" / f"{config_id}.FAILED.partial.json",
    ]
    return {
        "config": root / "configs" / f"{config_id}.config.json",
        "daily_duckdb": root / "daily_states" / f"{daily_stem}.duckdb",
        "daily_csv": root / "daily_states" / f"{daily_stem}.csv.gz",
        "interval_duckdb": root / "confirmed_intervals" / f"{interval_stem}.duckdb",
        "interval_csv": root / "confirmed_intervals" / f"{interval_stem}.csv.gz",
        "done": root / "status" / f"{config_id}.DONE.json",
        "failed": root / "status" / f"{config_id}.FAILED.json",
        "log": root / "logs" / f"{config_id}.log",
        "partials": partials,
    }


def _ensure_output_dirs(root: Path) -> None:
    for name in ("configs", "daily_states", "confirmed_intervals", "status", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)


def _guard_payload_path(path: Path) -> None:
    normalized = str(path).replace("\\", "/")
    forbidden = ("data/raw", "data/external", "MarketDB", ".day")
    if any(pattern in normalized for pattern in forbidden):
        raise R0T09MaterializationError(f"forbidden input payload path: {path}")


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if (
                str(key) in FORBIDDEN_MANIFEST_FIELDS
                or str(key) in LEGACY_V1_FIELD_NAMES
            ):
                return True
            if _contains_forbidden_key(nested):
                return True
    elif isinstance(value, list | tuple):
        for nested in value:
            if isinstance(nested, str) and nested in LEGACY_V1_FIELD_NAMES:
                return True
            if _contains_forbidden_key(nested):
                return True
    return False


def _artifact_paths(
    root: Path, configs: Sequence[Mapping[str, Any]], directory: str, suffix: str
) -> dict[str, dict[str, str]]:
    return {
        str(config["candidate_config_id"]): {
            "duckdb": str(
                root / directory / f"{config['candidate_config_id']}.{suffix}.duckdb"
            ),
            "csv": str(
                root / directory / f"{config['candidate_config_id']}.{suffix}.csv.gz"
            ),
        }
        for config in configs
    }


def _engine_versions() -> dict[str, str]:
    return {
        "r0_t08_candidate_artifact_engine": CANDIDATE_ARTIFACT_ENGINE_VERSION,
        "r0_t09_materialization_runner": MATERIALIZATION_RUNNER_VERSION,
    }


def _duration_seconds(started_at: str, finished_at: str) -> float:
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    return (finish - start).total_seconds()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _hash_object(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _csv_value(value: Any) -> Any:
    if isinstance(value, dict | list | tuple):
        return _canonical_json(value)
    return value
