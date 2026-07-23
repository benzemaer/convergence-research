from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.r2a.r2a_t06_formal_input_manifest import (
    FormalInputManifestError,
    authorize_candidate_manifest,
    build_candidate_manifest,
    canonical_json_bytes,
    load_formal_execution_config,
    validate_repository_relative_path,
    write_immutable_manifest,
)

ROOT = Path(__file__).resolve().parents[2]


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


def test_formal_config_and_schemas_are_valid() -> None:
    config = load_formal_execution_config()
    assert config["formal_execution_candidate_status"] == "pending_owner_review"
    assert config["formal_run_allowed"] is False
    for name in (
        "r2a_t06_formal_execution.schema.json",
        "r2a_t06_formal_authorization.schema.json",
        "r2a_t06_formal_input_manifest.schema.json",
    ):
        schema = json.loads((ROOT / "schemas/r2a" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_candidate_manifest_is_deterministic_and_metadata_only() -> None:
    left = build_candidate_manifest(created_at="2026-07-23T00:00:00Z")
    right = build_candidate_manifest(created_at="2026-07-23T00:00:00Z")
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert left["manifest_status"] == "candidate_metadata_only"
    assert left["reviewed_formal_execution_sha"] is None
    assert left["authorization_commit_sha"] is None
    assert left["committed_contract_bindings"] == []
    assert len(left["expected_formal_files"]) == 17


def test_candidate_builder_never_reads_score_database(monkeypatch) -> None:
    score_suffix = "score_data.duckdb"
    result_package_suffix = (
        "formal-runs/R2A-T05-20260722T012719685Z/result_package.json"
    )
    original = Path.read_bytes
    observed: list[str] = []

    def guarded(path: Path) -> bytes:
        observed.append(str(path))
        if str(path).endswith(score_suffix):
            raise AssertionError("Score content must not be read")
        if path.as_posix().endswith(result_package_suffix):
            raise AssertionError("T05 detail result package must not be read")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    build_candidate_manifest(created_at="2026-07-23T00:00:00Z")
    assert not any(value.endswith(score_suffix) for value in observed)
    assert not any(
        Path(value).as_posix().endswith(result_package_suffix) for value in observed
    )


@pytest.mark.parametrize(
    "value",
    (
        "C:/external/score.duckdb",
        "/external/score.duckdb",
        "data/../outside.duckdb",
        "convergence-research-inputs/score.duckdb",
        "data/backup/score.duckdb",
        "data/generated/score.bak",
    ),
)
def test_input_path_boundary_rejects_external_retired_and_backup(value: str) -> None:
    with pytest.raises(FormalInputManifestError):
        validate_repository_relative_path(value)


def test_authorization_requires_exact_sha_quality_success() -> None:
    candidate = build_candidate_manifest(created_at="2026-07-23T00:00:00Z")
    with pytest.raises(FormalInputManifestError, match="exact_sha_quality_success"):
        authorize_candidate_manifest(
            candidate,
            reviewed_formal_execution_sha="a" * 40,
            authorization_commit_sha="b" * 40,
            authorization_revision=1,
            quality_evidence={
                "run_id": 1,
                "sha": "a" * 40,
                "status": "completed",
                "conclusion": "failure",
            },
        )


def test_superseded_manifest_is_rejected() -> None:
    candidate = build_candidate_manifest(created_at="2026-07-23T00:00:00Z")
    candidate["superseded"] = True
    with pytest.raises(FormalInputManifestError):
        authorize_candidate_manifest(
            candidate,
            reviewed_formal_execution_sha="a" * 40,
            authorization_commit_sha="b" * 40,
            authorization_revision=1,
            quality_evidence={
                "run_id": 1,
                "sha": "a" * 40,
                "status": "completed",
                "conclusion": "success",
            },
        )


def test_authorized_manifest_write_is_immutable(tmp_path: Path) -> None:
    candidate = build_candidate_manifest(created_at="2026-07-23T00:00:00Z")
    authorized = authorize_candidate_manifest(
        candidate,
        reviewed_formal_execution_sha="a" * 40,
        authorization_commit_sha="b" * 40,
        authorization_revision=1,
        quality_evidence={
            "run_id": 1,
            "sha": "a" * 40,
            "status": "completed",
            "conclusion": "success",
        },
        committed_contract_bindings=_committed_bindings(candidate, "a" * 40),
    )
    target = tmp_path / "manifest.json"
    identity = write_immutable_manifest(target, authorized)
    assert identity["byte_size"] == len(target.read_bytes())
    with pytest.raises(FormalInputManifestError, match="manifest_overwrite_rejected"):
        write_immutable_manifest(target, copy.deepcopy(authorized))
