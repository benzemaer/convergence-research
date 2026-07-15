"""Thin CLI for the future EXP-C01 formal run.

This entrypoint is intentionally fail-closed.  It requires an explicit reviewed
implementation SHA and ``--allow-formal-run``; implementation review never calls
this script against the repository's local-only DuckDB files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sidecar.exp_c01_c_layer_ablation import (  # noqa: E402
    C1_ID,
    C2_ID,
    CSV_FIELDS,
    OUTPUT_FILES,
    TASK_ID,
    VARIANT_IDS,
    WEAK_DELTA,
    Q,
    W,
    build_profiles,
)
from src.sidecar.exp_c01_c_layer_ablation_validator import (  # noqa: E402
    EXPECTED_VARIANT_RULES,
    _canonical_optional_date_text,
    build_input_availability_summary,
    extract_source_artifact_declaration,
    read_csv_artifact,
    recompute_readback_metrics,
    scan_anomalies,
    validate_indicator_score_rows,
    validate_output_directory,
    validate_static_config,
)

DEFAULT_CONFIG = (
    ROOT / "configs" / "sidecar" / "exp_c01_c_layer_indicator_ablation_w120.v1.json"
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_formal(args)
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {"task_id": TASK_ID, "status": "failed", "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


def run_formal(args: argparse.Namespace) -> dict[str, Any]:
    if not args.allow_formal_run:
        raise RuntimeError("formal_run_not_allowed_without_--allow-formal-run")
    reviewed_sha = str(args.reviewed_implementation_sha or "")
    if not SHA_PATTERN.fullmatch(reviewed_sha):
        raise RuntimeError(
            "reviewed_implementation_sha must be an exact 40-character SHA"
        )

    config_path = Path(args.config).resolve()
    config = _load_json(config_path)
    _assert_config_scope(config)
    config_errors = validate_static_config(config)
    if config_errors:
        raise RuntimeError(
            "static config validation failed: " + ", ".join(config_errors)
        )
    current_sha = _current_git_sha(config_path.parent)
    if current_sha != reviewed_sha:
        raise RuntimeError(
            "current HEAD does not equal reviewed_implementation_sha; "
            f"current={current_sha} reviewed={reviewed_sha}"
        )
    formal_source_bindings = build_formal_source_bindings(current_sha, config_path)

    input_root_value = args.input_root or os.environ.get(
        "CONVERGENCE_RESEARCH_INPUT_ROOT"
    )
    if not input_root_value:
        raise RuntimeError(
            "--input-root or CONVERGENCE_RESEARCH_INPUT_ROOT is required"
        )
    input_root = Path(input_root_value).resolve()
    if not input_root.is_dir():
        raise RuntimeError(f"input root is not a directory: {input_root}")
    if args.input_manifest is None:
        raise RuntimeError("--input-manifest is required")
    input_manifest_path = Path(args.input_manifest).resolve()
    if not input_manifest_path.is_file():
        raise RuntimeError(f"input manifest is not a file: {input_manifest_path}")
    _validate_canonical_text_contract(
        input_manifest_path.read_bytes(), str(input_manifest_path)
    )

    run_id = str(args.run_id)
    if not run_id or Path(run_id).name != run_id:
        raise RuntimeError("run-id must be a non-empty single path component")
    output_root = Path(args.output_root).resolve()
    if output_root.name != run_id:
        raise RuntimeError("output-root basename must equal run-id")
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"output directory must be new and empty: {output_root}")

    started_at = _utc_now()
    paths, input_manifest = resolve_input_paths(
        input_root, config, manifest_path=input_manifest_path
    )
    source_declarations = {
        name: extract_source_artifact_declaration(
            input_manifest, name, config["input_contract"]["artifacts"][name]
        )
        for name in config["input_contract"]["artifacts"]
    }
    if any(value is None for value in source_declarations.values()):
        missing = [name for name, value in source_declarations.items() if value is None]
        raise RuntimeError(f"source manifest declarations missing: {missing}")

    artifact_loaders = {
        "indicator_score": load_indicator_rows,
        "dimension_score": load_dimension_score_rows,
        "dimension_state": load_dimension_state_rows,
    }
    loaded_rows: dict[str, list[dict[str, Any]]] = {}
    input_metadata: dict[str, dict[str, Any]] = {}
    for name, loader in artifact_loaders.items():
        artifact = config["input_contract"]["artifacts"][name]
        declaration = source_declarations[name]
        if declaration is None:
            raise RuntimeError(f"source manifest declaration missing: {name}")
        metadata = inspect_input_artifact(paths[name], artifact, declaration)
        rows = loader(paths[name], config)
        loaded_rows[name] = rows
        input_metadata[name] = {
            "filename": str(artifact["filename"]),
            "path": str(paths[name]),
            "sha256": sha256_file(paths[name]),
            "row_count": metadata["source_full_row_count"],
            "source_full_row_count": metadata["source_full_row_count"],
            "query_filtered_row_count": len(rows),
            "actual_table": metadata["actual_table"],
            "required_columns": list(artifact["required_columns"]),
            "actual_columns": metadata["actual_columns"],
            "actual_security_count": metadata["actual_security_count"],
            "actual_date_min": metadata["actual_date_min"],
            "actual_date_max": metadata["actual_date_max"],
            "source_manifest_declared_path": declaration.get("path"),
            "source_manifest_declared_sha256": declaration.get("sha256"),
            "source_manifest_declared_row_count": declaration.get("row_count"),
            "source_manifest_declared_table": declaration.get("table"),
            "source_manifest_declared_security_count": declaration.get(
                "security_count"
            ),
            "source_manifest_declared_date_min": declaration.get("date_min"),
            "source_manifest_declared_date_max": declaration.get("date_max"),
        }
    indicator_rows = loaded_rows["indicator_score"]
    dimension_rows = loaded_rows["dimension_score"]
    state_rows = loaded_rows["dimension_state"]
    input_validation_errors = validate_indicator_score_rows(indicator_rows)
    if input_validation_errors:
        raise RuntimeError(
            "indicator score input validation failed: "
            + ", ".join(input_validation_errors[:20])
        )
    input_availability = build_input_availability_summary(indicator_rows)
    profiles = build_profiles(
        indicator_rows,
        dimension_score_rows=dimension_rows,
        dimension_state_rows=state_rows,
    )
    output_root.mkdir(parents=True, exist_ok=False)
    for key in CSV_FIELDS:
        write_csv(output_root / OUTPUT_FILES[key], CSV_FIELDS[key], profiles[key])

    # Read the just-written artifacts back before producing analysis.  This keeps
    # every downstream review calculation tied to the actual six CSV files.
    actual_artifacts = {
        key: read_csv_artifact(output_root / OUTPUT_FILES[key]) for key in CSV_FIELDS
    }
    write_text(
        output_root / OUTPUT_FILES["result_analysis"], "# preliminary analysis\n"
    )
    manifest = build_manifest(
        output_root=output_root,
        run_id=run_id,
        config_path=config_path,
        config=config,
        input_manifest=input_manifest,
        input_manifest_path=input_manifest_path,
        input_root=input_root,
        input_metadata=input_metadata,
        input_availability=input_availability,
        reconciliation=profiles["baseline_reconciliation"],
        implementation_sha=reviewed_sha,
        formal_source_bindings=formal_source_bindings,
        started_at=started_at,
        finished_at=_utc_now(),
    )
    write_json(output_root / OUTPUT_FILES["manifest"], manifest)

    preliminary_validation = validate_output_directory(
        output_root,
        config=config,
        require_governance_files=False,
    )
    preliminary_anomaly = scan_anomalies(actual_artifacts, manifest)
    preliminary_recomputation = recompute_readback_metrics(actual_artifacts)
    write_text(
        output_root / OUTPUT_FILES["result_analysis"],
        build_result_analysis(
            actual_artifacts,
            manifest=manifest,
            validation=preliminary_validation,
            anomaly_scan=preliminary_anomaly,
            recomputation=preliminary_recomputation,
            reconciliation=profiles["baseline_reconciliation"],
        ),
    )
    manifest = build_manifest(
        output_root=output_root,
        run_id=run_id,
        config_path=config_path,
        config=config,
        input_manifest=input_manifest,
        input_manifest_path=input_manifest_path,
        input_root=input_root,
        input_metadata=input_metadata,
        input_availability=input_availability,
        reconciliation=profiles["baseline_reconciliation"],
        implementation_sha=reviewed_sha,
        formal_source_bindings=formal_source_bindings,
        started_at=started_at,
        finished_at=_utc_now(),
    )
    write_json(output_root / OUTPUT_FILES["manifest"], manifest)
    final_pre_governance_validation = validate_output_directory(
        output_root,
        config=config,
        require_governance_files=False,
    )
    final_anomaly = scan_anomalies(actual_artifacts, manifest)
    final_recomputation = recompute_readback_metrics(actual_artifacts)
    # The analysis is rebuilt from the final persisted CSVs, final manifest
    # binding, and the final pre-governance validation state.
    write_text(
        output_root / OUTPUT_FILES["result_analysis"],
        build_result_analysis(
            actual_artifacts,
            manifest=manifest,
            validation=final_pre_governance_validation,
            anomaly_scan=final_anomaly,
            recomputation=final_recomputation,
            reconciliation=profiles["baseline_reconciliation"],
        ),
    )
    manifest = build_manifest(
        output_root=output_root,
        run_id=run_id,
        config_path=config_path,
        config=config,
        input_manifest=input_manifest,
        input_manifest_path=input_manifest_path,
        input_root=input_root,
        input_metadata=input_metadata,
        input_availability=input_availability,
        reconciliation=profiles["baseline_reconciliation"],
        implementation_sha=reviewed_sha,
        formal_source_bindings=formal_source_bindings,
        started_at=started_at,
        finished_at=_utc_now(),
    )
    write_json(output_root / OUTPUT_FILES["manifest"], manifest)
    final_pre_governance_validation = validate_output_directory(
        output_root,
        config=config,
        require_governance_files=False,
    )
    final_anomaly = scan_anomalies(actual_artifacts, manifest)
    final_recomputation = recompute_readback_metrics(actual_artifacts)
    write_json(output_root / OUTPUT_FILES["anomaly_scan"], final_anomaly)
    write_json(
        output_root / OUTPUT_FILES["validator_result"], final_pre_governance_validation
    )
    final_validation = validate_output_directory(
        output_root,
        config=config,
        require_governance_files=True,
    )
    write_json(output_root / OUTPUT_FILES["validator_result"], final_validation)
    post_write_validation = validate_output_directory(
        output_root,
        config=config,
        require_governance_files=True,
    )
    if post_write_validation != final_validation:
        final_validation = post_write_validation
        write_json(output_root / OUTPUT_FILES["validator_result"], final_validation)
    reconciliation_ok = profiles["baseline_reconciliation"].get("mismatch_total") == 0
    status = (
        "passed"
        if final_validation["status"] == "passed"
        and final_anomaly["status"] == "passed"
        and final_recomputation["status"] == "passed"
        and reconciliation_ok
        else "failed"
    )
    return {
        "task_id": TASK_ID,
        "run_id": run_id,
        "status": status,
        "output_root": str(output_root),
        "formal_run_executed": True,
        "anomaly_status": final_anomaly["status"],
        "reconciliation_status": profiles["baseline_reconciliation"]["status"],
        "independent_recomputation_status": final_recomputation["status"],
        "errors": final_validation["errors"],
    }


def resolve_input_paths(
    input_root: Path,
    config: Mapping[str, Any],
    *,
    manifest_path: Path | None = None,
) -> tuple[dict[str, Path], dict[str, Any]]:
    if manifest_path is None:
        raise RuntimeError("exact --input-manifest path is required")
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise RuntimeError(f"input manifest is not a file: {manifest_path}")
    manifest = _load_json(manifest_path)
    paths: dict[str, Path] = {}
    for name, artifact in config["input_contract"]["artifacts"].items():
        declaration = extract_source_artifact_declaration(manifest, name, artifact)
        if declaration is None or not declaration.get("path"):
            raise RuntimeError(f"source manifest does not declare path for {name}")
        declared_path = Path(str(declaration["path"]))
        candidate = (
            declared_path
            if declared_path.is_absolute()
            else manifest_path.parent / declared_path
        )
        if not candidate.is_file():
            path_policy = str(declaration.get("path_policy", ""))
            local_relocation = declaration.get("local_only_relocation") is True
            is_basename = declared_path.name == str(declaration["path"])
            if not (local_relocation or path_policy == "basename_local_only"):
                raise RuntimeError(
                    f"declared {name} path is missing and relocation is not "
                    f"authorized: {candidate}"
                )
            if not is_basename:
                raise RuntimeError(
                    f"local-only relocation for {name} requires a basename declaration"
                )
            candidate = input_root / declared_path.name
            if not candidate.is_file():
                raise RuntimeError(f"relocated {name} input is missing: {candidate}")
        if declaration.get("sha256"):
            actual_hash = sha256_file(candidate)
            if actual_hash != declaration["sha256"]:
                raise RuntimeError(
                    f"source manifest hash mismatch for {name}: "
                    f"declared={declaration['sha256']} actual={actual_hash}"
                )
        paths[name] = candidate.resolve()
    return paths, manifest


def load_indicator_rows(path: Path, config: Mapping[str, Any]) -> list[dict[str, Any]]:
    artifact = config["input_contract"]["artifacts"]["indicator_score"]
    columns = (
        "security_id",
        "trading_date",
        "percentile_window_W",
        "indicator_id",
        "score",
        "eligible",
        "validity_status",
    )
    rows = _query_duckdb(
        path,
        artifact["table"],
        columns,
        "percentile_window_W = ? AND indicator_id IN (?, ?)",
        [W, C1_ID, C2_ID],
    )
    return rows


def load_dimension_score_rows(
    path: Path, config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    artifact = config["input_contract"]["artifacts"]["dimension_score"]
    columns = (
        "security_id",
        "trading_date",
        "percentile_window_W",
        "dimension",
        "score_dimension",
        "score_dimension_min",
        "eligible_dimension",
        "validity_status",
    )
    return _query_duckdb(
        path,
        artifact["table"],
        columns,
        "percentile_window_W = ? AND dimension = ?",
        [W, "C"],
    )


def load_dimension_state_rows(
    path: Path, config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    artifact = config["input_contract"]["artifacts"]["dimension_state"]
    columns = (
        "security_id",
        "trading_date",
        "percentile_window_W",
        "q",
        "weak_delta",
        "dimension",
        "dimension_active_weak",
        "validity_status",
    )
    return _query_duckdb(
        path,
        artifact["table"],
        columns,
        (
            "percentile_window_W = ? AND q = ? AND "
            "abs(weak_delta - ?) < 1e-12 AND dimension = ?"
        ),
        [W, Q, WEAK_DELTA, "C"],
    )


def inspect_input_artifact(
    path: Path,
    artifact: Mapping[str, Any],
    declaration: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify the opened DuckDB against the selected source-manifest declaration."""

    for field in ("path", "sha256", "row_count", "table"):
        if field not in declaration or declaration[field] in (None, ""):
            raise RuntimeError(f"source manifest declaration missing {field}: {path}")
    actual_hash = sha256_file(path)
    if actual_hash != declaration["sha256"]:
        raise RuntimeError(
            "source manifest hash mismatch: "
            f"declared={declaration['sha256']} actual={actual_hash}"
        )
    table = str(artifact["table"])
    required_columns = [str(value) for value in artifact["required_columns"]]
    _assert_identifier(table)
    import duckdb

    connection = duckdb.connect(str(path), read_only=True)
    try:
        table_exists = connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [table],
        ).fetchone()[0]
        if int(table_exists) != 1:
            raise RuntimeError(f"declared table is missing: {table} in {path}")
        actual_columns = [
            str(row[1])
            for row in connection.execute(
                f"PRAGMA table_info({_quote_identifier(table)})"
            ).fetchall()
        ]
        missing_columns = sorted(set(required_columns) - set(actual_columns))
        if missing_columns:
            raise RuntimeError(
                f"required columns are missing for {table}: {missing_columns}"
            )
        full_row_count = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
            ).fetchone()[0]
        )
        declared_row_count = int(declaration["row_count"])
        if full_row_count != declared_row_count:
            raise RuntimeError(
                f"source manifest row count mismatch for {table}: "
                f"declared={declared_row_count} actual={full_row_count}"
            )
        declared_table = str(declaration["table"])
        if declared_table != table:
            raise RuntimeError(
                f"source manifest table mismatch: declared={declared_table} "
                f"actual={table}"
            )
        actual_security_count = None
        if "security_id" in actual_columns:
            actual_security_count = int(
                connection.execute(
                    f"SELECT COUNT(DISTINCT {_quote_identifier('security_id')}) "
                    f"FROM {_quote_identifier(table)}"
                ).fetchone()[0]
            )
        actual_date_min = None
        actual_date_max = None
        if "trading_date" in actual_columns:
            date_values = connection.execute(
                f"SELECT MIN({_quote_identifier('trading_date')}), "
                f"MAX({_quote_identifier('trading_date')}) "
                f"FROM {_quote_identifier(table)}"
            ).fetchone()
            actual_date_min = _canonical_optional_date_text(date_values[0])
            actual_date_max = _canonical_optional_date_text(date_values[1])
        if declaration.get(
            "security_count"
        ) is not None and actual_security_count != int(declaration["security_count"]):
            raise RuntimeError(
                f"source manifest security count mismatch for {table}: "
                f"declared={declaration['security_count']} "
                f"actual={actual_security_count}"
            )
        declared_date_min = _canonical_optional_date_text(declaration.get("date_min"))
        declared_date_max = _canonical_optional_date_text(declaration.get("date_max"))
        if declared_date_min is not None and actual_date_min != declared_date_min:
            raise RuntimeError(
                f"source manifest date_min mismatch for {table}: "
                f"declared={declared_date_min} actual={actual_date_min}"
            )
        if declared_date_max is not None and actual_date_max != declared_date_max:
            raise RuntimeError(
                f"source manifest date_max mismatch for {table}: "
                f"declared={declared_date_max} actual={actual_date_max}"
            )
        return {
            "actual_table": table,
            "actual_columns": actual_columns,
            "source_full_row_count": full_row_count,
            "actual_security_count": actual_security_count,
            "actual_date_min": actual_date_min,
            "actual_date_max": actual_date_max,
        }
    finally:
        connection.close()


def build_formal_source_bindings(
    source_commit: str, config_path: Path
) -> dict[str, dict[str, Any]]:
    """Bind execution inputs to committed Git blobs before any formal query."""

    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        raise RuntimeError(
            "formal run requires a clean worktree before committed-source binding"
        )
    source_paths = {
        "config": config_path,
        "schema": ROOT
        / "schemas"
        / "sidecar"
        / "exp_c01_c_layer_indicator_ablation.schema.json",
        "runner": Path(__file__).resolve(),
        "core": ROOT / "src" / "sidecar" / "exp_c01_c_layer_ablation.py",
        "validator": ROOT / "src" / "sidecar" / "exp_c01_c_layer_ablation_validator.py",
    }
    result: dict[str, dict[str, Any]] = {}
    for name, path in source_paths.items():
        path = path.resolve()
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError as exc:
            raise RuntimeError(f"formal source is outside repository: {path}") from exc
        if not path.is_file():
            raise RuntimeError(f"formal source file is missing: {path}")
        committed = subprocess.run(
            ["git", "show", f"{source_commit}:{relative}"],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
        ).stdout
        _validate_canonical_text_contract(committed, relative)
        if path.read_bytes() != committed:
            raise RuntimeError(
                f"working tree differs from committed source: {relative}"
            )
        blob_sha = subprocess.run(
            ["git", "rev-parse", f"{source_commit}:{relative}"],
            cwd=str(ROOT),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        committed_hash = hashlib.sha256(committed).hexdigest()
        result[name] = {
            "source_commit": source_commit,
            "path": relative,
            "git_blob_sha": blob_sha,
            "committed_byte_sha256": committed_hash,
            "normalized_text_sha256": committed_hash,
            "encoding": "UTF-8",
            "line_ending": "LF",
            "bom": False,
            "final_lf_count": 1,
        }
    return result


def _validate_canonical_text_contract(raw: bytes, path: str) -> None:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise RuntimeError(f"formal source has BOM: {path}")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"formal source is not UTF-8: {path}") from exc
    if b"\r" in raw:
        raise RuntimeError(f"formal source is not LF-normalized: {path}")
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise RuntimeError(f"formal source must end with exactly one LF: {path}")


def build_manifest(
    *,
    output_root: Path,
    run_id: str,
    config_path: Path,
    config: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
    input_manifest_path: Path,
    input_root: Path,
    input_metadata: Mapping[str, Mapping[str, Any]],
    input_availability: Mapping[str, Mapping[str, Any]],
    reconciliation: Mapping[str, Any],
    implementation_sha: str,
    started_at: str,
    finished_at: str,
    formal_source_bindings: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    files = {}
    for key in (
        "variant_profile",
        "overlap_profile",
        "score_comparison",
        "year_profile",
        "security_profile",
        "availability_profile",
        "result_analysis",
    ):
        path = output_root / OUTPUT_FILES[key]
        files[path.name] = {
            "path": path.name,
            "sha256": sha256_file(path),
            "row_count": file_row_count(path),
        }
    source_manifest_schema_version = input_manifest.get(
        "schema_version", input_manifest.get("input_schema_version")
    )
    source_manifest_artifacts = {
        name: {
            key: declaration[key]
            for key in (
                "path",
                "sha256",
                "row_count",
                "table",
                "security_count",
                "date_min",
                "date_max",
            )
            if key in declaration
        }
        for name, declaration in (
            (
                name,
                {
                    key.replace("source_manifest_declared_", ""): metadata[key]
                    for key in metadata
                    if key.startswith("source_manifest_declared_")
                },
            )
            for name, metadata in input_metadata.items()
        )
    }
    return {
        "schema_version": "exp_c01_manifest.v1",
        "task_id": TASK_ID,
        "run_id": run_id,
        "implementation_sha": implementation_sha,
        "workflow_mode": "same_pr",
        "phase": "formal_run",
        "parameters": {"W": W, "q": Q, "weak_delta": WEAK_DELTA},
        "variants": list(VARIANT_IDS),
        "variant_rules": dict(EXPECTED_VARIANT_RULES),
        "denominator_scope": "pair_common_valid",
        "input_manifest": input_manifest,
        "source_manifest_path": str(input_manifest_path),
        "source_manifest_sha256": sha256_file(input_manifest_path),
        "source_manifest_schema_version": source_manifest_schema_version,
        "source_manifest_artifacts": source_manifest_artifacts,
        "input_artifacts": dict(input_metadata),
        "input_availability": dict(input_availability),
        "config": {
            "path": str(config_path),
            "sha256": (
                formal_source_bindings.get("config", {}).get("committed_byte_sha256")
                if formal_source_bindings
                else sha256_file(config_path)
            ),
        },
        "baseline_reconciliation": dict(reconciliation),
        "files": files,
        "execution": {
            "started_at": started_at,
            "finished_at": finished_at,
            "parallel_mode": "single_threaded",
            "worker_count": 1,
            "random_seed": None,
            "input_root": str(input_root),
            "config_version": config.get("config_version"),
            "source_bindings": dict(formal_source_bindings or {}),
        },
        "prohibited_outputs": [
            "future_return",
            "future_volatility",
            "future_direction",
            "release_label",
            "path_label",
            "backtest",
            "portfolio",
            "transaction_cost",
            "selected_indicator",
            "winner",
            "replacement_approved",
            "C_v2",
        ],
    }


def build_result_analysis(
    artifacts: Mapping[str, tuple[tuple[str, ...], list[dict[str, str]]]],
    *,
    manifest: Mapping[str, Any],
    validation: Mapping[str, Any],
    anomaly_scan: Mapping[str, Any],
    recomputation: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
) -> str:
    variant_rows = artifacts["variant_profile"][1]
    overlap_rows = artifacts["overlap_profile"][1]
    score_rows = artifacts["score_comparison"][1]
    year_rows = artifacts["year_profile"][1]
    security_rows = artifacts["security_profile"][1]
    availability_rows = artifacts["availability_profile"][1]
    variant_metrics = recomputation.get("variant_metrics", {})
    overlap_metrics = recomputation.get("overlap_metrics", [])
    year_metrics = recomputation.get("year_metrics", [])
    security_metrics = recomputation.get("security_metrics", [])

    def numeric(values: Sequence[Any]) -> list[float]:
        result: list[float] = []
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number == number and abs(number) != float("inf"):
                result.append(number)
        return result

    def quantile(values: Sequence[Any], probability: float) -> float | None:
        ordered = sorted(numeric(values))
        if not ordered:
            return None
        if len(ordered) == 1:
            return ordered[0]
        position = (len(ordered) - 1) * probability
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = position - lower
        return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction

    def triplet(values: Sequence[Any]) -> str:
        ordered = sorted(numeric(values))
        if not ordered:
            return "NULL / NULL / NULL"
        middle = quantile(ordered, 0.50)
        return f"{ordered[0]:.6g} / {middle:.6g} / {ordered[-1]:.6g}"

    def quartiles(values: Sequence[Any]) -> str:
        return " / ".join(
            compact(quantile(values, probability)) for probability in (0.25, 0.50, 0.75)
        )

    def range_text(values: Sequence[Any]) -> str:
        ordered = numeric(values)
        if not ordered:
            return "NULL"
        return f"[{min(ordered):.6g}, {max(ordered):.6g}]"

    def compact(value: Any) -> str:
        if value is None or value == "":
            return "NULL"
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

    year_values = [
        int(row["calendar_year"]) for row in year_metrics if row["calendar_year"] >= 0
    ]
    input_artifacts = manifest.get("input_artifacts", {})
    year_min = min(year_values) if year_values else "NULL"
    year_max = max(year_values) if year_values else "NULL"
    ready = (
        validation.get("status") == "passed"
        and anomaly_scan.get("status") == "passed"
        and recomputation.get("status") == "passed"
        and reconciliation.get("mismatch_total") == 0
    )
    readiness = (
        "ready_for_user_formal_result_review"
        if ready
        else "needs_investigation_before_user_review"
    )
    lines = [
        "# EXP-C01 结果分析",
        "",
        (
            "本文件只允许描述当前 C1/C2 指标状态身份、可用性、持续性和稳定性；"
            "不作未来结果、交易表现或指标替换结论。"
        ),
        "",
        "## 1. Actual run / reviewed SHA / input lineage",
        "",
        (
            f"run_id=`{manifest.get('run_id')}`；"
            f"reviewed implementation SHA=`{manifest.get('implementation_sha')}`；"
            f"工程 validator 状态=`{validation.get('status')}`。"
        ),
        (
            f"source manifest path=`{manifest.get('source_manifest_path')}`；"
            f"SHA=`{manifest.get('source_manifest_sha256')}`；"
            f"schema/version=`{manifest.get('source_manifest_schema_version')}`。"
        ),
    ]
    for name, entry in sorted(input_artifacts.items()):
        lines.append(
            f"- `{name}`：path=`{entry.get('path')}`，"
            f"SHA=`{entry.get('sha256')}`，table=`{entry.get('actual_table')}`，"
            f"required columns={entry.get('required_columns')}，"
            f"source full rows={entry.get('source_full_row_count')}，"
            f"filtered query rows={entry.get('query_filtered_row_count')}，"
            f"security count={entry.get('actual_security_count')}，"
            f"date range={entry.get('actual_date_min')} to "
            f"{entry.get('actual_date_max')}。"
        )
    lines.extend(
        [
            "",
            "## 2. Fixed parameters and variants",
            "",
            "W=120、q=0.20、weak_delta=0.10；denominator=`pair_common_valid`。",
            (
                "- `baseline_pair`: pair_valid AND score_C_mean >= 0.80 "
                "AND score_C_min >= 0.70。"
            ),
            (
                "- `c1_only`: C1 valid AND score_C1 >= 0.80；"
                "`c2_only`: C2 valid AND score_C2 >= 0.80。"
            ),
            "",
            "## 3. Cardinality and date range",
            "",
            (
                f"year profile calendar range=`{year_min}` to `{year_max}`；"
                f"year rows={len(year_rows)}；security rows={len(security_rows)}。"
            ),
            (
                f"persisted CSV row counts：variant={len(variant_rows)}，"
                f"overlap={len(overlap_rows)}，score={len(score_rows)}，"
                f"year={len(year_rows)}，security={len(security_rows)}，"
                f"availability={len(availability_rows)}。"
            ),
            "",
            "## 4. Core counts",
            "",
        ]
    )
    for row in variant_rows:
        lines.append(
            f"- `{row.get('variant_id')}`：valid rows={row.get('eligible_row_count')}，"
            f"active true={row.get('active_true_count')}，"
            f"active false={row.get('active_false_count')}，"
            f"active rate={row.get('active_rate')}，"
            f"valid blocks={row.get('valid_block_count')}，"
            f"valid steps={row.get('valid_step_count')}。"
        )
    lines.extend(["", "## 5. Overlap", ""])
    for row in overlap_rows:
        lines.append(
            f"- `{row.get('left_variant')}` vs `{row.get('right_variant')}`："
            f"Jaccard={row.get('jaccard')}，"
            f"baseline retention={row.get('baseline_retention')}，"
            f"candidate precision={row.get('candidate_precision')}，"
            f"symmetric difference rate={row.get('symmetric_difference_rate')}。"
        )
    lines.extend(["", "## 6. Score correlations and score differences", ""])
    for row in score_rows:
        lines.append(
            f"- `{row.get('comparison_id')}`："
            f"pooled Spearman={row.get('pooled_spearman')}，"
            "median absolute difference="
            f"{row.get('median_absolute_score_difference')}。"
        )
    lines.extend(["", "## 7. Duration, fragments, and transitions", ""])
    for row in variant_rows:
        lines.append(
            f"- `{row.get('variant_id')}`：segments={row.get('segment_count')}，"
            f"duration sum={row.get('segment_duration_sum')}，"
            f"singleton ratio={row.get('singleton_segment_ratio')}，"
            f"transitions={row.get('transition_count')}，"
            f"transition rate per 100 valid steps="
            f"{row.get('transition_rate_per_100_valid_steps')}。"
        )
    lines.extend(["", "## 8. Availability", ""])
    for row in availability_rows:
        lines.append(
            f"- `{row.get('indicator_id')}`："
            f"native valid={row.get('native_valid_count')}，"
            f"pair common-valid={row.get('pair_common_valid_count')}，"
            f"gain vs pair={row.get('availability_gain_vs_pair')}。"
        )
    lines.extend(["", "## 9. Year profiles", ""])
    for candidate in ("c1_only", "c2_only"):
        rows = [row for row in year_metrics if row["candidate_variant"] == candidate]
        annual_jaccard = range_text([row["jaccard"] for row in rows])
        annual_retention = triplet([row["baseline_retention"] for row in rows])
        annual_precision = triplet([row["candidate_precision"] for row in rows])
        lines.append(
            f"- `{candidate}`：annual Jaccard range={annual_jaccard}；"
            f"annual retention min/median/max={annual_retention}；"
            f"annual precision min/median/max={annual_precision}。"
        )
    for variant in VARIANT_IDS:
        metric = variant_metrics.get(variant, {})
        lines.append(
            f"- `{variant}`："
            f"max-year active share={compact(metric.get('max_year_active_share'))}，"
            f"max-year active rate={compact(metric.get('max_year_active_rate'))}，"
            f"dominant year={compact(metric.get('dominant_year'))}。"
        )
    lines.extend(["", "## 10. Security profiles", ""])
    for candidate in ("c1_only", "c2_only"):
        rows = [
            row for row in security_metrics if row["candidate_variant"] == candidate
        ]
        total_baseline = sum(max(0, row["baseline_true_count"]) for row in rows)
        total_candidate = sum(max(0, row["candidate_true_count"]) for row in rows)
        max_baseline = (
            max((row["baseline_true_count"] for row in rows), default=0)
            / total_baseline
            if total_baseline
            else None
        )
        max_candidate = (
            max((row["candidate_true_count"] for row in rows), default=0)
            / total_candidate
            if total_candidate
            else None
        )
        pooled = next(
            (
                row
                for row in overlap_metrics
                if row["left_variant"] == "baseline_pair"
                and row["right_variant"] == candidate
            ),
            None,
        )
        pooled_jaccard = pooled.get("jaccard") if pooled else None
        security_median = quartiles([row["jaccard"] for row in rows]).split(" / ")[1]
        direction = "not_comparable"
        if pooled_jaccard is not None and rows:
            jaccard_values = numeric([row["jaccard"] for row in rows])
            median_value = quantile(jaccard_values, 0.50)
            if median_value is not None:
                direction = (
                    "pooled_above_security_median"
                    if pooled_jaccard > median_value
                    else "pooled_at_or_below_security_median"
                )
        security_retention = triplet([row["baseline_retention"] for row in rows]).split(
            " / "
        )[1]
        security_precision = triplet(
            [row["candidate_precision"] for row in rows]
        ).split(" / ")[1]
        lines.append(
            f"- `{candidate}`：security Jaccard q25/median/q75="
            f"{quartiles([row['jaccard'] for row in rows])}；"
            f"retention median={security_retention}；"
            f"precision median={security_precision}；"
            f"max baseline-security active share={compact(max_baseline)}，"
            f"max candidate-security active share={compact(max_candidate)}；"
            f"pooled-vs-security-median direction={direction} "
            f"(pooled={compact(pooled_jaccard)}; "
            f"security median={security_median})。"
        )
    lines.extend(["", "## 11. Baseline reconciliation", ""])
    reconciliation_fields = [
        (key, reconciliation.get(key))
        for key in (
            "key_count_mismatch",
            "score_mean_mismatch",
            "score_min_mismatch",
            "eligible_mismatch",
            "active_mismatch",
            "validity_mismatch",
        )
    ]
    lines.append(
        f"reconciliation status=`{reconciliation.get('status')}`；"
        f"mismatch_total={reconciliation.get('mismatch_total')}；"
        f"key/score/eligible/active/validity mismatches={reconciliation_fields}。"
    )
    lines.extend(["", "## 12. Anomaly scan", ""])
    if anomaly_scan.get("anomalies"):
        for item in anomaly_scan["anomalies"]:
            detail = json.dumps(item.get("detail"), ensure_ascii=False, sort_keys=True)
            lines.append(f"- `{item.get('code')}`：{detail}")
    else:
        lines.append("- no anomaly was emitted by the registered scan.")
    lines.extend(["", "## 13. Independent recomputation", ""])
    lines.append(
        f"status=`{recomputation.get('status')}`；"
        f"mismatches={recomputation.get('mismatches', [])}。"
    )
    lines.append(
        "The readback formulas independently check n2x2 conservation, Jaccard, "
        "retention, precision, symmetric-difference rate, active rate, "
        "valid-step transition rate, segment-duration conservation, singleton "
        "ratio, max-year share/rate, and availability gain."
    )
    lines.extend(
        [
            "",
            "## 14. Alternative explanations",
            "",
            (
                "Observed identity or concentration can arise from the fixed "
                "threshold geometry, shared pair-valid availability, "
                "calendar/security composition, missing or blocked rows, or "
                "duplicated upstream materialization. These descriptive "
                "artifacts do not identify a causal mechanism."
            ),
            "",
            "## 15. Supported conclusions",
            "",
            (
                "Only the persisted counts, overlap statistics, score "
                "differences, duration summaries, availability differences, "
                "and year/security profile statistics are supported. A nonzero "
                "reconciliation mismatch, anomaly, or readback mismatch "
                "blocks a formal-result interpretation."
            ),
            (
                "User review may separately assess whether the descriptive "
                "strong-substitutability reference is reached, whether an "
                "availability advantage is evident, whether duration or "
                "fragmentation changes, whether year/security concentration "
                "exists, and whether any order-of-magnitude item needs "
                "investigation; this file does not make those decisions "
                "automatically."
            ),
            "",
            "## 16. Unsupported conclusions",
            "",
            (
                "This result does not support a statement about future "
                "outcomes, release direction, trading value, stable advantage, "
                "causal substitution, deletion of an indicator, or promotion "
                "of a replacement state definition."
            ),
            "",
            "## 17. Readiness for user formal-result review",
            "",
            f"`{readiness}`",
            "",
        ]
    )
    return "\n".join(lines)


def write_csv(
    path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fieldnames),
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        handle.write("\n")


def write_text(path: Path, value: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(value.rstrip("\n") + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_row_count(path: Path) -> int:
    if path.suffix.lower() == ".csv":
        _headers, rows = read_csv_artifact(path)
        return len(rows)
    return len(path.read_text(encoding="utf-8").splitlines())


def _query_duckdb(
    path: Path,
    table: str,
    columns: Sequence[str],
    where_clause: str,
    parameters: Sequence[Any],
) -> list[dict[str, Any]]:
    import duckdb

    _assert_identifier(table)
    connection = duckdb.connect(str(path), read_only=True)
    try:
        quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
        query = (
            f"SELECT {quoted_columns} FROM {_quote_identifier(table)} "
            f"WHERE {where_clause} ORDER BY security_id, trading_date"
        )
        cursor = connection.execute(query, list(parameters))
        names = [str(item[0]) for item in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
    finally:
        connection.close()


def _assert_config_scope(config: Mapping[str, Any]) -> None:
    if config.get("task_id") != TASK_ID:
        raise RuntimeError("config task_id mismatch")
    parameters = config.get("parameters", {})
    if parameters.get("W") != W or float(parameters.get("q")) != Q:
        raise RuntimeError("config must be W=120 and q=0.20")
    if float(parameters.get("weak_delta")) != WEAK_DELTA:
        raise RuntimeError("config weak_delta must be 0.10")
    if config.get("variants") is None or [
        row.get("variant_id") for row in config["variants"]
    ] != list(VARIANT_IDS):
        raise RuntimeError("config variant set mismatch")


def _current_git_sha(cwd: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON object required: {path}")
    return value


def _assert_identifier(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise RuntimeError(f"unsafe SQL identifier: {value}")


def _quote_identifier(value: str) -> str:
    _assert_identifier(value)
    return f'"{value}"'


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--allow-formal-run", action="store_true")
    parser.add_argument("--reviewed-implementation-sha")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
