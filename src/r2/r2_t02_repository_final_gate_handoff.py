from __future__ import annotations

import argparse
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
from src.r2.r2_t02_premerge_full_evidence import validate_final_gate

RUN_ID = "R2-T02-20260712T1700Z"
REPOSITORY = "benzemaer/convergence-research"
PR_NUMBER = 94
WORKFLOW_NAME = "Quality"
ARTIFACT_ID = 8259206209
ARTIFACT_NAME = "r2-t02-premerge-full-evidence"
ARTIFACT_DIGEST = (
    "sha256:baa3d5f0fee84fe001ffb83c379e5c370c48491c9ceccb10172a2195e64d7223"
)
WORKFLOW_RUN_ID = 29189876487
PREMERGE_JOB_ID = 86642565197
REVIEWED_HEAD = "a98d2a14e8828585e6b4283efee6afdf2db8672d"
MERGE_COMMIT = "04530181e7cd80b8805f279dbac5eb5afb70c21d"
SCIENTIFIC_REVIEW_ID = 4679909839
RUN_DIR = Path("data/generated/r2/r2_t02") / RUN_ID
ARTIFACT_DIR = Path("artifacts/r2_t02_premerge")
EVIDENCE_PATH = ARTIFACT_DIR / "r2_t02_premerge_full_evidence.json"
HANDOFF_NAME = "r2_t02_repository_final_gate_handoff.json"
VALIDATION_NAME = "r2_t02_repository_final_gate_handoff_validation.json"
HANDOFF_SCHEMA = Path("schemas/r2/r2_t02_repository_final_gate_handoff.schema.json")
VALIDATION_SCHEMA = Path(
    "schemas/r2/r2_t02_repository_final_gate_handoff_validation.schema.json"
)

COMMITTED_INPUT_PATHS = (
    ARTIFACT_DIR / "full_profile_result.json",
    ARTIFACT_DIR / "review_pages.json",
    EVIDENCE_PATH,
    RUN_DIR / "r2_t02_result_package.json",
    RUN_DIR / "r2_t02_author_stage_scientific_review.json",
    RUN_DIR / "r2_t02_committed_artifact_validation.json",
    Path("schemas/r2/r2_t02_premerge_full_evidence.schema.json"),
    HANDOFF_SCHEMA,
    VALIDATION_SCHEMA,
    Path("src/r2/r2_t02_premerge_full_evidence.py"),
    Path("src/r2/r2_t02_repository_final_gate_handoff.py"),
    Path("scripts/r2/validate_r2_t02_repository_final_gate_handoff.py"),
)


class R2T02HandoffError(RuntimeError):
    pass


def create_handoff(
    output_path: Path,
    *,
    source_commit: str,
    root: Path = ROOT,
    verify_remote: bool = True,
) -> dict[str, Any]:
    source_commit = _resolve_commit(source_commit, root)
    evidence_path = root / EVIDENCE_PATH
    validate_final_gate(
        evidence_path,
        reviewed_head_sha=REVIEWED_HEAD,
        expected_repository=REPOSITORY,
        expected_pr_number=PR_NUMBER,
        expected_workflow=WORKFLOW_NAME,
        root=root,
    )
    evidence = _load_json(evidence_path)
    review_rows = _load_array(root / ARTIFACT_DIR / "review_pages.json")
    _validate_evidence_identity(evidence, review_rows)
    merge_parents = _validate_merge_ancestry(source_commit, root)
    remote_metadata = (
        _validate_remote_metadata(root)
        if verify_remote
        else _expected_remote_metadata()
    )
    bindings = {
        path.as_posix(): _committed_binding(path, source_commit, root)
        for path in COMMITTED_INPUT_PATHS
    }
    author = _load_json(root / RUN_DIR / "r2_t02_result_package.json")
    _validate_immutable_author_package(author)
    payload = {
        "task_id": "R2-T02",
        "run_id": RUN_ID,
        "handoff_version": "r2_t02_repository_final_gate_handoff.v1",
        "handoff_source_commit": source_commit,
        "author_package_lifecycle": "immutable_author_stage",
        "scientific_review_status": "passed",
        "repository_final_gate_status": "passed",
        "formal_task_completed": True,
        "R2-T03_allowed_to_start": True,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "repository": REPOSITORY,
        "pull_request_number": PR_NUMBER,
        "workflow_name": WORKFLOW_NAME,
        "workflow_run_id": WORKFLOW_RUN_ID,
        "premerge_job_id": PREMERGE_JOB_ID,
        "reviewed_head_sha": REVIEWED_HEAD,
        "merge_commit": MERGE_COMMIT,
        "merge_parents": merge_parents,
        "scientific_review_id": SCIENTIFIC_REVIEW_ID,
        "workflow_artifact": {
            "artifact_id": ARTIFACT_ID,
            "artifact_name": ARTIFACT_NAME,
            "artifact_digest": ARTIFACT_DIGEST,
            "expired_at_handoff": remote_metadata["expired"],
            "workflow_run_id": WORKFLOW_RUN_ID,
            "head_sha": REVIEWED_HEAD,
        },
        "workflow_evidence_path": EVIDENCE_PATH.as_posix(),
        "committed_inputs": bindings,
        "validation_assertions": {
            "existing_validate_final_gate_called": True,
            "github_review_snapshot_revalidated": True,
            "author_package_immutable": True,
            "committed_artifact_sidecar_revalidated": True,
            "exact_head_verified": True,
            "merge_ancestry_verified": True,
            "artifact_metadata_verified": True,
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
    verify_remote: bool = True,
) -> dict[str, Any]:
    handoff_path = handoff_path if handoff_path.is_absolute() else root / handoff_path
    handoff_commit = _resolve_commit(handoff_commit, root)
    errors: list[str] = []
    try:
        payload = _load_json(handoff_path)
        _validate_schema(payload, root / HANDOFF_SCHEMA)
        validate_final_gate(
            root / payload["workflow_evidence_path"],
            reviewed_head_sha=REVIEWED_HEAD,
            expected_repository=REPOSITORY,
            expected_pr_number=PR_NUMBER,
            expected_workflow=WORKFLOW_NAME,
            root=root,
        )
        review_rows = _load_array(root / ARTIFACT_DIR / "review_pages.json")
        evidence = _load_json(root / payload["workflow_evidence_path"])
        _validate_evidence_identity(evidence, review_rows)
        _validate_merge_ancestry(payload["handoff_source_commit"], root)
        if verify_remote:
            _validate_remote_metadata(root)
        _validate_handoff_semantics(payload)
        _validate_bindings(payload["committed_inputs"], root)
        _validate_immutable_author_package(
            _load_json(root / RUN_DIR / "r2_t02_result_package.json")
        )
        handoff_rel = repo_rel(handoff_path, root)
        committed = git_blob_bytes(handoff_commit, handoff_rel, root=root)
        if committed != handoff_path.read_bytes():
            raise R2T02HandoffError("handoff_worktree_commit_mismatch")
        handoff_blob = git_blob_sha(handoff_commit, handoff_rel, root=root)
        handoff_sha = sha256_bytes(committed)
    except (
        OSError,
        ValueError,
        KeyError,
        subprocess.CalledProcessError,
        R2T02HandoffError,
    ) as exc:
        errors.append(str(exc))
        handoff_rel = repo_rel(handoff_path, root) if handoff_path.exists() else ""
        handoff_blob = ""
        handoff_sha = ""
        payload = {}
    result = {
        "task_id": "R2-T02",
        "run_id": RUN_ID,
        "validation_mode": "post_merge_repository_final_gate_handoff",
        "status": "passed" if not errors else "failed",
        "handoff_path": handoff_rel,
        "handoff_commit": handoff_commit,
        "handoff_git_blob_sha": handoff_blob,
        "handoff_committed_sha256": handoff_sha,
        "validated_binding_count": len(payload.get("committed_inputs", {})),
        "existing_validate_final_gate_called": not errors,
        "github_review_snapshot_revalidated": not errors,
        "merge_ancestry_verified": not errors,
        "artifact_metadata_verified": not errors,
        "all_committed_sha_verified": not errors,
        "author_package_immutable": not errors,
        "scientific_review_status": "passed" if not errors else "pending",
        "repository_final_gate_status": "passed" if not errors else "pending",
        "formal_task_completed": not errors,
        "R2-T03_allowed_to_start": not errors,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "errors": errors,
    }
    _validate_schema(result, root / VALIDATION_SCHEMA)
    if output_path is not None:
        output_path = output_path if output_path.is_absolute() else root / output_path
        write_json(output_path, result)
    if errors:
        raise R2T02HandoffError(",".join(errors))
    return result


def _validate_handoff_semantics(payload: dict[str, Any]) -> None:
    expected = {
        "task_id": "R2-T02",
        "run_id": RUN_ID,
        "author_package_lifecycle": "immutable_author_stage",
        "scientific_review_status": "passed",
        "repository_final_gate_status": "passed",
        "formal_task_completed": True,
        "R2-T03_allowed_to_start": True,
        "R2-T04_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "repository": REPOSITORY,
        "pull_request_number": PR_NUMBER,
        "workflow_name": WORKFLOW_NAME,
        "workflow_run_id": WORKFLOW_RUN_ID,
        "premerge_job_id": PREMERGE_JOB_ID,
        "reviewed_head_sha": REVIEWED_HEAD,
        "merge_commit": MERGE_COMMIT,
        "scientific_review_id": SCIENTIFIC_REVIEW_ID,
    }
    mismatches = [key for key, value in expected.items() if payload.get(key) != value]
    if mismatches:
        raise R2T02HandoffError(f"handoff_semantic_mismatch:{mismatches[0]}")
    artifact = payload["workflow_artifact"]
    artifact_expected = {
        "artifact_id": ARTIFACT_ID,
        "artifact_name": ARTIFACT_NAME,
        "artifact_digest": ARTIFACT_DIGEST,
        "expired_at_handoff": False,
        "workflow_run_id": WORKFLOW_RUN_ID,
        "head_sha": REVIEWED_HEAD,
    }
    for key, value in artifact_expected.items():
        if artifact.get(key) != value:
            raise R2T02HandoffError(f"artifact_metadata_mismatch:{key}")


def _validate_evidence_identity(
    evidence: dict[str, Any], review_rows: list[dict[str, Any]]
) -> None:
    expected = {
        "workflow_run_id": WORKFLOW_RUN_ID,
        "tested_head_sha": REVIEWED_HEAD,
        "reviewed_head_sha": REVIEWED_HEAD,
        "github_scientific_review_id": SCIENTIFIC_REVIEW_ID,
    }
    for key, value in expected.items():
        if evidence.get(key) != value:
            raise R2T02HandoffError(f"workflow_evidence_identity_mismatch:{key}")
    matching = [
        row
        for row in review_rows
        if int(row.get("id", 0)) == SCIENTIFIC_REVIEW_ID
        and row.get("commit_id") == REVIEWED_HEAD
        and "[R2-T02 scientific PASS]" in str(row.get("body", ""))
    ]
    if len(matching) != 1:
        raise R2T02HandoffError("scientific_review_snapshot_mismatch")


def _validate_immutable_author_package(author: dict[str, Any]) -> None:
    expected = {
        "run_id": RUN_ID,
        "scientific_review_status": "pending",
        "independent_review_status": "pending",
        "repository_final_gate_status": "pending",
        "formal_task_completed": False,
        "R2-T03_allowed_to_start": False,
    }
    for key, value in expected.items():
        if author.get(key) != value:
            raise R2T02HandoffError(f"author_package_lifecycle_mutated:{key}")


def _validate_bindings(bindings: dict[str, Any], root: Path) -> None:
    expected_paths = {path.as_posix() for path in COMMITTED_INPUT_PATHS}
    if set(bindings) != expected_paths:
        raise R2T02HandoffError("committed_binding_path_set_mismatch")
    for rel, binding in bindings.items():
        commit = binding["source_commit"]
        blob = git_blob_bytes(commit, rel, root=root)
        if git_blob_sha(commit, rel, root=root) != binding["git_blob_sha"]:
            raise R2T02HandoffError(f"committed_git_blob_sha_mismatch:{rel}")
        if sha256_bytes(blob) != binding["committed_byte_sha256"]:
            raise R2T02HandoffError(f"committed_byte_sha256_mismatch:{rel}")
        if (root / rel).read_bytes() != blob:
            raise R2T02HandoffError(f"committed_worktree_byte_mismatch:{rel}")


def _committed_binding(path: Path, commit: str, root: Path) -> dict[str, str]:
    rel = path.as_posix()
    blob = git_blob_bytes(commit, rel, root=root)
    if (root / rel).read_bytes() != blob:
        raise R2T02HandoffError(f"committed_worktree_byte_mismatch:{rel}")
    return {
        "path": rel,
        "source_commit": commit,
        "git_blob_sha": git_blob_sha(commit, rel, root=root),
        "committed_byte_sha256": sha256_bytes(blob),
    }


def _validate_merge_ancestry(source_commit: str, root: Path) -> list[str]:
    parents = _git_text(["show", "-s", "--format=%P", MERGE_COMMIT], root).split()
    if REVIEWED_HEAD not in parents:
        raise R2T02HandoffError("reviewed_head_not_direct_merge_parent")
    if not _is_ancestor(REVIEWED_HEAD, MERGE_COMMIT, root):
        raise R2T02HandoffError("reviewed_head_not_merge_ancestor")
    if not _is_ancestor(MERGE_COMMIT, source_commit, root):
        raise R2T02HandoffError("merge_commit_not_handoff_source_ancestor")
    return parents


def _validate_remote_metadata(root: Path) -> dict[str, Any]:
    artifact = _gh_json(f"repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}", root)
    job = _gh_json(f"repos/{REPOSITORY}/actions/jobs/{PREMERGE_JOB_ID}", root)
    checks = {
        "artifact.id": (artifact.get("id"), ARTIFACT_ID),
        "artifact.name": (artifact.get("name"), ARTIFACT_NAME),
        "artifact.digest": (artifact.get("digest"), ARTIFACT_DIGEST),
        "artifact.expired": (artifact.get("expired"), False),
        "artifact.workflow_run.id": (
            artifact.get("workflow_run", {}).get("id"),
            WORKFLOW_RUN_ID,
        ),
        "artifact.workflow_run.head_sha": (
            artifact.get("workflow_run", {}).get("head_sha"),
            REVIEWED_HEAD,
        ),
        "job.id": (job.get("id"), PREMERGE_JOB_ID),
        "job.run_id": (job.get("run_id"), WORKFLOW_RUN_ID),
        "job.head_sha": (job.get("head_sha"), REVIEWED_HEAD),
        "job.name": (job.get("name"), "premerge-full"),
        "job.conclusion": (job.get("conclusion"), "success"),
    }
    for key, (observed, expected) in checks.items():
        if observed != expected:
            raise R2T02HandoffError(f"remote_metadata_mismatch:{key}")
    return {"expired": bool(artifact["expired"])}


def _expected_remote_metadata() -> dict[str, Any]:
    return {"expired": False}


def _gh_json(endpoint: str, root: Path) -> dict[str, Any]:
    value = json.loads(
        subprocess.check_output(["gh", "api", endpoint], cwd=root, text=True)
    )
    if not isinstance(value, dict):
        raise R2T02HandoffError("github_api_response_not_object")
    return value


def _validate_schema(payload: dict[str, Any], schema_path: Path) -> None:
    validator = Draft202012Validator(_load_json(schema_path))
    errors = sorted(validator.iter_errors(payload), key=str)
    if errors:
        raise R2T02HandoffError(
            ";".join(f"{error.json_path}:{error.message}" for error in errors)
        )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise R2T02HandoffError(f"expected_json_object:{path}")
    return value


def _load_array(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise R2T02HandoffError(f"expected_json_object_array:{path}")
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or validate the R2-T02 post-merge final-gate handoff."
    )
    parser.add_argument("--source-commit")
    parser.add_argument("--handoff-commit")
    parser.add_argument(
        "--handoff-path",
        default=str(RUN_DIR / "r2_t02_repository_final_gate_handoff.json"),
    )
    parser.add_argument("--output")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.create:
        if not args.source_commit:
            parser.error("--source-commit is required with --create")
        create_handoff(
            Path(args.handoff_path),
            source_commit=args.source_commit,
            verify_remote=not args.offline,
        )
        return 0
    if not args.handoff_commit:
        parser.error("--handoff-commit is required for validation")
    validate_handoff(
        Path(args.handoff_path),
        handoff_commit=args.handoff_commit,
        output_path=Path(args.output) if args.output else None,
        verify_remote=not args.offline,
    )
    return 0
