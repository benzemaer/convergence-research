"""Fail-closed future formal-run gate for EXP-A01.

This implementation phase validates the complete input lineage and dense
window contract, then stops deliberately.  It never creates a formal output
directory and never executes the large-data metric run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sidecar.exp_a01_price_ma_attachment import TASK_ID  # noqa: E402
from src.sidecar.exp_a01_price_ma_attachment_validator import (  # noqa: E402
    canonical_text_errors,
    load_json,
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
    """Validate every future formal-run precondition, then stop by design."""

    gate = validate_formal_gate(args)
    raise RuntimeError(
        "formal_run_not_implemented_in_implementation_phase; "
        f"validated_run_id={gate['run_id']}"
    )


def validate_formal_gate(args: argparse.Namespace) -> dict[str, Any]:
    """Validate code, manifest, evidence, tables, and dense-index lineage."""

    if not args.allow_formal_run:
        raise RuntimeError("formal_run_not_allowed_without_--allow-formal-run")
    reviewed_sha = str(args.reviewed_implementation_sha or "")
    if not SHA_PATTERN.fullmatch(reviewed_sha):
        raise RuntimeError(
            "reviewed_implementation_sha must be an exact 40-character SHA"
        )

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
    if manifest.get("task_id") not in (None, TASK_ID):
        raise RuntimeError("source manifest task_id does not match EXP-A01")

    run_id = str(args.run_id or "")
    if not run_id or Path(run_id).name != run_id:
        raise RuntimeError("run-id must be a non-empty single path component")
    output_root = Path(args.output_root).resolve()
    if output_root.name != run_id:
        raise RuntimeError("output-root basename must equal run-id")
    if output_root.exists():
        raise RuntimeError(f"output directory must be new and absent: {output_root}")

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

    _validate_d3_t07_evidence(
        candidate_path=paths["d3_t07_candidate_daily_observation"],
        candidate_artifact=artifacts["d3_t07_candidate_daily_observation"],
        quality=metadata["d3_t07_quality_report"]["json"],
        handoff=metadata["d3_t07_handoff_report"]["json"],
        gate=config["d3_t07_evidence_gate"],
    )
    _validate_d3_t08_evidence(
        quality=metadata["d3_t08_quality_report"]["json"],
        handoff=metadata["d3_t08_handoff_report"]["json"],
        gate=config["d3_t08_evidence_gate"],
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
        "status": "gate_passed_formal_not_executed",
        "run_id": run_id,
        "reviewed_implementation_sha": reviewed_sha,
        "input_manifest_path": str(manifest_path),
        "input_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "input_paths": {key: str(value) for key, value in paths.items()},
        "input_metadata": metadata,
        "expected_index_reconciliation": index_reconciliation,
        "output_root": str(output_root),
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


def _validate_d3_t08_evidence(
    *, quality: Mapping[str, Any], handoff: Mapping[str, Any], gate: Mapping[str, Any]
) -> None:
    _require_equal(quality, "task_id", "D3-T08", "D3-T08 quality")
    _require_equal(quality, "source_task_id", "D3-T07", "D3-T08 quality")
    _require_equal(handoff, "task_id", "D3-T08", "D3-T08 handoff")
    _require_equal(handoff, "source_task_id", "D3-T07", "D3-T08 handoff")
    accepted = set(gate["accepted_generation_decisions"])
    if quality.get("d3_t08_generation_decision") not in accepted:
        raise RuntimeError("D3-T08 quality generation decision is not accepted")
    if handoff.get("d3_t08_generation_decision") not in accepted:
        raise RuntimeError("D3-T08 handoff generation decision is not accepted")
    _require_true(quality, gate["generated_field"], "D3-T08 quality")
    _require_true(handoff, gate["generated_field"], "D3-T08 handoff")
    _require_false(handoff, gate["formal_data_version_field"], "D3-T08 handoff")
    for field in gate["forbidden_true_fields"]:
        _require_false(handoff, field, "D3-T08 handoff")
    for field in gate["quality_blockers"]:
        _require_zero(quality, field, "D3-T08 quality")


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input-root", type=Path)
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--allow-formal-run", action="store_true")
    parser.add_argument("--reviewed-implementation-sha")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
