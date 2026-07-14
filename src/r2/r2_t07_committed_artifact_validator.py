# ruff: noqa: E501

"""Validate T07 output manifest against committed Git object bytes."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from src.common.canonical_io import write_json


def _git(root: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe(path: str) -> str:
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"path_escape:{path}")
    return value.as_posix()


def validate_manifest_records(item: dict[str, Any], payload: bytes) -> list[str]:
    """Pure mutation-testable check for manifest SHA and size claims."""
    errors: list[str] = []
    if item.get("sha256") != _sha256(payload):
        errors.append("committed_byte_sha256_mismatch")
    if item.get("size_bytes") != len(payload):
        errors.append("committed_byte_size_mismatch")
    return errors


def validate_committed_artifacts(
    output_dir: Path, artifact_commit: str, root: Path
) -> dict[str, Any]:
    manifest_rel = (
        output_dir.relative_to(root).as_posix() + "/r2_t07_output_manifest.json"
    )
    failures: list[str] = []
    records: list[dict[str, Any]] = []
    manifest_blob_sha: str | None = None
    try:
        _git(root, "cat-file", "-e", f"{artifact_commit}^{{commit}}")
        blob = _git(root, "show", f"{artifact_commit}:{manifest_rel}", binary=True)
        assert isinstance(blob, bytes)
        manifest_blob_sha = str(
            _git(root, "rev-parse", f"{artifact_commit}:{manifest_rel}")
        )
        manifest_byte_sha = _sha256(blob)
        manifest = json.loads(blob.decode("utf-8"))
        artifacts = manifest.get("artifacts", [])
        if manifest.get("artifact_hash_basis") != "committed_artifact_bytes":
            failures.append("manifest_hash_basis")
        if manifest.get("artifact_count") != len(artifacts):
            failures.append("manifest_artifact_count")
        if (
            manifest.get("task_id") != "R2-T07"
            or manifest.get("run_id") != output_dir.name
        ):
            failures.append("manifest_identity")
        paths = [item.get("path") for item in artifacts]
        if len(paths) != len(set(paths)):
            failures.append("manifest_duplicate_path")
        for item in artifacts:
            try:
                rel = _safe(str(item["path"]))
                payload = _git(root, "show", f"{artifact_commit}:{rel}", binary=True)
                assert isinstance(payload, bytes)
                errors = validate_manifest_records(item, payload)
                failures.extend(f"{error}:{rel}" for error in errors)
                records.append(
                    {
                        "path": rel,
                        "git_blob_sha": str(
                            _git(root, "rev-parse", f"{artifact_commit}:{rel}")
                        ),
                        "committed_byte_sha256": _sha256(payload),
                        "size_bytes": len(payload),
                    }
                )
            except (
                KeyError,
                ValueError,
                subprocess.CalledProcessError,
                AssertionError,
            ) as exc:
                failures.append(f"unreadable:{item.get('path', '<missing>')}:{exc}")
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        subprocess.CalledProcessError,
        AssertionError,
    ) as exc:
        failures.append(f"manifest_unreadable:{exc}")
    result = {
        "task_id": "R2-T07",
        "run_id": output_dir.name,
        "status": "passed" if not failures else "failed",
        "failure_count": len(failures),
        "failures": failures,
        "validation_mode": "git_show_committed_blob_bytes",
        "validated_commit": artifact_commit,
        "validated_manifest_path": manifest_rel,
        "validated_manifest_blob_sha": manifest_blob_sha,
        "validated_manifest_committed_byte_sha256": manifest_byte_sha
        if manifest_blob_sha
        else None,
        "validated_manifest_size_bytes": len(blob) if manifest_blob_sha else None,
        "validated_artifacts": records,
    }
    write_json(output_dir / "r2_t07_committed_artifact_validation.json", result)
    return result


__all__ = ["validate_committed_artifacts", "validate_manifest_records"]
