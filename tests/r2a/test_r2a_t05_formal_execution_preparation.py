"""Preparation-only tests for the R2A-T05 formal execution entry."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from src.r2a.r2a_t02_request_identity import build_canonical_request
from src.r2a.r2a_t05_formal_execution import (
    FormalExecutionError,
    create_unique_run_root,
    execute_request_sequence,
    finalize_formal_candidate,
    inspect_git_preflight,
    preflight_formal_execution,
    validate_formal_completion_lifecycle,
)
from src.r2a.r2a_t05_formal_input_manifest import (
    FormalInputManifestError,
    build_formal_input_manifest,
    load_authorized_input_manifest,
    load_formal_execution_config,
    sha256_file,
)

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
        connection.execute("CREATE TABLE dimension_definitions (definition_id INTEGER)")
        connection.execute("CREATE TABLE dimension_components (component_id INTEGER)")
        connection.execute("CREATE TABLE daily_component_scores (score DOUBLE)")
        if forbidden_field:
            connection.execute("CREATE TABLE daily_dimension_scores (return_1d DOUBLE)")
        else:
            connection.execute(
                "CREATE TABLE daily_dimension_scores (score_dimension DOUBLE)"
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


def _build_manifest(
    tmp_path: Path, **kwargs: Any
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    config, score_path, output_path = _make_authorized_inputs(tmp_path, **kwargs)
    payload = build_formal_input_manifest(
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
    verified = load_authorized_input_manifest(
        output_path, repo_root=tmp_path, verify_files=True
    )
    assert verified["requests"] == payload["requests"]
    assert config["formal_run_attempts_consumed"] == 0


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
        build_formal_input_manifest(
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
        build_formal_input_manifest(
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
        build_formal_input_manifest(
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
    payload["source_commit"] = "b" * 40
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
        verify_manifest_files=False,
    )
    assert result["status"] == "preflight_passed"
    assert result["real_score_data_read"] is False
    assert result["formal_artifacts_generated"] is False
    assert result["formal_run_attempts_consumed"] == 0
    assert not score_opened
    assert not (tmp_path / "data/generated/r2a/r2a_t05/formal-runs").exists()


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"manifest": False, "runroot": False}
    config = load_formal_execution_config()
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
            manifest_path=Path("unused.json"), operator_authorized=True
        )
    assert called == {"manifest": False, "runroot": False}
    assert config["formal_run_attempts_consumed"] == 0
