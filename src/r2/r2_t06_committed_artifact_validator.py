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


def _safe_relpath(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"artifact_path_escape:{value}")
    return path.as_posix()


def validate_committed_artifacts(
    output_dir: Path, artifact_commit: str, root: Path
) -> dict[str, Any]:
    manifest_rel = (
        output_dir.relative_to(root).as_posix() + "/r2_t06_output_manifest.json"
    )
    failures: list[str] = []
    validated_artifacts: list[dict[str, Any]] = []
    manifest_blob_sha: str | None = None
    try:
        _git(root, "cat-file", "-e", f"{artifact_commit}^{{commit}}")
        manifest_blob = _git(
            root, "show", f"{artifact_commit}:{manifest_rel}", binary=True
        )
        assert isinstance(manifest_blob, bytes)
        manifest_blob_sha = str(
            _git(root, "rev-parse", f"{artifact_commit}:{manifest_rel}")
        )
        manifest = json.loads(manifest_blob.decode("utf-8"))
        if manifest.get("artifact_hash_basis") != "committed_artifact_bytes":
            failures.append("manifest_hash_basis")
        artifacts = manifest.get("artifacts", [])
        if manifest.get("artifact_count") != len(artifacts):
            failures.append("manifest_artifact_count")
        paths = [item.get("path") for item in artifacts]
        if len(paths) != len(set(paths)):
            failures.append("manifest_duplicate_path")
        for item in artifacts:
            try:
                rel = _safe_relpath(str(item["path"]))
                blob = _git(root, "show", f"{artifact_commit}:{rel}", binary=True)
                assert isinstance(blob, bytes)
                blob_sha = str(_git(root, "rev-parse", f"{artifact_commit}:{rel}"))
                byte_sha = _sha256(blob)
                if byte_sha != item.get("sha256"):
                    failures.append(f"sha256:{rel}")
                if len(blob) != item.get("size_bytes"):
                    failures.append(f"size:{rel}")
                validated_artifacts.append(
                    {
                        "path": rel,
                        "git_blob_sha": blob_sha,
                        "committed_byte_sha256": byte_sha,
                        "size_bytes": len(blob),
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
        "task_id": "R2-T06",
        "run_id": output_dir.name,
        "status": "passed" if not failures else "failed",
        "failure_count": len(failures),
        "failures": failures,
        "validation_mode": "git_show_committed_blob_bytes",
        "validated_commit": artifact_commit,
        "validated_manifest_path": manifest_rel,
        "validated_manifest_blob_sha": manifest_blob_sha,
        "validated_artifacts": validated_artifacts,
    }
    write_json(output_dir / "r2_t06_committed_artifact_validation.json", result)
    return result


__all__ = ["validate_committed_artifacts"]
