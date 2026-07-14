"""Verify T08 artifacts from committed Git object bytes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.common.canonical_io import (
    ROOT,
    git_blob_bytes,
    git_blob_sha,
    sha256_bytes,
    write_json,
)

TASK_ID = "R2-T08"


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _load_manifest(
    root: Path, commit: str, output_dir: Path
) -> tuple[dict[str, Any], str]:
    rel = output_dir.relative_to(root).as_posix()
    path = f"{rel}/r2_t08_output_manifest.json"
    return json.loads(git_blob_bytes(commit, path, root=root)), path


def validate_committed_artifacts(
    output_dir: Path, artifact_commit: str, repo: Path = ROOT
) -> dict[str, Any]:
    try:
        manifest, manifest_path = _load_manifest(repo, artifact_commit, output_dir)
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as exc:
        result = {
            "task_id": TASK_ID,
            "run_id": output_dir.name,
            "status": "failed",
            "failure_count": 1,
            "failures": [f"manifest_read:{exc}"],
            "validated_commit": artifact_commit,
            "validation_mode": "git_show_committed_blob_bytes",
            "validated_artifacts": [],
        }
        write_json(output_dir / "r2_t08_committed_artifact_validation.json", result)
        return result
    failures: list[str] = []
    validated: list[dict[str, Any]] = []
    for item in manifest.get("artifacts", []):
        path = item.get("path")
        try:
            payload = git_blob_bytes(artifact_commit, path, root=repo)
            blob = git_blob_sha(artifact_commit, path, root=repo)
        except subprocess.CalledProcessError:
            failures.append(f"missing_blob:{path}")
            continue
        actual_sha = sha256_bytes(payload)
        row = {
            "path": path,
            "git_blob_sha": blob,
            "committed_byte_sha256": actual_sha,
            "size_bytes": len(payload),
        }
        validated.append(row)
        if item.get("sha256") != actual_sha:
            failures.append(f"sha256:{path}")
        if item.get("size_bytes") != len(payload):
            failures.append(f"size:{path}")
        if blob != _git(repo, "rev-parse", f"{artifact_commit}:{path}"):
            failures.append(f"blob:{path}")
    if manifest.get("artifact_count") != len(manifest.get("artifacts", [])):
        failures.append("manifest_artifact_count")
    result = {
        "task_id": TASK_ID,
        "run_id": output_dir.name,
        "status": "passed" if not failures else "failed",
        "failure_count": len(failures),
        "failures": failures,
        "validated_commit": artifact_commit,
        "validated_manifest_path": manifest_path,
        "validated_manifest_blob_sha": git_blob_sha(
            artifact_commit, manifest_path, root=repo
        ),
        "validated_manifest_committed_byte_sha256": sha256_bytes(
            git_blob_bytes(artifact_commit, manifest_path, root=repo)
        ),
        "validated_manifest_size_bytes": len(
            git_blob_bytes(artifact_commit, manifest_path, root=repo)
        ),
        "validation_mode": "git_show_committed_blob_bytes",
        "validated_artifacts": validated,
    }
    write_json(output_dir / "r2_t08_committed_artifact_validation.json", result)
    return result
