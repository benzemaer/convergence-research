from __future__ import annotations

import csv
import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.r0.upstream_artifact_io import sha256_file, write_json_atomic

from .r0_t15_layer_q_vector_materializer import ROOT, TASK_ID, git_commit

REVISION_CONFIG_PATH = ROOT / "configs/r0/r0_t15_author_revision.v1.json"
REVISION_SCHEMA_PATH = ROOT / "schemas/r0/r0_t15_author_revision.schema.json"


def build_r0_t15_author_revision(
    *,
    run_dir: str | Path,
    analysis_path: str | Path,
    evidence_path: str | Path,
    local_attestation_path: str | Path,
    revision_config_path: str | Path = REVISION_CONFIG_PATH,
    revision_code_commit: str | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    analysis_path = Path(analysis_path)
    evidence_path = Path(evidence_path)
    local_attestation_path = Path(local_attestation_path)
    revision_config_path = Path(revision_config_path)
    revision = _load_json(revision_config_path)
    Draft202012Validator(_load_json(REVISION_SCHEMA_PATH)).validate(revision)
    source = revision["source_run"]
    final_binding = revision["upstream_final_gate_binding"]
    governance = revision["governance"]
    head_commit = git_commit()
    if revision_code_commit is not None and revision_code_commit != head_commit:
        raise RuntimeError("revision_code_commit_must_equal_head")
    commit = head_commit

    _archive_original(
        run_dir / "r0_t15_authorized_handoff_manifest.json",
        ROOT / source["original_handoff_archive_path"],
        source["original_handoff_sha256"],
    )
    _archive_original(
        run_dir / "r0_t15_result_package.json",
        ROOT / source["original_result_package_archive_path"],
        source["original_result_package_sha256"],
    )
    _archive_original(
        run_dir / "r0_t15_result_analysis.md",
        ROOT / source["original_analysis_archive_path"],
        source["original_analysis_sha256"],
    )
    _archive_original(
        run_dir / "r0_t15_evidence.md",
        ROOT / source["original_evidence_archive_path"],
        source["original_evidence_sha256"],
    )
    _verify_reference_group(source)
    _verify_reference_group(final_binding)
    _verify_final_gate_semantics(final_binding)
    _assert_commit_ancestor(final_binding["finalization_commit"])
    _assert_commit_ancestor(final_binding["merge_commit"])

    attestation = _load_json(local_attestation_path)
    if (
        attestation.get("status") != "passed"
        or attestation.get("local_duckdb_byte_access") is not True
        or attestation.get("external_direct_duckdb_byte_review_performed") is not False
        or attestation.get("independent_byte_validation_status") != "not_performed"
        or attestation.get("run_id") != source["run_id"]
    ):
        raise RuntimeError("local_duckdb_attestation_invalid")
    if attestation.get("validator_code_commit") != commit:
        raise RuntimeError("local_duckdb_attestation_revision_commit_mismatch")
    if not analysis_path.is_file() or not evidence_path.is_file():
        raise RuntimeError("revision_analysis_or_evidence_missing")

    analysis_copy = run_dir / "r0_t15_result_analysis.md"
    evidence_copy = run_dir / "r0_t15_evidence.md"
    shutil.copyfile(analysis_path, analysis_copy)
    shutil.copyfile(evidence_path, evidence_copy)

    manifest_path = ROOT / source["artifact_manifest_path"]
    registry_path = ROOT / source["candidate_registry_path"]
    old_handoff_path = ROOT / source["original_handoff_archive_path"]
    old_handoff = _load_json(old_handoff_path)
    old_manifest_hash = old_handoff.get("artifact_manifest_sha256")
    old_registry_hash = old_handoff.get("candidate_registry_sha256")
    manifest_sha256 = sha256_file(manifest_path)
    registry_sha256 = sha256_file(registry_path)
    revision_record_path = run_dir / "r0_t15_author_revision.json"
    revision_record = {
        "task_id": TASK_ID,
        "run_id": source["run_id"],
        "revision_id": revision["revision_id"],
        "revision_class": revision["revision_class"],
        "revision_code_commit": commit,
        "revision_config_path": _rel(revision_config_path),
        "revision_config_sha256": sha256_file(revision_config_path),
        "execution_code_commit": source["execution_code_commit"],
        "execution_artifacts_recomputed": False,
        "execution_upstream_binding_is_historical": True,
        "execution_runtime_text_representation": (
            "windows_crlf_before_repository_normalization"
        ),
        "execution_recorded_upstream_result_package_sha256": old_handoff[
            "upstream_binding"
        ].get("upstream_result_package_actual_sha256"),
        "source_artifact_manifest_path": _rel(manifest_path),
        "source_artifact_manifest_sha256": manifest_sha256,
        "candidate_registry_path": _rel(registry_path),
        "candidate_registry_sha256": registry_sha256,
        "line_ending_root_cause": (
            "runtime_crlf_hashes_persisted_after_repository_lf_normalization"
        ),
        "corrected_handoff_targets": {
            "artifact_manifest": {
                "stale_sha256": old_manifest_hash,
                "canonical_lf_sha256": manifest_sha256,
            },
            "candidate_registry": {
                "stale_sha256": old_registry_hash,
                "canonical_lf_sha256": registry_sha256,
            },
        },
        "upstream_final_gate_binding": final_binding,
        "review_history": [
            {
                "pr_number": revision["external_review"]["pr_number"],
                "comment_id": revision["external_review"]["comment_id"],
                "outcome": revision["external_review"]["prior_review_status"],
                "blocking_findings": revision["external_review"]["blocking_findings"],
            }
        ],
        "local_duckdb_attestation_path": _rel(local_attestation_path),
        "local_duckdb_attestation_sha256": sha256_file(local_attestation_path),
        "external_direct_duckdb_byte_review_performed": False,
        "author_revision_status": governance["author_revision_status"],
        "independent_review_status": governance["independent_review_status"],
        "repository_final_gate_status": governance["repository_final_gate_status"],
        "formal_task_completed": False,
    }
    write_json_atomic(revision_record_path, revision_record)

    handoff_path = run_dir / "r0_t15_authorized_handoff_manifest.json"
    handoff = {
        "task_id": TASK_ID,
        "run_id": source["run_id"],
        "revision_id": revision["revision_id"],
        "revision_code_commit": commit,
        "handoff_status": "author_revision_candidate_pending_external_rereview",
        "artifact_manifest_path": _rel(manifest_path),
        "artifact_manifest_sha256": manifest_sha256,
        "candidate_registry_path": _rel(registry_path),
        "candidate_registry_sha256": registry_sha256,
        "execution_upstream_binding": old_handoff["upstream_binding"],
        "upstream_final_gate_binding": final_binding,
        "author_revision_path": _rel(revision_record_path),
        "author_revision_sha256": sha256_file(revision_record_path),
        "local_duckdb_attestation_path": _rel(local_attestation_path),
        "local_duckdb_attestation_sha256": sha256_file(local_attestation_path),
        "supersedes_handoff_path": source["original_handoff_archive_path"],
        "supersedes_handoff_sha256": source["original_handoff_sha256"],
        "review_history": revision_record["review_history"],
        "goal_internal_continuation_gate_status": "closed_pending_external_rereview",
        "goal_internal_continuation_allowed": False,
        "goal_internal_t14_02_authorized": False,
        "repository_t14_02_gate_passed": False,
        "R1-T14-02_allowed_to_start": False,
        "R1-T10_allowed_to_start": False,
        "R2_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "independent_review_status": "pending_rereview",
        "repository_final_gate_status": "pending",
        "formal_task_completed": False,
        "external_direct_duckdb_byte_review_performed": False,
    }
    write_json_atomic(handoff_path, handoff)

    manifest = _load_json(manifest_path)
    committed_paths = [
        revision_config_path,
        ROOT / source["execution_config_path"],
        run_dir / "r0_t15_request_binding.json",
        registry_path,
        manifest_path,
        handoff_path,
        run_dir / "r0_t15_schema_validation.json",
        run_dir / "r0_t15_upstream_reconciliation.csv",
        run_dir / "r0_t15_anomaly_scan.json",
        run_dir / "r0_t15_execution_summary.json",
        run_dir / "r0_t15_engineering_validation_result.json",
        run_dir / "r0_t15_final_gate_validation_result.json",
        revision_record_path,
        local_attestation_path,
        analysis_copy,
        evidence_copy,
        ROOT / source["original_handoff_archive_path"],
        ROOT / source["original_result_package_archive_path"],
        ROOT / source["original_analysis_archive_path"],
        ROOT / source["original_evidence_archive_path"],
        analysis_path,
        evidence_path,
    ]
    package = {
        "task_id": TASK_ID,
        "stage": "R0",
        "task_class": "formal_materialization_bridge",
        "run_id": source["run_id"],
        "revision_id": revision["revision_id"],
        "execution_code_commit": source["execution_code_commit"],
        "revision_code_commit": commit,
        "execution_config_path": source["execution_config_path"],
        "execution_config_sha256": source["execution_config_sha256"],
        "revision_config_path": _rel(revision_config_path),
        "revision_config_sha256": sha256_file(revision_config_path),
        "execution_upstream_binding": old_handoff["upstream_binding"],
        "upstream_final_gate_binding": final_binding,
        "request_binding_path": source["request_binding_path"],
        "request_binding_sha256": source["request_binding_sha256"],
        "artifact_manifest_path": _rel(manifest_path),
        "artifact_manifest_sha256": manifest_sha256,
        "candidate_registry_path": _rel(registry_path),
        "candidate_registry_sha256": registry_sha256,
        "handoff_manifest_path": _rel(handoff_path),
        "handoff_manifest_sha256": sha256_file(handoff_path),
        "author_revision_path": _rel(revision_record_path),
        "author_revision_sha256": sha256_file(revision_record_path),
        "local_duckdb_attestation_path": _rel(local_attestation_path),
        "local_duckdb_attestation_sha256": sha256_file(local_attestation_path),
        "result_analysis_path": _rel(analysis_path),
        "result_analysis_sha256": sha256_file(analysis_path),
        "run_copy_result_analysis_path": _rel(analysis_copy),
        "run_copy_result_analysis_sha256": sha256_file(analysis_copy),
        "formal_evidence_path": _rel(evidence_path),
        "formal_evidence_sha256": sha256_file(evidence_path),
        "run_copy_formal_evidence_path": _rel(evidence_copy),
        "run_copy_formal_evidence_sha256": sha256_file(evidence_copy),
        "committed_artifacts": [_artifact(path) for path in committed_paths],
        "local_materialized_artifacts": [
            {
                "path": record["path"],
                "sha256": record["sha256"],
                "row_count": record["row_count"],
                "table": record["table"],
                "committed_to_repo": False,
            }
            for record in manifest["outputs"].values()
        ],
        "supersedes": {
            "result_package_path": source["original_result_package_archive_path"],
            "result_package_sha256": source["original_result_package_sha256"],
            "handoff_path": source["original_handoff_archive_path"],
            "handoff_sha256": source["original_handoff_sha256"],
            "reason": revision["external_review"]["blocking_findings"],
        },
        "review_history": revision_record["review_history"],
        "gate_status": {
            "engineering_validator_status": "passed",
            "author_result_analysis_status": "passed",
            "anomaly_resolution_status": "passed",
            "author_revision_status": "completed",
            "goal_internal_continuation_gate_status": (
                "closed_pending_external_rereview"
            ),
            "goal_internal_continuation_allowed": False,
            "goal_internal_t14_02_authorized": False,
            "repository_t14_02_gate_passed": False,
        },
        "R0_q_vector_materialization_status": (
            "author_revision_complete_pending_rereview"
        ),
        "R0_q_vector_materialization_request_status": "approved",
        "independent_review_status": "pending_rereview",
        "repository_final_gate_status": "pending",
        "R1-T14-02_allowed_to_start": False,
        "R1-T10_allowed_to_start": False,
        "R2_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "external_direct_duckdb_byte_review_performed": False,
        "formal_task_completed": False,
        "status": "author_revision_complete",
        "superseded": False,
    }
    write_json_atomic(run_dir / "r0_t15_result_package.json", package)
    return package


def _archive_original(current: Path, archive: Path, expected_sha256: str) -> None:
    if archive.is_file():
        if sha256_file(archive) != expected_sha256:
            raise RuntimeError(f"archive_hash_mismatch:{archive}")
        return
    if not current.is_file() or sha256_file(current) != expected_sha256:
        raise RuntimeError(f"source_archive_bytes_unavailable:{current}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(current, archive)
    if sha256_file(archive) != expected_sha256:
        raise RuntimeError(f"archive_copy_hash_mismatch:{archive}")


def _verify_reference_group(group: Mapping[str, Any]) -> None:
    for key, value in group.items():
        if not key.endswith("_path"):
            continue
        prefix = key.removesuffix("_path")
        hash_key = f"{prefix}_sha256"
        if hash_key not in group:
            continue
        path = ROOT / str(value)
        if not path.is_file():
            raise RuntimeError(f"reference_missing:{key}")
        if sha256_file(path) != group[hash_key]:
            raise RuntimeError(f"reference_hash_mismatch:{key}")


def _verify_final_gate_semantics(binding: Mapping[str, Any]) -> None:
    package = _load_json(ROOT / binding["result_package_path"])
    review = _load_json(ROOT / binding["scientific_review_path"])
    gate = _load_json(ROOT / binding["final_gate_validation_path"])
    request = _load_json(ROOT / binding["materialization_request_path"])
    if (
        package.get("status") != "completed"
        or package.get("scientific_review_status") != "passed"
        or package.get("formal_task_completed") is not True
        or package.get("downstream_gate_scope") != "R0-T15_only"
        or package.get("R0_q_vector_materialization_allowed_to_start") is not True
        or package.get("R1-T14-02_allowed_to_start") is not False
    ):
        raise RuntimeError("upstream_result_package_final_gate_invalid")
    if (
        review.get("scientific_review_status") != "passed"
        or review.get("reviewer_identity") != "benzemaer"
        or str(review.get("review_comment_id")) != "4941866339"
    ):
        raise RuntimeError("upstream_scientific_review_invalid")
    if (
        gate.get("status") != "passed"
        or gate.get("formal_task_completed") is not True
        or gate.get("downstream_gate_scope") != "R0-T15_only"
        or gate.get("R1-T14-02_allowed_to_start") is not False
    ):
        raise RuntimeError("upstream_final_gate_validation_invalid")
    if (
        request.get("decision") != "q_vector_materialization_request"
        or request.get("scientific_review_status") != "pending"
    ):
        raise RuntimeError("reviewed_materialization_request_invalid")


def _assert_commit_ancestor(commit: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=ROOT
    )
    if result.returncode != 0:
        raise RuntimeError(f"revision_upstream_commit_not_ancestor:{commit}")


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": _rel(path),
        "sha256": sha256_file(path),
        "record_count": _row_count(path),
        "committed_to_repo": True,
    }


def _row_count(path: Path) -> int:
    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    return 1


def _rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(path)
    return value
