from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.common.canonical_io import (
    ROOT,
    git_blob_bytes,
    git_blob_sha,
    repo_rel,
    sha256_bytes,
    write_json,
)

RUN_ID = "R2-T03-PROMOTED-20260713T050903Z"
REPOSITORY = "benzemaer/convergence-research"
PR_NUMBER = 95
REVIEWED_HEAD = "31cb6dfde21aca517257e510dbef00296035ad6e"
MERGE_COMMIT = "9745c08c730f9764e1acdc1c3ccdf21062343c08"
SCIENTIFIC_REVIEW_ID = 4682273489
READY_WORKFLOW_RUN_ID = 29229652890
PREMERGE_JOB_ID = 86750926577
WORKFLOW_NAME = "Quality"
RUN_DIR = Path("data/generated/r2/r2_t03") / RUN_ID
HANDOFF_NAME = "r2_t03_repository_final_gate_handoff.json"
VALIDATION_NAME = "r2_t03_repository_final_gate_handoff_validation.json"
HANDOFF_SCHEMA = Path("schemas/r2/r2_t03_repository_final_gate_handoff.schema.json")
VALIDATION_SCHEMA = Path(
    "schemas/r2/r2_t03_repository_final_gate_handoff_validation.schema.json"
)

BOUND_PATHS = (
    RUN_DIR / "r2_t03_execution_promotion.json",
    RUN_DIR / "r2_t03_promoted_execution_summary.json",
    RUN_DIR / "r2_t03_result_package.json",
    RUN_DIR / "r2_t03_output_manifest.json",
    RUN_DIR / "r2_t03_author_stage_scientific_review.json",
    RUN_DIR / "r2_t03_result_analysis.md",
    RUN_DIR / "r2_t03_anomaly_scan.json",
    RUN_DIR / "r2_t03_runtime_gate_validation.json",
    RUN_DIR / "r2_t03_independent_validation.json",
    RUN_DIR / "r2_t03_post_validation_fingerprint.json",
    RUN_DIR / "database_fingerprint.json",
    HANDOFF_SCHEMA,
    VALIDATION_SCHEMA,
    Path("src/r2/r2_t03_repository_final_gate_handoff.py"),
    Path("scripts/r2/validate_r2_t03_repository_final_gate_handoff.py"),
)


class R2T03HandoffError(RuntimeError):
    pass


def create_handoff(
    output_path: Path, *, source_commit: str, root: Path = ROOT
) -> dict[str, Any]:
    source_commit = _resolve_commit(source_commit, root)
    remote = _validate_remote_facts(root)
    merge_parents = _validate_merge_ancestry(source_commit, root)
    author = _load_json(root / RUN_DIR / "r2_t03_result_package.json")
    _validate_immutable_author(author)
    promotion = _load_json(root / RUN_DIR / "r2_t03_execution_promotion.json")
    summary = _load_json(root / RUN_DIR / "r2_t03_promoted_execution_summary.json")
    package = _load_json(root / RUN_DIR / "r2_t03_result_package.json")
    if (
        promotion.get("promotion_id") != RUN_ID
        or summary.get("promoted_run_id") != RUN_ID
    ):
        raise R2T03HandoffError("promotion_identity_mismatch")
    if (
        package.get("database_sha256")
        != "9e6015a612ad839a386a4300e289be87d9fd3d073658c1b095a7ce02bb3a14e0"
    ):
        raise R2T03HandoffError("database_sha_mismatch")
    bindings = {
        path.as_posix(): _committed_binding(path, source_commit, root)
        for path in BOUND_PATHS
    }
    payload = {
        "task_id": "R2-T03",
        "promoted_run_id": RUN_ID,
        "handoff_version": "r2_t03_repository_final_gate_handoff.v1",
        "handoff_source_commit": source_commit,
        "author_package_lifecycle": "immutable_author_stage",
        "scientific_review_status": "passed",
        "repository_final_gate_status": "passed",
        "formal_task_completed": True,
        "R2-T04_allowed_to_start": True,
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "repository": REPOSITORY,
        "pull_request_number": PR_NUMBER,
        "reviewed_head_sha": REVIEWED_HEAD,
        "merge_commit": MERGE_COMMIT,
        "merge_parents": merge_parents,
        "scientific_review_id": SCIENTIFIC_REVIEW_ID,
        "ready_workflow_run_id": READY_WORKFLOW_RUN_ID,
        "premerge_job_id": PREMERGE_JOB_ID,
        "workflow_name": WORKFLOW_NAME,
        "ready_workflow_overall_conclusion": remote["run"]["conclusion"],
        "full_profile_status": "passed",
        "full_profile_test_count": 1200,
        "full_profile_failure_count": 0,
        "github_scientific_review_fetch_status": "passed",
        "exact_head_scientific_review_recognized": True,
        "t02_evidence_build_status": "passed",
        "t02_evidence_consumer_status": "failed",
        "t02_evidence_consumer_error": "formal_surface_changed_after_artifact_commit",
        "t02_consumer_applicability_to_r2_t03": "not_applicable",
        "consumer_scope": "R2-T02 artifact formal-surface immutability",
        "not_applicable_reason": (
            "The reused consumer byte-compares the R2-T02 v8 formal source surface "
            "between the T02 artifact commit and the reviewed T03 head. R2-T03 "
            "introduced reviewed compatibility changes in "
            "src/r2/r2_t02_protocol_freeze.py, which is included in that T02 formal "
            "source list. The consumer therefore answers a T02 artifact immutability "
            "question, not the R2-T03 execution/scientific gate."
        ),
        "exception_scope": "only_the_reused_t02_consumer",
        "exception_does_not_waive": (
            "T03 implementation review, T03 runtime gates, T03 independent validation, "
            "T03 anomaly scan, T03 scientific review, T03 committed-artifact "
            "validation, "
            "exact-head full test profile"
        ),
        "administrator_merge": True,
        "administrator_exception_recorded": True,
        "database_sha256": package["database_sha256"],
        "database_size_bytes": 1099968512,
        "database_fingerprint": _load_json(
            root / RUN_DIR / "database_fingerprint.json"
        ),
        "committed_inputs": bindings,
        "validation_assertions": {
            "github_api_identity_revalidated": True,
            "github_scientific_review_snapshot_revalidated": True,
            "ready_workflow_snapshot_revalidated": True,
            "premerge_job_snapshot_revalidated": True,
            "author_package_immutable": True,
            "promotion_and_result_artifacts_bound": True,
            "database_metadata_bound": True,
            "merge_ancestry_verified": True,
            "all_committed_sha_verified": True,
        },
    }
    _validate_schema(payload, root / HANDOFF_SCHEMA)
    output_path = output_path if output_path.is_absolute() else root / output_path
    write_json(output_path, payload)
    return payload


def validate_handoff(
    handoff_path: Path,
    *,
    handoff_commit: str,
    output_path: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    handoff_path = handoff_path if handoff_path.is_absolute() else root / handoff_path
    errors: list[str] = []
    payload: dict[str, Any] = {}
    try:
        handoff_commit = _resolve_commit(handoff_commit, root)
        payload = _load_json(handoff_path)
        _validate_schema(payload, root / HANDOFF_SCHEMA)
        _validate_remote_facts(root)
        _validate_immutable_author(
            _load_json(root / RUN_DIR / "r2_t03_result_package.json")
        )
        _validate_handoff_semantics(payload)
        _validate_merge_ancestry(payload["handoff_source_commit"], root)
        _validate_bindings(payload["committed_inputs"], root)
        rel = repo_rel(handoff_path, root)
        committed = git_blob_bytes(handoff_commit, rel, root=root)
        if committed != handoff_path.read_bytes():
            raise R2T03HandoffError("handoff_worktree_commit_mismatch")
        handoff_blob = git_blob_sha(handoff_commit, rel, root=root)
        handoff_sha = sha256_bytes(committed)
    except (
        OSError,
        ValueError,
        KeyError,
        subprocess.CalledProcessError,
        R2T03HandoffError,
    ) as exc:
        errors.append(str(exc))
        handoff_blob = ""
        handoff_sha = ""
    result = {
        "task_id": "R2-T03",
        "promoted_run_id": RUN_ID,
        "validation_mode": "post_merge_repository_final_gate_handoff",
        "status": "passed" if not errors else "failed",
        "handoff_path": repo_rel(handoff_path, root),
        "handoff_commit": _resolve_commit(handoff_commit, root),
        "handoff_git_blob_sha": handoff_blob,
        "handoff_committed_sha256": handoff_sha,
        "validated_binding_count": len(payload.get("committed_inputs", {})),
        "github_api_identity_revalidated": not errors,
        "github_scientific_review_snapshot_revalidated": not errors,
        "ready_workflow_snapshot_revalidated": not errors,
        "premerge_job_snapshot_revalidated": not errors,
        "author_package_immutable": not errors,
        "promotion_and_result_artifacts_bound": not errors,
        "database_metadata_bound": not errors,
        "merge_ancestry_verified": not errors,
        "all_committed_sha_verified": not errors,
        "scientific_review_status": "passed" if not errors else "pending",
        "repository_final_gate_status": "passed" if not errors else "pending",
        "formal_task_completed": not errors,
        "R2-T04_allowed_to_start": not errors,
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "errors": errors,
    }
    _validate_schema(result, root / VALIDATION_SCHEMA)
    if output_path is not None:
        output_path = output_path if output_path.is_absolute() else root / output_path
        write_json(output_path, result)
    if errors:
        raise R2T03HandoffError(",".join(errors))
    return result


def _validate_handoff_semantics(payload: dict[str, Any]) -> None:
    expected = {
        "task_id": "R2-T03",
        "promoted_run_id": RUN_ID,
        "scientific_review_status": "passed",
        "repository_final_gate_status": "passed",
        "formal_task_completed": True,
        "R2-T04_allowed_to_start": True,
        "R2-T05_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "reviewed_head_sha": REVIEWED_HEAD,
        "merge_commit": MERGE_COMMIT,
        "scientific_review_id": SCIENTIFIC_REVIEW_ID,
        "ready_workflow_run_id": READY_WORKFLOW_RUN_ID,
        "premerge_job_id": PREMERGE_JOB_ID,
        "ready_workflow_overall_conclusion": "failure",
        "full_profile_status": "passed",
        "t02_evidence_build_status": "passed",
        "t02_evidence_consumer_status": "failed",
        "t02_evidence_consumer_error": "formal_surface_changed_after_artifact_commit",
        "t02_consumer_applicability_to_r2_t03": "not_applicable",
        "administrator_merge": True,
        "administrator_exception_recorded": True,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise R2T03HandoffError(f"handoff_semantic_mismatch:{key}")


def _validate_immutable_author(author: dict[str, Any]) -> None:
    for key, value in {
        "scientific_review_status": "pending_independent_scientific_review",
        "formal_task_completed": False,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
    }.items():
        if author.get(key) != value:
            raise R2T03HandoffError(f"author_package_lifecycle_mutated:{key}")


def _validate_remote_facts(root: Path) -> dict[str, Any]:
    run = _gh_json(f"repos/{REPOSITORY}/actions/runs/{READY_WORKFLOW_RUN_ID}", root)
    job = _gh_json(f"repos/{REPOSITORY}/actions/jobs/{PREMERGE_JOB_ID}", root)
    pr = _gh_json(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}", root)
    reviews = _gh_json_list(
        f"repos/{REPOSITORY}/pulls/{PR_NUMBER}/reviews?per_page=100", root
    )
    checks = [
        ("run.id", run.get("id"), READY_WORKFLOW_RUN_ID),
        ("run.head_sha", run.get("head_sha"), REVIEWED_HEAD),
        ("run.conclusion", run.get("conclusion"), "failure"),
        ("job.id", job.get("id"), PREMERGE_JOB_ID),
        ("job.head_sha", job.get("head_sha"), REVIEWED_HEAD),
        ("job.name", job.get("name"), "premerge-full"),
        ("pr.merge_commit_sha", pr.get("merge_commit_sha"), MERGE_COMMIT),
        ("pr.head.sha", pr.get("head", {}).get("sha"), REVIEWED_HEAD),
    ]
    for key, observed, expected in checks:
        if observed != expected:
            raise R2T03HandoffError(f"github_metadata_mismatch:{key}")
    review = next(
        (row for row in reviews if int(row.get("id", 0)) == SCIENTIFIC_REVIEW_ID), None
    )
    if (
        not review
        or review.get("commit_id") != REVIEWED_HEAD
        or review.get("state") not in {"COMMENTED", "APPROVED"}
        or "[R2-T02 scientific PASS]" not in str(review.get("body", ""))
        or "scientific_review_status=passed" not in str(review.get("body", ""))
    ):
        raise R2T03HandoffError("scientific_review_snapshot_mismatch")
    steps = {step.get("name"): step.get("conclusion") for step in job.get("steps", [])}
    if (
        steps.get("Run full profile on reviewed head") != "success"
        or steps.get("Fetch authenticated GitHub scientific reviews") != "success"
        or steps.get("Build R2-T02 premerge full evidence") != "success"
        or steps.get("Consume R2-T02 premerge full evidence final gate") != "failure"
    ):
        raise R2T03HandoffError("premerge_step_status_mismatch")
    return {"run": run, "job": job, "pr": pr, "review": review}


def _validate_bindings(bindings: dict[str, Any], root: Path) -> None:
    expected = {path.as_posix() for path in BOUND_PATHS}
    if set(bindings) != expected:
        raise R2T03HandoffError("committed_binding_path_set_mismatch")
    for rel, binding in bindings.items():
        blob = git_blob_bytes(binding["source_commit"], rel, root=root)
        if (
            git_blob_sha(binding["source_commit"], rel, root=root)
            != binding["git_blob_sha"]
            or sha256_bytes(blob) != binding["committed_byte_sha256"]
            or (root / rel).read_bytes() != blob
        ):
            raise R2T03HandoffError(f"committed_binding_mismatch:{rel}")


def _committed_binding(path: Path, commit: str, root: Path) -> dict[str, str]:
    rel = path.as_posix()
    blob = git_blob_bytes(commit, rel, root=root)
    if (root / rel).read_bytes() != blob:
        raise R2T03HandoffError(f"worktree_commit_mismatch:{rel}")
    return {
        "path": rel,
        "source_commit": commit,
        "git_blob_sha": git_blob_sha(commit, rel, root=root),
        "committed_byte_sha256": sha256_bytes(blob),
    }


def _validate_merge_ancestry(source_commit: str, root: Path) -> list[str]:
    parents = _git_text(["show", "-s", "--format=%P", MERGE_COMMIT], root).split()
    if REVIEWED_HEAD not in parents or not _is_ancestor(
        MERGE_COMMIT, source_commit, root
    ):
        raise R2T03HandoffError("merge_ancestry_mismatch")
    return parents


def _validate_schema(payload: dict[str, Any], schema_path: Path) -> None:
    errors = sorted(
        Draft202012Validator(_load_json(schema_path)).iter_errors(payload), key=str
    )
    if errors:
        raise R2T03HandoffError(";".join(f"{e.json_path}:{e.message}" for e in errors))


def _gh_json(endpoint: str, root: Path) -> dict[str, Any]:
    value = json.loads(
        subprocess.check_output(["gh", "api", endpoint], cwd=root, text=True)
    )
    if not isinstance(value, dict):
        raise R2T03HandoffError("github_response_not_object")
    return value


def _gh_json_list(endpoint: str, root: Path) -> list[dict[str, Any]]:
    value = json.loads(
        subprocess.check_output(
            ["gh", "api", "--paginate", endpoint], cwd=root, text=True
        )
    )
    if not isinstance(value, list):
        raise R2T03HandoffError("github_response_not_array")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise R2T03HandoffError(f"expected_json_object:{path}")
    return value


def _resolve_commit(commit: str, root: Path) -> str:
    return _git_text(["rev-parse", commit], root)


def _git_text(args: list[str], root: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _is_ancestor(ancestor: str, descendant: str, root: Path) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=root,
            capture_output=True,
        ).returncode
        == 0
    )
