from __future__ import annotations

import copy
import inspect

import pytest

import src.r2a.r2a_t06_consecutive_failure_exit as production
import src.r2a.r2a_t06_validator as validator_module
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


def test_validator_does_not_import_production_private_semantics() -> None:
    source = inspect.getsource(validator_module)
    assert "_normalize_rows," not in source
    assert "_exit_type," not in source
    assert "_stable_id," not in source


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


def test_validator_rejects_fault_injected_production_exit_type(monkeypatch) -> None:
    source = _panel([_row(0, True), _row(1, False, exit_type="A_ONLY_FAIL")])
    monkeypatch.setattr(production, "_exit_type", lambda row: "C_ONLY_FAIL")
    candidate = production.build_t06_candidate(source)
    with pytest.raises(T06ValidationError, match="independent_recalculation_mismatch"):
        validate_t06_candidate(source, candidate)


def test_validator_rejects_fault_injected_production_quality(monkeypatch) -> None:
    source = _panel(
        [
            _row(0, True),
            _row(1, False),
            _row(2, None, quality="selected_dimension_blocked"),
        ]
    )
    for rows in source.values():
        rows[2]["raw_state"] = False
        rows[2]["confirmed_state_v1"] = False
        rows[2]["dimension_active"] = {"C": True, "A": False}
    monkeypatch.setattr(production, "_quality_reason", lambda row: None)
    candidate = production.build_t06_candidate(source)
    with pytest.raises(T06ValidationError, match="independent_recalculation_mismatch"):
        validate_t06_candidate(source, candidate)


def test_validator_rejects_fault_injected_production_identity(monkeypatch) -> None:
    source = _panel([_row(0, True), _row(1, False)])
    monkeypatch.setattr(production, "_stable_id", lambda *parts: "bad-identity")
    candidate = production.build_t06_candidate(source)
    with pytest.raises(T06ValidationError, match="independent_recalculation_mismatch"):
        validate_t06_candidate(source, candidate)


def test_validator_rejects_observation_sorting_corruption() -> None:
    source = _panel([_row(0, True), _row(1, False), _row(2, True, interval=1)])
    candidate = build_t06_candidate(source)
    corrupted = copy.deepcopy(candidate)
    corrupted["candidates"][0]["observation_rows"].reverse()
    with pytest.raises(T06ValidationError, match="independent_recalculation_mismatch"):
        validate_t06_candidate(source, corrupted)


def _candidate_result(candidate, name: str, m: int):
    return next(
        row
        for row in candidate["candidates"]
        if row["logical_request_name"] == name and row["exit_confirmation_m"] == m
    )


def test_candidate_lifecycle_cross_q_passes_for_every_m_and_security() -> None:
    rows = [
        _row(0, True, security="S1"),
        _row(1, False, security="S1"),
        _row(0, True, security="S2"),
        _row(1, False, security="S2"),
        _row(2, True, security="S2", interval=1),
    ]
    source = _panel(rows)
    candidate = build_t06_candidate(source)
    receipt = validate_t06_candidate(source, candidate)
    assert receipt["cross_q_nesting"] == "passed"
    assert len(candidate["cross_q_nesting_validation"]) == 9
    assert {
        row["exit_confirmation_m"] for row in candidate["cross_q_nesting_validation"]
    } == {1, 2, 3}


def test_validator_rejects_lifecycle_membership_without_raw_mutation() -> None:
    source = _panel([_row(0, True), _row(1, False), _row(2, True, interval=1)])
    candidate = build_t06_candidate(source)
    corrupted = copy.deepcopy(candidate)
    parent = _candidate_result(corrupted, "CA_q15_k5", 2)
    parent["observation_rows"][0]["lifecycle_state"] = "INACTIVE"
    with pytest.raises(T06ValidationError, match="cross_q_nesting_violation"):
        validate_t06_candidate(source, corrupted)


def test_validator_rejects_unmapped_stricter_episode() -> None:
    source = _panel([_row(0, True), _row(1, True), _row(2, False)])
    candidate = build_t06_candidate(source)
    corrupted = copy.deepcopy(candidate)
    _candidate_result(corrupted, "CA_q15_k5", 2)["episode_rows"] = []
    with pytest.raises(T06ValidationError, match="cross_q_nesting_violation"):
        validate_t06_candidate(source, corrupted)


def test_validator_rejects_child_episode_spanning_two_parents() -> None:
    source = _panel([_row(0, True), _row(1, True), _row(2, True), _row(3, False)])
    candidate = build_t06_candidate(source)
    corrupted = copy.deepcopy(candidate)
    parent = _candidate_result(corrupted, "CA_q15_k5", 2)
    original = parent["episode_rows"][0]
    left = copy.deepcopy(original)
    right = copy.deepcopy(original)
    left["end_observation_sequence"] = 1
    right["start_observation_sequence"] = 2
    right["episode_ordinal"] = 1
    right["episode_id"] = "split-parent"
    parent["episode_rows"] = [left, right]
    with pytest.raises(T06ValidationError, match="cross_q_nesting_violation"):
        validate_t06_candidate(source, corrupted)


def test_validator_rejects_multiple_parent_mapping() -> None:
    source = _panel([_row(0, True), _row(1, True), _row(2, False)])
    candidate = build_t06_candidate(source)
    corrupted = copy.deepcopy(candidate)
    parent = _candidate_result(corrupted, "CA_q15_k5", 3)
    duplicate = copy.deepcopy(parent["episode_rows"][0])
    duplicate["episode_ordinal"] = 1
    duplicate["episode_id"] = "duplicate-parent"
    parent["episode_rows"].append(duplicate)
    with pytest.raises(T06ValidationError, match="cross_q_nesting_violation"):
        validate_t06_candidate(source, corrupted)
