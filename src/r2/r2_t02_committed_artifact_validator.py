from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.common.canonical_io import ROOT, repo_rel, sha256_bytes


def validate_committed_artifacts(
    output_dir: Path,
    *,
    commit: str = "HEAD",
    root: Path = ROOT,
    write_sidecar: bool = False,
    update_package: bool = False,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    package = json.loads(
        (output_dir / "r2_t02_result_package.json").read_text(encoding="utf-8")
    )
    errors = []
    artifact_git_blobs = {}
    package_rel = f"{repo_rel(output_dir, root)}/r2_t02_result_package.json"
    try:
        package_committed_bytes = subprocess.check_output(
            ["git", "show", f"{commit}:{package_rel}"],
            cwd=root,
        )
        package_git_blob_sha = subprocess.check_output(
            ["git", "rev-parse", f"{commit}:{package_rel}"],
            cwd=root,
            text=True,
        ).strip()
        package_committed_sha256 = sha256_bytes(package_committed_bytes)
    except subprocess.CalledProcessError:
        errors.append("missing_committed_artifact:r2_t02_result_package.json")
        package_git_blob_sha = ""
        package_committed_sha256 = ""
    for name, expected_hash in sorted(package["artifact_hashes"].items()):
        rel = f"{repo_rel(output_dir, root)}/{name}"
        try:
            committed_bytes = subprocess.check_output(
                ["git", "show", f"{commit}:{rel}"],
                cwd=root,
            )
            blob_sha = subprocess.check_output(
                ["git", "rev-parse", f"{commit}:{rel}"],
                cwd=root,
                text=True,
            ).strip()
        except subprocess.CalledProcessError:
            errors.append(f"missing_committed_artifact:{name}")
            continue
        actual_hash = sha256_bytes(committed_bytes)
        artifact_git_blobs[name] = {
            "git_blob_sha": blob_sha,
            "sha256": actual_hash,
        }
        if actual_hash != expected_hash:
            errors.append(f"committed_hash_mismatch:{name}")
    result = {
        "task_id": "R2-T02",
        "run_id": package["run_id"],
        "status": "passed" if not errors else "failed",
        "artifact_commit": _resolve_commit(commit, root),
        "reviewed_pr_head": _resolve_commit(commit, root),
        "package_sha256": sha256_bytes(
            (output_dir / "r2_t02_result_package.json").read_bytes()
        ),
        "package_git_blob_sha": package_git_blob_sha,
        "package_committed_sha256": package_committed_sha256,
        "package_hash_in_closed_set": bool(package_committed_sha256),
        "artifact_hash_basis": "committed_git_blob",
        "artifact_count": len(package["artifact_hashes"]),
        "artifact_git_blobs": artifact_git_blobs,
        "errors": errors,
    }
    if write_sidecar:
        (output_dir / "r2_t02_committed_artifact_validation.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if update_package and not errors:
        package["artifact_commit"] = result["artifact_commit"]
        package["reviewed_pr_head"] = "pending_repository_final_gate_exact_head"
        package["artifact_commit_binding_status"] = "passed"
        package["artifact_hash_basis"] = "committed_git_blob"
        (output_dir / "r2_t02_result_package.json").write_text(
            json.dumps(package, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return result


def _resolve_commit(commit: str, root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", commit], cwd=root, text=True
    ).strip()
