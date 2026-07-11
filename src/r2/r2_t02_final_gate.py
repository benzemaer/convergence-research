from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.run_unittest_profile import profile_test_ids
from src.r0.upstream_artifact_io import sha256_file, write_json_atomic
from src.r2.r2_t02_premerge_full_evidence import (
    collection_sha256,
    formal_surface_sha256,
)

ROOT = Path(__file__).resolve().parents[2]


class R2T02FinalGateError(RuntimeError):
    pass


def finalize_r2_t02_reviewed_package(
    *,
    output_dir: Path,
    review_record_path: Path,
    reviewed_head: str,
    task_index_path: Path,
    premerge_full_evidence_path: Path,
) -> dict[str, Any]:
    errors = []
    review = _load(review_record_path)
    package = _load(output_dir / "r2_t02_result_package.json")
    validation = _load(output_dir / "r2_t02_contract_validation_result.json")
    premerge = _load(premerge_full_evidence_path)
    expected = {
        "task_id": "R2-T02",
        "scientific_review_status": "passed",
        "independent_review_status": "passed",
        "independence_attestation": True,
        "blocking_findings": [],
        "downstream_gate_recommendation": True,
        "downstream_gate_scope": "R2-T03_only",
    }
    for k, v in expected.items():
        if review.get(k) != v:
            errors.append(f"review_field_mismatch:{k}")
    if review.get("reviewed_pr_head_commit") != reviewed_head:
        errors.append("reviewed_head_binding")
    if review.get("reviewed_author_package_sha256") != sha256_file(
        output_dir / "r2_t02_result_package.json"
    ):
        errors.append("reviewed_package_hash")
    if validation.get("status") != "passed" or not validation.get(
        "all_synthetic_cases_passed"
    ):
        errors.append("contract_validation_not_passed")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", reviewed_head, "HEAD"],
        cwd=ROOT,
        capture_output=True,
    ).returncode:
        errors.append("reviewed_head_not_ancestor")
    full_ids = profile_test_ids("full")
    heavy_ids = profile_test_ids("r0-heavy-premerge")
    premerge_expected = {
        "task_id": "R2-T02",
        "profile": "full",
        "status": "passed",
        "tested_head": reviewed_head,
        "test_count": len(full_ids),
        "unique_test_count": len(set(full_ids)),
        "failure_count": 0,
        "error_count": 0,
        "test_collection_sha256": collection_sha256(full_ids),
        "heavy_profile": "r0-heavy-premerge",
        "heavy_test_count": len(heavy_ids),
        "heavy_test_collection_sha256": collection_sha256(heavy_ids),
        "heavy_test_ids": heavy_ids,
        "formal_surface_sha256": formal_surface_sha256(reviewed_head),
    }
    for key, value in premerge_expected.items():
        if premerge.get(key) != value:
            errors.append(f"premerge_full_evidence:{key}")
    if not premerge.get("workflow_run_id") or not premerge.get("workflow_run_attempt"):
        errors.append("premerge_full_evidence:workflow_binding")
    if premerge.get("collection_conservation") != {
        "full_equals_current_collection": True,
        "heavy_is_subset_of_full": True,
        "executed_equals_collected": True,
    }:
        errors.append("premerge_full_evidence:collection_conservation")
    current = task_index_path.read_text(encoding="utf-8")
    for marker in [
        "R2-T02_scientific_review_status: pending",
        "R2-T03_allowed_to_start: false",
    ]:
        if marker not in current:
            errors.append(f"readme_pre_final:{marker}")
    for artifact in package.get("committed_artifacts", []):
        path = ROOT / artifact["path"]
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            errors.append(f"reviewed_artifact_hash:{artifact['path']}")
    if errors:
        raise R2T02FinalGateError(json.dumps(errors, ensure_ascii=False))
    final = {
        "task_id": "R2-T02",
        "run_id": output_dir.name,
        "status": "completed",
        "reviewed_pr_head_commit": reviewed_head,
        "review_record_path": review_record_path.relative_to(ROOT).as_posix(),
        "review_record_sha256": sha256_file(review_record_path),
        "premerge_full_evidence_path": premerge_full_evidence_path.relative_to(
            ROOT
        ).as_posix(),
        "premerge_full_evidence_sha256": sha256_file(premerge_full_evidence_path),
        "reviewed_author_package_sha256": sha256_file(
            output_dir / "r2_t02_result_package.json"
        ),
        "scientific_review_status": "passed",
        "independent_review_status": "passed",
        "repository_final_gate_status": "passed",
        "blocking_findings": [],
        "formal_task_completed": True,
        "R2-T03_allowed_to_start": True,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "downstream_gate_scope": "R2-T03_only",
        "selection_path_not_independently_confirmed": True,
    }
    write_json_atomic(output_dir / "r2_t02_final_gate_package.json", final)
    return final


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
