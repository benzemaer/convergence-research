from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

from .r0_t15_layer_q_vector_materializer import ROOT, TASK_ID


def build_r0_t15_author_package(
    *,
    run_dir: str | Path,
    analysis_path: str | Path,
    evidence_path: str | Path,
    engineering_validation_path: str | Path,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    analysis_path = Path(analysis_path)
    evidence_path = Path(evidence_path)
    engineering_validation_path = Path(engineering_validation_path)
    anomaly = _load_json(run_dir / "r0_t15_anomaly_scan.json")
    engineering = _load_json(engineering_validation_path)
    summary = _load_json(run_dir / "r0_t15_execution_summary.json")
    manifest = _load_json(run_dir / "r0_t15_artifact_manifest.json")
    handoff_path = run_dir / "r0_t15_authorized_handoff_manifest.json"
    handoff = _load_json(handoff_path)
    if anomaly.get("status") != "passed" or anomaly.get("blocking_findings"):
        raise RuntimeError("anomaly_gate_not_passed")
    if engineering.get("status") != "passed":
        raise RuntimeError("engineering_validation_not_passed")
    if not analysis_path.is_file() or not evidence_path.is_file():
        raise RuntimeError("analysis_or_evidence_missing")
    analysis_copy = run_dir / "r0_t15_result_analysis.md"
    evidence_copy = run_dir / "r0_t15_evidence.md"
    shutil.copyfile(analysis_path, analysis_copy)
    shutil.copyfile(evidence_path, evidence_copy)
    handoff.update(
        {
            "goal_internal_continuation_gate_status": "passed",
            "goal_internal_continuation_allowed": True,
            "goal_internal_t14_02_authorized": True,
            "repository_t14_02_gate_passed": False,
            "R1-T14-02_allowed_to_start": False,
            "independent_review_status": "not_started",
            "repository_final_gate_status": "pending",
        }
    )
    write_json_atomic(handoff_path, handoff)
    committed_names = [
        "r0_t15_request_binding.json",
        "r0_t15_candidate_registry.csv",
        "r0_t15_artifact_manifest.json",
        "r0_t15_authorized_handoff_manifest.json",
        "r0_t15_schema_validation.json",
        "r0_t15_upstream_reconciliation.csv",
        "r0_t15_anomaly_scan.json",
        "r0_t15_execution_summary.json",
        "r0_t15_engineering_validation_result.json",
        "r0_t15_final_gate_validation_result.json",
        "r0_t15_result_analysis.md",
        "r0_t15_evidence.md",
    ]
    committed = [_artifact(run_dir / name, True) for name in committed_names]
    uncommitted = [
        {
            "path": record["path"],
            "sha256": record["sha256"],
            "row_count": record["row_count"],
            "table": record["table"],
            "committed_to_repo": False,
        }
        for record in manifest["outputs"].values()
    ]
    package = {
        "task_id": TASK_ID,
        "stage": "R0",
        "task_class": "formal_materialization_bridge",
        "run_id": summary["run_id"],
        "code_commit": summary["code_commit"],
        "config_path": summary["config_path"],
        "config_sha256": summary["config_sha256"],
        "upstream_binding": summary["upstream_binding"],
        "artifact_manifest_path": _rel(run_dir / "r0_t15_artifact_manifest.json"),
        "artifact_manifest_sha256": sha256_file(
            run_dir / "r0_t15_artifact_manifest.json"
        ),
        "handoff_manifest_path": _rel(handoff_path),
        "handoff_manifest_sha256": sha256_file(handoff_path),
        "result_analysis_path": _rel(analysis_path),
        "result_analysis_sha256": sha256_file(analysis_path),
        "formal_evidence_path": _rel(evidence_path),
        "formal_evidence_sha256": sha256_file(evidence_path),
        "committed_artifacts": committed,
        "local_materialized_artifacts": uncommitted,
        "gate_status": {
            "engineering_validator_status": "passed",
            "author_result_analysis_status": "passed",
            "anomaly_resolution_status": "passed",
            "goal_internal_continuation_gate_status": "passed",
            "goal_internal_continuation_allowed": True,
            "goal_internal_t14_02_authorized": True,
            "repository_t14_02_gate_passed": False,
        },
        "R0_q_vector_materialization_status": "author_draft_complete",
        "independent_review_status": "not_started",
        "repository_final_gate_status": "pending",
        "R0_q_vector_materialization_request_status": "pending_external_review",
        "R1-T14-02_allowed_to_start": False,
        "R1-T10_allowed_to_start": False,
        "R2_allowed_to_start": False,
        "formal_task_completed": False,
        "status": "author_draft_complete",
        "superseded": False,
    }
    write_json_atomic(run_dir / "r0_t15_result_package.json", package)
    return package


def _artifact(path: Path, committed: bool) -> dict[str, Any]:
    return {
        "path": _rel(path),
        "sha256": sha256_file(path),
        "record_count": _row_count(path),
        "committed_to_repo": committed,
    }


def _row_count(path: Path) -> int:
    if path.suffix == ".csv":
        with path.open(encoding="utf-8") as handle:
            return max(sum(1 for _ in handle) - 1, 0)
    return 1


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(path)
    return value
