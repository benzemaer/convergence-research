from __future__ import annotations

import copy
from pathlib import Path

import pytest

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
        summarize=lambda target: counts[target.stem],
        expected_counts=counts,
    )
    assert tuple(order) == REQUEST_ORDER
    assert tuple(outputs) == REQUEST_ORDER
    assert tuple(receipts) == REQUEST_ORDER
    assert summaries == counts


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
            request_concurrency=2,
        )
    assert called is False


def test_count_mismatch_stops_before_later_q(tmp_path: Path) -> None:
    order: list[str] = []

    def evaluate(request, target):
        order.append(request["logical_request_name"])
        target.write_bytes(b"synthetic")

    with pytest.raises(FormalExecutionError, match="accepted_t04_t05_count_mismatch"):
        execute_request_sequence(
            requests=_requests(),
            output_dir=tmp_path / "outputs",
            evaluate=evaluate,
            validate=lambda _request, _target: {"status": "passed"},
            summarize=lambda _target: {
                "raw_true": 0,
                "confirmed_true": 0,
                "intervals": 0,
                "securities_with_interval": 0,
            },
            expected_counts=_counts(),
        )
    assert order == ["CA_q10_k5"]


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
        assert not score_path.exists()
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
        summarize_request=lambda target: counts[target.stem],
        load_facts=lambda _target, request: facts[request["logical_request_name"]],
    )
    run_root = Path(result["run_root"])
    assert run_root.is_dir()
    assert evaluated == list(REQUEST_ORDER)
    assert result["result_package"]["selected_exit_confirmation_m"] is None
    assert result["result_package"]["winner_selected"] is False
    assert not (run_root / "DONE").exists()
    assert not any(path.name.startswith(".") for path in run_root.parent.iterdir())
