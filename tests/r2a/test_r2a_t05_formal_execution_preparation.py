"""Preparation-only tests for the R2A-T05 formal execution entry."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import patch

import duckdb
import pytest

from src.r2a.r2a_t02_request_identity import build_canonical_request
from src.r2a.r2a_t05_ca_exit_decomposition import build_t05_candidate
from src.r2a.r2a_t05_formal_execution import (
    FormalExecutionError,
    build_determinism_receipt,
    build_formal_authorization_evidence,
    compare_formal_builds,
    create_unique_run_root,
    execute_request_sequence,
    finalize_formal_candidate,
    inspect_git_preflight,
    load_formal_authorization,
    preflight_formal_execution,
    validate_formal_completion_lifecycle,
    validate_t05_output_scope,
)
from src.r2a.r2a_t05_formal_input_manifest import (
    FormalInputManifestError,
    build_formal_input_manifest,
    load_authorized_input_manifest,
    load_formal_execution_config,
    sha256_file,
)
from src.r2a.r2a_t05_formal_result_analysis import (
    analyze_persisted_formal_artifacts,
    render_persisted_result_analysis,
)
from tests.r2a.test_r2a_t05_ca_exit_decomposition import _fixture as _ca_fixture

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_COUNTS = {
    "CA_q10_k5": {
        "raw_true": 20559,
        "confirmed_true": 1916,
        "intervals": 751,
        "securities_with_interval": 473,
    },
    "CA_q15_k5": {
        "raw_true": 46651,
        "confirmed_true": 7125,
        "intervals": 2426,
        "securities_with_interval": 734,
    },
    "CA_q20_k5": {
        "raw_true": 81535,
        "confirmed_true": 17642,
        "intervals": 5372,
        "securities_with_interval": 775,
    },
    "CA_q25_k5": {
        "raw_true": 124893,
        "confirmed_true": 35098,
        "intervals": 9107,
        "securities_with_interval": 788,
    },
}
REQUEST_ORDER = ("CA_q10_k5", "CA_q15_k5", "CA_q20_k5", "CA_q25_k5")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _authorization_base_payload() -> dict[str, Any]:
    config = load_formal_execution_config()
    return {
        "$schema": "../../schemas/r2a/r2a_t05_formal_authorization.schema.json",
        "task_id": "R2A-T05",
        "formal_scope_id": "r2a_t05_ca_exit_mechanism_formal_execution.v1",
        "reviewed_implementation_sha": config["reviewed_implementation_sha"],
        "formal_run_attempt_limit": config["formal_run_attempt_limit"],
        "authorization_diff_whitelist": [
            "configs/r2a/r2a_t05_formal_authorization.v1.json",
            "docs/tasks/R2A-T05_CA退出机制与跨q结构分解.md",
        ],
        "protected_execution_files": copy.deepcopy(config["protected_execution_files"]),
    }


def _unauthorized_authorization_payload() -> dict[str, Any]:
    payload = _authorization_base_payload()
    payload.update(
        {
            "reviewed_formal_execution_sha": None,
            "authorization_revision": 0,
            "authorization_parent": None,
            "formal_run_allowed": False,
            "formal_run_attempts_consumed_before_start": 0,
            "authorized_manifest_sha256": None,
            "authorized_manifest_byte_size": None,
            "authorization_status": "not_authorized",
        }
    )
    return payload


def _authorized_authorization_payload(
    *,
    reviewed_formal_execution_sha: str = "a" * 40,
    authorized_manifest_sha256: str = "e" * 64,
    authorized_manifest_byte_size: int = 1,
) -> dict[str, Any]:
    payload = _authorization_base_payload()
    payload.update(
        {
            "reviewed_formal_execution_sha": reviewed_formal_execution_sha,
            "authorization_revision": 1,
            "authorization_parent": reviewed_formal_execution_sha,
            "formal_run_allowed": True,
            "formal_run_attempts_consumed_before_start": 0,
            "authorized_manifest_sha256": authorized_manifest_sha256,
            "authorized_manifest_byte_size": authorized_manifest_byte_size,
            "authorization_status": "authorized_pending_execution",
        }
    )
    payload["protected_execution_files"] = [
        {**record, "source_commit": reviewed_formal_execution_sha}
        for record in payload["protected_execution_files"]
    ]
    return payload


def _write_authorization_fixture(tmp_path: Path, payload: Mapping[str, Any]) -> Path:
    path = tmp_path / "authorization.json"
    _write_json(path, payload)
    return path


def _request_envelopes(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in config["requests"]:
        name = item["logical_request_name"]
        q = int(item["q_by_dimension"]["C"])
        spec = {
            "request_schema_version": "r2a_t02_dynamic_request_spec.v1",
            "dynamic_protocol_version": "pcavt_dynamic_state_protocol.v1",
            "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
            "selected_dimensions": ["C", "A"],
            "q_by_dimension": {"C": q, "A": q},
            "confirmation_k": 5,
        }
        envelope = build_canonical_request(spec)
        assert envelope["request_id"] == item["request_id"]
        assert envelope["request_hash"] == item["request_hash"]
        result[name] = envelope
    return result


def _make_score_database(path: Path, *, forbidden_field: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE TABLE securities (security_id VARCHAR)")
        connection.executemany(
            "INSERT INTO securities VALUES (?)",
            [(f"S{index:04d}",) for index in range(800)],
        )
        connection.execute("CREATE TABLE trading_sessions (trading_date DATE)")
        connection.execute("INSERT INTO trading_sessions VALUES ('2016-01-04')")
        connection.execute(
            "CREATE TABLE security_observation_spine (trading_date DATE)"
        )
        connection.execute(
            "INSERT INTO security_observation_spine VALUES "
            "('2016-01-04'), ('2026-06-30')"
        )
        connection.execute(
            "CREATE TABLE dimension_definitions ("
            "dimension_id VARCHAR, canonical_order INTEGER, dimension_name VARCHAR, "
            "component_count INTEGER, definition_version VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO dimension_definitions VALUES (?, ?, ?, ?, ?)",
            [
                ("P", 1, "Price", 1, "fixture.v1"),
                ("C", 2, "Reference", 1, "fixture.v1"),
                ("A", 3, "Alignment", 1, "fixture.v1"),
                ("V", 4, "Participation", 1, "fixture.v1"),
                ("T", 5, "Trend", 1, "fixture.v1"),
            ],
        )
        connection.execute(
            "CREATE TABLE dimension_components ("
            "dimension_id VARCHAR, component_id VARCHAR, component_order INTEGER)"
        )
        connection.executemany(
            "INSERT INTO dimension_components VALUES (?, ?, ?)",
            [
                (dimension, f"{dimension}01", 1)
                for dimension in ("P", "C", "A", "V", "T")
            ],
        )
        connection.execute(
            "CREATE TABLE daily_component_scores (dimension_id VARCHAR, score DOUBLE)"
        )
        connection.executemany(
            "INSERT INTO daily_component_scores VALUES (?, ?)",
            [(dimension, 0.5) for dimension in ("P", "C", "A", "V", "T")],
        )
        if forbidden_field:
            connection.execute("CREATE TABLE daily_dimension_scores (return_1d DOUBLE)")
        else:
            connection.execute(
                "CREATE TABLE daily_dimension_scores ("
                "dimension_id VARCHAR, score_dimension DOUBLE)"
            )
            connection.executemany(
                "INSERT INTO daily_dimension_scores VALUES (?, ?)",
                [(dimension, 0.5) for dimension in ("P", "C", "A", "V", "T")],
            )


def _make_authorized_inputs(
    tmp_path: Path,
    *,
    forbidden_field: bool = False,
    mutate_t04_identity: bool = False,
) -> tuple[dict[str, Any], Path, Path]:
    config = copy.deepcopy(load_formal_execution_config())
    for directory in (
        "data/raw",
        "data/external",
        "data/interim/duckdb",
        "data/generated",
    ):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)

    score_relative = "data/interim/duckdb/score.duckdb"
    score_path = tmp_path / score_relative
    _make_score_database(score_path, forbidden_field=forbidden_field)
    score_binding = config["accepted_bindings"]["score_release"]
    score_binding.update(
        {
            "relative_path": score_relative,
            "sha256": sha256_file(score_path),
            "byte_size": score_path.stat().st_size,
            "security_count": 800,
            "date_min": "2016-01-04",
            "date_max": "2026-06-30",
        }
    )
    config["input_authorization"]["score_database_relative_path"] = score_relative

    t01 = {
        "task_id": "R2A-T01",
        "status": "completed_accepted",
        "score_release": {"score_release_id": score_binding["score_release_id"]},
    }
    t03 = {
        "task_id": "R2A-T03",
        "status": "completed_accepted",
        "evaluator_version": "r2a_t03_dynamic_evaluator.v1",
        "output_schema_version": "r2a_t03_dynamic_evaluation_output.v1",
        "dynamic_protocol_version": "pcavt_dynamic_state_protocol.v1",
    }
    requests = _request_envelopes(config)
    t04_requests = []
    for item in config["requests"]:
        name = item["logical_request_name"]
        counts = EXPECTED_COUNTS[name]
        t04_item = {
            **{
                key: item[key]
                for key in (
                    "logical_request_name",
                    "request_id",
                    "request_hash",
                    "selected_dimensions",
                    "q_by_dimension",
                    "confirmation_k",
                    "selection_status",
                )
            },
            "raw_true_count": counts["raw_true"],
            "confirmed_true_count": counts["confirmed_true"],
            "confirmed_interval_count": counts["intervals"],
            "security_with_interval_count": counts["securities_with_interval"],
        }
        if mutate_t04_identity and name == "CA_q20_k5":
            t04_item["request_hash"] = "0" * 64
        t04_requests.append(t04_item)
    t04 = {
        "task_id": "R2A-T04",
        "status": "completed_accepted",
        "scope_id": config["accepted_bindings"]["t04_handoff"]["scope_id"],
        "panel_id": config["accepted_bindings"]["t04_handoff"]["panel_id"],
        "accepted_run_id": config["accepted_bindings"]["t04_handoff"][
            "accepted_run_id"
        ],
        "requests": t04_requests,
    }
    files = {
        "t01_handoff": ("data/generated/upstream/t01.json", t01),
        "t03_handoff": ("data/generated/upstream/t03.json", t03),
        "t03_config": (
            "configs/r2a/t03.json",
            {"evaluator_version": "r2a_t03_dynamic_evaluator.v1"},
        ),
        "t04_handoff": ("data/generated/upstream/t04.json", t04),
    }
    for key, (relative, payload) in files.items():
        path = tmp_path / relative
        _write_json(path, payload)
        binding = config["accepted_bindings"][key]
        binding["relative_path"] = relative
        binding["sha256"] = sha256_file(path)
    config["request_sources"] = []
    for name in REQUEST_ORDER:
        relative = f"data/generated/upstream/requests/{name}.json"
        path = tmp_path / relative
        _write_json(path, requests[name])
        config["request_sources"].append(
            {
                "logical_request_name": name,
                "relative_path": relative,
                "sha256": sha256_file(path),
                "byte_size": path.stat().st_size,
            }
        )
    output_path = tmp_path / "data/generated/formal_input_manifest.json"
    return config, score_path, output_path


def _build_formal_manifest(**kwargs: Any) -> dict[str, Any]:
    with patch(
        "src.r2a.r2a_t05_formal_input_manifest._git_head", return_value="a" * 40
    ):
        return build_formal_input_manifest(**kwargs)


def _build_manifest(
    tmp_path: Path, **kwargs: Any
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    config, score_path, output_path = _make_authorized_inputs(tmp_path, **kwargs)
    payload = _build_formal_manifest(
        output_path=output_path,
        repo_root=tmp_path,
        config=config,
        score_database_path=score_path,
        source_commit="a" * 40,
        created_at="2026-07-20T00:00:00Z",
    )
    return config, payload, output_path


def test_formal_manifest_builder_reads_only_synthetic_score_and_binds_metadata(
    tmp_path: Path,
) -> None:
    config, payload, output_path = _build_manifest(tmp_path)

    assert output_path.is_file()
    assert (
        payload["score_database"]["byte_size"]
        == (tmp_path / "data/interim/duckdb/score.duckdb").stat().st_size
    )
    assert payload["score_coverage"] == {
        "security_count": 800,
        "date_min": "2016-01-04",
        "date_max": "2026-06-30",
    }
    assert [item["logical_request_name"] for item in payload["requests"]] == list(
        REQUEST_ORDER
    )
    assert set(payload["required_schema_fingerprints"]) == {
        "securities",
        "trading_sessions",
        "security_observation_spine",
        "dimension_definitions",
        "dimension_components",
        "daily_component_scores",
        "daily_dimension_scores",
    }
    assert payload["score_dimension_inventory"] == ["P", "C", "A", "V", "T"]
    assert payload["analysis_dimension_scope"] == ["C", "A"]
    assert payload["selected_dimensions_required"] == ["C", "A"]
    assert payload["unselected_dimensions_must_not_affect_results"] is True
    assert set(payload["component_inventory"]) == {"P", "C", "A", "V", "T"}
    assert all(
        payload["t05_request_selected_dimensions"][name] == ["C", "A"]
        for name in REQUEST_ORDER
    )
    verified = load_authorized_input_manifest(
        output_path, repo_root=tmp_path, verify_files=True
    )
    assert verified["requests"] == payload["requests"]
    assert config["formal_run_attempts_consumed"] == 0


def test_formal_manifest_binds_current_head_and_rejects_stale_source_commit(
    tmp_path: Path,
) -> None:
    config, score_path, output_path = _make_authorized_inputs(tmp_path)
    with patch(
        "src.r2a.r2a_t05_formal_input_manifest._git_head", return_value="a" * 40
    ):
        with pytest.raises(
            FormalInputManifestError, match="manifest_source_commit_mismatch"
        ):
            build_formal_input_manifest(
                output_path=output_path,
                repo_root=tmp_path,
                config=config,
                score_database_path=score_path,
                source_commit="b" * 40,
            )
    _, payload, _ = _build_manifest(tmp_path / "valid")
    assert payload["source_commit"] == "a" * 40
    assert payload["reviewed_formal_execution_sha"] == "a" * 40


def test_manifest_loader_rejects_reviewed_execution_lineage_mismatch(
    tmp_path: Path,
) -> None:
    _, payload, output_path = _build_manifest(tmp_path)
    payload["reviewed_formal_execution_sha"] = "b" * 40
    _write_json(output_path, payload)
    with pytest.raises(
        FormalInputManifestError, match="manifest_execution_lineage_mismatch"
    ):
        load_authorized_input_manifest(
            output_path, repo_root=tmp_path, verify_files=False
        )


@pytest.mark.parametrize(
    "mutator,reason",
    [
        (
            lambda config: config.update(reviewed_implementation_sha="0" * 40),
            "reviewed_implementation_sha_mismatch",
        ),
        (
            lambda config: config["accepted_bindings"]["score_release"].update(
                sha256="0" * 64
            ),
            "input_hash_mismatch",
        ),
        (
            lambda config: config["accepted_bindings"]["score_release"].update(
                byte_size=1
            ),
            "input_byte_size_mismatch",
        ),
        (
            lambda config: config["accepted_bindings"]["t04_handoff"].update(
                sha256="0" * 64
            ),
            "input_hash_mismatch",
        ),
        (
            lambda config: config["accepted_bindings"]["t01_handoff"].update(
                relative_path="data/generated/convergence-research-inputs/t01.json"
            ),
            "retired_external_root_path",
        ),
    ],
)
def test_formal_manifest_rejects_wrong_authorization_bindings(
    tmp_path: Path, mutator: Any, reason: str
) -> None:
    config, score_path, output_path = _make_authorized_inputs(tmp_path)
    mutator(config)
    with pytest.raises(FormalInputManifestError, match=reason):
        _build_formal_manifest(
            output_path=output_path,
            repo_root=tmp_path,
            config=config,
            score_database_path=score_path,
            source_commit="a" * 40,
        )


def test_formal_manifest_rejects_request_identity_mismatch(tmp_path: Path) -> None:
    config, score_path, output_path = _make_authorized_inputs(
        tmp_path, mutate_t04_identity=True
    )
    with pytest.raises(
        FormalInputManifestError, match="formal_request_identity_mismatch"
    ):
        _build_formal_manifest(
            output_path=output_path,
            repo_root=tmp_path,
            config=config,
            score_database_path=score_path,
            source_commit="a" * 40,
        )


def test_formal_manifest_rejects_forbidden_score_field(tmp_path: Path) -> None:
    config, score_path, output_path = _make_authorized_inputs(
        tmp_path, forbidden_field=True
    )
    with pytest.raises(FormalInputManifestError, match="forbidden_score_field"):
        _build_formal_manifest(
            output_path=output_path,
            repo_root=tmp_path,
            config=config,
            score_database_path=score_path,
            source_commit="a" * 40,
        )


def test_manifest_loader_rejects_forbidden_manifest_field(tmp_path: Path) -> None:
    _, payload, output_path = _build_manifest(tmp_path)
    payload["table_inventory"][0]["ohlc"] = True
    _write_json(output_path, payload)
    with pytest.raises(FormalInputManifestError, match="forbidden_manifest_field"):
        load_authorized_input_manifest(
            output_path, repo_root=tmp_path, verify_files=False
        )


def test_preflight_does_not_read_score_create_runroot_or_consume_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest_config, payload, output_path = _build_manifest(tmp_path)
    authorization_path = _write_authorization_fixture(
        tmp_path, _unauthorized_authorization_payload()
    )
    payload["source_commit"] = "b" * 40
    payload["reviewed_formal_execution_sha"] = "b" * 40
    _write_json(output_path, payload)
    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution.load_formal_execution_config",
        lambda _: manifest_config,
    )
    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution.inspect_git_preflight",
        lambda **_: {
            "head": "b" * 40,
            "worktree_status": "clean",
            "protected_files": [],
        },
    )
    score_opened = False

    def fail_score_open(*args: Any, **kwargs: Any) -> None:
        nonlocal score_opened
        score_opened = True
        raise AssertionError("real Score/database access is outside preparation scope")

    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution.duckdb.connect", fail_score_open
    )
    result = preflight_formal_execution(
        manifest_path=output_path,
        repo_root=tmp_path,
        authorization_path=authorization_path,
        verify_manifest_files=False,
    )
    assert result["status"] == "preflight_passed"
    assert result["real_score_data_read"] is False
    assert result["formal_artifacts_generated"] is False
    assert result["formal_run_attempts_consumed"] == 0
    assert not score_opened
    assert not (tmp_path / "data/generated/r2a/r2a_t05/formal-runs").exists()


def test_preflight_accepts_authorized_child_head_with_parent_manifest_lineage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest_config, _, output_path = _build_manifest(tmp_path)
    authorization = _authorized_authorization_payload()
    authorization.update(
        {
            "authorization_status": "authorized_pending_execution",
            "reviewed_formal_execution_sha": "a" * 40,
            "authorization_revision": 1,
            "authorization_parent": "a" * 40,
            "formal_run_allowed": True,
            "authorized_manifest_sha256": sha256_file(output_path),
            "authorized_manifest_byte_size": output_path.stat().st_size,
        }
    )
    authorization["protected_execution_files"] = [
        {**record, "source_commit": "a" * 40}
        for record in authorization["protected_execution_files"]
    ]
    authorization_path = tmp_path / "authorization.json"
    _write_json(authorization_path, authorization)
    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution.load_formal_execution_config",
        lambda _: manifest_config,
    )

    def fake_git(_: Path, *args: str) -> str:
        if args[:2] == ("rev-parse", "HEAD"):
            return "b" * 40
        if args[:1] == ("status",):
            return ""
        if args[:2] == ("merge-base", "--is-ancestor"):
            return ""
        if args[:4] == ("rev-list", "--parents", "-n", "1"):
            return f"{'b' * 40} {'a' * 40}"
        if args[:2] == ("diff", "--name-only"):
            return "\n".join(
                (
                    "configs/r2a/r2a_t05_formal_authorization.v1.json",
                    "docs/tasks/R2A-T05_CA退出机制与跨q结构分解.md",
                )
            )
        if args[:1] == ("rev-parse",) and len(args) == 2 and ":" in args[1]:
            return "0" * 40
        raise AssertionError(args)

    monkeypatch.setattr("src.r2a.r2a_t05_formal_execution._git", fake_git)
    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution._protected_file_record",
        lambda *_args, **_kwargs: {"path": "synthetic", "sha256": "0" * 64},
    )
    result = preflight_formal_execution(
        manifest_path=output_path,
        repo_root=tmp_path,
        authorization_path=authorization_path,
        verify_manifest_files=False,
    )
    assert result["current_head"] == "b" * 40
    assert result["authorization_head"] == "b" * 40
    assert result["reviewed_formal_execution_sha"] == "a" * 40
    assert "authorization_head" not in authorization


def test_preflight_blocks_authorized_reviewed_parent_manifest_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest_config, _, output_path = _build_manifest(tmp_path)
    authorization = _authorized_authorization_payload()
    authorization.update(
        {
            "authorization_status": "authorized_pending_execution",
            "reviewed_formal_execution_sha": "c" * 40,
            "authorization_revision": 1,
            "authorization_parent": "a" * 40,
            "formal_run_allowed": True,
            "authorized_manifest_sha256": sha256_file(output_path),
            "authorized_manifest_byte_size": output_path.stat().st_size,
        }
    )
    authorization["protected_execution_files"] = [
        {**record, "source_commit": "c" * 40}
        for record in authorization["protected_execution_files"]
    ]
    authorization_path = tmp_path / "authorization.json"
    _write_json(authorization_path, authorization)
    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution.load_formal_execution_config",
        lambda _: manifest_config,
    )
    with pytest.raises(
        FormalExecutionError, match="authorized_execution_lineage_mismatch"
    ):
        preflight_formal_execution(
            manifest_path=output_path,
            repo_root=tmp_path,
            authorization_path=authorization_path,
            verify_manifest_files=False,
        )


def test_preflight_blocks_authorized_manifest_source_parent_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest_config, manifest, output_path = _build_manifest(tmp_path)
    manifest["source_commit"] = "b" * 40
    manifest["reviewed_formal_execution_sha"] = "b" * 40
    _write_json(output_path, manifest)
    authorization = _authorized_authorization_payload()
    authorization.update(
        {
            "authorization_status": "authorized_pending_execution",
            "reviewed_formal_execution_sha": "a" * 40,
            "authorization_revision": 1,
            "authorization_parent": "a" * 40,
            "formal_run_allowed": True,
            "authorized_manifest_sha256": sha256_file(output_path),
            "authorized_manifest_byte_size": output_path.stat().st_size,
        }
    )
    authorization["protected_execution_files"] = [
        {**record, "source_commit": "a" * 40}
        for record in authorization["protected_execution_files"]
    ]
    authorization_path = tmp_path / "authorization.json"
    _write_json(authorization_path, authorization)
    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution.load_formal_execution_config",
        lambda _: manifest_config,
    )
    with pytest.raises(
        FormalExecutionError, match="authorized_manifest_source_commit_mismatch"
    ):
        preflight_formal_execution(
            manifest_path=output_path,
            repo_root=tmp_path,
            authorization_path=authorization_path,
            verify_manifest_files=False,
        )


def test_git_preflight_uses_superseded_candidate_for_unauthorized_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_formal_execution_config()
    authorization = _unauthorized_authorization_payload()
    head = "f" * 40

    def fake_git(_: Path, *args: str) -> str:
        if args[:2] == ("rev-parse", "HEAD"):
            return head
        if args[:1] in {("status",), ("merge-base",)}:
            return ""
        raise AssertionError(args)

    monkeypatch.setattr("src.r2a.r2a_t05_formal_execution._git", fake_git)
    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution._protected_file_record",
        lambda *_args, **_kwargs: {"path": "synthetic", "sha256": "0" * 64},
    )
    result = inspect_git_preflight(config=config, authorization=authorization)
    assert (
        result["reviewed_formal_execution_sha"]
        == config["superseded_formal_execution_candidate_sha"]
    )


def test_git_preflight_rejects_dirty_worktree(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_formal_execution_config()

    def fake_git(_: Path, *args: str) -> str:
        if args[:2] == ("rev-parse", "HEAD"):
            return config["reviewed_implementation_sha"]
        if args[:1] == ("status",):
            return " M protected.py"
        return ""

    monkeypatch.setattr("src.r2a.r2a_t05_formal_execution._git", fake_git)
    with pytest.raises(FormalExecutionError, match="dirty_worktree"):
        inspect_git_preflight(config=config)


def test_git_preflight_rejects_changed_protected_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_formal_execution_config()
    target = config["protected_implementation_files"][0]["path"]

    def fake_git(_: Path, *args: str) -> str:
        if args[:2] == ("rev-parse", "HEAD"):
            return config["reviewed_implementation_sha"]
        if args[:1] == ("status",):
            return ""
        if args[:2] == ("merge-base", "--is-ancestor"):
            return ""
        if args[:1] == ("rev-parse",) and len(args) == 2 and ":" in args[1]:
            path = args[1].split(":", 1)[1]
            if path == target:
                return "0" * 40
            return next(
                item["git_blob_sha"]
                for item in config["protected_implementation_files"]
                if item["path"] == path
            )
        raise AssertionError(args)

    monkeypatch.setattr("src.r2a.r2a_t05_formal_execution._git", fake_git)
    with pytest.raises(FormalExecutionError, match="protected_file_git_blob_mismatch"):
        inspect_git_preflight(config=config)


def test_runroot_rejects_existing_root_and_does_not_resume(tmp_path: Path) -> None:
    first, run_id = create_unique_run_root(
        repo_root=tmp_path, run_id="R2A-T05-20260720T000000001Z"
    )
    assert first.is_dir()
    with pytest.raises(FormalExecutionError, match="run_root_already_exists"):
        create_unique_run_root(repo_root=tmp_path, run_id=run_id)


def _sequence_callbacks(
    *,
    failing_name: str | None = None,
    summaries: dict[str, dict[str, int]] | None = None,
):
    def evaluate(name: str, _source: Path, target: Path) -> None:
        target.write_bytes(name.encode("utf-8"))

    def validate(name: str, _target: Path) -> dict[str, Any]:
        if name == failing_name:
            return {"status": "blocked"}
        return {"status": "passed", "logical_request_name": name}

    def summarize(target: Path) -> dict[str, int]:
        name = target.stem
        return dict((summaries or {}).get(name, {"ok": 1}))

    return evaluate, validate, summarize


def test_request_order_mutation_is_blocked_before_output_directory(
    tmp_path: Path,
) -> None:
    evaluate, validate, summarize = _sequence_callbacks()
    with pytest.raises(FormalExecutionError, match="request_order_mutation"):
        execute_request_sequence(
            request_order=tuple(reversed(REQUEST_ORDER)),
            request_sources={
                name: tmp_path / f"{name}.json" for name in reversed(REQUEST_ORDER)
            },
            output_dir=tmp_path / "request-results",
            evaluate=evaluate,
            validate=validate,
            summarize=summarize,
        )
    assert not (tmp_path / "request-results").exists()


def test_request_validator_failure_and_partial_output_fail_closed(
    tmp_path: Path,
) -> None:
    evaluate, validate, summarize = _sequence_callbacks(failing_name="CA_q20_k5")
    sources = {name: tmp_path / f"{name}.json" for name in REQUEST_ORDER}
    with pytest.raises(FormalExecutionError, match="request_validator_blocked"):
        execute_request_sequence(
            request_order=REQUEST_ORDER,
            request_sources=sources,
            output_dir=tmp_path / "request-results",
            evaluate=evaluate,
            validate=validate,
            summarize=summarize,
        )
    assert (tmp_path / "request-results/CA_q10_k5.duckdb").is_file()
    assert (tmp_path / "request-results/CA_q15_k5.duckdb").is_file()
    assert (tmp_path / "request-results/CA_q20_k5.duckdb").is_file()

    output_dir = tmp_path / "partial-request-results"
    output_dir.mkdir()
    (output_dir / "CA_q10_k5.duckdb").write_bytes(b"partial")
    with pytest.raises(
        FormalExecutionError, match="partial_request_output_or_resume_rejected"
    ):
        execute_request_sequence(
            request_order=REQUEST_ORDER,
            request_sources=sources,
            output_dir=output_dir,
            evaluate=evaluate,
            validate=validate,
            summarize=summarize,
        )


def test_t04_count_mismatch_blocks_before_t05_promotion(tmp_path: Path) -> None:
    evaluate, validate, summarize = _sequence_callbacks(
        summaries={name: EXPECTED_COUNTS[name] for name in REQUEST_ORDER}
    )
    wrong_counts = copy.deepcopy(EXPECTED_COUNTS)
    wrong_counts["CA_q20_k5"]["raw_true"] += 1
    with pytest.raises(FormalExecutionError, match="accepted_t04_count_mismatch"):
        execute_request_sequence(
            request_order=REQUEST_ORDER,
            request_sources={name: tmp_path / f"{name}.json" for name in REQUEST_ORDER},
            output_dir=tmp_path / "request-results",
            evaluate=evaluate,
            validate=validate,
            expected_counts=wrong_counts,
            summarize=summarize,
        )


def test_independent_validator_and_result_analysis_blocked() -> None:
    candidate = {"request_reconciliation": []}
    with pytest.raises(FormalExecutionError, match="independent_validator_blocked"):
        finalize_formal_candidate(candidate, {"status": "blocked"})
    with pytest.raises(FormalExecutionError, match="result_analysis_blocked"):
        finalize_formal_candidate(
            candidate,
            {"status": "passed"},
            analysis_function=lambda *_: {
                "status": "blocked",
                "blocking_anomalies": ["x"],
            },
        )


def test_formal_completion_lifecycle_mismatch_is_blocked() -> None:
    with pytest.raises(FormalExecutionError, match="lifecycle_mismatch"):
        validate_formal_completion_lifecycle(
            {
                "status": "completed_accepted",
                "formal_run_started": True,
                "real_score_data_read": True,
                "formal_artifacts_generated": True,
                "R2A-T05_DONE": "present",
                "R2A-T06_allowed_to_start": True,
            }
        )


def test_preparation_config_cannot_consume_formal_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called = {"manifest": False, "runroot": False}
    config = load_formal_execution_config()
    authorization_path = _write_authorization_fixture(
        tmp_path, _unauthorized_authorization_payload()
    )
    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution.load_formal_execution_config",
        lambda _: config,
    )
    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution.preflight_formal_execution",
        lambda **_: {
            "current_head": config["reviewed_implementation_sha"],
            "formal_run_attempts_consumed": 0,
        },
    )

    def manifest_guard(*args: Any, **kwargs: Any) -> None:
        called["manifest"] = True
        raise AssertionError(
            "Score manifest verification must wait for owner authorization"
        )

    def runroot_guard(*args: Any, **kwargs: Any) -> None:
        called["runroot"] = True
        raise AssertionError("RunRoot must not be created during preparation")

    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution.load_authorized_input_manifest",
        manifest_guard,
    )
    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution.create_unique_run_root", runroot_guard
    )
    with pytest.raises(FormalExecutionError, match="formal_run_not_authorized"):
        from src.r2a.r2a_t05_formal_execution import run_formal_execution

        run_formal_execution(
            manifest_path=Path("unused.json"),
            authorization_path=authorization_path,
            operator_authorized=True,
        )
    assert called == {"manifest": False, "runroot": False}
    assert config["formal_run_attempts_consumed"] == 0


def test_manifest_accepts_complete_pcavt_score_but_freezes_ca_consumption(
    tmp_path: Path,
) -> None:
    _, payload, _ = _build_manifest(tmp_path)

    assert payload["score_dimension_inventory"] == ["P", "C", "A", "V", "T"]
    assert payload["component_inventory"]["C"] == ["C01"]
    assert payload["component_inventory"]["A"] == ["A01"]
    assert payload["score_dimension_rows"]["P"]["daily_dimension_score_rows"] == 1
    assert payload["score_dimension_rows"]["V"]["daily_component_score_rows"] == 1
    assert payload["analysis_dimension_scope"] == ["C", "A"]
    assert payload["unselected_dimensions_must_not_affect_results"] is True


@pytest.mark.parametrize(
    "selected_dimensions", [["P", "C", "A"], ["C", "A", "V"], ["C", "A", "T"]]
)
def test_manifest_rejects_non_ca_request_selection(
    tmp_path: Path, selected_dimensions: list[str]
) -> None:
    config, score_path, output_path = _make_authorized_inputs(tmp_path)
    config["requests"][0]["selected_dimensions"] = selected_dimensions

    with pytest.raises(FormalInputManifestError):
        _build_formal_manifest(
            output_path=output_path,
            repo_root=tmp_path,
            config=config,
            score_database_path=score_path,
            source_commit="a" * 40,
        )


def _make_t03_scope_outputs(tmp_path: Path, *, dimension: str = "C") -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    for name in REQUEST_ORDER:
        path = tmp_path / f"{name}.duckdb"
        with duckdb.connect(str(path)) as connection:
            connection.execute(
                "CREATE TABLE dynamic_request (selected_dimensions VARCHAR)"
            )
            connection.execute('INSERT INTO dynamic_request VALUES (\'["C","A"]\')')
            connection.execute("CREATE TABLE evaluation_scope (scope_id VARCHAR)")
            connection.execute(
                "CREATE TABLE daily_dimension_states (dimension_id VARCHAR)"
            )
            connection.execute(
                "INSERT INTO daily_dimension_states VALUES (?)", [dimension]
            )
            connection.execute("CREATE TABLE daily_joint_states (joint_state BOOLEAN)")
            connection.execute("CREATE TABLE confirmed_intervals (interval_id INTEGER)")
        outputs[name] = path
    return outputs


def test_t05_output_scope_allows_ca_and_blocks_unselected_or_forbidden_fields(
    tmp_path: Path,
) -> None:
    outputs = _make_t03_scope_outputs(tmp_path)
    validate_t05_output_scope(outputs)

    p_outputs = _make_t03_scope_outputs(tmp_path / "p", dimension="P")
    with pytest.raises(
        FormalExecutionError, match="unselected_dimension_in_t05_output"
    ):
        validate_t05_output_scope(p_outputs)

    with pytest.raises(
        FormalExecutionError, match="unselected_dimension_in_t05_output"
    ):
        validate_t05_output_scope(
            outputs, candidate={"component_output": {"dimension_id": "T"}}
        )
    with pytest.raises(
        FormalExecutionError, match="unselected_dimension_in_t05_output"
    ):
        validate_t05_output_scope(
            outputs, candidate={"component_output": {"component_id": "P01"}}
        )
    with pytest.raises(FormalExecutionError, match="forbidden_t05_output_field"):
        validate_t05_output_scope(outputs, candidate={"future_return": 0.1})
    validate_t05_output_scope(
        outputs,
        candidate={
            "selected_dimensions": ["C", "A"],
            "analysis_dimension_scope": ["C", "A"],
            "selected_dimensions_required": ["C", "A"],
            "dimension_id": "C",
            "component_dimension": "A",
            "component_id": ["C01", "A01"],
        },
    )


def test_t05_output_scope_scans_real_builder_candidate(tmp_path: Path) -> None:
    config, score, outputs = _ca_fixture(tmp_path)
    candidate = build_t05_candidate(outputs, score, config=config)
    validate_t05_output_scope(outputs, candidate=candidate)


def test_formal_authorization_starts_without_a_future_head(tmp_path: Path) -> None:
    authorization = load_formal_authorization()
    assert "authorization_head" not in authorization
    assert authorization["authorization_status"] in {
        "not_authorized",
        "authorized_pending_execution",
    }
    if authorization["authorization_status"] == "not_authorized":
        assert authorization["authorization_parent"] is None
        assert authorization["reviewed_formal_execution_sha"] is None
        assert authorization["formal_run_allowed"] is False
        assert authorization["authorization_revision"] == 0
        assert authorization["authorized_manifest_sha256"] is None
        assert authorization["authorized_manifest_byte_size"] is None
    else:
        assert re.fullmatch(r"[0-9a-f]{40}", str(authorization["authorization_parent"]))
        assert re.fullmatch(
            r"[0-9a-f]{40}", str(authorization["reviewed_formal_execution_sha"])
        )
        assert authorization["authorization_revision"] >= 1
        assert authorization["formal_run_allowed"] is True
        assert re.fullmatch(
            r"[0-9a-f]{64}", str(authorization["authorized_manifest_sha256"])
        )
        assert authorization["authorized_manifest_byte_size"] >= 1
    assert authorization["formal_run_attempts_consumed_before_start"] == 0

    mutated = copy.deepcopy(authorization)
    mutated["authorization_head"] = "b" * 40
    path = tmp_path / "authorization.json"
    _write_json(path, mutated)
    with pytest.raises(
        FormalExecutionError, match="formal_authorization_schema_invalid"
    ):
        load_formal_authorization(path)


def _authorized_git_payload() -> dict[str, Any]:
    return _authorized_authorization_payload()


def _patch_authorized_git(
    monkeypatch: pytest.MonkeyPatch,
    *,
    parent_output: str = "b" * 40 + " " + "a" * 40,
    diff_output: str = (
        "configs/r2a/r2a_t05_formal_authorization.v1.json\n"
        "docs/tasks/R2A-T05_CA退出机制与跨q结构分解.md"
    ),
) -> None:
    def fake_git(_: Path, *args: str) -> str:
        if args[:2] == ("rev-parse", "HEAD"):
            return "b" * 40
        if args[:1] == ("status",):
            return ""
        if args[:2] == ("merge-base", "--is-ancestor"):
            return ""
        if args[:4] == ("rev-list", "--parents", "-n", "1"):
            return parent_output
        if args[:2] == ("diff", "--name-only"):
            return diff_output
        if args[:1] == ("rev-parse",) and len(args) == 2 and ":" in args[1]:
            return "0" * 40
        raise AssertionError(args)

    monkeypatch.setattr("src.r2a.r2a_t05_formal_execution._git", fake_git)
    monkeypatch.setattr(
        "src.r2a.r2a_t05_formal_execution._protected_file_record",
        lambda *_args, **_kwargs: {"path": "synthetic", "sha256": "0" * 64},
    )


@pytest.mark.parametrize(
    "parent_output",
    [
        "b" * 40 + " " + "c" * 40 + " " + "a" * 40,
        "b" * 40 + " " + "a" * 40 + " " + "c" * 40,
        "b" * 40,
        "b" * 40 + " c" * 40,
    ],
)
def test_authorized_git_preflight_requires_exact_single_parent(
    monkeypatch: pytest.MonkeyPatch, parent_output: str
) -> None:
    config = load_formal_execution_config()
    authorization = _authorized_git_payload()
    _patch_authorized_git(monkeypatch, parent_output=parent_output)
    with pytest.raises(FormalExecutionError, match="authorization_parent_not_exact"):
        inspect_git_preflight(config=config, authorization=authorization)


def test_authorized_git_preflight_rejects_diff_outside_whitelist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_formal_execution_config()
    authorization = _authorized_git_payload()
    _patch_authorized_git(monkeypatch, diff_output="outside.py")
    with pytest.raises(
        FormalExecutionError, match="authorization_diff_outside_whitelist"
    ):
        inspect_git_preflight(config=config, authorization=authorization)


@pytest.mark.parametrize(
    "authorization_factory",
    [_unauthorized_authorization_payload, _authorized_authorization_payload],
)
def test_formal_authorization_evidence_adds_only_runtime_head(
    tmp_path: Path, authorization_factory: Any
) -> None:
    authorization = authorization_factory()
    original = copy.deepcopy(authorization)
    evidence = build_formal_authorization_evidence(authorization, current_head="b" * 40)
    evidence_path = tmp_path / "formal-runs/synthetic/formal_authorization.json"
    _write_json(evidence_path, evidence)
    persisted = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert authorization == original
    assert "authorization_head" not in original
    assert set(evidence) == {*original, "authorization_head"}
    assert persisted == evidence
    assert evidence["authorization_head"] == "b" * 40
    for key, value in original.items():
        assert evidence[key] == value


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["rows"][0].update(value=0.6),
        lambda payload: payload["rows"].reverse(),
        lambda payload: payload["rows"].pop(),
        lambda payload: payload["rows"].append(copy.deepcopy(payload["rows"][0])),
        lambda payload: payload.update(nullable=None),
        lambda payload: payload.update(flag=False),
        lambda payload: payload.update(float_value=0.6),
    ],
)
def test_determinism_mutations_fail_closed(mutation: Any) -> None:
    base = {
        "rows": [{"key": "a", "value": 0.5}, {"key": "b", "value": 0.8}],
        "nullable": "value",
        "flag": True,
        "float_value": 0.5,
        "termination_reason_profile": [{"reason": "raw_false", "count": 2}],
    }
    calls = 0

    def build() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        payload = copy.deepcopy(base)
        if calls == 2:
            mutation(payload)
        return payload

    with pytest.raises(FormalExecutionError, match="determinism_mismatch"):
        build_determinism_receipt(build)

    receipt = compare_formal_builds(base, copy.deepcopy(base))
    assert receipt["status"] == "passed"
    assert receipt["build_count"] == 2
    assert receipt["left_fingerprint"] == receipt["right_fingerprint"]


def _write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _make_persisted_analysis_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "R2A-T05-20260720T000000001Z"
    compact = root / "compact-review"
    compact.mkdir(parents=True)
    expected = {
        name: {
            "raw_true": 10,
            "confirmed_true": 5,
            "intervals": 8,
            "securities_with_interval": 2,
        }
        for name in REQUEST_ORDER
    }
    reconciliation = [
        {
            "logical_request_name": name,
            "actual": dict(expected[name]),
            "expected": dict(expected[name]),
            "matches_accepted_t04": True,
            "selected_dimensions": ["C", "A"],
        }
        for name in REQUEST_ORDER
    ]

    def _endpoint_metrics(endpoint: str, subclass: str, index: int) -> dict[str, Any]:
        bases = {
            "A_ONLY_FAIL": {"C": 0.12, "A": -0.18},
            "C_ONLY_FAIL": {"C": -0.16, "A": 0.14},
            "CA_BOTH_FAIL": {"C": -0.20, "A": -0.24},
        }
        gates = {
            "A_ONLY_FAIL": {"C": "NO_GATE_FAIL", "A": "MAIN_AND_WEAK_FAIL"},
            "C_ONLY_FAIL": {"C": "MAIN_AND_WEAK_FAIL", "A": "NO_GATE_FAIL"},
            "CA_BOTH_FAIL": {
                "C": "MAIN_AND_WEAK_FAIL",
                "A": "MAIN_AND_WEAK_FAIL",
            },
        }
        result = {}
        for dimension in ("C", "A"):
            mean = bases[subclass][dimension] + index * 0.03
            if endpoint == "termination_observation_metrics":
                mean += 0.01
            minimum = mean - 0.04
            result[dimension] = {
                "endpoint": endpoint,
                "dimension_id": dimension,
                "mean_margin": mean,
                "min_margin": minimum,
                "active_margin": min(mean, minimum),
                "gate_failure_class": gates[subclass][dimension],
            }
        return result

    quality_reasons = {
        "CA_q10_k5": "expected_observation_missing",
        "CA_q15_k5": "expected_observation_listing_pause",
        "CA_q20_k5": "selected_dimension_blocked",
        "CA_q25_k5": "selected_dimension_diagnostic_required",
    }
    termination_records = []
    for name in REQUEST_ORDER:
        for subclass in ("A_ONLY_FAIL", "C_ONLY_FAIL", "CA_BOTH_FAIL"):
            for index in (0, 1):
                termination_records.append(
                    {
                        "logical_request_name": name,
                        "primary_termination_reason": "raw_false",
                        "original_primary_termination_reason": "raw_false",
                        "raw_false_subclass": subclass,
                        "right_censored": False,
                        "last_confirmed_end_metrics": _endpoint_metrics(
                            "last_confirmed_end_metrics", subclass, index
                        ),
                        "termination_observation_metrics": _endpoint_metrics(
                            "termination_observation_metrics", subclass, index
                        ),
                    }
                )
        termination_records.extend(
            [
                {
                    "logical_request_name": name,
                    "primary_termination_reason": "quality_or_availability_termination",
                    "original_primary_termination_reason": quality_reasons[name],
                    "raw_false_subclass": None,
                    "right_censored": False,
                },
                {
                    "logical_request_name": name,
                    "primary_termination_reason": "input_end_open_right_censored",
                    "original_primary_termination_reason": (
                        "input_end_open_right_censored"
                    ),
                    "raw_false_subclass": None,
                    "right_censored": True,
                },
            ]
        )
    margin_rows = [
        {
            "logical_request_name": name,
            "endpoint": "last_confirmed_end",
            "dimension_id": "C",
            "margin_name": "mean_margin",
            "count": 2,
            "finite_count": 2,
            "null_count": 0,
            "min": 0.1,
            "p05": 0.1,
            "p50": 0.2,
            "p95": 0.3,
            "max": 0.3,
            "mean": 0.2,
            "all_null": False,
            "all_zero": False,
            "constant": False,
            "gate_failure_counts": {"MAIN_ONLY_FAIL": 1},
        }
        for name in REQUEST_ORDER
    ]
    reentry_rows = [
        {
            "logical_request_name": name,
            "metric": metric,
            "lag_threshold": threshold,
            "total_non_right_censored_termination_count": 2,
            "observable_denominator": 1,
            "reentered_count": 1,
            "clean_not_reentered_count": 0,
            "quality_interrupted_count": 1,
            "insufficient_followup_censored_count": 0,
            "reentry_rate": 1.0,
        }
        for name in REQUEST_ORDER
        for metric, thresholds in (("raw", (1, 3, 5)), ("confirmed", (5, 10)))
        for threshold in thresholds
    ]
    parent_rows = [
        {
            "security_id": "S001",
            "q25_parent_interval_ordinal": 1,
            "q25_parent_confirmed_day_count": 4,
            "q20_confirmed_day_count_inside_parent": 3,
            "q25_only_shell_day_count": 1,
            "q20_fragmented_within_q25_parent": True,
        }
    ]
    child_rows = [
        {
            "security_id": "S001",
            "q20_interval_ordinal": 1,
            "q25_parent_interval_ordinal": 1,
            "q25_local_leading_shell_days": 1,
            "q25_local_trailing_shell_days": 0,
        }
    ]
    daily_rows = [
        {
            "security_id": "S001",
            "observation_sequence": index,
            "q25_parent_interval_ordinal": 1,
            "identity": identity,
        }
        for index, identity in enumerate(
            ("Q10_CORE", "Q15_NOT_Q10_CORE", "Q20_NOT_Q15_ANCHOR", "Q25_NOT_Q20_SHELL"),
            start=1,
        )
    ]
    mappings = [
        {
            "child_request_name": name,
            "child_security_id": "S001",
            "child_interval_ordinal": index,
        }
        for index, name in enumerate(("CA_q10_k5", "CA_q15_k5", "CA_q20_k5"), start=1)
    ]
    year_rows = [
        {"logical_request_name": name, "year": 2025, "interval_count": 4}
        for name in REQUEST_ORDER
    ] + [
        {"logical_request_name": name, "year": 2026, "interval_count": 4}
        for name in REQUEST_ORDER
    ]
    security_rows = [
        {"logical_request_name": name, "security_id": "S001", "interval_count": 4}
        for name in REQUEST_ORDER
    ] + [
        {"logical_request_name": name, "security_id": "S002", "interval_count": 4}
        for name in REQUEST_ORDER
    ]
    termination_reason_profile = []
    raw_false_exit_decomposition = []
    for name in REQUEST_ORDER:
        raw_false_exit_decomposition.extend(
            {
                "logical_request_name": name,
                "raw_false_subclass": subclass,
                "interval_count": 2,
            }
            for subclass in ("A_ONLY_FAIL", "C_ONLY_FAIL", "CA_BOTH_FAIL")
        )
        termination_reason_profile.extend(
            [
                {
                    "logical_request_name": name,
                    "primary_termination_reason": "raw_false",
                    "original_primary_termination_reason": "raw_false",
                    "interval_count": 6,
                },
                {
                    "logical_request_name": name,
                    "primary_termination_reason": "quality_or_availability_termination",
                    "original_primary_termination_reason": quality_reasons[name],
                    "interval_count": 1,
                },
                {
                    "logical_request_name": name,
                    "primary_termination_reason": "input_end_open_right_censored",
                    "original_primary_termination_reason": (
                        "input_end_open_right_censored"
                    ),
                    "interval_count": 1,
                },
            ]
        )
    candidate = {
        "request_reconciliation": reconciliation,
        "termination_records": termination_records,
        "threshold_margin_summary": margin_rows,
        "quick_reentry_profile": reentry_rows,
        "cross_q_structure_summary": parent_rows,
        "cross_q_child_structure_summary": child_rows,
        "daily_level_identities": daily_rows,
        "cross_q_mapping": mappings,
        "year_profile": year_rows,
        "security_profile": security_rows,
        "termination_reason_profile": termination_reason_profile,
        "raw_false_exit_decomposition": raw_false_exit_decomposition,
        "deterministic_interval_samples": [{"sample": "known"}],
    }
    with duckdb.connect(str(root / "t05_detail.duckdb")) as connection:
        connection.execute("CREATE TABLE candidate_json (payload JSON NOT NULL)")
        connection.execute(
            "INSERT INTO candidate_json VALUES (?)", [json.dumps(candidate)]
        )
    _write_json(
        root / "input_manifest.json",
        {
            "source_commit": "a" * 40,
            "reviewed_formal_execution_sha": "a" * 40,
        },
    )
    _write_json(
        root / "run_summary.json",
        {
            "status": "formal_completed_pending_owner_review",
            "request_summaries": expected,
            "reviewed_formal_execution_sha": "a" * 40,
            "authorization_head": "b" * 40,
            "authorization_parent": "a" * 40,
        },
    )
    _write_json(
        root / "formal_authorization.json",
        {
            "authorization_status": "authorized_pending_execution",
            "reviewed_formal_execution_sha": "a" * 40,
            "authorization_parent": "a" * 40,
            "authorization_head": "b" * 40,
            "authorized_manifest_sha256": sha256_file(root / "input_manifest.json"),
            "authorized_manifest_byte_size": (root / "input_manifest.json")
            .stat()
            .st_size,
        },
    )
    _write_json(root / "independent_validation_receipt.json", {"status": "passed"})
    _write_json(
        root / "formal_determinism_receipt.json",
        {
            "status": "passed",
            "build_count": 2,
            "left_fingerprint": "x",
            "right_fingerprint": "x",
        },
    )
    _write_json(
        root / "anomaly_scan.json", {"status": "pending", "blocking_anomalies": []}
    )
    (root / "execution_log.jsonl").write_text(
        json.dumps({"event": "formal_run_completed_pending_owner_review"}) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    csv_sources = {
        "request_reconciliation.csv": reconciliation,
        "termination_reason_profile.csv": termination_reason_profile,
        "raw_false_exit_decomposition.csv": raw_false_exit_decomposition,
        "threshold_margin_summary.csv": margin_rows,
        "quick_reentry_profile.csv": reentry_rows,
        "cross_q_structure_summary.csv": parent_rows,
        "cross_q_parent_structure_summary.csv": parent_rows,
        "cross_q_child_structure_summary.csv": child_rows,
        "year_profile.csv": year_rows,
        "security_profile.csv": security_rows,
        "deterministic_interval_samples.csv": [{"sample": "known"}],
    }
    for filename, rows in csv_sources.items():
        _write_csv_rows(compact / filename, rows)

    identities = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "artifact_manifest.json":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            identities.append(
                {
                    "relative_path": path.relative_to(root).as_posix(),
                    "sha256": digest,
                    "byte_size": path.stat().st_size,
                }
            )
    _write_json(root / "artifact_manifest.json", {"files": identities})
    return root


def test_persisted_result_analysis_reports_actual_values_and_blocks_mutations(
    tmp_path: Path,
) -> None:
    root = _make_persisted_analysis_fixture(tmp_path)
    expected = {
        name: {
            "raw_true": 10,
            "confirmed_true": 5,
            "intervals": 8,
            "securities_with_interval": 2,
        }
        for name in REQUEST_ORDER
    }
    analysis = analyze_persisted_formal_artifacts(root, expected_counts=expected)
    assert analysis["status"] == "passed_pending_owner_review"
    report = render_persisted_result_analysis(analysis)
    assert "10" in report
    assert "1.0" in report
    assert "0.1" in report
    assert "q25_only_shell_days" in report
    assert "2026_partial_year_boundary" in report
    quality_q20 = analysis["quality_availability_reasons"]["q20"]
    assert sum(row["quality_termination_count"] for row in quality_q20) == 1
    assert any(
        row["original_quality_reason"] == "selected_dimension_blocked"
        and row["quality_termination_count"] == 1
        for row in quality_q20
    )
    raw_q20 = analysis["raw_false_margin_decomposition"]["q20_subclass_summary"]
    assert [row["interval_count"] for row in raw_q20] == [2, 2, 2]
    assert "q20 raw-false subclass decomposition" in report
    assert "selected_dimension_blocked" in report

    _write_json(
        root / "anomaly_scan.json",
        {"status": "blocked", "blocking_anomalies": ["daily_identity_not_conserved"]},
    )
    blocked = analyze_persisted_formal_artifacts(root, expected_counts=expected)
    assert "daily_identity_not_conserved" in blocked["blocking_anomalies"]


@pytest.mark.parametrize(
    "mutation,expected_reason",
    [
        (
            "authorization_parent",
            "artifact_hash_readback_mismatch:formal_authorization.json",
        ),
        (
            "authorization_head",
            "artifact_hash_readback_mismatch:formal_authorization.json",
        ),
        (
            "authorization_manifest_hash",
            "artifact_hash_readback_mismatch:formal_authorization.json",
        ),
        ("execution_log", "artifact_hash_readback_mismatch:execution_log.jsonl"),
        ("input_manifest", "artifact_hash_readback_mismatch:input_manifest.json"),
    ],
)
def test_persisted_authorization_and_execution_evidence_mutations_block(
    tmp_path: Path, mutation: str, expected_reason: str
) -> None:
    root = _make_persisted_analysis_fixture(tmp_path)
    expected = {
        name: {
            "raw_true": 10,
            "confirmed_true": 5,
            "intervals": 8,
            "securities_with_interval": 2,
        }
        for name in REQUEST_ORDER
    }
    if mutation.startswith("authorization_"):
        authorization = json.loads(
            (root / "formal_authorization.json").read_text(encoding="utf-8")
        )
        if mutation == "authorization_parent":
            authorization["authorization_parent"] = "c" * 40
        elif mutation == "authorization_head":
            authorization["authorization_head"] = "d" * 40
        else:
            authorization["authorized_manifest_sha256"] = "e" * 64
        _write_json(root / "formal_authorization.json", authorization)
    elif mutation == "execution_log":
        with (root / "execution_log.jsonl").open(
            "a", encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(json.dumps({"event": "tampered_after_terminal"}) + "\n")
    else:
        manifest = json.loads(
            (root / "input_manifest.json").read_text(encoding="utf-8")
        )
        manifest["source_commit"] = "f" * 40
        _write_json(root / "input_manifest.json", manifest)

    analysis = analyze_persisted_formal_artifacts(root, expected_counts=expected)
    assert analysis["status"] == "blocked"
    assert expected_reason in analysis["blocking_anomalies"]
