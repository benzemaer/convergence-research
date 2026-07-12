from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from scripts.run_unittest_profile import _build_suite, _load_profiles, _suite_test_ids

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas/r2/r2_t02_premerge_full_evidence.schema.json"
PROFILE_CONFIG = ROOT / "configs/ci/unittest_profiles.v1.json"
FORMAL_CONFIG = (
    ROOT / "configs/r2/r2_t02_confirmed_event_zone_state_machine_contract.v5.json"
)


def build_evidence(
    profile_result_path: Path,
    output_path: Path,
    *,
    reviewed_head_sha: str,
    author_package_path: Path | None = None,
    committed_artifact_sidecar_path: Path | None = None,
    author_stage_review_record_path: Path | None = None,
    github_reviews_path: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    profile_result = _load_json(profile_result_path)
    profiles = _load_profiles(root / "configs/ci/unittest_profiles.v1.json")
    full_test_ids = sorted(_suite_test_ids(_build_suite(profiles["full"])))
    heavy_test_ids = sorted(
        _suite_test_ids(_build_suite(profiles["r0-heavy-premerge"]))
    )
    runner_test_ids = sorted(profile_result.get("test_ids", []))
    full_collection_hash = _collection_sha256(full_test_ids)
    heavy_collection_hash = _collection_sha256(heavy_test_ids)
    heavy_files = sorted(profiles["r0-heavy-premerge"].get("files", []))
    review = _select_exact_head_scientific_pass(github_reviews_path, reviewed_head_sha)
    payload = {
        "task_id": "R2-T02",
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
        "pull_request_number": _int_env("PR_NUMBER"),
        "workflow_name": os.environ.get("GITHUB_WORKFLOW", ""),
        "workflow_event": os.environ.get("GITHUB_EVENT_NAME", ""),
        "workflow_run_id": _int_env("GITHUB_RUN_ID"),
        "workflow_attempt": _int_env("GITHUB_RUN_ATTEMPT"),
        "workflow_conclusion": "success"
        if profile_result["status"] == "passed"
        else "failed",
        "tested_head_sha": _git_sha(root),
        "reviewed_head_sha": reviewed_head_sha,
        "profile": profile_result["profile"],
        "status": profile_result["status"],
        "test_count": profile_result["test_count"],
        "unique_test_count": profile_result["unique_test_count"],
        "test_collection_sha256": profile_result["test_collection_sha256"],
        "independent_full_collection_sha256": full_collection_hash,
        "runner_test_ids_match_current_full": runner_test_ids == full_test_ids,
        "full_test_ids": full_test_ids,
        "failure_count": profile_result["failure_count"],
        "error_count": profile_result["error_count"],
        "skipped_count": profile_result["skipped_count"],
        "elapsed_seconds": profile_result["elapsed_seconds"],
        "heavy_profile": "r0-heavy-premerge",
        "heavy_test_file_set": heavy_files,
        "heavy_test_count": len(heavy_files),
        "heavy_test_ids": heavy_test_ids,
        "heavy_test_collection_sha256": heavy_collection_hash,
        "heavy_subset_of_full": set(heavy_test_ids).issubset(full_test_ids),
        "completed_at_utc": profile_result["completed_at_utc"],
        "formal_surface_sha256": _formal_surface_sha256(root),
        "formal_surface_git_blob_sha256": _formal_surface_git_blob_sha256(root),
        "author_package_path": _rel_optional(author_package_path, root),
        "author_package_sha256": _sha_optional(author_package_path),
        "committed_artifact_sidecar_path": _rel_optional(
            committed_artifact_sidecar_path, root
        ),
        "committed_artifact_sidecar_sha256": _sha_optional(
            committed_artifact_sidecar_path
        ),
        "author_stage_review_record_path": _rel_optional(
            author_stage_review_record_path, root
        ),
        "author_stage_review_record_sha256": _sha_optional(
            author_stage_review_record_path
        ),
        "github_reviews_api_path": _rel_optional(github_reviews_path, root),
        "github_reviews_api_sha256": _sha_optional(github_reviews_path),
        "github_scientific_review_id": int(review["id"]),
        "github_scientific_review_commit_id": review["commit_id"],
        "github_scientific_reviewer_login": review["user"]["login"],
        "github_scientific_review_state": review["state"],
        "github_scientific_review_submitted_at": review["submitted_at"],
        "github_scientific_review_body_sha256": hashlib.sha256(
            review["body"].encode("utf-8")
        ).hexdigest(),
        "github_scientific_review_api_verified": True,
    }
    _validate(payload, root)
    if payload["tested_head_sha"] != payload["reviewed_head_sha"]:
        raise ValueError("tested_head_sha_must_equal_reviewed_head_sha")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def validate_final_gate(
    evidence_path: Path,
    *,
    reviewed_head_sha: str,
    expected_repository: str = "",
    expected_pr_number: int = 0,
    expected_workflow: str = "",
    root: Path = ROOT,
) -> None:
    payload = _load_json(evidence_path)
    _validate(payload, root)
    errors = []
    if payload["tested_head_sha"] != reviewed_head_sha:
        errors.append("reviewed_head_mismatch")
    if payload["tested_head_sha"] != payload["reviewed_head_sha"]:
        errors.append("tested_reviewed_head_mismatch")
    if expected_repository and payload["repository"] != expected_repository:
        errors.append("repository_identity_mismatch")
    if expected_pr_number and payload["pull_request_number"] != expected_pr_number:
        errors.append("pull_request_identity_mismatch")
    if expected_workflow and payload["workflow_name"] != expected_workflow:
        errors.append("workflow_identity_mismatch")
    if payload["status"] != "passed":
        errors.append("full_profile_not_passed")
    if payload["failure_count"] != 0 or payload["error_count"] != 0:
        errors.append("full_profile_failures_or_errors")
    if not payload["runner_test_ids_match_current_full"]:
        errors.append("runner_test_ids_do_not_match_current_full")
    if (
        payload["test_collection_sha256"]
        != payload["independent_full_collection_sha256"]
    ):
        errors.append("full_collection_hash_mismatch")
    if not payload["heavy_subset_of_full"]:
        errors.append("heavy_tests_not_subset_of_full")
    for key in [
        "author_package",
        "committed_artifact_sidecar",
        "author_stage_review_record",
    ]:
        if not payload.get(f"{key}_path") or not payload.get(f"{key}_sha256"):
            errors.append(f"{key}_binding_missing")
        elif not (root / payload[f"{key}_path"]).is_file():
            errors.append(f"{key}_file_missing")
        elif _sha_optional(root / payload[f"{key}_path"]) != payload[f"{key}_sha256"]:
            errors.append(f"{key}_sha_mismatch")
    if not errors:
        author = _load_json(root / payload["author_package_path"])
        sidecar = _load_json(root / payload["committed_artifact_sidecar_path"])
        author_stage_review = _load_json(
            root / payload["author_stage_review_record_path"]
        )
        review_errors = _github_review_attestation_errors(payload, root)
        errors.extend(review_errors)
        if author.get("run_id") != sidecar.get("run_id"):
            errors.append("author_sidecar_run_id_mismatch")
        if author.get("run_id") != author_stage_review.get("run_id"):
            errors.append("author_stage_review_run_id_mismatch")
        if author_stage_review.get("scientific_review_status") != "pending":
            errors.append("author_stage_review_not_pending")
        if sidecar.get("status") != "passed":
            errors.append("committed_sidecar_not_passed")
        if sidecar.get("package_committed_sha256") != payload["author_package_sha256"]:
            errors.append("sidecar_package_hash_mismatch")
        if author.get("repository_final_gate_status") != "pending":
            errors.append("author_package_final_gate_not_pending")
        artifact_commit = sidecar.get("artifact_commit", "")
        if not artifact_commit or not _is_ancestor(
            artifact_commit, payload["tested_head_sha"], root
        ):
            errors.append("artifact_commit_not_reviewed_head_ancestor")
        elif not _formal_surface_unchanged_between(
            artifact_commit, payload["tested_head_sha"], root
        ):
            errors.append("formal_surface_changed_after_artifact_commit")
    if errors:
        raise ValueError(",".join(errors))


def _validate(payload: dict[str, Any], root: Path) -> None:
    schema = _load_json(root / "schemas/r2/r2_t02_premerge_full_evidence.schema.json")
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=str)
    if errors:
        raise ValueError(
            "; ".join(f"{error.json_path}:{error.message}" for error in errors)
        )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"expected JSON object array: {path}")
    return value


def _select_exact_head_scientific_pass(
    reviews_path: Path | None, reviewed_head_sha: str
) -> dict[str, Any]:
    if reviews_path is None or not reviews_path.is_file():
        raise ValueError("github_reviews_api_binding_missing")
    eligible = [
        review
        for review in _load_json_array(reviews_path)
        if review.get("commit_id") == reviewed_head_sha
        and review.get("state") in {"APPROVED", "COMMENTED"}
        and "[R2-T02 scientific PASS]" in str(review.get("body", ""))
        and review.get("id")
        and review.get("user", {}).get("login")
        and review.get("submitted_at")
    ]
    if not eligible:
        raise ValueError("exact_head_github_scientific_pass_not_found")
    return max(eligible, key=lambda row: (row["submitted_at"], int(row["id"])))


def _github_review_attestation_errors(payload: dict[str, Any], root: Path) -> list[str]:
    path_value = payload.get("github_reviews_api_path", "")
    if not path_value:
        return ["github_reviews_api_binding_missing"]
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    if not path.is_file():
        return ["github_reviews_api_file_missing"]
    if _sha_optional(path) != payload.get("github_reviews_api_sha256"):
        return ["github_reviews_api_sha_mismatch"]
    try:
        review = _select_exact_head_scientific_pass(path, payload["tested_head_sha"])
    except ValueError as exc:
        return [str(exc)]
    expected = {
        "github_scientific_review_id": int(review["id"]),
        "github_scientific_review_commit_id": review["commit_id"],
        "github_scientific_reviewer_login": review["user"]["login"],
        "github_scientific_review_state": review["state"],
        "github_scientific_review_submitted_at": review["submitted_at"],
        "github_scientific_review_body_sha256": hashlib.sha256(
            review["body"].encode("utf-8")
        ).hexdigest(),
        "github_scientific_review_api_verified": True,
    }
    return [
        f"github_review_attestation_mismatch:{key}"
        for key, value in expected.items()
        if payload.get(key) != value
    ]


def _int_env(name: str) -> int:
    value = os.environ.get(name, "0")
    return int(value) if value else 0


def _git_sha(root: Path) -> str:
    import subprocess

    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def _rel_optional(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _sha_optional(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _formal_surface_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for rel in sorted(_formal_surface_paths(root)):
        path = root / rel
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _formal_surface_git_blob_sha256(root: Path) -> str:
    import subprocess

    digest = hashlib.sha256()
    head = _git_sha(root)
    for rel in sorted(_formal_surface_paths(root)):
        blob = subprocess.check_output(["git", "show", f"{head}:{rel}"], cwd=root)
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(blob)
        digest.update(b"\0")
    return digest.hexdigest()


def _is_ancestor(ancestor: str, descendant: str, root: Path) -> bool:
    import subprocess

    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=root
        ).returncode
        == 0
    )


def _formal_surface_unchanged_between(left: str, right: str, root: Path) -> bool:
    import subprocess

    for rel in _formal_surface_paths(root):
        left_blob = subprocess.check_output(["git", "show", f"{left}:{rel}"], cwd=root)
        right_blob = subprocess.check_output(
            ["git", "show", f"{right}:{rel}"], cwd=root
        )
        if left_blob != right_blob:
            return False
    return True


def _formal_surface_paths(root: Path) -> list[str]:
    config = _load_json(
        FORMAL_CONFIG if FORMAL_CONFIG.is_absolute() else root / FORMAL_CONFIG
    )
    paths = set(config.get("formal_source_paths", []))
    paths.add(str(FORMAL_CONFIG.relative_to(root)).replace("\\", "/"))
    return sorted(paths)


def _collection_sha256(test_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(test_ids)).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or validate R2-T02 premerge evidence."
    )
    parser.add_argument("--profile-result", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--reviewed-head-sha", required=True)
    parser.add_argument("--final-gate-validate", type=Path)
    parser.add_argument("--author-package", type=Path)
    parser.add_argument("--committed-artifact-sidecar", type=Path)
    parser.add_argument("--author-stage-review-record", type=Path)
    parser.add_argument("--github-reviews-json", type=Path)
    parser.add_argument("--expected-repository", default="")
    parser.add_argument("--expected-pr-number", type=int, default=0)
    parser.add_argument("--expected-workflow", default="")
    args = parser.parse_args(argv)
    if args.final_gate_validate:
        validate_final_gate(
            args.final_gate_validate,
            reviewed_head_sha=args.reviewed_head_sha,
            expected_repository=args.expected_repository,
            expected_pr_number=args.expected_pr_number,
            expected_workflow=args.expected_workflow,
        )
        return 0
    if not args.profile_result or not args.output:
        parser.error(
            "--profile-result and --output are required unless "
            "--final-gate-validate is used"
        )
    build_evidence(
        args.profile_result,
        args.output,
        reviewed_head_sha=args.reviewed_head_sha,
        author_package_path=args.author_package,
        committed_artifact_sidecar_path=args.committed_artifact_sidecar,
        author_stage_review_record_path=args.author_stage_review_record,
        github_reviews_path=args.github_reviews_json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
