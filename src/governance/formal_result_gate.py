"""Generic fail-closed gate for post-implementation formal-result PRs."""

from __future__ import annotations

import json
import re
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SUBMISSION_SCHEMA = ROOT / "schemas/governance/formal_result_submission.schema.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
PASS_MARKER = re.compile(
    r"^\[SCIENTIFIC PASS\] task_id=(?P<task_id>\S+) "
    r"run_id=(?P<run_id>\S+) artifact_commit=(?P<artifact_commit>[0-9a-f]{40}) "
    r"result_package_sha256=(?P<result_package_sha256>[0-9a-f]{64}) "
    r"independence_attestation=(?P<independence_attestation>true|false)$"
)


def validate_formal_result_gate(
    *,
    submission_manifest: Path,
    github_reviews_json: Path,
    full_profile_result: Path,
    current_head_sha: str,
    pull_request_number: int,
    repository: str,
    output: Path | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    errors: list[str] = []
    manifest = _load_json(submission_manifest, errors, "submission_manifest")
    reviews = _load_json(github_reviews_json, errors, "github_reviews")
    full_profile = _load_json(full_profile_result, errors, "full_profile")

    _validate_manifest(manifest, errors)
    _check_request_identity(repository, pull_request_number, current_head_sha, errors)
    selected_review_id: int | None = None
    if isinstance(manifest, dict):
        _check_commit_boundaries(manifest, current_head_sha, root, errors)
        _check_bound_files(manifest, root, errors)
        _check_result_package_identity(manifest, root, errors)
        _check_scientific_review_surface(manifest, current_head_sha, root, errors)
        selected_review_id = _check_scientific_pass(
            manifest, reviews, current_head_sha, root, errors
        )
    _check_full_profile(full_profile, current_head_sha, errors)

    passed = not errors
    result: dict[str, Any] = {
        "status": "passed" if passed else "failed",
        "repository": repository,
        "pull_request_number": pull_request_number,
        "current_head_sha": current_head_sha,
        "task_id": manifest.get("task_id") if isinstance(manifest, dict) else None,
        "run_id": manifest.get("run_id") if isinstance(manifest, dict) else None,
        "implementation_merge_sha": (
            manifest.get("implementation_merge_sha")
            if isinstance(manifest, dict)
            else None
        ),
        "formal_execution_sha": (
            manifest.get("formal_execution_sha") if isinstance(manifest, dict) else None
        ),
        "artifact_commit_sha": (
            manifest.get("artifact_commit_sha") if isinstance(manifest, dict) else None
        ),
        "full_profile_status": full_profile.get("status"),
        "scientific_review_status": "passed" if passed else "failed",
        "selected_scientific_review_id": selected_review_id,
        "protected_surface_unchanged": not any(
            error.startswith("implementation_changed_requires_new_implementation_pr")
            or error.startswith("scientific_review_protected_surface_changed")
            for error in errors
        ),
        "formal_task_completed": passed,
        "downstream_gate_allowed": passed,
        "downstream_gate_scope": (
            manifest.get("downstream_gate_scope")
            if isinstance(manifest, dict)
            else None
        ),
        "errors": errors,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return result


def _validate_manifest(payload: Any, errors: list[str]) -> None:
    if not isinstance(payload, dict):
        errors.append("submission_manifest_invalid")
        return
    try:
        schema = json.loads(SUBMISSION_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(payload)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"submission_manifest_schema_invalid:{exc}")
    for field in (
        "implementation_merge_sha",
        "formal_execution_sha",
        "artifact_commit_sha",
    ):
        if not SHA40.fullmatch(str(payload.get(field, ""))):
            errors.append(f"invalid_sha:{field}")


def _check_request_identity(
    repository: str, pull_request_number: int, current_head_sha: str, errors: list[str]
) -> None:
    if not repository or "/" not in repository:
        errors.append("repository_invalid")
    if pull_request_number <= 0:
        errors.append("pull_request_number_invalid")
    if not SHA40.fullmatch(current_head_sha):
        errors.append("current_head_sha_invalid")


def _check_commit_boundaries(
    manifest: dict[str, Any], current_head_sha: str, root: Path, errors: list[str]
) -> None:
    implementation = manifest.get("implementation_merge_sha", "")
    execution = manifest.get("formal_execution_sha", "")
    artifact = manifest.get("artifact_commit_sha", "")
    if not _is_ancestor(root, implementation, execution):
        errors.append("implementation_merge_not_ancestor_of_formal_execution")
    if not _is_ancestor(root, implementation, artifact):
        errors.append("implementation_merge_not_ancestor_of_artifact_commit")
    if not _is_ancestor(root, artifact, current_head_sha):
        errors.append("artifact_commit_not_ancestor_of_current_head")

    if _commits_exist(root, implementation, artifact):
        changed = _changed_paths(root, implementation, artifact)
        protected = set(manifest.get("implementation_protected_paths", []))
        for path in sorted(changed & protected):
            errors.append(
                "implementation_changed_requires_new_implementation_pr:" + path
            )


def _check_bound_files(manifest: dict[str, Any], root: Path, errors: list[str]) -> None:
    artifact_commit = manifest.get("artifact_commit_sha", "")
    scientific = set(manifest.get("scientific_review_protected_paths", []))
    for field in ("result_package", "result_analysis", "input_manifest"):
        bound = manifest.get(field, {})
        path_value = bound.get("path") if isinstance(bound, dict) else None
        expected_hash = bound.get("sha256") if isinstance(bound, dict) else None
        if not isinstance(path_value, str) or not isinstance(expected_hash, str):
            errors.append(f"bound_file_invalid:{field}")
            continue
        path = _repo_path(root, path_value, field, errors)
        if path is None or not path.is_file():
            errors.append(f"bound_file_missing:{field}")
            continue
        actual = _sha256_bytes(path.read_bytes())
        if actual != expected_hash:
            errors.append(
                "result_package_hash_mismatch"
                if field == "result_package"
                else f"hash_mismatch:{field}"
            )
        committed = _git_blob(root, artifact_commit, path_value)
        if committed is None:
            errors.append(f"artifact_commit_file_missing:{field}")
        elif _sha256_bytes(committed) != expected_hash:
            errors.append(f"artifact_commit_hash_mismatch:{field}")
        elif _sha256_bytes(committed) != actual and path_value in scientific:
            errors.append("scientific_review_protected_surface_changed:" + path_value)


def _check_result_package_identity(
    manifest: dict[str, Any], root: Path, errors: list[str]
) -> None:
    bound = manifest.get("result_package", {})
    path = _repo_path(root, bound.get("path", ""), "result_package", errors)
    if path is None or not path.is_file():
        return
    try:
        package = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"result_package_invalid_json:{exc}")
        return
    for field in ("task_id", "run_id"):
        if package.get(field) != manifest.get(field):
            errors.append(f"result_package_{field}_mismatch")


def _check_scientific_review_surface(
    manifest: dict[str, Any], current_head_sha: str, root: Path, errors: list[str]
) -> None:
    artifact = manifest.get("artifact_commit_sha", "")
    if not _valid_commits(artifact, current_head_sha):
        return
    changed = _changed_paths(root, artifact, current_head_sha)
    allowed = set(manifest.get("allowed_post_review_paths", []))
    scientific = set(manifest.get("scientific_review_protected_paths", []))
    for path in sorted(changed):
        if path in scientific:
            errors.append("scientific_review_protected_surface_changed:" + path)
        elif path not in allowed:
            errors.append("post_review_unallowed_path_changed:" + path)


def _check_scientific_pass(
    manifest: dict[str, Any],
    reviews: Any,
    current_head_sha: str,
    root: Path,
    errors: list[str],
) -> int | None:
    if not isinstance(reviews, list):
        errors.append("github_reviews_invalid")
        return None
    expected_hash = manifest.get("result_package", {}).get("sha256")
    valid: list[tuple[str, dict[str, Any]]] = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        body = str(review.get("body", ""))
        reviewer = str((review.get("user") or {}).get("login", ""))
        for line in body.splitlines():
            match = PASS_MARKER.fullmatch(line.strip())
            if not match:
                continue
            values = match.groupdict()
            if values["task_id"] != manifest.get("task_id"):
                errors.append("scientific_pass_task_id_mismatch")
            if values["run_id"] != manifest.get("run_id"):
                errors.append("scientific_pass_run_id_mismatch")
            if values["artifact_commit"] != manifest.get("artifact_commit_sha"):
                errors.append("scientific_pass_artifact_commit_mismatch")
            if values["result_package_sha256"] != expected_hash:
                errors.append("scientific_pass_result_package_hash_mismatch")
            if values["independence_attestation"] != "true":
                errors.append("scientific_pass_independence_attestation_missing")
            if reviewer == manifest.get("implementation_actor"):
                errors.append("scientific_pass_reviewer_is_implementation_actor")
            state = str(review.get("state", "")).upper()
            commit_id = str(review.get("commit_id", ""))
            if state not in {"APPROVED", "COMMENTED"}:
                errors.append("scientific_pass_review_state_invalid")
            elif not _is_ancestor(root, commit_id, current_head_sha):
                errors.append("scientific_pass_review_commit_not_ancestor")
            elif (
                values["task_id"] == manifest.get("task_id")
                and values["run_id"] == manifest.get("run_id")
                and values["artifact_commit"] == manifest.get("artifact_commit_sha")
                and values["result_package_sha256"] == expected_hash
                and values["independence_attestation"] == "true"
                and reviewer != manifest.get("implementation_actor")
            ):
                valid.append((str(review.get("submitted_at", "")), review))
    if not valid:
        errors.append("scientific_pass_missing")
        return None
    _, selected = max(
        valid,
        key=lambda item: (item[0], int(item[1].get("id", 0))),
    )
    return int(selected.get("id", 0)) or None


def _check_full_profile(profile: Any, current_head_sha: str, errors: list[str]) -> None:
    if not isinstance(profile, dict):
        errors.append("full_profile_invalid")
        return
    if profile.get("profile") != "full":
        errors.append("full_profile_name_mismatch")
    if profile.get("status") != "passed":
        errors.append("full_profile_failed")
    if profile.get("failure_count") != 0:
        errors.append("full_profile_failure_count_nonzero")
    if profile.get("error_count") != 0:
        errors.append("full_profile_error_count_nonzero")
    if not isinstance(profile.get("test_count"), int) or profile["test_count"] <= 0:
        errors.append("full_profile_test_count_invalid")
    if profile.get("tested_head_sha") != current_head_sha:
        errors.append("full_profile_current_head_mismatch")


def _repo_path(root: Path, value: str, label: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value or "\\" in value:
        errors.append(f"repo_path_invalid:{label}")
        return None
    raw = Path(value)
    if raw.is_absolute() or any(part in {"", ".", ".."} for part in raw.parts):
        errors.append(f"repo_path_invalid:{label}")
        return None
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        errors.append(f"repo_path_escapes_root:{label}")
        return None
    return path


def _changed_paths(root: Path, base: str, head: str) -> set[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", base, head],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        line.strip().replace("\\", "/")
        for line in completed.stdout.splitlines()
        if line.strip()
    }


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    if not _commits_exist(root, ancestor, descendant):
        return False
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=root,
            check=False,
        ).returncode
        == 0
    )


def _commits_exist(root: Path, *values: str) -> bool:
    if not _valid_commits(*values):
        return False
    return all(
        subprocess.run(
            ["git", "cat-file", "-e", f"{value}^{{commit}}"],
            cwd=root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
        for value in values
    )


def _valid_commits(*values: str) -> bool:
    return all(SHA40.fullmatch(str(value)) for value in values)


def _git_blob(root: Path, commit: str, path: str) -> bytes | None:
    if not SHA40.fullmatch(str(commit)):
        return None
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    return completed.stdout if completed.returncode == 0 else None


def _sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _load_json(path: Path, errors: list[str], label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{label}_invalid:{exc}")
        return {}
