"""Terminal, read-only validation for the R3-T01 result package.

The terminal validator runs after the analyzer has written the manifest.  It
does not rebuild production results, invoke the independent replay, or modify
any bound artifact.  Its only write is the sidecar named by the protocol
registry, which is intentionally excluded from the manifest hash set.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from src.common.canonical_io import read_csv, write_json

ROOT = Path(__file__).resolve().parents[2]
SIDECAR = "r3_t01_final_validation.json"
MANIFEST = "r3_t01_manifest.json"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _error(errors: list[dict[str, str]], code: str, message: str = "") -> None:
    errors.append({"code": code, "message": message})


def _git_bytes(root: Path, source_commit: str, relative_path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{source_commit}:{relative_path}"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def _is_commit(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(char in "0123456789abcdef" for char in value.lower())
    )


def _row_count(path: Path, kind: str, value: Any | None = None) -> int | None:
    if kind == "csv":
        return len(read_csv(path))
    if kind != "json" or value is None:
        return None
    if isinstance(value, dict) and isinstance(value.get("cases"), list):
        return len(value["cases"])
    if isinstance(value, list):
        return len(value)
    return None


def _validate_source_binding(
    root: Path,
    binding: Any,
    errors: list[dict[str, str]],
    formal_execution_sha: str | None,
) -> None:
    if not isinstance(binding, dict):
        _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", "binding")
        return
    path = root / str(binding.get("path", ""))
    try:
        payload = path.read_bytes()
    except OSError:
        _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", str(path))
        return
    if _sha_bytes(payload) != binding.get("sha256"):
        _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", str(path))
    if len(payload) != binding.get("size_bytes"):
        _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", str(path))
    source_commit = binding.get("source_commit")
    if source_commit is None:
        if _is_commit(formal_execution_sha):
            _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", str(path))
        return
    committed = _git_bytes(root, str(source_commit), str(binding.get("path")))
    if committed is None or _sha_bytes(committed) != binding.get(
        "committed_byte_sha256"
    ):
        _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", str(path))
        return
    if binding.get("git_blob_sha"):
        result = subprocess.run(
            ["git", "rev-parse", f"{source_commit}:{binding['path']}"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or result.stdout.strip() != binding.get(
            "git_blob_sha"
        ):
            _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", str(path))
    try:
        decoded = committed.decode("utf-8")
    except UnicodeDecodeError:
        _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", str(path))
        return
    normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
    terminal_lf_count = len(committed) - len(committed.rstrip(b"\n"))
    if (
        _sha_bytes(normalized.encode("utf-8")) != binding.get("normalized_text_sha256")
        or binding.get("encoding") != "utf-8"
        or binding.get("line_ending") != "lf"
        or binding.get("bom") is not False
        or binding.get("terminal_lf_count") != terminal_lf_count
    ):
        _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", str(path))


def _validate_manifest_artifacts(
    run_dir: Path,
    root: Path,
    config: dict[str, Any],
    manifest: dict[str, Any],
    errors: list[dict[str, str]],
) -> int:
    declarations = {
        item["filename"]: item
        for item in config.get("output_contract", {}).get("formal_artifacts", [])
        if isinstance(item, dict)
    }
    expected_paths = set(declarations) - {MANIFEST, SIDECAR}
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or not entries:
        _error(errors, "FINAL_VALIDATION_MANIFEST_MISSING", "artifacts")
        return 0
    actual_paths = {str(item.get("path")) for item in entries if isinstance(item, dict)}
    if actual_paths != expected_paths:
        _error(errors, "FINAL_VALIDATION_MANIFEST_MISSING", "artifact_set")
    for entry in entries:
        if not isinstance(entry, dict):
            _error(errors, "FINAL_VALIDATION_MANIFEST_MISSING", "artifact_entry")
            continue
        name = str(entry.get("path"))
        declaration = declarations.get(name)
        path = run_dir / name
        if declaration is None:
            _error(errors, "FINAL_VALIDATION_MANIFEST_MISSING", name)
            continue
        if entry.get("artifact_owner") != declaration.get(
            "artifact_owner"
        ) or entry.get("kind") != declaration.get("kind"):
            _error(
                errors, "FINAL_VALIDATION_ARTIFACT_HASH_MISMATCH", f"metadata:{name}"
            )
        if not path.is_file():
            _error(errors, "FINAL_VALIDATION_ARTIFACT_HASH_MISMATCH", name)
            _error(errors, "FINAL_VALIDATION_TAMPER_DETECTED", name)
            continue
        payload = path.read_bytes()
        if _sha_bytes(payload) != entry.get("artifact_sha256"):
            _error(errors, "FINAL_VALIDATION_ARTIFACT_HASH_MISMATCH", name)
            _error(errors, "FINAL_VALIDATION_TAMPER_DETECTED", name)
        if len(payload) != entry.get("size_bytes"):
            _error(errors, "FINAL_VALIDATION_ARTIFACT_SIZE_MISMATCH", name)
            _error(errors, "FINAL_VALIDATION_TAMPER_DETECTED", name)
        value: Any | None = None
        try:
            if declaration.get("kind") == "json":
                value = _load_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            _error(errors, "FINAL_VALIDATION_ARTIFACT_HASH_MISMATCH", name)
        actual_rows = _row_count(path, str(declaration.get("kind")), value)
        if entry.get("row_count") is not None and actual_rows != entry.get("row_count"):
            _error(errors, "FINAL_VALIDATION_ARTIFACT_ROW_COUNT_MISMATCH", name)
            _error(errors, "FINAL_VALIDATION_TAMPER_DETECTED", name)
        schema_path = entry.get("schema_path")
        schema_hash = entry.get("schema_sha256")
        if (schema_path is None) != (schema_hash is None):
            _error(errors, "FINAL_VALIDATION_MANIFEST_MISSING", f"schema:{name}")
        elif schema_path is not None:
            schema_file = root / str(schema_path)
            try:
                schema_bytes = schema_file.read_bytes()
            except OSError:
                _error(
                    errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", str(schema_file)
                )
            else:
                if _sha_bytes(schema_bytes) != schema_hash:
                    _error(
                        errors,
                        "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH",
                        str(schema_file),
                    )
    return len(entries)


def _validate_approval(
    config: dict[str, Any],
    upstream: dict[str, Any],
    manifest: dict[str, Any],
    errors: list[dict[str, str]],
) -> None:
    contract = config.get("formal_authorization_contract", {})
    expected_sha = manifest.get("formal_execution_sha")
    fields = {
        "approval_comment_id",
        "approval_comment_url",
        "approval_author_login",
        "approval_created_at",
        "approval_updated_at",
        "approval_body_sha256",
        "reviewed_implementation_sha",
        "formal_execution_sha",
        "pr_head_sha",
    }
    if not fields.issubset(upstream):
        _error(errors, "FINAL_VALIDATION_APPROVAL_BINDING_MISMATCH", "approval_fields")
        return
    if (
        upstream.get("approval_author_login") != contract.get("required_author_login")
        or upstream.get("reviewed_implementation_sha") != expected_sha
        or upstream.get("formal_execution_sha") != expected_sha
        or upstream.get("pr_head_sha") != expected_sha
        or upstream.get("approval_scope") != "R3-T01_formal_run_only"
        or upstream.get("pr_state") not in {None, "OPEN"}
    ):
        _error(errors, "FINAL_VALIDATION_APPROVAL_BINDING_MISMATCH", "approval_values")
    nested = upstream.get("approval")
    if isinstance(nested, dict) and any(
        upstream.get(key) != nested.get(key) for key in fields if key in nested
    ):
        _error(errors, "FINAL_VALIDATION_APPROVAL_BINDING_MISMATCH", "approval_nested")


def _validate_upstream_bindings(
    root: Path,
    config: dict[str, Any],
    manifest: dict[str, Any],
    errors: list[dict[str, str]],
) -> None:
    expected = {
        (item.get("path"), item.get("committed_byte_sha256"))
        for item in config.get("upstream_binding", {}).get("required_artifacts", [])
    }
    actual = {
        (item.get("path"), item.get("sha256"))
        for item in manifest.get("upstream_bindings", [])
        if isinstance(item, dict)
    }
    if not expected.issubset(actual):
        _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", "upstream_set")
    for item in manifest.get("upstream_bindings", []):
        if not isinstance(item, dict):
            continue
        payload = _git_bytes(
            root, str(item.get("source_commit")), str(item.get("path"))
        )
        if payload is None or _sha_bytes(payload) != item.get("sha256"):
            _error(
                errors,
                "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH",
                str(item.get("path")),
            )


def validate_final_run_dir(run_dir: Path, *, root: Path = ROOT) -> dict[str, Any]:
    """Validate a completed analyzer package and write only the terminal sidecar."""

    run_dir = run_dir if run_dir.is_absolute() else root / run_dir
    errors: list[dict[str, str]] = []
    manifest_path = run_dir / MANIFEST
    config_path = run_dir / "r3_t01_protocol_registry.json"
    manifest: dict[str, Any] = {}
    config: dict[str, Any] = {}
    if not manifest_path.is_file():
        _error(errors, "FINAL_VALIDATION_MANIFEST_MISSING", MANIFEST)
    else:
        try:
            manifest = _load_json(manifest_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            _error(errors, "FINAL_VALIDATION_MANIFEST_MISSING", MANIFEST)
    if config_path.is_file():
        try:
            config = _load_json(config_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", config_path.name)
    else:
        _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", config_path.name)
    manifest_sha = (
        _sha_bytes(manifest_path.read_bytes()) if manifest_path.is_file() else None
    )
    prior_sidecar: dict[str, Any] = {}
    sidecar_path = run_dir / SIDECAR
    if sidecar_path.is_file():
        try:
            prior_sidecar = _load_json(sidecar_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            _error(errors, "FINAL_VALIDATION_TAMPER_DETECTED", SIDECAR)
    if prior_sidecar and prior_sidecar.get("validated_manifest_sha256") != manifest_sha:
        _error(errors, "FINAL_VALIDATION_MANIFEST_HASH_MISMATCH", MANIFEST)
        _error(errors, "FINAL_VALIDATION_TAMPER_DETECTED", MANIFEST)
    if manifest.get("manifest_self_hash_excluded") is not True:
        _error(
            errors, "FINAL_VALIDATION_MANIFEST_MISSING", "manifest_self_hash_excluded"
        )

    formal_sha = manifest.get("formal_execution_sha")
    reviewed_sha = manifest.get("reviewed_implementation_sha")
    artifact_count = _validate_manifest_artifacts(
        run_dir, root, config, manifest, errors
    )
    if isinstance(manifest.get("config"), dict):
        _validate_source_binding(root, manifest["config"], errors, formal_sha)
    else:
        _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", "config")
    if isinstance(manifest.get("fixture"), dict):
        _validate_source_binding(root, manifest["fixture"], errors, formal_sha)
    else:
        _error(errors, "FINAL_VALIDATION_SOURCE_BINDING_MISMATCH", "fixture")
    _validate_upstream_bindings(root, config, manifest, errors)

    validator: dict[str, Any] = {}
    anomaly: dict[str, Any] = {}
    upstream: dict[str, Any] = {}
    try:
        validator = _load_json(run_dir / "r3_t01_validator_result.json")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _error(errors, "FINAL_VALIDATION_VALIDATOR_NOT_PASSED", "validator")
    try:
        anomaly = _load_json(run_dir / "r3_t01_anomaly_scan.json")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _error(errors, "FINAL_VALIDATION_ANOMALY_NOT_CLEAN", "anomaly")
    try:
        upstream = _load_json(run_dir / "r3_t01_upstream_binding.json")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _error(errors, "FINAL_VALIDATION_APPROVAL_BINDING_MISMATCH", "upstream")
    if (
        validator.get("status") != "passed"
        or validator.get("formal_run_status") != "generated_pending_analysis"
    ):
        _error(errors, "FINAL_VALIDATION_VALIDATOR_NOT_PASSED", "validator_status")
    if (
        anomaly.get("status") != "complete"
        or anomaly.get("anomaly_count") != 0
        or anomaly.get("findings")
    ):
        _error(errors, "FINAL_VALIDATION_ANOMALY_NOT_CLEAN", "anomaly_status")
    analysis_path = run_dir / "r3_t01_result_analysis.md"
    try:
        analysis_text = analysis_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        analysis_text = ""
    if (
        not analysis_text.strip()
        or "placeholder" in analysis_text.lower()
        or "Pending independent result review" in analysis_text
        or manifest.get("result_analysis_status") != "passed"
        or manifest.get("formal_run_status")
        != "analysis_complete_pending_final_validation"
    ):
        _error(errors, "FINAL_VALIDATION_ANALYSIS_NOT_PASSED", analysis_path.name)
    try:
        production = _load_json(run_dir / "r3_t01_production_synthetic_results.json")
        independent = _load_json(run_dir / "r3_t01_independent_replay_results.json")
        if production.get("cases") != independent.get("cases"):
            _error(
                errors, "FINAL_VALIDATION_ANALYSIS_NOT_PASSED", "production_independent"
            )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _error(errors, "FINAL_VALIDATION_ANALYSIS_NOT_PASSED", "replay_artifacts")
    try:
        mutation_rows = read_csv(run_dir / "r3_t01_mutation_results.csv")
        declared = int(config.get("mutation_contract", {}).get("declared_count", 0))
        if len(mutation_rows) != declared or any(
            row.get("status") != "passed" for row in mutation_rows
        ):
            _error(errors, "FINAL_VALIDATION_ANALYSIS_NOT_PASSED", "mutations")
    except (OSError, UnicodeDecodeError, csv.Error):
        _error(errors, "FINAL_VALIDATION_ANALYSIS_NOT_PASSED", "mutations")
    if manifest_sha is None:
        _error(errors, "FINAL_VALIDATION_MANIFEST_HASH_MISMATCH", MANIFEST)
    _validate_approval(config, upstream, manifest, errors)

    tamper_codes = {
        "FINAL_VALIDATION_MANIFEST_HASH_MISMATCH",
        "FINAL_VALIDATION_ARTIFACT_HASH_MISMATCH",
        "FINAL_VALIDATION_ARTIFACT_SIZE_MISMATCH",
        "FINAL_VALIDATION_ARTIFACT_ROW_COUNT_MISMATCH",
        "FINAL_VALIDATION_TAMPER_DETECTED",
    }
    tamper = not any(item["code"] in tamper_codes for item in errors)
    status = "passed" if not errors else "failed"
    sidecar = {
        "task_id": config.get("task_id", "R3-T01"),
        "run_id": run_dir.name,
        "status": status,
        "validated_manifest_sha256": manifest_sha or ("0" * 64),
        "validated_artifact_count": artifact_count,
        "reviewed_implementation_sha": reviewed_sha,
        "formal_execution_sha": formal_sha,
        "approval_comment_id": upstream.get("approval_comment_id"),
        "validator_status": "passed"
        if validator.get("status") == "passed"
        else "failed",
        "anomaly_status": "passed"
        if anomaly.get("status") == "complete"
        and anomaly.get("anomaly_count") == 0
        and not anomaly.get("findings")
        else "failed",
        "result_analysis_status": manifest.get("result_analysis_status", "failed"),
        "manifest_binding_status": "passed"
        if manifest_sha
        and not any(
            item["code"].startswith("FINAL_VALIDATION_MANIFEST") for item in errors
        )
        else "failed",
        "tamper_check_status": "passed" if tamper else "failed",
        "error_count": len(errors),
        "errors": errors,
        "formal_run_status": "completed"
        if status == "passed"
        else "blocked_needs_revision",
    }
    if run_dir.is_dir():
        write_json(sidecar_path, sidecar)
    return sidecar
