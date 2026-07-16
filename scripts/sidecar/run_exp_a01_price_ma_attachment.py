"""Fail-closed future formal-run gate for EXP-A01.

The implementation commit only provides the gate.  It never creates a formal
output directory and never executes the future large-data metric run.
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
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
    """Validate the formal-run boundary without creating output or querying rows."""

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

    artifact = config["input_contract"]["artifacts"]["adjusted_ohlc"]
    declaration = _extract_declaration(manifest, "adjusted_ohlc")
    if declaration is None:
        raise RuntimeError("source manifest does not declare adjusted_ohlc")
    path = resolve_declared_input_path(
        manifest_path,
        input_root,
        declaration,
        artifact,
    )
    metadata = inspect_input_artifact(path, artifact, declaration)
    return {
        "task_id": TASK_ID,
        "status": "gate_passed_formal_not_executed",
        "run_id": run_id,
        "reviewed_implementation_sha": reviewed_sha,
        "input_manifest_path": str(manifest_path),
        "input_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "input_path": str(path),
        "input_metadata": metadata,
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
                "declared adjusted_ohlc path is missing and relocation is not "
                "authorized: "
                f"{candidate}"
            )
        candidate = input_root / declared_path.name
    if not candidate.is_file():
        raise RuntimeError(f"declared adjusted_ohlc input is missing: {candidate}")
    if declaration.get("table") != artifact.get("table"):
        raise RuntimeError(
            "source manifest table declaration does not match implementation contract"
        )
    return candidate.resolve()


def inspect_input_artifact(
    path: Path,
    artifact: Mapping[str, Any],
    declaration: Mapping[str, Any],
) -> dict[str, Any]:
    """Check hash, table identity, complete row count, and required columns."""

    for field in ("sha256", "row_count", "table"):
        if field not in declaration or declaration[field] in (None, ""):
            raise RuntimeError(f"source manifest declaration missing {field}")
    actual_hash = sha256_file(path)
    if actual_hash != declaration["sha256"]:
        raise RuntimeError(
            "source manifest hash mismatch: "
            f"declared={declaration['sha256']} actual={actual_hash}"
        )
    table = str(artifact["table"])
    if not IDENTIFIER_PATTERN.fullmatch(table):
        raise RuntimeError(f"unsafe declared table identifier: {table}")
    required_columns = [str(value) for value in artifact["required_columns"]]
    declared_columns = declaration.get("required_columns")
    if declared_columns is not None and list(declared_columns) != required_columns:
        raise RuntimeError("source manifest required columns mismatch")

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
            raise RuntimeError(f"declared table is missing: {table}")
        actual_columns = [
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        ]
        missing_columns = sorted(set(required_columns) - set(actual_columns))
        if missing_columns:
            raise RuntimeError(f"required columns are missing: {missing_columns}")
        full_row_count = int(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        )
        if full_row_count != int(declaration["row_count"]):
            raise RuntimeError(
                "source manifest row count mismatch: "
                f"declared={declaration['row_count']} actual={full_row_count}"
            )
        return {
            "table": table,
            "actual_columns": actual_columns,
            "source_full_row_count": full_row_count,
            "sha256": actual_hash,
        }
    finally:
        connection.close()


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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
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
