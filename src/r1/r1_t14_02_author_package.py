from __future__ import annotations

# ruff: noqa: E501
import shutil
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

from .r1_t14_02_formal_structural_revalidation import (
    TASK_ID,
    _load_json,
    _rel,
    _row_count,
)


def build_r1_t14_02_author_package(
    *, run_dir: str | Path, analysis_path: str | Path, evidence_path: str | Path
) -> dict[str, Any]:
    run_dir, analysis_path, evidence_path = (
        Path(run_dir),
        Path(analysis_path),
        Path(evidence_path),
    )
    anomaly = _load_json(run_dir / "r1_t14_02_anomaly_scan.json")
    engineering = _load_json(run_dir / "r1_t14_02_engineering_validation_result.json")
    summary = _load_json(run_dir / "r1_t14_02_experiment_summary.json")
    if (
        anomaly.get("status") != "passed"
        or anomaly.get("blocking_findings")
        or engineering.get("status") != "passed"
    ):
        raise RuntimeError("engineering_or_anomaly_gate_not_passed")
    shutil.copyfile(analysis_path, run_dir / "r1_t14_02_result_analysis.md")
    shutil.copyfile(evidence_path, run_dir / "r1_t14_02_evidence.md")
    names = [
        path.name
        for path in sorted(run_dir.iterdir())
        if path.is_file()
        and path.name
        not in {
            "r1_t14_02_result_package.json",
            "r1_t14_02_author_draft_package_validation_result.json",
        }
    ]
    committed = [
        {
            "path": _rel(run_dir / name),
            "sha256": sha256_file(run_dir / name),
            "row_count": _row_count(run_dir / name),
            "committed_to_repo": True,
        }
        for name in names
    ]
    committed.extend(
        [
            {
                "path": _rel(analysis_path),
                "sha256": sha256_file(analysis_path),
                "row_count": 1,
                "committed_to_repo": True,
            },
            {
                "path": _rel(evidence_path),
                "sha256": sha256_file(evidence_path),
                "row_count": 1,
                "committed_to_repo": True,
            },
        ]
    )
    package = {
        "task_id": TASK_ID,
        "stage": "R1",
        "task_class": "same_sample_formal_structural_revalidation",
        "run_id": summary["run_id"],
        "code_commit": summary["code_commit"],
        "config_path": summary["config_path"],
        "config_sha256": summary["config_sha256"],
        "upstream_binding": summary["upstream_binding"],
        "superseded_run": summary.get("superseded_run"),
        "diagnostic_reconciliation_inputs": summary.get(
            "diagnostic_reconciliation_inputs"
        ),
        "robust_envelope_policy": summary.get("robust_envelope_policy"),
        "denominator_reconciliation_policy": summary.get(
            "denominator_reconciliation_policy"
        ),
        "stale_dependency": True,
        "result_analysis_path": _rel(analysis_path),
        "result_analysis_sha256": sha256_file(analysis_path),
        "formal_evidence_path": _rel(evidence_path),
        "formal_evidence_sha256": sha256_file(evidence_path),
        "committed_artifacts": committed,
        "selection_path_not_independently_confirmed": True,
        "engineering_validator_status": "passed",
        "anomaly_resolution_status": "passed",
        "author_result_analysis_status": "passed",
        "goal_internal_completion_gate_status": "passed",
        "goal_internal_completion_allowed": True,
        "scientific_review_status": "pending",
        "review_phase": "author_analysis_complete",
        "independent_review_status": "not_started",
        "repository_final_gate_status": "pending",
        "downstream_gate_allowed": False,
        "R1-T10_allowed_to_start": False,
        "R2_allowed_to_start": False,
        "formal_task_completed": False,
        "status": "author_draft_complete",
        "superseded": False,
    }
    write_json_atomic(run_dir / "r1_t14_02_result_package.json", package)
    return package
