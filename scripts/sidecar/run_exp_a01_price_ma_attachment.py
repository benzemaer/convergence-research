"""Run the EXP-A01 formal package behind an explicit exact-SHA gate.

The package is executable for an explicitly authorized input manifest, while
the repository configuration keeps formal authorization false. Tests use
temporary synthetic inputs; no repository formal output is created here.
"""

# SQL-adjacent lineage messages intentionally keep fixed wording.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sidecar.exp_a01_price_ma_attachment import TASK_ID  # noqa: E402
from src.sidecar.exp_a01_price_ma_attachment_formal import (  # noqa: E402
    materialize_raw_metrics,
    write_compact_csvs,
)
from src.sidecar.exp_a01_price_ma_attachment_validator import (  # noqa: E402
    canonical_text_errors,
    load_json,
    scan_persisted_anomalies,
    validate_formal_result,
    validate_static_config,
)

DEFAULT_CONFIG = (
    ROOT / "configs" / "sidecar" / "exp_a01_price_ma_attachment_candidates.v1.json"
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
FILE_SHA_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
QUALIFIED_COLUMN_PATTERN = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z_][A-Za-z0-9_]*$"
)
EXPECTED_INDEX_STATUSES = {"present", "listing_pause", "missing", "unresolved"}
RUN_ID_PATTERN = re.compile(r"^EXP-A01-[0-9]{8}T[0-9]{6}(?:[0-9]{3,6})?Z$")
AUTHORIZED_MANIFEST_SCHEMA = (
    ROOT / "schemas" / "sidecar" / "exp_a01_authorized_input_manifest.schema.json"
)
FORMAL_SOURCE_PATHS = (
    "configs/sidecar/exp_a01_price_ma_attachment_candidates.v1.json",
    "schemas/sidecar/exp_a01_price_ma_attachment_candidates.schema.json",
    "schemas/sidecar/exp_a01_authorized_input_manifest.schema.json",
    "src/sidecar/exp_a01_price_ma_attachment.py",
    "src/sidecar/exp_a01_price_ma_attachment_formal.py",
    "src/sidecar/exp_a01_price_ma_attachment_validator.py",
    "scripts/sidecar/run_exp_a01_price_ma_attachment.py",
    "scripts/sidecar/validate_exp_a01_price_ma_attachment.py",
)
FORMAL_OUTPUT_FILES = (
    "exp_a01_raw_metrics.duckdb",
    "exp_a01_metric_profile.csv",
    "exp_a01_validity_profile.csv",
    "exp_a01_year_coverage.csv",
    "exp_a01_security_coverage.csv",
    "exp_a01_manifest.json",
    "exp_a01_validator_result.json",
    "exp_a01_anomaly_scan.json",
    "exp_a01_result_analysis.md",
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_formal(args)
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {"task_id": TASK_ID, "status": "blocked", "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def run_formal(args: argparse.Namespace) -> dict[str, Any]:
    """Execute the authorized A01 package with atomic output publication."""

    gate = validate_formal_gate(args)
    output_root = Path(gate["output_root"])
    staging = Path(f"{output_root}.partial-{os.getpid()}")
    if staging.exists():
        raise RuntimeError(f"partial staging directory already exists: {staging}")

    started_at = _utc_timestamp()
    published = False
    try:
        staging.mkdir(parents=True)
        raw_path = staging / "exp_a01_raw_metrics.duckdb"
        raw_metadata = materialize_raw_metrics(
            candidate_path=gate["input_paths"]["d3_t07_candidate_daily_observation"],
            candidate_table=gate["config"]["input_contract"]["artifacts"][
                "d3_t07_candidate_daily_observation"
            ]["table"],
            index_path=gate["input_paths"]["expected_price_observation_index"],
            index_table=gate["config"]["input_contract"]["artifacts"][
                "expected_price_observation_index"
            ]["table"],
            output_path=raw_path,
            run_id=gate["run_id"],
            memory_limit=args.memory_limit,
        )
        profile_metadata = write_compact_csvs(
            output_dir=staging, raw_duckdb=raw_path, memory_limit=args.memory_limit
        )

        preliminary_manifest = _build_formal_manifest(
            gate=gate,
            args=args,
            started_at=started_at,
            finished_at=None,
            staging=staging,
            raw_metadata=raw_metadata,
            profile_metadata=profile_metadata,
            validator_status="pending",
            anomaly_status="pending",
        )
        _write_json(staging / "exp_a01_manifest.json", preliminary_manifest)
        preliminary_validation = validate_formal_result(
            staging,
            config_path=gate["config_path"],
            input_manifest_path=gate["input_manifest_path"],
            input_root=args.input_root,
            reviewed_implementation_sha=gate["reviewed_sha"],
            require_final_manifest=False,
        )
        _write_json(staging / "exp_a01_validator_result.json", preliminary_validation)
        preliminary_anomaly = scan_persisted_anomalies(
            staging,
            expected_index_row_count=gate["expected_index_reconciliation"][
                "index_row_count"
            ],
        )
        _write_json(staging / "exp_a01_anomaly_scan.json", preliminary_anomaly)
        analysis = _build_result_analysis(
            gate=gate,
            args=args,
            started_at=started_at,
            finished_at=_utc_timestamp(),
            raw_metadata=raw_metadata,
            validation=preliminary_validation,
            anomaly=preliminary_anomaly,
            staging=staging,
        )
        (staging / "exp_a01_result_analysis.md").write_text(
            analysis, encoding="utf-8", newline="\n"
        )

        final_manifest = _build_formal_manifest(
            gate=gate,
            args=args,
            started_at=started_at,
            finished_at=_utc_timestamp(),
            staging=staging,
            raw_metadata=raw_metadata,
            profile_metadata=profile_metadata,
            validator_status=preliminary_validation["status"],
            anomaly_status=preliminary_anomaly["status"],
        )
        _write_json(staging / "exp_a01_manifest.json", final_manifest)
        manifest_sha = sha256_file(staging / "exp_a01_manifest.json")

        final_anomaly = scan_persisted_anomalies(
            staging,
            expected_index_row_count=gate["expected_index_reconciliation"][
                "index_row_count"
            ],
        )
        final_anomaly["final_manifest_sha256"] = manifest_sha
        _write_json(staging / "exp_a01_anomaly_scan.json", final_anomaly)
        final_validation = validate_formal_result(
            staging,
            config_path=gate["config_path"],
            input_manifest_path=gate["input_manifest_path"],
            input_root=args.input_root,
            reviewed_implementation_sha=gate["reviewed_sha"],
            require_final_manifest=True,
        )
        final_validation["final_manifest_sha256"] = manifest_sha
        _write_json(staging / "exp_a01_validator_result.json", final_validation)
        if final_validation["status"] != "passed":
            raise RuntimeError(
                "independent formal-result validation failed: "
                + "; ".join(final_validation.get("errors", []))
            )
        if final_anomaly["status"] == "failed":
            raise RuntimeError(
                "formal-result anomaly scan failed: "
                + "; ".join(final_anomaly.get("blocking_anomalies", []))
            )

        output_root.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(output_root)
        published = True
        return {
            "task_id": TASK_ID,
            "status": "passed",
            "run_id": gate["run_id"],
            "output_root": str(output_root),
            "reviewed_implementation_sha": gate["reviewed_sha"],
            "formal_run_executed": True,
            "validator_status": final_validation["status"],
            "anomaly_status": final_anomaly["status"],
        }
    except Exception:
        if output_root.exists() and not published:
            _remove_path(output_root)
        if staging.exists():
            _remove_path(staging)
        raise


def validate_formal_gate(args: argparse.Namespace) -> dict[str, Any]:
    """Validate every formal precondition without creating any output."""

    if not args.allow_formal_run:
        raise RuntimeError("formal_run_not_allowed_without_--allow-formal-run")
    reviewed_sha = str(args.reviewed_implementation_sha or "")
    if not SHA_PATTERN.fullmatch(reviewed_sha):
        raise RuntimeError(
            "reviewed_implementation_sha must be an exact 40-character SHA"
        )
    if not RUN_ID_PATTERN.fullmatch(str(args.run_id or "")):
        raise RuntimeError("run-id does not match the EXP-A01 formal pattern")
    memory_limit = getattr(args, "memory_limit", "8GB")
    if not str(memory_limit or "").strip():
        raise RuntimeError("memory-limit must be non-empty")

    config_path = Path(args.config).resolve()
    config = load_json(config_path)
    config_errors = validate_static_config(config)
    if config_errors:
        raise RuntimeError(
            "static config validation failed: " + ", ".join(config_errors)
        )
    current_sha = _current_git_sha()
    if current_sha != reviewed_sha:
        raise RuntimeError(
            "current HEAD does not equal reviewed_implementation_sha; "
            f"current={current_sha} reviewed={reviewed_sha}"
        )
    worktree_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if worktree_status.strip():
        raise RuntimeError("formal run requires a clean worktree")
    source_bindings = _validate_committed_source_bindings(reviewed_sha)

    if args.input_manifest is None:
        raise RuntimeError("--input-manifest is required")
    manifest_path = Path(args.input_manifest).resolve()
    if not manifest_path.is_file():
        raise RuntimeError(f"input manifest is not a file: {manifest_path}")
    manifest_raw = manifest_path.read_bytes()
    text_errors = canonical_text_errors(manifest_raw)
    if text_errors:
        raise RuntimeError(
            f"source manifest is not canonical UTF-8/LF: {manifest_path}: {text_errors}"
        )
    try:
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"source manifest is invalid JSON: {manifest_path}") from exc
    if not isinstance(manifest, Mapping):
        raise RuntimeError("source manifest root must be an object")
    _validate_authorized_manifest_schema(manifest)
    _validate_manifest_authorization_bindings(manifest)

    run_id = str(args.run_id)
    output_root = Path(args.output_root).resolve()
    if output_root.name != run_id:
        raise RuntimeError("output-root basename must equal run-id")
    if output_root.exists():
        raise RuntimeError(f"output directory must be new and absent: {output_root}")
    partial_root = Path(f"{output_root}.partial-{os.getpid()}")
    if partial_root.exists():
        raise RuntimeError(f"partial staging directory already exists: {partial_root}")

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

    input_contract = config["input_contract"]
    artifacts = input_contract["artifacts"]
    declarations: dict[str, Mapping[str, Any]] = {}
    paths: dict[str, Path] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for artifact_id in input_contract["manifest_artifact_names"]:
        artifact = artifacts[artifact_id]
        declaration = _extract_declaration(manifest, artifact_id)
        if declaration is None:
            raise RuntimeError(f"source manifest does not declare {artifact_id}")
        declarations[artifact_id] = declaration
        path = resolve_declared_input_path(
            manifest_path, input_root, declaration, artifact
        )
        paths[artifact_id] = path
        metadata[artifact_id] = inspect_input_artifact(path, artifact, declaration)
        metadata[artifact_id]["path"] = str(path)
    _validate_cross_artifact_bindings(manifest, declarations)

    _validate_d3_t07_evidence(
        candidate_path=paths["d3_t07_candidate_daily_observation"],
        candidate_artifact=artifacts["d3_t07_candidate_daily_observation"],
        quality=metadata["d3_t07_quality_report"]["json"],
        handoff=metadata["d3_t07_handoff_report"]["json"],
        gate=config["d3_t07_evidence_gate"],
    )
    index_reconciliation = validate_expected_index_reconciliation(
        candidate_path=paths["d3_t07_candidate_daily_observation"],
        candidate_artifact=artifacts["d3_t07_candidate_daily_observation"],
        index_path=paths["expected_price_observation_index"],
        index_artifact=artifacts["expected_price_observation_index"],
        dense_contract=config["dense_window_contract"],
    )

    return {
        "task_id": TASK_ID,
        "status": "gate_passed",
        "run_id": run_id,
        "reviewed_sha": reviewed_sha,
        "input_manifest_path": str(manifest_path),
        "input_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "manifest": dict(manifest),
        "input_paths": paths,
        "input_metadata": metadata,
        "input_declarations": declarations,
        "expected_index_reconciliation": index_reconciliation,
        "output_root": str(output_root),
        "config": config,
        "config_path": config_path,
        "source_bindings": source_bindings,
        "formal_run_executed": False,
    }


def resolve_declared_input_path(
    manifest_path: Path,
    input_root: Path,
    declaration: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> Path:
    declared_path_value = declaration.get("path")
    if not isinstance(declared_path_value, str) or not declared_path_value.strip():
        raise RuntimeError("source manifest declaration path is missing")
    declared_path = Path(declared_path_value)
    candidate = (
        declared_path
        if declared_path.is_absolute()
        else manifest_path.parent / declared_path
    )
    if not candidate.is_file():
        path_policy = str(declaration.get("path_policy", ""))
        if (
            path_policy != "basename_local_only"
            or declared_path.name != declared_path_value
        ):
            raise RuntimeError(
                f"declared {artifact['artifact_id']} path is missing and relocation "
                f"is not authorized: {candidate}"
            )
        candidate = input_root / declared_path.name
    if not candidate.is_file():
        raise RuntimeError(
            f"declared {artifact['artifact_id']} input is missing: {candidate}"
        )
    expected_filename = str(artifact.get("filename", ""))
    if candidate.name != expected_filename:
        raise RuntimeError(
            f"declared {artifact['artifact_id']} filename mismatch: "
            f"expected={expected_filename} actual={candidate.name}"
        )
    if artifact.get("artifact_kind") == "duckdb_table":
        if declaration.get("table") != artifact.get("table"):
            raise RuntimeError(
                f"source manifest {artifact['artifact_id']} table declaration "
                "does not match implementation contract"
            )
    return candidate.resolve()


def inspect_input_artifact(
    path: Path,
    artifact: Mapping[str, Any],
    declaration: Mapping[str, Any],
) -> dict[str, Any]:
    """Check declaration identity, SHA, canonical evidence, or DuckDB schema."""

    artifact_id = str(artifact.get("artifact_id", ""))
    for field in (
        "artifact_id",
        "source_contract",
        "source_role",
        "formal_data_version",
        "sha256",
    ):
        if field not in declaration or declaration[field] in (None, ""):
            raise RuntimeError(
                f"source manifest declaration missing {artifact_id}.{field}"
            )
    if declaration.get("artifact_id") != artifact_id:
        raise RuntimeError(f"source manifest artifact_id mismatch: {artifact_id}")
    for field in ("source_contract", "source_role", "formal_data_version"):
        if declaration.get(field) != artifact.get(field):
            raise RuntimeError(f"source manifest {artifact_id} {field} mismatch")
    if not FILE_SHA_PATTERN.fullmatch(str(declaration["sha256"])):
        raise RuntimeError(f"source manifest {artifact_id} sha256 is invalid")
    actual_hash = sha256_file(path)
    if actual_hash != declaration["sha256"]:
        raise RuntimeError(
            f"source manifest hash mismatch for {artifact_id}: "
            f"declared={declaration['sha256']} actual={actual_hash}"
        )

    if artifact.get("artifact_kind") == "evidence_json":
        raw = path.read_bytes()
        text_errors = canonical_text_errors(raw)
        if text_errors:
            raise RuntimeError(
                f"evidence JSON is not canonical for {artifact_id}: {text_errors}"
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"evidence JSON is invalid for {artifact_id}") from exc
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"evidence JSON root is not an object for {artifact_id}")
        missing = sorted(
            set(str(value) for value in artifact["required_json_fields"]) - set(payload)
        )
        if missing:
            raise RuntimeError(
                f"evidence JSON fields are missing for {artifact_id}: {missing}"
            )
        return {
            "artifact_id": artifact_id,
            "sha256": actual_hash,
            "json": dict(payload),
        }

    if artifact.get("artifact_kind") != "duckdb_table":
        raise RuntimeError(f"unsupported artifact kind for {artifact_id}")
    for field in ("row_count", "table", "required_columns"):
        if field not in declaration or declaration[field] in (None, ""):
            raise RuntimeError(
                f"source manifest declaration missing {artifact_id}.{field}"
            )
    if declaration.get("table") != artifact.get("table"):
        raise RuntimeError(
            f"source manifest table declaration mismatch for {artifact_id}"
        )
    required_columns = [str(value) for value in artifact["required_columns"]]
    declared_columns = declaration.get("required_columns")
    if declared_columns is None or list(declared_columns) != required_columns:
        raise RuntimeError(
            f"source manifest required columns mismatch for {artifact_id}"
        )
    table = str(artifact["table"])
    if not IDENTIFIER_PATTERN.fullmatch(table):
        raise RuntimeError(
            f"unsafe declared table identifier for {artifact_id}: {table}"
        )
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("duckdb is required for formal input binding") from exc
    connection = duckdb.connect(str(path), read_only=True)
    try:
        table_exists = connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [table],
        ).fetchone()[0]
        if int(table_exists) != 1:
            raise RuntimeError(f"declared table is missing for {artifact_id}: {table}")
        actual_columns = [
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()
        ]
        missing_columns = sorted(set(required_columns) - set(actual_columns))
        if missing_columns:
            raise RuntimeError(
                f"required columns are missing for {artifact_id}: {missing_columns}"
            )
        full_row_count = int(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        )
        if full_row_count != int(declaration["row_count"]):
            raise RuntimeError(
                f"source manifest row count mismatch for {artifact_id}: "
                f"declared={declaration['row_count']} actual={full_row_count}"
            )
        return {
            "artifact_id": artifact_id,
            "table": table,
            "actual_columns": actual_columns,
            "source_full_row_count": full_row_count,
            "sha256": actual_hash,
        }
    finally:
        connection.close()


def validate_expected_index_reconciliation(
    *,
    candidate_path: Path,
    candidate_artifact: Mapping[str, Any],
    index_path: Path,
    index_artifact: Mapping[str, Any],
    dense_contract: Mapping[str, Any],
) -> dict[str, int]:
    """Validate index ordering and exact main-table/index key reconciliation."""

    candidate_table = str(candidate_artifact["table"])
    index_table = str(index_artifact["table"])
    for table in (candidate_table, index_table):
        if not IDENTIFIER_PATTERN.fullmatch(table):
            raise RuntimeError(
                f"unsafe table identifier in dense reconciliation: {table}"
            )
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for dense index validation") from exc
    connection = duckdb.connect(":memory:")
    try:
        candidate_literal = str(candidate_path).replace("'", "''")
        index_literal = str(index_path).replace("'", "''")
        connection.execute(f"ATTACH '{candidate_literal}' AS candidate (READ_ONLY)")
        connection.execute(f"ATTACH '{index_literal}' AS expected (READ_ONLY)")
        statuses = sorted(set(str(value) for value in dense_contract["statuses"]))
        if set(statuses) != EXPECTED_INDEX_STATUSES:
            raise RuntimeError("dense index status vocabulary mismatch")

        errors: dict[str, int] = {}
        schema_rows = connection.execute(
            f"PRAGMA table_info('expected.{index_table}')"
        ).fetchall()
        schema_types = {str(row[1]): str(row[2]).upper() for row in schema_rows}
        sequence_type = schema_types.get("observation_sequence", "")
        date_type = schema_types.get("trading_date", "")
        errors["index_sequence_type_invalid"] = int(
            not any(token in sequence_type for token in ("INT", "DECIMAL", "HUGEINT"))
        )
        errors["index_date_type_invalid"] = int(
            not any(
                token in date_type for token in ("DATE", "TIMESTAMP", "VARCHAR", "TEXT")
            )
        )
        candidate_date_expr = _canonical_sql_date_expression("m.trade_date")
        index_date_expr = _canonical_sql_date_expression("i.trading_date")
        errors["invalid_index_identity"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM expected.{index_table}
            WHERE security_id IS NULL OR trim(CAST(security_id AS VARCHAR)) = ''
               OR trading_date IS NULL
               OR observation_sequence IS NULL
            """,
        )
        errors["invalid_index_sequence_value"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM expected.{index_table}
            WHERE try_cast(observation_sequence AS DECIMAL(38, 10)) IS NULL
               OR try_cast(observation_sequence AS DECIMAL(38, 10)) < 0
               OR try_cast(observation_sequence AS DECIMAL(38, 10))
                    != floor(try_cast(observation_sequence AS DECIMAL(38, 10)))
            """,
        )
        errors["invalid_index_date"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM expected.{index_table} AS i
            WHERE {index_date_expr} IS NULL
            """,
        )
        errors["invalid_main_date"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM candidate.{candidate_table} AS m
            WHERE {candidate_date_expr} IS NULL
            """,
        )
        errors["duplicate_index_security_date"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM (
              SELECT security_id, canonical_date
              FROM (
                SELECT i.security_id, {index_date_expr} AS canonical_date
                FROM expected.{index_table} AS i
                WHERE {index_date_expr} IS NOT NULL
              ) canonical_index
              GROUP BY 1, 2 HAVING count(*) > 1
            )
            """,
        )
        errors["duplicate_index_security_sequence"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM (
              SELECT security_id, observation_sequence
              FROM expected.{index_table}
              GROUP BY 1, 2 HAVING count(*) > 1
            )
            """,
        )
        errors["invalid_index_status"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM expected.{index_table}
            WHERE expected_observation_status NOT IN (
                'present', 'listing_pause', 'missing', 'unresolved'
            )
               OR expected_observation_status IS NULL
            """,
        )
        expected_source_contract = str(index_artifact["source_contract"]).replace(
            "'", "''"
        )
        errors["empty_index_source_contract"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM expected.{index_table}
            WHERE source_contract IS NULL OR trim(source_contract) = ''
               OR source_contract != '{expected_source_contract}'
            """,
        )
        errors["empty_index_source_ref"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM expected.{index_table}
            WHERE source_ref IS NULL OR trim(source_ref) = ''
            """,
        )
        errors["non_monotonic_index_sequence"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM (
              SELECT observation_sequence,
                     lag(observation_sequence) OVER (
                       PARTITION BY security_id ORDER BY observation_sequence
                     ) AS previous_sequence
              FROM (
                SELECT security_id,
                       try_cast(observation_sequence AS DECIMAL(38, 10))
                         AS observation_sequence
                FROM expected.{index_table}
              ) ordered_index
            )
            WHERE previous_sequence IS NOT NULL
              AND observation_sequence != previous_sequence + 1
            """,
        )
        errors["non_monotonic_index_date"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM (
              SELECT canonical_date,
                     lag(canonical_date) OVER (
                       PARTITION BY security_id ORDER BY observation_sequence
                     ) AS previous_date
              FROM (
                SELECT security_id,
                       observation_sequence,
                       {index_date_expr} AS canonical_date
                FROM expected.{index_table} AS i
              ) ordered_index
            )
            WHERE previous_date IS NOT NULL AND canonical_date <= previous_date
            """,
        )
        errors["main_duplicate_security_date"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM (
              SELECT ts_code, canonical_date
              FROM (
                SELECT m.ts_code, {candidate_date_expr} AS canonical_date
                FROM candidate.{candidate_table} AS m
                WHERE {candidate_date_expr} IS NOT NULL
              ) canonical_candidate
              GROUP BY 1, 2 HAVING count(*) > 1
            )
            """,
        )
        errors["main_invalid_identity"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM candidate.{candidate_table}
            WHERE ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = ''
               OR trade_date IS NULL
            """,
        )
        errors["main_listing_pause_row_present"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM candidate.{candidate_table}
            WHERE is_listing_pause IS NOT FALSE
            """,
        )
        errors["main_source_task_invalid"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM candidate.{candidate_table}
            WHERE source_task_id IS NULL OR source_task_id != 'D2-T20'
            """,
        )
        errors["main_generated_by_task_invalid"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM candidate.{candidate_table}
            WHERE generated_by_task IS NULL OR generated_by_task != 'D3-T07'
            """,
        )
        errors["main_row_provenance_missing"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM candidate.{candidate_table}
            WHERE row_provenance IS NULL OR trim(row_provenance) = ''
            """,
        )
        errors["main_effective_factor_invalid"] = _scalar_count(
            connection,
            f"""
            SELECT count(*) FROM candidate.{candidate_table}
            WHERE effective_adj_factor IS NULL
               OR NOT isfinite(effective_adj_factor)
               OR effective_adj_factor <= 0
            """,
        )
        errors["main_key_not_present_index"] = _scalar_count(
            connection,
            f"""
            SELECT count(*)
            FROM candidate.{candidate_table} m
            LEFT JOIN expected.{index_table} i
              ON i.security_id = m.ts_code
             AND {index_date_expr} = {candidate_date_expr}
             AND i.expected_observation_status = 'present'
            WHERE i.security_id IS NULL
            """,
        )
        errors["present_index_key_missing_main"] = _scalar_count(
            connection,
            f"""
            SELECT count(*)
            FROM expected.{index_table} i
            LEFT JOIN candidate.{candidate_table} m
              ON m.ts_code = i.security_id
             AND {candidate_date_expr} = {index_date_expr}
            WHERE i.expected_observation_status = 'present'
              AND m.ts_code IS NULL
            """,
        )
        errors["non_present_index_key_in_main"] = _scalar_count(
            connection,
            f"""
            SELECT count(*)
            FROM expected.{index_table} i
            JOIN candidate.{candidate_table} m
              ON m.ts_code = i.security_id
             AND {candidate_date_expr} = {index_date_expr}
            WHERE i.expected_observation_status != 'present'
            """,
        )
        errors["index_row_count"] = _scalar_count(
            connection, f"SELECT count(*) FROM expected.{index_table}"
        )
        errors["main_row_count"] = _scalar_count(
            connection, f"SELECT count(*) FROM candidate.{candidate_table}"
        )
        if errors["index_row_count"] <= 0:
            errors["empty_index"] = 1
        failures = {
            key: value
            for key, value in errors.items()
            if value > 0 and key not in {"index_row_count", "main_row_count"}
        }
        if failures:
            raise RuntimeError(f"expected_index_reconcile_failed: {failures}")
        return errors
    finally:
        connection.close()


def _validate_d3_t07_evidence(
    *,
    candidate_path: Path,
    candidate_artifact: Mapping[str, Any],
    quality: Mapping[str, Any],
    handoff: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> None:
    _require_equal(quality, "task_id", "D3-T07", "D3-T07 quality")
    _require_equal(quality, "source_task_id", "D2-T20", "D3-T07 quality")
    _require_equal(handoff, "task_id", "D3-T07", "D3-T07 handoff")
    _require_equal(handoff, "source_task_id", "D2-T20", "D3-T07 handoff")
    accepted = set(gate["accepted_generation_decisions"])
    if handoff.get("d3_t07_generation_decision") not in accepted:
        raise RuntimeError("D3-T07 handoff generation decision is not accepted")
    if quality.get("candidate_generation_decision") not in accepted:
        raise RuntimeError("D3-T07 quality generation decision is not accepted")
    _require_true(handoff, gate["generated_field"], "D3-T07 handoff")
    _require_true(quality, "candidate_observation_generated", "D3-T07 quality")
    _require_false(handoff, gate["formal_data_version_field"], "D3-T07 handoff")
    for field in gate["forbidden_true_fields"]:
        _require_false(handoff, field, "D3-T07 handoff")
    for field in gate["quality_blockers"]:
        _require_zero(quality, field, "D3-T07 quality")

    _validate_candidate_main_table(
        candidate_path, candidate_artifact, gate["main_table_identity"]
    )


def _validate_candidate_main_table(
    path: Path, artifact: Mapping[str, Any], identity: Mapping[str, Any]
) -> None:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is required for D3-T07 table validation") from exc
    table = str(artifact["table"])
    connection = duckdb.connect(str(path), read_only=True)
    try:
        source_task_id = str(identity["source_task_id"]).replace("'", "''")
        generated_by_task = str(identity["generated_by_task"]).replace("'", "''")
        predicates = {
            "source_task_id_invalid": (
                f"source_task_id IS NULL OR source_task_id != '{source_task_id}'"
            ),
            "generated_by_task_invalid": (
                "generated_by_task IS NULL OR "
                f"generated_by_task != '{generated_by_task}'"
            ),
            "row_provenance_missing": (
                "row_provenance IS NULL OR trim(row_provenance) = ''"
            ),
            "listing_pause_present": "is_listing_pause IS NOT FALSE",
            "effective_factor_invalid": (
                "effective_adj_factor IS NULL OR "
                "NOT isfinite(effective_adj_factor) OR "
                "effective_adj_factor <= 0"
            ),
        }
        failures = {
            key: _scalar_count(
                connection, f"SELECT count(*) FROM {table} WHERE {predicate}"
            )
            for key, predicate in predicates.items()
        }
        if any(value > 0 for value in failures.values()):
            raise RuntimeError(f"D3-T07 main table gate failed: {failures}")
    finally:
        connection.close()


def _require_equal(
    payload: Mapping[str, Any], field: str, expected: Any, label: str
) -> None:
    if payload.get(field) != expected:
        raise RuntimeError(
            f"{label} {field} mismatch: expected={expected!r} "
            f"actual={payload.get(field)!r}"
        )


def _require_true(payload: Mapping[str, Any], field: str, label: str) -> None:
    if payload.get(field) is not True:
        raise RuntimeError(f"{label} {field} must be true")


def _require_false(payload: Mapping[str, Any], field: str, label: str) -> None:
    if payload.get(field) is not False:
        raise RuntimeError(f"{label} {field} must be false")


def _require_zero(payload: Mapping[str, Any], field: str, label: str) -> None:
    if field not in payload:
        raise RuntimeError(f"{label} blocker field is missing: {field}")
    try:
        value = int(payload[field])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} blocker is not numeric: {field}") from exc
    if value != 0:
        raise RuntimeError(f"{label} blocker is nonzero: {field}={value}")


def _scalar_count(connection: Any, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0] or 0)


def _canonical_sql_date_expression(column: str) -> str:
    """Return the only accepted YYYY-MM-DD/YYYYMMDD-to-DATE SQL expression."""

    if not QUALIFIED_COLUMN_PATTERN.fullmatch(column):
        raise ValueError(f"unsafe SQL date column: {column!r}")
    return (
        "CAST(COALESCE("
        f"try_strptime(CAST({column} AS VARCHAR), '%Y-%m-%d'), "
        f"try_strptime(CAST({column} AS VARCHAR), '%Y%m%d')"
        ") AS DATE)"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_declaration(
    manifest: Mapping[str, Any], name: str
) -> Mapping[str, Any] | None:
    for key in ("input_artifacts", "artifacts"):
        value = manifest.get(key)
        if isinstance(value, Mapping) and isinstance(value.get(name), Mapping):
            return value[name]
    return None


def _current_git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _validate_authorized_manifest_schema(manifest: Mapping[str, Any]) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "jsonschema is required for input manifest validation"
        ) from exc
    schema_raw = AUTHORIZED_MANIFEST_SCHEMA.read_bytes()
    schema_errors = canonical_text_errors(schema_raw)
    if schema_errors:
        raise RuntimeError(
            f"authorized input manifest schema is not canonical: {schema_errors}"
        )
    schema = load_json(AUTHORIZED_MANIFEST_SCHEMA)
    try:
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                manifest
            ),
            key=lambda item: list(item.path),
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"authorized input manifest schema validation failed: {exc}")
    if errors:
        raise RuntimeError(
            "authorized input manifest schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def _validate_manifest_authorization_bindings(manifest: Mapping[str, Any]) -> None:
    if manifest.get("authorized_for_task") != TASK_ID:
        raise RuntimeError("authorized input manifest task authorization mismatch")
    if manifest.get("authorized_research_candidate_input") is not True:
        raise RuntimeError(
            "authorized input manifest is not a research-candidate authorization"
        )
    if manifest.get("formal_data_version") is not False:
        raise RuntimeError(
            "authorized input manifest formal_data_version must be false"
        )
    authorization = manifest.get("authorization")
    if not isinstance(authorization, Mapping):
        raise RuntimeError("authorized input manifest authorization is missing")
    if authorization.get("authorization_status") != "authorized_for_exp_a01":
        raise RuntimeError("authorized input manifest authorization status is invalid")
    if not str(authorization.get("authorization_evidence", "")).strip():
        raise RuntimeError("authorized input manifest authorization evidence is empty")
    governance = manifest.get("input_governance")
    if not isinstance(governance, Mapping):
        raise RuntimeError("authorized input manifest input governance is missing")
    if governance.get("d3_t08_required") is not False:
        raise RuntimeError("authorized input manifest D3-T08 required flag is invalid")
    if governance.get("owner_override") is not True:
        raise RuntimeError("authorized input manifest D3-T08 owner override is invalid")
    if not str(governance.get("override_reason", "")).strip():
        raise RuntimeError("authorized input manifest D3-T08 override reason is empty")
    expected = {
        "d3_t07_candidate_daily_observation",
        "d3_t07_handoff_report",
        "d3_t07_quality_report",
        "expected_price_observation_index",
    }
    artifacts = manifest.get("input_artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != expected:
        raise RuntimeError(
            "authorized input manifest must declare exactly four artifacts"
        )
    bindings = manifest.get("cross_artifact_bindings")
    if not isinstance(bindings, Mapping):
        raise RuntimeError(
            "authorized input manifest cross-artifact bindings are missing"
        )


def _validate_cross_artifact_bindings(
    manifest: Mapping[str, Any], declarations: Mapping[str, Mapping[str, Any]]
) -> None:
    bindings = manifest["cross_artifact_bindings"]
    expected = {
        "d3_t07_candidate_sha256": "d3_t07_candidate_daily_observation",
        "d3_t07_quality_sha256": "d3_t07_quality_report",
        "d3_t07_handoff_sha256": "d3_t07_handoff_report",
        "expected_index_sha256": "expected_price_observation_index",
    }
    for binding_name, artifact_id in expected.items():
        if bindings.get(binding_name) != declarations[artifact_id].get("sha256"):
            raise RuntimeError(
                f"authorized input manifest cross-artifact binding mismatch: {binding_name}"
            )


def _validate_committed_source_bindings(reviewed_sha: str) -> dict[str, Any]:
    """Bind formal source lineage to Git objects and compare clean worktree bytes."""

    bindings: dict[str, Any] = {}
    for relative in FORMAL_SOURCE_PATHS:
        try:
            blob_sha = subprocess.run(
                ["git", "rev-parse", f"{reviewed_sha}:{relative}"],
                cwd=str(ROOT),
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            committed = subprocess.run(
                ["git", "show", f"{reviewed_sha}:{relative}"],
                cwd=str(ROOT),
                check=True,
                capture_output=True,
            ).stdout
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"formal source binding is missing from reviewed commit: {relative}"
            ) from exc
        if not isinstance(committed, bytes):
            raise RuntimeError(f"Git source bytes were not returned for {relative}")
        current_path = ROOT / relative
        if not current_path.is_file() or current_path.read_bytes() != committed:
            raise RuntimeError(
                f"working-tree source differs from reviewed Git blob: {relative}"
            )
        text_errors = canonical_text_errors(committed)
        if text_errors:
            raise RuntimeError(
                f"reviewed formal source is not canonical UTF-8/LF: {relative}: {text_errors}"
            )
        bindings[relative] = {
            "source_commit": reviewed_sha,
            "git_blob_sha": blob_sha,
            "committed_byte_sha256": hashlib.sha256(committed).hexdigest(),
            "normalized_text_sha256": hashlib.sha256(
                committed.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            ).hexdigest(),
            "encoding": "UTF-8",
            "line_ending": "LF",
            "BOM": False,
            "final_LF_count": len(committed) - len(committed.rstrip(b"\n")),
        }
    return bindings


def _build_formal_manifest(
    *,
    gate: Mapping[str, Any],
    args: argparse.Namespace,
    started_at: str,
    finished_at: str | None,
    staging: Path,
    raw_metadata: Mapping[str, Any],
    profile_metadata: Mapping[str, Mapping[str, Any]],
    validator_status: str,
    anomaly_status: str,
) -> dict[str, Any]:
    output_artifacts: dict[str, Any] = {}
    raw_path = staging / "exp_a01_raw_metrics.duckdb"
    output_artifacts[raw_path.name] = {
        "path": raw_path.name,
        "sha256": sha256_file(raw_path),
        "row_count": raw_metadata["row_count"],
    }
    for filename, metadata in profile_metadata.items():
        path = staging / filename
        output_artifacts[filename] = {
            "path": filename,
            "sha256": sha256_file(path),
            "row_count": metadata["row_count"],
        }
    analysis_path = staging / "exp_a01_result_analysis.md"
    if analysis_path.exists():
        output_artifacts[analysis_path.name] = {
            "path": analysis_path.name,
            "sha256": sha256_file(analysis_path),
            "row_count": len(analysis_path.read_text(encoding="utf-8").splitlines()),
        }
    input_metadata = {
        artifact_id: {key: value for key, value in metadata.items() if key != "json"}
        for artifact_id, metadata in gate["input_metadata"].items()
    }
    return {
        "task_id": TASK_ID,
        "program_id": "EXP-A",
        "run_id": gate["run_id"],
        "phase": "formal_run",
        "implementation_sha": gate["reviewed_sha"],
        "reviewed_implementation_sha": gate["reviewed_sha"],
        "formal_data_version": False,
        "started_at": started_at,
        "finished_at": finished_at,
        "parallel_mode": "single_threaded",
        "worker_count": 1,
        "duckdb_threads": 1,
        "memory_limit": args.memory_limit,
        "random_seed": None,
        "config": {
            "path": str(gate["config_path"].relative_to(ROOT)).replace("\\", "/"),
            "sha256": gate["source_bindings"][
                "configs/sidecar/exp_a01_price_ma_attachment_candidates.v1.json"
            ]["committed_byte_sha256"],
        },
        "source_bindings": gate["source_bindings"],
        "input_manifest_path": str(gate["input_manifest_path"]),
        "input_manifest_sha256": gate["input_manifest_sha256"],
        "input_artifact_declarations": gate["input_declarations"],
        "input_artifact_actual_metadata": input_metadata,
        "dense_reconciliation_counts": gate["expected_index_reconciliation"],
        "candidate_ids": [
            candidate["indicator_id"] for candidate in gate["config"]["candidates"]
        ],
        "parameters": gate["config"]["parameters"],
        "raw_metric_table": raw_metadata,
        "output_artifacts": output_artifacts,
        "validator_status": validator_status,
        "anomaly_status": anomaly_status,
        "governance_files": [
            "exp_a01_validator_result.json",
            "exp_a01_anomaly_scan.json",
        ],
        "prohibited_outputs": gate["config"]["output_contract"][
            "forbidden_output_fields"
        ],
    }


def _build_result_analysis(
    *,
    gate: Mapping[str, Any],
    args: argparse.Namespace,
    started_at: str,
    finished_at: str,
    raw_metadata: Mapping[str, Any],
    validation: Mapping[str, Any],
    anomaly: Mapping[str, Any],
    staging: Path,
) -> str:
    profile_path = staging / "exp_a01_metric_profile.csv"
    with profile_path.open(encoding="utf-8", newline="") as profile_handle:
        profile_rows = list(csv.DictReader(profile_handle))
    readiness = (
        "ready_for_user_formal_result_review"
        if validation.get("status") == "passed" and anomaly.get("status") == "passed"
        else "needs_investigation_before_user_review"
    )
    valid_summary = "; ".join(
        f"{row.get('indicator_id')}: valid_count={row.get('valid_count')}, "
        f"valid_rate={row.get('valid_rate')}"
        for row in profile_rows
    )
    sections = [
        "# EXP-A01 formal result analysis",
        "",
        "## 1. Actual run / reviewed SHA",
        f"run_id: {gate['run_id']}",
        f"reviewed_implementation_sha: {gate['reviewed_sha']}",
        f"started_at: {started_at}",
        f"finished_at: {finished_at}",
        "parallel_mode: single_threaded; worker_count: 1",
        f"memory_limit: {args.memory_limit}",
        "",
        "## 2. Input manifest and authorization",
        f"input_manifest_sha256: {gate['input_manifest_sha256']}",
        "authorized_for_task: EXP-A01; authorized_research_candidate_input: true",
        "formal_data_version: false",
        "",
        "## 3. D3-T07 lineage",
        "The D3-T07 candidate, handoff and quality evidence passed their declared source, role and quality gates.",
        "",
        "## 4. Input governance override",
        "D3-T08 is explicitly not required for EXP-A01 under the owner-approved four-artifact input contract; no D3-T08 evidence is used or synthesized.",
        "",
        "## 5. Dense expected-index reconciliation",
        json.dumps(
            gate["expected_index_reconciliation"], ensure_ascii=False, sort_keys=True
        ),
        "",
        "## 6. Fixed candidate definitions",
        "A1, A2 and A2b use the frozen current-day-inclusive adjusted-price definitions, MA windows and dense slot counts.",
        "",
        "## 7. Raw table cardinality",
        f"raw_table_rows: {raw_metadata['row_count']}; expected_index_rows: {raw_metadata['expected_index_row_count']}; expected_raw_rows: {raw_metadata['expected_row_count']}",
        "Each expected slot has exactly three persisted indicator rows.",
        "",
        "## 8. Metric domains and distributions",
        valid_summary or "No metric profile rows were available.",
        "",
        "## 9. Validity status profile",
        "The persisted validity profile is checked independently against the raw table.",
        "",
        "## 10. Reason-code profile",
        "Reason-code counts are derived from the canonical compact JSON arrays and are not interpreted as additional metrics.",
        "",
        "## 11. Year coverage",
        "The year coverage table reports every observed calendar year and candidate.",
        "",
        "## 12. Security coverage",
        "The security coverage table reports every observed security and candidate.",
        "",
        "## 13. Independent full recomputation",
        "The independent validator recomputed every persisted raw row from the two input DuckDBs and compared values, statuses, reasons and windows within the declared 1e-12 tolerances.",
        f"comparison_counts: {json.dumps(validation.get('comparison_counts', {}), sort_keys=True)}",
        "",
        "## 14. Validator result",
        f"status: {validation.get('status')}; valid: {validation.get('valid')}; errors: {len(validation.get('errors', []))}",
        "",
        "## 15. Anomaly scan",
        f"status: {anomaly.get('status')}; blocking_anomaly_count: {anomaly.get('blocking_anomaly_count')}; investigation_item_count: {anomaly.get('investigation_item_count')}",
        "",
        "## 16. Supported and unsupported conclusions",
        "This package supports statements about raw-metric materialization, numeric domains, validity, coverage and persisted-result integrity only. It does not establish downstream selection or later-stage decisions.",
        "",
        "## 17. Readiness for user Formal-result review",
        f"{readiness}",
        "",
    ]
    return "\n".join(sections)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--allow-formal-run", action="store_true")
    parser.add_argument("--reviewed-implementation-sha")
    parser.add_argument("--memory-limit", default="8GB")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
