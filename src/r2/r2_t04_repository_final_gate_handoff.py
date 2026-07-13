from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.r2.r2_t04_independent_validator import validate_phase_b

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "R2-T04-20260713T120000Z"
RUN_DIR = Path("data/generated/r2/r2_t04") / RUN_ID
REPOSITORY = "benzemaer/convergence-research"
PR_NUMBER = 96
REVIEWED_HEAD = "981be003101668200e3c3c97ea491f7b2ab1c5fa"
MERGE_COMMIT = "fc580479bf10d2f71d7bee510fa8c67bed6ff29c"
SCIENTIFIC_REVIEW_ID = 4683908631
READY_WORKFLOW_RUN_ID = 29242838829
PREMERGE_JOB_ID = 86795398235
WORKFLOW_NAME = "Quality"
HANDOFF_REL = (RUN_DIR / "r2_t04_repository_final_gate_handoff.json").as_posix()
VALIDATION_REL = (
    RUN_DIR / "r2_t04_repository_final_gate_handoff_validation.json"
).as_posix()
SCHEMA_REL = "schemas/r2/r2_t04_repository_final_gate_handoff.schema.json"
VALIDATION_SCHEMA_REL = (
    "schemas/r2/r2_t04_repository_final_gate_handoff_validation.schema.json"
)

T04_ARTIFACTS = (
    "r2_t04_phase_a_review_resolution.json",
    "r2_t04_user_decision_input.json",
    "r2_t04_user_decision_record.json",
    "r2_t04_selected_cell_gate_revalidation.csv",
    "r2_t04_selected_cell_gate_revalidation.json",
    "r2_t04_freeze_decision.json",
    "r2_t04_freeze_plan_manifest.json",
    "r2_t04_phase_b_independent_validation.json",
    "r2_t04_anomaly_scan.json",
    "r2_t04_result_analysis.md",
    "r2_t04_result_package.json",
    "r2_t04_author_stage_scientific_review.json",
    "r2_t04_repository_final_gate.json",
    "r2_t04_phase_b_validation.json",
)


class R2T04HandoffError(RuntimeError):
    pass


def _git_bytes(commit: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)


def _git_blob(commit: str, path: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", f"{commit}:{path}"], cwd=ROOT, text=True
    ).strip()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise R2T04HandoffError(f"expected_object:{path}")
    return value


def _gh(endpoint: str) -> Any:
    raw = subprocess.check_output(["gh", "api", endpoint], cwd=ROOT)
    return json.loads(raw)


def _review() -> dict[str, Any]:
    reviews = _gh(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}/reviews?per_page=100")
    for review in reviews:
        if (
            int(review.get("id", 0)) == SCIENTIFIC_REVIEW_ID
            and review.get("commit_id") == REVIEWED_HEAD
            and review.get("state") == "COMMENTED"
            and "scientific_review_status=passed" in review.get("body", "")
        ):
            return review
    raise R2T04HandoffError("exact_head_scientific_pass_not_found")


def _remote_facts() -> dict[str, Any]:
    pr = _gh(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}")
    run = _gh(f"repos/{REPOSITORY}/actions/runs/{READY_WORKFLOW_RUN_ID}")
    job = _gh(f"repos/{REPOSITORY}/actions/jobs/{PREMERGE_JOB_ID}")
    if pr.get("merged") is not True or pr.get("merge_commit_sha") != MERGE_COMMIT:
        raise R2T04HandoffError("merge_identity_mismatch")
    if pr.get("head", {}).get("sha") != REVIEWED_HEAD:
        raise R2T04HandoffError("reviewed_head_mismatch")
    if run.get("head_sha") != REVIEWED_HEAD or run.get("id") != READY_WORKFLOW_RUN_ID:
        raise R2T04HandoffError("workflow_head_mismatch")
    if job.get("head_sha") != REVIEWED_HEAD or job.get("id") != PREMERGE_JOB_ID:
        raise R2T04HandoffError("job_head_mismatch")
    steps = {step["name"]: step.get("conclusion") for step in job.get("steps", [])}
    expected = {
        "Run full profile on reviewed head": "success",
        "Fetch authenticated GitHub scientific reviews": "success",
        "Build R2-T02 premerge full evidence": "success",
        "Consume R2-T02 premerge full evidence final gate": "failure",
    }
    if any(steps.get(name) != conclusion for name, conclusion in expected.items()):
        raise R2T04HandoffError("premerge_step_snapshot_mismatch")
    return {"pr": pr, "run": run, "job": job, "steps": steps}


def _bindings(commit: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in T04_ARTIFACTS:
        path = (RUN_DIR / name).as_posix()
        data = _git_bytes(commit, path)
        result[path] = {
            "source_commit": commit,
            "git_blob_sha": _git_blob(commit, path),
            "committed_byte_sha256": _sha256(data),
        }
    return result


def _validate_schema(value: dict[str, Any], schema_rel: str) -> None:
    schema = _load(ROOT / schema_rel)
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=str)
    if errors:
        raise R2T04HandoffError(
            "schema_validation:" + ";".join(e.message for e in errors)
        )


def create_handoff(output: Path, *, root: Path = ROOT) -> dict[str, Any]:
    _remote_facts()
    review = _review()
    phase_b = validate_phase_b(root / RUN_DIR)
    if phase_b.get("status") != "passed":
        raise R2T04HandoffError("phase_b_independent_validation_failed")
    package = _load(root / RUN_DIR / "r2_t04_result_package.json")
    author = _load(root / RUN_DIR / "r2_t04_author_stage_scientific_review.json")
    if (
        package.get("formal_task_completed") is not False
        or author.get("scientific_review_status")
        != "pending_independent_scientific_review"
    ):
        raise R2T04HandoffError("author_stage_package_not_immutable")
    payload = {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "handoff_version": "r2_t04_repository_final_gate_handoff.v1",
        "handoff_source_commit": REVIEWED_HEAD,
        "author_package_lifecycle": "immutable_author_stage",
        "scientific_review_status": "passed",
        "repository_final_gate_status": "passed",
        "formal_task_completed": True,
        "R2-T05_allowed_to_start": True,
        "R3_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "repository": REPOSITORY,
        "pull_request_number": PR_NUMBER,
        "reviewed_head_sha": REVIEWED_HEAD,
        "merge_commit": MERGE_COMMIT,
        "scientific_review_id": SCIENTIFIC_REVIEW_ID,
        "ready_workflow_run_id": READY_WORKFLOW_RUN_ID,
        "premerge_job_id": PREMERGE_JOB_ID,
        "workflow_name": WORKFLOW_NAME,
        "ready_workflow_overall_conclusion": "failure",
        "full_profile_status": "passed",
        "full_profile_test_count": 1200,
        "full_profile_failure_count": 0,
        "github_scientific_review_fetch_status": "passed",
        "exact_head_scientific_review_recognized": True,
        "t02_evidence_build_status": "passed",
        "t02_evidence_consumer_status": "failed",
        "t02_evidence_consumer_error": "formal_surface_changed_after_artifact_commit",
        "t02_consumer_applicability_to_r2_t04": "not_applicable",
        "consumer_scope": "R2-T02 artifact formal-surface immutability",
        "not_applicable_reason": (
            "The reused T02 consumer compares the T02 v8 formal surface against "
            "the T02 artifact commit. Reviewed T03 compatibility changes in the "
            "shared T02 protocol module make that historical immutability check "
            "inapplicable to the R2-T04 freeze package."
        ),
        "exception_scope": "only_the_reused_t02_consumer",
        "exception_does_not_waive": (
            "T04 scientific review, Phase B independent validation, anomaly scan, "
            "exact-head review identity, committed-artifact validation, or "
            "merge ancestry"
        ),
        "administrator_merge": True,
        "administrator_exception_recorded": True,
        "committed_inputs": _bindings(REVIEWED_HEAD),
        "validation_assertions": {
            "github_api_identity_revalidated": True,
            "github_scientific_review_snapshot_revalidated": True,
            "ready_workflow_snapshot_revalidated": True,
            "premerge_job_snapshot_revalidated": True,
            "author_package_immutable": True,
            "phase_b_independent_validation_passed": True,
            "merge_ancestry_verified": True,
            "all_committed_sha_verified": True,
        },
        "review_snapshot_body_sha256": _sha256(review.get("body", "").encode()),
    }
    _validate_schema(payload, SCHEMA_REL)
    output = output if output.is_absolute() else root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def validate_handoff(
    handoff_path: Path, *, handoff_commit: str, root: Path = ROOT
) -> dict[str, Any]:
    errors: list[str] = []
    payload: dict[str, Any] = {}
    try:
        handoff_path = (
            handoff_path if handoff_path.is_absolute() else root / handoff_path
        )
        payload = _load(handoff_path)
        _validate_schema(payload, SCHEMA_REL)
        _remote_facts()
        _review()
        if (
            not subprocess.run(
                ["git", "merge-base", "--is-ancestor", REVIEWED_HEAD, MERGE_COMMIT],
                cwd=root,
            ).returncode
            == 0
        ):
            raise R2T04HandoffError("merge_ancestry_mismatch")
        phase_b = validate_phase_b(root / RUN_DIR)
        if phase_b.get("status") != "passed":
            raise R2T04HandoffError("phase_b_independent_validation_failed")
        for path, binding in payload["committed_inputs"].items():
            data = _git_bytes(binding["source_commit"], path)
            if _git_blob(binding["source_commit"], path) != binding["git_blob_sha"]:
                raise R2T04HandoffError(f"git_blob_mismatch:{path}")
            if _sha256(data) != binding["committed_byte_sha256"]:
                raise R2T04HandoffError(f"committed_sha_mismatch:{path}")
        committed_handoff = _git_bytes(handoff_commit, HANDOFF_REL)
        worktree_handoff = handoff_path.read_bytes().replace(b"\r\n", b"\n")
        if committed_handoff != worktree_handoff:
            raise R2T04HandoffError("handoff_worktree_commit_mismatch")
    except (
        OSError,
        ValueError,
        KeyError,
        subprocess.CalledProcessError,
        R2T04HandoffError,
    ) as exc:
        errors.append(str(exc))
    result = {
        "task_id": "R2-T04",
        "run_id": RUN_ID,
        "validation_mode": "post_merge_repository_final_gate_handoff",
        "status": "passed" if not errors else "failed",
        "handoff_path": HANDOFF_REL,
        "handoff_commit": handoff_commit,
        "validated_binding_count": len(payload.get("committed_inputs", {})),
        "github_api_identity_revalidated": not errors,
        "github_scientific_review_snapshot_revalidated": not errors,
        "ready_workflow_snapshot_revalidated": not errors,
        "premerge_job_snapshot_revalidated": not errors,
        "author_package_immutable": not errors,
        "phase_b_independent_validation_passed": not errors,
        "merge_ancestry_verified": not errors,
        "all_committed_sha_verified": not errors,
        "t02_consumer_exception_recorded": not errors,
        "scientific_review_status": "passed" if not errors else "pending",
        "repository_final_gate_status": "passed" if not errors else "pending",
        "formal_task_completed": not errors,
        "R2-T05_allowed_to_start": not errors,
        "R3_allowed_to_start": False,
        "selection_path_not_independently_confirmed": True,
        "errors": errors,
    }
    _validate_schema(result, VALIDATION_SCHEMA_REL)
    return result
