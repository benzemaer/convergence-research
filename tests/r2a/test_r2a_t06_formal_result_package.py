from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.r2a.r2a_t06_formal_execution import build_and_validate_lifecycle
from src.r2a.r2a_t06_formal_input_manifest import (
    build_candidate_manifest,
    load_formal_execution_config,
)
from src.r2a.r2a_t06_result_package import (
    CONTROL_FILES,
    SCIENTIFIC_FILES,
    ResultPackageError,
    artifact_manifest,
    create_stage_root,
    preserve_failed_stage,
    publish_stage_atomic,
    scientific_inventory,
    verify_artifact_manifest,
    write_scientific_stage,
)
from src.r2a.r2a_t06_validator import T06ValidationError, validate_t06_result_package
from tests.r2a.test_r2a_t06_formal_execution_preparation import _source


def _package_stage(tmp_path: Path):
    candidate, validation, _determinism = build_and_validate_lifecycle(_source())
    candidate_config = load_formal_execution_config()
    candidate_config["formal_run_allowed"] = False
    manifest = build_candidate_manifest(
        config=candidate_config, created_at="2026-07-23T00:00:00Z"
    )
    run_summary = {
        "run_id": "R2A-T06-20260723T000000000Z",
        "request_summaries": manifest["accepted_counts"],
        "accepted_counts": manifest["accepted_counts"],
        "selected_exit_confirmation_m": None,
        "winner_selected": False,
    }
    stage = tmp_path / "stage"
    stage.mkdir()
    scientific = write_scientific_stage(
        stage,
        candidate=candidate,
        manifest=manifest,
        run_summary=run_summary,
        validation_receipt=validation,
        result_analysis="Persisted analysis placeholder.",
    )
    return stage, scientific, candidate, validation, manifest


def test_scientific_package_has_exactly_17_unique_files(tmp_path: Path) -> None:
    stage, scientific, _candidate, _validation, _manifest = _package_stage(tmp_path)
    assert tuple(path.name for path in scientific.iterdir()) != CONTROL_FILES
    assert set(path.name for path in scientific.iterdir()) == set(SCIENTIFIC_FILES)
    assert len(scientific_inventory(scientific)) == 17
    for name in CONTROL_FILES:
        (stage / name).write_text("{}\n", encoding="utf-8")
    assert len(scientific_inventory(scientific)) == 17


def test_detail_database_is_repository_local_scientific_file(tmp_path: Path) -> None:
    _stage, scientific, _candidate, _validation, _manifest = _package_stage(tmp_path)
    inventory = scientific_inventory(scientific)
    detail = next(
        row for row in inventory if row["relative_path"] == "t06_detail.duckdb"
    )
    assert detail["storage_class"] == "repository_local_detail"
    assert detail["byte_size"] > 0


def test_missing_or_duplicate_scientific_file_rejected(tmp_path: Path) -> None:
    _stage, scientific, _candidate, _validation, _manifest = _package_stage(tmp_path)
    (scientific / "year_profile.csv").unlink()
    with pytest.raises(ResultPackageError, match="scientific_file_inventory_mismatch"):
        scientific_inventory(scientific)


def test_atomic_publication_and_collision(tmp_path: Path) -> None:
    parent = tmp_path / "runs"
    stage = create_stage_root(parent, "R2A-T06-20260723T000000000Z")
    (stage / "execution_log.jsonl").write_text("{}\n", encoding="utf-8")
    final = parent / "R2A-T06-20260723T000000000Z"
    publish_stage_atomic(stage, final)
    assert final.is_dir()
    replacement = create_stage_root(parent, "R2A-T06-20260723T000000000Z")
    with pytest.raises(ResultPackageError, match="run_root_collision"):
        publish_stage_atomic(replacement, final)


def test_failed_partial_stage_is_preserved_without_result_package(
    tmp_path: Path,
) -> None:
    stage = create_stage_root(tmp_path, "R2A-T06-20260723T000000000Z")
    (stage / "execution_log.jsonl").write_text("failed\n", encoding="utf-8")
    failed = preserve_failed_stage(stage)
    assert failed is not None and failed.is_dir()
    assert (failed / "execution_log.jsonl").is_file()
    assert not (failed / "result_package.json").exists()


def test_formal_pending_package_cannot_select_m_or_create_done(tmp_path: Path) -> None:
    _stage, scientific, _candidate, validation, _manifest = _package_stage(tmp_path)
    files = scientific_inventory(scientific)
    package = {
        "task_id": "R2A-T06",
        "package_schema_version": "r2a_t06_result_package.v1",
        "status": "formal_completed_pending_owner_review",
        "scope_id": "r2a_t06_consecutive_failure_exit_confirmation.v1",
        "q_selection_status": "not_selected",
        "canonical_dynamic_request_selected": False,
        "winner_selected": False,
        "accepted_run_id": "R2A-T06-20260723T000000000Z",
        "reviewed_implementation_sha": "2710d282fadcb998b80b9a482a5d55a4facc775a",
        "reviewed_execution_sha": "3" * 40,
        "owner_result_review": "pending",
        "result_analysis_status": "completed_blocked",
        "blocking_anomaly_count": 1,
        "selected_exit_confirmation_m": None,
        "selection_principle": "minimum_sufficient_complexity",
        "selection_evidence": [],
        "formal_run_executed": True,
        "real_score_data_read": True,
        "formal_artifacts_generated": True,
        "R2A-T06_DONE": "absent",
        "R2A-T07_allowed_to_start": False,
        "R3_allowed_to_start": False,
        "files": files,
        "validation": {
            key: validation[key]
            for key in (
                "status",
                "independent_recalculation",
                "accepted_daily_fact_immutability",
                "online_replay_equivalence",
                "deterministic_output",
                "parallel_consistency",
                "cross_q_nesting",
            )
        },
    }
    validate_t06_result_package(package)
    selected = copy.deepcopy(package)
    selected["selected_exit_confirmation_m"] = 2
    with pytest.raises(T06ValidationError):
        validate_t06_result_package(selected)
    done = copy.deepcopy(package)
    done["R2A-T06_DONE"] = "present"
    with pytest.raises(T06ValidationError):
        validate_t06_result_package(done)


def _sealed_stage(tmp_path: Path) -> tuple[Path, dict]:
    stage, _scientific, _candidate, _validation, _manifest = _package_stage(tmp_path)
    (stage / "execution_log.jsonl").write_text(
        '{"event":"stage_7_atomic_publication_ready"}\n', encoding="utf-8"
    )
    (stage / "formal_authorization.json").write_text("{}\n", encoding="utf-8")
    (stage / "determinism_receipt.json").write_text("{}\n", encoding="utf-8")
    (stage / "anomaly_scan.json").write_text("{}\n", encoding="utf-8")
    manifest = artifact_manifest(stage)
    (stage / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return stage, manifest


def test_artifact_manifest_verifies_all_hashes_and_sizes(tmp_path: Path) -> None:
    stage, manifest = _sealed_stage(tmp_path)
    receipt = verify_artifact_manifest(stage)
    assert receipt["status"] == "passed"
    assert receipt["verified_file_count"] == len(manifest["files"])


@pytest.mark.parametrize(
    "relative_path",
    ("execution_log.jsonl", "scientific/candidate_exit_summary.csv"),
)
def test_artifact_manifest_rejects_tampered_file(
    tmp_path: Path, relative_path: str
) -> None:
    stage, _manifest = _sealed_stage(tmp_path)
    path = stage.joinpath(*relative_path.split("/"))
    original = path.read_bytes()
    path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    with pytest.raises(ResultPackageError, match="artifact_manifest_sha256_mismatch"):
        verify_artifact_manifest(stage)


def test_artifact_manifest_rejects_missing_registered_file(tmp_path: Path) -> None:
    stage, _manifest = _sealed_stage(tmp_path)
    (stage / "execution_log.jsonl").unlink()
    with pytest.raises(
        ResultPackageError, match="artifact_manifest_inventory_mismatch"
    ):
        verify_artifact_manifest(stage)


def test_artifact_manifest_rejects_unregistered_control_file(tmp_path: Path) -> None:
    stage, _manifest = _sealed_stage(tmp_path)
    (stage / "unexpected_control.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        ResultPackageError, match="artifact_manifest_inventory_mismatch"
    ):
        verify_artifact_manifest(stage)
