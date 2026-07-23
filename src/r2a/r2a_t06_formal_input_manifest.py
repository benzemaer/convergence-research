"""Metadata-only manifest preparation for a future authorized R2A-T06 run.

The candidate builder reads accepted JSON handoffs and versioned contracts only.
It deliberately never opens the Score database.  Authoritative publication is a
separate, fail-closed operation for a later authorization commit.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r2a/r2a_t06_formal_execution.v1.json"
CONFIG_SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t06_formal_execution.schema.json"
MANIFEST_SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t06_formal_input_manifest.schema.json"
MANIFEST_VERSION = "r2a_t06_formal_input_manifest.v1"
FORMAL_SCOPE_ID = "r2a_t06_consecutive_failure_exit_formal_execution.v1"
APPROVED_IMPLEMENTATION_SHA = "2710d282fadcb998b80b9a482a5d55a4facc775a"
REQUEST_ORDER = ("CA_q10_k5", "CA_q15_k5", "CA_q20_k5", "CA_q25_k5")
RETIRED_ROOT_NAMES = {"convergence-research-inputs", "backup", "backups"}
CONTRACT_PATHS = (
    "configs/r2a/r2a_t06_formal_execution.v1.json",
    "schemas/r2a/r2a_t06_formal_execution.schema.json",
    "schemas/r2a/r2a_t06_formal_authorization.schema.json",
    "schemas/r2a/r2a_t06_formal_input_manifest.schema.json",
)


class FormalInputManifestError(RuntimeError):
    def __init__(self, reason_code: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code if detail is None else f"{reason_code}: {detail}")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FormalInputManifestError("json_input_invalid", str(path)) from error
    if not isinstance(value, dict):
        raise FormalInputManifestError("json_object_required", str(path))
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def load_formal_execution_config(
    path: str | Path = CONFIG_PATH,
) -> dict[str, Any]:
    config = _read_json(Path(path))
    schema = _read_json(CONFIG_SCHEMA_PATH)
    errors = sorted(Draft202012Validator(schema).iter_errors(config), key=str)
    if errors:
        raise FormalInputManifestError(
            "formal_execution_config_schema_invalid", errors[0].message
        )
    return config


def validate_manifest(payload: Mapping[str, Any]) -> None:
    schema = _read_json(MANIFEST_SCHEMA_PATH)
    errors = sorted(Draft202012Validator(schema).iter_errors(dict(payload)), key=str)
    if errors:
        raise FormalInputManifestError(
            "formal_manifest_schema_invalid", errors[0].message
        )
    _validate_request_order(payload["requests"])
    _validate_paths(payload)


def _validate_request_order(requests: Any) -> None:
    if not isinstance(requests, list):
        raise FormalInputManifestError("manifest_requests_invalid")
    names = tuple(str(item.get("logical_request_name")) for item in requests)
    if names != REQUEST_ORDER or len(set(names)) != len(names):
        raise FormalInputManifestError("manifest_request_order_mismatch")
    for item in requests:
        q = item.get("q_by_dimension")
        if item.get("selected_dimensions") != ["C", "A"] or q is None:
            raise FormalInputManifestError("manifest_request_scope_mismatch")
        if q.get("C") != q.get("A"):
            raise FormalInputManifestError("manifest_request_q_mismatch")


def validate_repository_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise FormalInputManifestError("repository_relative_path_invalid", str(value))
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or ":" in pure.parts[0]:
        raise FormalInputManifestError("repository_relative_path_invalid", value)
    lowered = {part.lower() for part in pure.parts}
    if lowered & RETIRED_ROOT_NAMES or any(
        part.lower().endswith((".bak", ".backup")) for part in pure.parts
    ):
        raise FormalInputManifestError("retired_or_backup_path_rejected", value)
    if not pure.parts or pure.parts[0] != "data":
        raise FormalInputManifestError("path_outside_repository_data_root", value)
    return pure.as_posix()


def _validate_paths(payload: Mapping[str, Any]) -> None:
    validate_repository_relative_path(str(payload["score_release"]["relative_path"]))
    for identity in payload["accepted_handoffs"].values():
        validate_repository_relative_path(str(identity["relative_path"]))
    if payload.get("repository_local_storage_root") != "data":
        raise FormalInputManifestError("repository_local_storage_root_mismatch")


def _identity(path: Path, relative_path: str) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "relative_path": relative_path,
        "sha256": sha256_bytes(content),
        "byte_size": len(content),
    }


def _verify_accepted_metadata(
    repo_root: Path,
    config: Mapping[str, Any],
    *,
    require_local_result_package: bool,
) -> None:
    expected_tasks = {
        "t01": "R2A-T01",
        "t02": "R2A-T02",
        "t03": "R2A-T03",
        "t04": "R2A-T04",
        "t05": "R2A-T05",
    }
    for name, identity in config["accepted_handoffs"].items():
        if name == "t05_result_package":
            continue
        relative = validate_repository_relative_path(str(identity["relative_path"]))
        path = repo_root / relative
        if not path.is_file():
            raise FormalInputManifestError("accepted_metadata_missing", name)
        actual = _identity(path, relative)
        if actual != dict(identity):
            raise FormalInputManifestError("accepted_metadata_identity_mismatch", name)
        if name in expected_tasks:
            payload = _read_json(path)
            if (
                payload.get("task_id") != expected_tasks[name]
                or payload.get("status") != "completed_accepted"
            ):
                raise FormalInputManifestError(
                    "accepted_metadata_status_mismatch", name
                )
    t05 = _read_json(repo_root / config["accepted_handoffs"]["t05"]["relative_path"])
    result_package_evidence = t05["evidence_identities"]["result_package"]
    result_package_identity = {
        "relative_path": result_package_evidence["relative_locator"],
        "sha256": result_package_evidence["sha256"],
        "byte_size": result_package_evidence["byte_size"],
    }
    configured_result_package = config["accepted_handoffs"]["t05_result_package"]
    if result_package_identity != configured_result_package:
        raise FormalInputManifestError("accepted_result_package_binding_mismatch")
    if require_local_result_package:
        relative = validate_repository_relative_path(
            str(configured_result_package["relative_path"])
        )
        path = repo_root / relative
        if not path.is_file():
            raise FormalInputManifestError(
                "accepted_metadata_missing", "t05_result_package"
            )
        if _identity(path, relative) != configured_result_package:
            raise FormalInputManifestError(
                "accepted_metadata_identity_mismatch", "t05_result_package"
            )
    reconciled = {
        row["logical_request_name"]: {
            key: int(row[key])
            for key in (
                "raw_true",
                "confirmed_true",
                "intervals",
                "securities_with_interval",
            )
        }
        for row in t05["request_reconciliation"]
    }
    if reconciled != config["accepted_counts"]:
        raise FormalInputManifestError("accepted_t05_count_mismatch")


def _contract_bindings(repo_root: Path) -> list[dict[str, Any]]:
    return [_identity(repo_root / relative, relative) for relative in CONTRACT_PATHS]


def _git_bytes(repo_root: Path, *args: str) -> bytes:
    process = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, check=False
    )
    if process.returncode:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise FormalInputManifestError("committed_contract_read_failed", detail)
    return process.stdout


def build_committed_contract_bindings(
    repo_root: str | Path, source_commit: str
) -> list[dict[str, Any]]:
    """Bind canonical contract bytes from Git objects, never the worktree."""

    if len(source_commit) != 40:
        raise FormalInputManifestError("committed_contract_source_sha_invalid")
    root = Path(repo_root).resolve()
    bindings: list[dict[str, Any]] = []
    for relative in CONTRACT_PATHS:
        content = _git_bytes(root, "show", f"{source_commit}:{relative}")
        blob_sha = (
            _git_bytes(root, "rev-parse", f"{source_commit}:{relative}")
            .decode("ascii")
            .strip()
        )
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise FormalInputManifestError(
                "committed_contract_not_utf8", relative
            ) from error
        if (
            content.startswith(b"\xef\xbb\xbf")
            or b"\r" in content
            or not content.endswith(b"\n")
            or content.endswith(b"\n\n")
        ):
            raise FormalInputManifestError(
                "committed_contract_canonical_text_invalid", relative
            )
        bindings.append(
            {
                "relative_path": relative,
                "source_commit": source_commit,
                "git_blob_sha": blob_sha,
                "committed_byte_sha256": sha256_bytes(content),
                "normalized_text_sha256": sha256_bytes(text.encode("utf-8")),
                "encoding": "utf-8",
                "line_ending": "lf",
                "bom": False,
                "trailing_lf_count": 1,
                "byte_size": len(content),
            }
        )
    return bindings


def verify_committed_contract_bindings(
    repo_root: str | Path,
    source_commit: str,
    bindings: Any,
) -> None:
    expected = build_committed_contract_bindings(repo_root, source_commit)
    if bindings != expected:
        raise FormalInputManifestError("committed_contract_binding_mismatch")


def build_candidate_manifest(
    *,
    config: Mapping[str, Any] | None = None,
    repo_root: str | Path = ROOT,
    created_at: str | None = None,
    verify_accepted_metadata: bool = True,
) -> dict[str, Any]:
    """Build a non-authoritative metadata candidate without opening Score."""

    loaded = deepcopy(dict(config or load_formal_execution_config()))
    root = Path(repo_root).resolve()
    if loaded.get("approved_implementation_sha") != APPROVED_IMPLEMENTATION_SHA:
        raise FormalInputManifestError("approved_implementation_sha_mismatch")
    if loaded.get("formal_run_allowed") is not False:
        raise FormalInputManifestError("candidate_builder_requires_unapproved_state")
    if verify_accepted_metadata:
        _verify_accepted_metadata(root, loaded, require_local_result_package=False)
    payload = {
        "$schema": "../../schemas/r2a/r2a_t06_formal_input_manifest.schema.json",
        "task_id": "R2A-T06",
        "scope_id": FORMAL_SCOPE_ID,
        "manifest_version": MANIFEST_VERSION,
        "manifest_status": "candidate_metadata_only",
        "created_at": created_at
        or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "approved_implementation_sha": APPROVED_IMPLEMENTATION_SHA,
        "reviewed_formal_execution_sha": None,
        "authorization_parent_sha": None,
        "authorization_commit_sha": None,
        "authorization_revision": 0,
        "formal_attempt_limit": int(loaded["formal_attempt_limit"]),
        "formal_attempts_consumed": int(loaded["formal_attempts_consumed"]),
        "score_release": deepcopy(loaded["score_release"]),
        "protocol_identity": deepcopy(loaded["protocol_identity"]),
        "evaluator_identity": deepcopy(loaded["evaluator_identity"]),
        "accepted_handoffs": deepcopy(loaded["accepted_handoffs"]),
        "requests": deepcopy(loaded["requests"]),
        "accepted_counts": deepcopy(loaded["accepted_counts"]),
        "execution_plan": deepcopy(loaded["execution_plan"]),
        "config_schema_bindings": _contract_bindings(root),
        "committed_contract_bindings": [],
        "repository_local_storage_root": loaded["repository_local_data_root"],
        "forbidden_input_fields": deepcopy(loaded["forbidden_input_fields"]),
        "expected_formal_files": deepcopy(loaded["scientific_package_files"]),
        "superseded": False,
    }
    validate_manifest(payload)
    return payload


def authorize_candidate_manifest(
    candidate: Mapping[str, Any],
    *,
    reviewed_formal_execution_sha: str,
    authorization_commit_sha: str,
    authorization_revision: int,
    quality_evidence: Mapping[str, Any],
    repo_root: str | Path = ROOT,
    committed_contract_bindings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bind a reviewed candidate after exact-SHA Quality success.

    This pure function does not write a manifest.  A later authorization commit
    must persist the returned bytes exactly once through ``write_immutable_manifest``.
    """

    validate_manifest(candidate)
    if candidate.get("manifest_status") != "candidate_metadata_only":
        raise FormalInputManifestError("superseded_or_non_candidate_manifest")
    if candidate.get("superseded") is not False:
        raise FormalInputManifestError("superseded_manifest_rejected")
    if not (
        quality_evidence.get("sha") == reviewed_formal_execution_sha
        and quality_evidence.get("status") == "completed"
        and quality_evidence.get("conclusion") == "success"
        and quality_evidence.get("run_id")
    ):
        raise FormalInputManifestError("exact_sha_quality_success_required")
    if len(reviewed_formal_execution_sha) != 40 or len(authorization_commit_sha) != 40:
        raise FormalInputManifestError("authorization_sha_invalid")
    payload = deepcopy(dict(candidate))
    payload.update(
        {
            "manifest_status": "authorized_immutable",
            "reviewed_formal_execution_sha": reviewed_formal_execution_sha,
            "authorization_parent_sha": reviewed_formal_execution_sha,
            "authorization_commit_sha": authorization_commit_sha,
            "authorization_revision": authorization_revision,
            "committed_contract_bindings": deepcopy(
                committed_contract_bindings
                if committed_contract_bindings is not None
                else build_committed_contract_bindings(
                    repo_root, reviewed_formal_execution_sha
                )
            ),
        }
    )
    validate_manifest(payload)
    return payload


def verify_formal_accepted_metadata(
    repo_root: str | Path, config: Mapping[str, Any]
) -> None:
    """Verify every accepted local identity before formal Score discovery."""

    _verify_accepted_metadata(
        Path(repo_root).resolve(), config, require_local_result_package=True
    )


def write_immutable_manifest(
    path: str | Path, payload: Mapping[str, Any]
) -> dict[str, Any]:
    validate_manifest(payload)
    if payload.get("manifest_status") != "authorized_immutable":
        raise FormalInputManifestError("authoritative_manifest_required")
    target = Path(path)
    if target.exists():
        raise FormalInputManifestError("manifest_overwrite_rejected", str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_json_bytes(payload)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target, flags, 0o444)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {"sha256": sha256_bytes(content), "byte_size": len(content)}


__all__ = [
    "APPROVED_IMPLEMENTATION_SHA",
    "FormalInputManifestError",
    "authorize_candidate_manifest",
    "build_candidate_manifest",
    "build_committed_contract_bindings",
    "canonical_json_bytes",
    "load_formal_execution_config",
    "sha256_file",
    "validate_manifest",
    "validate_repository_relative_path",
    "verify_formal_accepted_metadata",
    "verify_committed_contract_bindings",
    "write_immutable_manifest",
]
