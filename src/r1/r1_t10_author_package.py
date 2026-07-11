from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dump(path: Path, value: dict) -> None:
    path.write_bytes(
        (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    )


def build_author_package(root: Path) -> dict:
    out = root / "data/generated/r1/r1_t10/R1-T10-20260711T2000Z"
    analysis = (
        root / "docs/experiments/r1/R1-T10_R1验收门禁与R2交接矩阵_result_analysis.md"
    )
    evidence = root / "docs/evidence/r1/R1-T10_R1验收门禁与R2交接矩阵_evidence.md"
    (out / "r1_t10_result_analysis.md").write_bytes(analysis.read_bytes())
    (out / "r1_t10_evidence.md").write_bytes(evidence.read_bytes())
    excluded = {
        "r1_t10_result_package.json",
        "r1_t10_author_draft_package_validation_result.json",
    }
    required = [path for path in out.iterdir() if path.name not in excluded]
    package = {
        "task_id": "R1-T10",
        "run_id": out.name,
        "task_class": "stage_acceptance_gate_and_handoff",
        "status": "author_draft_complete",
        "review_phase": "author_analysis_complete",
        "scientific_review_status": "pending",
        "independent_review_status": "not_started",
        "repository_final_gate_status": "pending",
        "formal_task_completed": False,
        "downstream_gate_allowed": False,
        "R1-T10_allowed_to_start": True,
        "R2_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "contains_same_sample_selected_candidates": True,
        "blocking_findings": [],
        "unresolved_findings": [],
        "task_index_path": "docs/tasks/README.md",
        "task_index_sha256": _sha(root / "docs/tasks/README.md"),
        "committed_artifacts": {
            str(path.relative_to(root)).replace("\\", "/"): {"sha256": _sha(path)}
            for path in sorted(required)
        },
    }
    _dump(out / "r1_t10_result_package.json", package)
    errors = [
        f"artifact_mismatch:{rel}"
        for rel, meta in package["committed_artifacts"].items()
        if not (root / rel).exists() or _sha(root / rel) != meta["sha256"]
    ]
    if package["R2_allowed_to_start"]:
        errors.append("R2_opened_before_external_review")
    validation = {
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "errors": errors,
        "scientific_review_status": "pending",
        "repository_final_gate_status": "pending",
    }
    _dump(out / "r1_t10_author_draft_package_validation_result.json", validation)
    return validation
