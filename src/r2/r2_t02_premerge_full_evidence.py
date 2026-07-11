from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.run_unittest_profile import profile_test_ids
from src.r0.upstream_artifact_io import write_json_atomic

ROOT = Path(__file__).resolve().parents[2]


class R2T02PremergeEvidenceError(RuntimeError):
    pass


def collection_sha256(test_ids: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(test_ids), separators=(",", ":")).encode()
    ).hexdigest()


def formal_surface_sha256(commit: str) -> str:
    paths = ["src/r2", "scripts/r2", "configs/r2", "schemas/r2", "tests/r2"]
    result = subprocess.run(
        ["git", "ls-tree", "-r", commit, "--", *paths],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return hashlib.sha256(result.stdout.encode()).hexdigest()


def build_premerge_full_evidence(
    *,
    runner_result_path: Path,
    output_path: Path,
    tested_head: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
) -> dict[str, Any]:
    runner = json.loads(runner_result_path.read_text(encoding="utf-8"))
    full_ids = profile_test_ids("full")
    heavy_ids = profile_test_ids("r0-heavy-premerge")
    errors = []
    for key, expected in {
        "profile": "full",
        "status": "passed",
        "failure_count": 0,
        "error_count": 0,
    }.items():
        if runner.get(key) != expected:
            errors.append(f"runner_field_mismatch:{key}")
    if runner.get("test_ids") != full_ids:
        errors.append("full_collection_mismatch")
    if runner.get("test_collection_sha256") != collection_sha256(full_ids):
        errors.append("full_collection_hash_mismatch")
    if runner.get("test_count") != len(full_ids):
        errors.append("full_executed_count_mismatch")
    if errors:
        raise R2T02PremergeEvidenceError(json.dumps(errors))
    evidence = {
        "schema_version": "r2_t02_premerge_full_evidence.v1",
        "task_id": "R2-T02",
        "profile": "full",
        "status": "passed",
        "tested_head": tested_head,
        "workflow_run_id": str(workflow_run_id),
        "workflow_run_attempt": str(workflow_run_attempt),
        "test_count": len(full_ids),
        "unique_test_count": len(set(full_ids)),
        "skipped_count": runner["skipped_count"],
        "failure_count": 0,
        "error_count": 0,
        "elapsed_seconds": runner["elapsed_seconds"],
        "test_collection_sha256": collection_sha256(full_ids),
        "heavy_profile": "r0-heavy-premerge",
        "heavy_test_count": len(heavy_ids),
        "heavy_test_collection_sha256": collection_sha256(heavy_ids),
        "heavy_test_ids": heavy_ids,
        "collection_conservation": {
            "full_equals_current_collection": True,
            "heavy_is_subset_of_full": set(heavy_ids).issubset(full_ids),
            "executed_equals_collected": runner["test_count"] == len(full_ids),
        },
        "formal_surface_sha256": formal_surface_sha256(tested_head),
    }
    write_json_atomic(output_path, evidence)
    return evidence
