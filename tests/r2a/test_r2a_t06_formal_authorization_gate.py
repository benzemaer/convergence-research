from __future__ import annotations

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.r2a.r2a_t06_formal_execution import (
    FormalExecutionError,
    consume_formal_attempt,
    preflight_formal_execution,
)
from src.r2a.r2a_t06_formal_input_manifest import (
    authorize_candidate_manifest,
    build_candidate_manifest,
    canonical_json_bytes,
    load_formal_execution_config,
)


def _committed_bindings(candidate: dict, source_commit: str) -> list[dict]:
    return [
        {
            "relative_path": item["relative_path"],
            "source_commit": source_commit,
            "git_blob_sha": "c" * 40,
            "committed_byte_sha256": item["sha256"],
            "normalized_text_sha256": item["sha256"],
            "encoding": "utf-8",
            "line_ending": "lf",
            "bom": False,
            "trailing_lf_count": 1,
            "byte_size": item["byte_size"],
        }
        for item in candidate["config_schema_bindings"]
    ]


def _authorized(tmp_path: Path):
    reviewed = "a" * 40
    authorization_head = "b" * 40
    config = load_formal_execution_config()
    candidate = build_candidate_manifest(created_at="2026-07-23T00:00:00Z")
    score_path = tmp_path / config["score_release"]["relative_path"]
    score_path.parent.mkdir(parents=True, exist_ok=True)
    score_content = b"synthetic-score-release"
    score_path.write_bytes(score_content)
    score_identity = {
        **config["score_release"],
        "sha256": hashlib.sha256(score_content).hexdigest(),
        "byte_size": len(score_content),
    }
    config["score_release"] = copy.deepcopy(score_identity)
    candidate["score_release"] = copy.deepcopy(score_identity)
    manifest = authorize_candidate_manifest(
        candidate,
        reviewed_formal_execution_sha=reviewed,
        authorization_commit_sha=authorization_head,
        authorization_revision=1,
        quality_evidence={
            "run_id": 123,
            "sha": reviewed,
            "status": "completed",
            "conclusion": "success",
        },
        committed_contract_bindings=_committed_bindings(candidate, reviewed),
    )
    content = canonical_json_bytes(manifest)
    run_id = "R2A-T06-20260723T000000000Z"
    authorization = {
        "$schema": "../../schemas/r2a/r2a_t06_formal_authorization.schema.json",
        "task_id": "R2A-T06",
        "formal_scope_id": "r2a_t06_consecutive_failure_exit_formal_execution.v1",
        "owner_authorized": True,
        "approved_implementation_sha": "2710d282fadcb998b80b9a482a5d55a4facc775a",
        "reviewed_formal_execution_sha": reviewed,
        "execution_parent_sha": reviewed,
        "authorization_commit_sha": authorization_head,
        "authorization_commit_parent": reviewed,
        "authorization_revision": 1,
        "quality_run_id": 123,
        "quality_sha": reviewed,
        "quality_status": "completed",
        "quality_conclusion": "success",
        "formal_attempt_limit": 1,
        "formal_attempts_consumed": 0,
        "manifest_sha256": hashlib.sha256(content).hexdigest(),
        "manifest_byte_size": len(content),
        "run_id": run_id,
        "run_root_relative_path": f"data/generated/r2a/r2a_t06/formal-runs/{run_id}",
    }
    config["formal_run_allowed"] = True
    return (
        authorization,
        content,
        config,
        {
            "head": authorization_head,
            "parent": reviewed,
            "clean": True,
            "committed_contract_bindings_verified": True,
            "accepted_metadata_verified": True,
        },
    )


def test_missing_authorization_rejected_before_input_discovery(tmp_path: Path) -> None:
    discovered = False

    def discover(_path: Path) -> None:
        nonlocal discovered
        discovered = True

    with pytest.raises(
        FormalExecutionError, match="owner_formal_authorization_missing"
    ):
        preflight_formal_execution(
            authorization=None,
            manifest_bytes=b"not parsed",
            config=load_formal_execution_config(),
            repo_root=tmp_path,
            input_discovery=discover,
        )
    assert discovered is False


def test_complete_preflight_calls_discovery_only_after_all_gates(
    tmp_path: Path,
) -> None:
    authorization, manifest, config, git_state = _authorized(tmp_path)
    observed = []

    def discover(path: Path) -> None:
        run_root = tmp_path / authorization["run_root_relative_path"]
        marker = run_root.with_name(run_root.name + ".attempt-consumed.json")
        assert marker.is_file()
        observed.append(path)

    result = preflight_formal_execution(
        authorization=authorization,
        manifest_bytes=manifest,
        config=config,
        repo_root=tmp_path,
        git_state=git_state,
        input_discovery=discover,
    )
    assert result["status"] == "passed"
    assert len(observed) == 1
    assert observed[0].name == "score_data.duckdb"
    marker = Path(result["attempt_marker"])
    assert marker.is_file()
    assert marker.stat().st_size > 0
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["status"] == "consumed"
    assert payload["attempt_number"] == 1


def test_same_authorization_cannot_consume_or_discover_twice(tmp_path: Path) -> None:
    authorization, manifest, config, git_state = _authorized(tmp_path)
    preflight_formal_execution(
        authorization=authorization,
        manifest_bytes=manifest,
        config=config,
        repo_root=tmp_path,
        git_state=git_state,
    )
    discovered = False

    def discover(_path: Path) -> None:
        nonlocal discovered
        discovered = True

    with pytest.raises(FormalExecutionError, match="formal_attempt_already_consumed"):
        preflight_formal_execution(
            authorization=authorization,
            manifest_bytes=manifest,
            config=config,
            repo_root=tmp_path,
            git_state=git_state,
            input_discovery=discover,
        )
    assert discovered is False


def test_concurrent_attempt_consumption_has_one_winner(tmp_path: Path) -> None:
    authorization, _manifest, _config, _git_state = _authorized(tmp_path)
    run_root = tmp_path / authorization["run_root_relative_path"]

    def consume() -> str:
        try:
            consume_formal_attempt(run_root, authorization)
        except FormalExecutionError as error:
            return error.reason_code
        return "consumed"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _index: consume(), range(8)))
    assert outcomes.count("consumed") == 1
    assert outcomes.count("formal_attempt_already_consumed") == 7


def test_different_run_ids_consume_independently(tmp_path: Path) -> None:
    authorization, _manifest, _config, _git_state = _authorized(tmp_path)
    first = tmp_path / authorization["run_root_relative_path"]
    second_authorization = copy.deepcopy(authorization)
    second_authorization["run_id"] = "R2A-T06-20260723T000000001Z"
    second_authorization["run_root_relative_path"] = (
        "data/generated/r2a/r2a_t06/formal-runs/R2A-T06-20260723T000000001Z"
    )
    second = tmp_path / second_authorization["run_root_relative_path"]
    assert consume_formal_attempt(first, authorization).is_file()
    assert consume_formal_attempt(second, second_authorization).is_file()


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        (lambda path: path.unlink(), "score_file_missing"),
        (
            lambda path: path.write_bytes(path.read_bytes() + b"x"),
            "score_byte_size_mismatch",
        ),
        (
            lambda path: path.write_bytes(b"X" * path.stat().st_size),
            "score_sha256_mismatch",
        ),
    ),
)
def test_score_identity_fails_after_attempt_before_discovery(
    tmp_path: Path, mutation, reason: str
) -> None:
    authorization, manifest, config, git_state = _authorized(tmp_path)
    score_path = tmp_path / config["score_release"]["relative_path"]
    mutation(score_path)
    discovered = False

    def discover(_path: Path) -> None:
        nonlocal discovered
        discovered = True

    with pytest.raises(FormalExecutionError, match=reason):
        preflight_formal_execution(
            authorization=authorization,
            manifest_bytes=manifest,
            config=config,
            repo_root=tmp_path,
            git_state=git_state,
            input_discovery=discover,
        )
    run_root = tmp_path / authorization["run_root_relative_path"]
    assert run_root.with_name(run_root.name + ".attempt-consumed.json").is_file()
    assert discovered is False


@pytest.mark.parametrize("kind", ("staging", "failed", "reserved"))
def test_partial_run_state_conflict_rejected_before_attempt(
    tmp_path: Path, kind: str
) -> None:
    authorization, manifest, config, git_state = _authorized(tmp_path)
    run_root = tmp_path / authorization["run_root_relative_path"]
    run_root.parent.mkdir(parents=True, exist_ok=True)
    conflict = {
        "staging": run_root.parent / f".{run_root.name}.staging-existing",
        "failed": run_root.parent / f".{run_root.name}.staging-existing.failed",
        "reserved": run_root.parent / f".{run_root.name}.reserved",
    }[kind]
    conflict.mkdir()
    with pytest.raises(FormalExecutionError, match="formal_run_state_conflict"):
        preflight_formal_execution(
            authorization=authorization,
            manifest_bytes=manifest,
            config=config,
            repo_root=tmp_path,
            git_state=git_state,
        )
    assert not run_root.with_name(run_root.name + ".attempt-consumed.json").exists()


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        (
            lambda auth, _manifest, _config, _git: auth.update(
                quality_conclusion="failure"
            ),
            "formal_authorization_schema_invalid",
        ),
        (
            lambda auth, _manifest, _config, _git: auth.update(
                formal_attempts_consumed=1
            ),
            "formal_authorization_schema_invalid",
        ),
        (
            lambda auth, _manifest, _config, _git: auth.update(
                manifest_sha256="0" * 64
            ),
            "authorized_manifest_hash_mismatch",
        ),
        (
            lambda _auth, _manifest, _config, git: git.update(clean=False),
            "formal_worktree_not_clean",
        ),
        (
            lambda _auth, _manifest, _config, git: git.update(parent="c" * 40),
            "authorization_parent_mismatch",
        ),
    ),
)
def test_authorization_gate_mutations_fail_closed(tmp_path, mutation, reason) -> None:
    authorization, manifest, config, git_state = _authorized(tmp_path)
    mutation(authorization, manifest, config, git_state)
    with pytest.raises(FormalExecutionError, match=reason):
        preflight_formal_execution(
            authorization=authorization,
            manifest_bytes=manifest,
            config=config,
            repo_root=tmp_path,
            git_state=git_state,
        )


def test_run_root_collision_rejected(tmp_path: Path) -> None:
    authorization, manifest, config, git_state = _authorized(tmp_path)
    collision = tmp_path / authorization["run_root_relative_path"]
    collision.mkdir(parents=True)
    with pytest.raises(FormalExecutionError, match="run_root_collision"):
        preflight_formal_execution(
            authorization=authorization,
            manifest_bytes=manifest,
            config=config,
            repo_root=tmp_path,
            git_state=git_state,
        )


def test_forbidden_field_policy_rejected(tmp_path: Path) -> None:
    authorization, manifest, config, git_state = _authorized(tmp_path)
    config = copy.deepcopy(config)
    config["forbidden_input_fields"].append("score_release")
    with pytest.raises(FormalExecutionError, match="forbidden_input_field"):
        preflight_formal_execution(
            authorization=authorization,
            manifest_bytes=manifest,
            config=config,
            repo_root=tmp_path,
            git_state=git_state,
        )


def test_accepted_metadata_must_be_verified_before_discovery(tmp_path: Path) -> None:
    authorization, manifest, config, git_state = _authorized(tmp_path)
    git_state["accepted_metadata_verified"] = False
    discovered = False

    def discover(_path: Path) -> None:
        nonlocal discovered
        discovered = True

    with pytest.raises(FormalExecutionError, match="accepted_metadata_not_verified"):
        preflight_formal_execution(
            authorization=authorization,
            manifest_bytes=manifest,
            config=config,
            repo_root=tmp_path,
            git_state=git_state,
            input_discovery=discover,
        )
    assert discovered is False
