from __future__ import annotations

import copy

import pytest

from src.r2a.r2a_t06_consecutive_failure_exit import (
    REQUEST_ORDER,
    build_t06_candidate,
)
from src.r2a.r2a_t06_validator import T06ValidationError, validate_t06_candidate
from tests.r2a.test_r2a_t06_consecutive_failure_exit import _panel, _row


def test_independent_validator_recalculates_every_candidate() -> None:
    source = _panel([_row(0, True), _row(1, False), _row(2, True, interval=1)])
    candidate = build_t06_candidate(source)
    receipt = validate_t06_candidate(source, candidate)
    assert receipt["status"] == "passed"
    assert receipt["independent_recalculation"] is True
    assert receipt["mismatch_count"] == 0


def test_validator_rejects_builder_self_report_and_daily_fact_mutation() -> None:
    source = _panel([_row(0, True), _row(1, False), _row(2, True, interval=1)])
    candidate = build_t06_candidate(source)
    mutated = copy.deepcopy(candidate)
    mutated["candidates"][0]["observation_rows"][0]["raw_state"] = False
    mutated["candidate_exit_summary"][0]["recognized_exit_count"] = 999
    with pytest.raises(T06ValidationError) as error:
        validate_t06_candidate(source, mutated)
    assert "independent_recalculation_mismatch" in str(error.value)
    assert "accepted_daily_fact_modified" in str(error.value)
    assert "candidate_summary_reconciliation_mismatch" in str(error.value)


def test_m1_reproduces_each_accepted_v1_valid_raw_false_exit() -> None:
    source = _panel(
        [
            _row(0, True, interval=0),
            _row(1, False),
            _row(2, True, interval=1),
            _row(3, False, exit_type="C_ONLY_FAIL"),
        ]
    )
    candidate = build_t06_candidate(source)
    for name in REQUEST_ORDER:
        m1 = next(
            item
            for item in candidate["candidates"]
            if item["logical_request_name"] == name and item["exit_confirmation_m"] == 1
        )
        assert len(m1["trigger_rows"]) == 2
        assert all(
            row["disposition"] == "EXIT_RECOGNIZED" for row in m1["trigger_rows"]
        )


def test_input_and_config_produce_identical_results_under_worker_labels() -> None:
    source = _panel([_row(0, True), _row(1, False), _row(2, False)])
    worker_1 = build_t06_candidate(source, worker_count=1)
    worker_4 = build_t06_candidate(copy.deepcopy(source), worker_count=4)
    assert worker_1 == worker_4
