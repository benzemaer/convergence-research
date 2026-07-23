from __future__ import annotations

import copy
from pathlib import Path

import pytest

import src.r2a.r2a_t06_formal_execution as formal_execution_module
from src.r2a.r2a_t06_consecutive_failure_exit import REQUEST_ORDER
from src.r2a.r2a_t06_formal_execution import (
    FormalExecutionError,
    build_and_validate_lifecycle,
    execute_request_sequence,
    run_formal,
    run_formal_execution,
)
from src.r2a.r2a_t06_formal_input_manifest import load_formal_execution_config
from tests.r2a.test_r2a_t06_consecutive_failure_exit import _row
from tests.r2a.test_r2a_t06_formal_authorization_gate import _authorized


def _requests():
    return copy.deepcopy(load_formal_execution_config()["requests"])


def _counts():
    return copy.deepcopy(load_formal_execution_config()["accepted_counts"])


def _receipt(request, counts=None):
    config = load_formal_execution_config()
    values = dict(counts or config["accepted_counts"][request["logical_request_name"]])
    spine = config["accepted_coverage"]["spine_row_count"]
    return {
        "request_id": request["request_id"],
        "request_hash": request["request_hash"],
        "score_release_id": config["score_release"]["score_release_id"],
        "evaluator_version": config["evaluator_identity"]["evaluator_version"],
        "output_schema_version": config["evaluator_identity"]["output_schema_version"],
        "evaluated_security_count": config["score_release"]["security_count"],
        "date_min": config["score_release"]["date_min"],
        "date_max": config["score_release"]["date_max"],
        "spine_row_count": spine,
        "daily_joint_state_count": spine,
        "daily_dimension_state_count": spine * 2,
        "confirmed_interval_count": values["intervals"],
        **values,
    }


def _source():
    rows = [
        _row(0, True),
        _row(1, True),
        _row(2, False),
        _row(3, True, interval=1),
        _row(4, False),
        _row(5, False),
        _row(6, True, interval=2),
        _row(7, False),
        _row(8, False),
        _row(9, False),
    ]
    return {
        name: [{**copy.deepcopy(row), "logical_request_name": name} for row in rows]
        for name in REQUEST_ORDER
    }


def test_execution_plan_is_frozen() -> None:
    plan = load_formal_execution_config()["execution_plan"]
    assert plan == {
        "request_order": list(REQUEST_ORDER),
        "request_concurrency": 1,
        "evaluation_count_per_request": 1,
        "m_candidate_order": [1, 2, 3],
        "canonical_worker_count": 1,
        "parallel_check_worker_count": 4,
        "determinism_build_count": 2,
        "reuse_daily_facts_across_m": True,
    }


def test_four_q_runs_in_fixed_order_exactly_once(tmp_path: Path) -> None:
    order: list[str] = []
    counts = _counts()

    def evaluate(request, target):
        order.append(request["logical_request_name"])
        target.write_bytes(b"synthetic")

    outputs, receipts, summaries = execute_request_sequence(
        requests=_requests(),
        output_dir=tmp_path / "outputs",
        evaluate=evaluate,
        validate=lambda request, _target: {
            "status": "passed",
            "request_id": request["request_id"],
        },
        summarize=lambda target: _receipt(
            next(
                request
                for request in _requests()
                if request["logical_request_name"] == target.stem
            ),
            counts[target.stem],
        ),
        expected_counts=counts,
        score_release=load_formal_execution_config()["score_release"],
        evaluator_identity=load_formal_execution_config()["evaluator_identity"],
        expected_spine_row_count=load_formal_execution_config()["accepted_coverage"][
            "spine_row_count"
        ],
    )
    assert tuple(order) == REQUEST_ORDER
    assert tuple(outputs) == REQUEST_ORDER
    assert tuple(receipts) == REQUEST_ORDER
    assert {
        name: {
            key: receipt[key]
            for key in (
                "raw_true",
                "confirmed_true",
                "intervals",
                "securities_with_interval",
            )
        }
        for name, receipt in summaries.items()
    } == counts


def test_q_level_concurrency_is_rejected_before_evaluation(tmp_path: Path) -> None:
    called = False

    def evaluate(_request, _target):
        nonlocal called
        called = True

    with pytest.raises(FormalExecutionError, match="q_level_concurrency_rejected"):
        execute_request_sequence(
            requests=_requests(),
            output_dir=tmp_path / "outputs",
            evaluate=evaluate,
            validate=lambda _request, _target: {"status": "passed"},
            summarize=lambda _target: {},
            expected_counts=_counts(),
            score_release=load_formal_execution_config()["score_release"],
            evaluator_identity=load_formal_execution_config()["evaluator_identity"],
            expected_spine_row_count=load_formal_execution_config()[
                "accepted_coverage"
            ]["spine_row_count"],
            request_concurrency=2,
        )
    assert called is False


def test_count_mismatch_stops_before_later_q(tmp_path: Path) -> None:
    order: list[str] = []

    def evaluate(request, target):
        order.append(request["logical_request_name"])
        target.write_bytes(b"synthetic")

    with pytest.raises(FormalExecutionError, match="confirmed_interval_count_mismatch"):
        execute_request_sequence(
            requests=_requests(),
            output_dir=tmp_path / "outputs",
            evaluate=evaluate,
            validate=lambda _request, _target: {"status": "passed"},
            summarize=lambda _target: _receipt(
                _requests()[0],
                {
                    "raw_true": 0,
                    "confirmed_true": 0,
                    "intervals": 0,
                    "securities_with_interval": 0,
                },
            ),
            expected_counts=_counts(),
            score_release=load_formal_execution_config()["score_release"],
            evaluator_identity=load_formal_execution_config()["evaluator_identity"],
            expected_spine_row_count=load_formal_execution_config()[
                "accepted_coverage"
            ]["spine_row_count"],
        )
    assert order == ["CA_q10_k5"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("request_id", "pcavt-dynreq-v1-0000000000000000", "request_id_mismatch"),
        ("request_hash", "0" * 64, "request_hash_mismatch"),
        ("score_release_id", "wrong-release", "score_release_id_mismatch"),
        ("evaluated_security_count", 799, "evaluated_security_count_mismatch"),
        ("date_min", "2016-01-05", "date_min_mismatch"),
        ("date_max", "2026-06-29", "date_max_mismatch"),
        ("spine_row_count", 1751065, "spine_row_count_mismatch"),
        ("daily_joint_state_count", 1751065, "daily_joint_state_count_mismatch"),
        (
            "daily_dimension_state_count",
            3502131,
            "daily_dimension_state_count_mismatch",
        ),
        ("confirmed_interval_count", 750, "confirmed_interval_count_mismatch"),
    ),
)
def test_request_coverage_mutation_stops_all_downstream_work(
    tmp_path: Path, field: str, value, reason: str
) -> None:
    authorization, manifest, config, git_state = _authorized(tmp_path)
    evaluated: list[str] = []
    lifecycle_called = False

    def evaluate(request, target, _score_path):
        evaluated.append(request["logical_request_name"])
        target.write_bytes(b"synthetic")

    def summarize(target):
        request = next(
            item
            for item in config["requests"]
            if item["logical_request_name"] == target.stem
        )
        receipt = _receipt(request, config["accepted_counts"][target.stem])
        receipt[field] = value
        return receipt

    def lifecycle(_source):
        nonlocal lifecycle_called
        lifecycle_called = True
        raise AssertionError("lifecycle must not run")

    with pytest.raises(FormalExecutionError, match=reason):
        run_formal_execution(
            authorization=authorization,
            manifest_bytes=manifest,
            config=config,
            repo_root=tmp_path,
            git_state=git_state,
            evaluate_request=evaluate,
            validate_request=lambda _request, _target: {"status": "passed"},
            summarize_request=summarize,
            load_facts=lambda _target, _request: [],
            build_lifecycle=lifecycle,
        )
    assert evaluated == ["CA_q10_k5"]
    assert lifecycle_called is False
    assert not (tmp_path / authorization["run_root_relative_path"]).exists()


def test_stage1_failure_preserves_attempt_and_blocks_retry(tmp_path: Path) -> None:
    authorization, manifest, config, git_state = _authorized(tmp_path)
    evaluations = 0

    def fail_stage1(_request, _target, _score_path):
        nonlocal evaluations
        evaluations += 1
        raise FormalExecutionError("synthetic_stage1_failure")

    with pytest.raises(FormalExecutionError, match="synthetic_stage1_failure"):
        run_formal_execution(
            authorization=authorization,
            manifest_bytes=manifest,
            config=config,
            repo_root=tmp_path,
            git_state=git_state,
            evaluate_request=fail_stage1,
        )
    run_root = tmp_path / authorization["run_root_relative_path"]
    marker = run_root.with_name(run_root.name + ".attempt-consumed.json")
    assert marker.is_file()
    assert list(run_root.parent.glob(f".{run_root.name}.staging-*.failed"))
    with pytest.raises(FormalExecutionError, match="formal_attempt_already_consumed"):
        run_formal_execution(
            authorization=authorization,
            manifest_bytes=manifest,
            config=config,
            repo_root=tmp_path,
            git_state=git_state,
            evaluate_request=fail_stage1,
        )
    assert evaluations == 1


def test_lifecycle_build_validates_online_parallel_determinism_and_m1() -> None:
    candidate, validation, determinism = build_and_validate_lifecycle(_source())
    assert len(candidate["candidates"]) == 12
    assert candidate["selected_exit_confirmation_m"] is None
    assert candidate["winner_selected"] is False
    assert validation["m1_baseline_exact_reproduction"] is True
    assert validation["online_replay_equivalence"] is True
    assert validation["parallel_consistency"] is True
    assert determinism["canonical_builds"]["status"] == "passed"
    assert determinism["worker_1_vs_4"]["status"] == "passed"


def test_formal_entry_is_disabled_without_reading_manifest_or_score() -> None:
    with pytest.raises(
        FormalExecutionError, match="owner_formal_authorization_missing"
    ):
        run_formal(None, manifest_bytes=b"not-json")


def test_synthetic_full_runner_publishes_atomically_and_keeps_m_null(
    tmp_path: Path,
) -> None:
    authorization, manifest, config, git_state = _authorized(tmp_path)
    counts = config["accepted_counts"]
    facts = _source()
    evaluated: list[str] = []

    def evaluate(request, target, score_path):
        assert score_path.name == "score_data.duckdb"
        assert score_path.exists()
        evaluated.append(request["logical_request_name"])
        target.write_bytes(b"synthetic")

    result = run_formal_execution(
        authorization=authorization,
        manifest_bytes=manifest,
        config=config,
        repo_root=tmp_path,
        git_state=git_state,
        evaluate_request=evaluate,
        validate_request=lambda request, _target: {
            "status": "passed",
            "request_id": request["request_id"],
            "request_hash": request["request_hash"],
        },
        summarize_request=lambda target: _receipt(
            next(
                request
                for request in config["requests"]
                if request["logical_request_name"] == target.stem
            ),
            counts[target.stem],
        ),
        load_facts=lambda _target, request: facts[request["logical_request_name"]],
    )
    run_root = Path(result["run_root"])
    assert run_root.is_dir()
    assert evaluated == list(REQUEST_ORDER)
    assert result["result_package"]["selected_exit_confirmation_m"] is None
    assert result["result_package"]["winner_selected"] is False
    assert not (run_root / "DONE").exists()
    assert not any(path.name.startswith(".") for path in run_root.parent.iterdir())
    assert result["publication_receipt"]["status"] == "passed"
    assert result["post_publish_receipt"]["status"] == "passed"


def test_manifest_verification_failure_prevents_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization, manifest, config, git_state = _authorized(tmp_path)
    facts = _source()

    def reject_manifest(_root):
        raise formal_execution_module.ResultPackageError(
            "artifact_manifest_sha256_mismatch"
        )

    monkeypatch.setattr(
        formal_execution_module, "verify_artifact_manifest", reject_manifest
    )
    with pytest.raises(FormalExecutionError, match="artifact_manifest_sha256_mismatch"):
        run_formal_execution(
            authorization=authorization,
            manifest_bytes=manifest,
            config=config,
            repo_root=tmp_path,
            git_state=git_state,
            evaluate_request=lambda _request, target, _score: target.write_bytes(
                b"synthetic"
            ),
            validate_request=lambda request, _target: {
                "status": "passed",
                "request_id": request["request_id"],
                "request_hash": request["request_hash"],
            },
            summarize_request=lambda target: _receipt(
                next(
                    request
                    for request in config["requests"]
                    if request["logical_request_name"] == target.stem
                ),
                config["accepted_counts"][target.stem],
            ),
            load_facts=lambda _target, request: facts[request["logical_request_name"]],
        )
    final_root = tmp_path / authorization["run_root_relative_path"]
    assert not final_root.exists()
    assert list(final_root.parent.glob(f".{final_root.name}.staging-*.failed"))
