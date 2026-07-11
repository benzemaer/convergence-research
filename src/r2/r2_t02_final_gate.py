from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

ROOT = Path(__file__).resolve().parents[2]


class R2T02FinalGateError(RuntimeError):
    pass


def finalize_r2_t02_reviewed_package(
    *,
    output_dir: Path,
    review_record_path: Path,
    reviewed_head: str,
    task_index_path: Path,
) -> dict[str, Any]:
    errors = []
    review = _load(review_record_path)
    package = _load(output_dir / "r2_t02_result_package.json")
    validation = _load(output_dir / "r2_t02_contract_validation_result.json")
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
