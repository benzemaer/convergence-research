from __future__ import annotations

import copy
import itertools
from typing import Any

import pytest

from src.r2a.r2a_t06_consecutive_failure_exit import (
    REQUEST_ORDER,
    T06Error,
    build_exit_lifecycle,
    build_t06_candidate,
    candidate_to_json,
)


def _row(
    sequence: int,
    raw: bool | None,
    *,
    security: str = "S1",
    confirmed: bool | None = None,
    interval: int | None = 0,
    quality: str | None = None,
    exit_type: str = "A_ONLY_FAIL",
    day: int | None = None,
) -> dict[str, Any]:
    status = "present"
    validity = "valid"
    ready = True
    reasons: list[str] = []
    if quality == "expected_observation_missing":
        status, ready = "missing", False
    elif quality == "expected_observation_listing_pause":
        status, ready = "listing_pause", False
    elif quality == "selected_dimension_blocked":
        validity, ready = "blocked", False
    elif quality == "selected_dimension_diagnostic_required":
        validity, ready = "diagnostic_required", False
    elif quality == "selected_dimension_unknown":
        validity, ready = "unknown", False
    elif quality == "selected_dimension_not_eligible":
        ready, reasons = False, ["C:dimension_not_eligible"]
    elif quality == "selected_dimension_score_non_finite":
        ready, reasons = False, ["A:score_non_finite"]
    if quality:
        raw = None
        confirmed = None
        interval = None
    if confirmed is None and quality is None:
        confirmed = bool(raw)
    if confirmed is not True:
        interval = None
    active = {"C": True, "A": True}
    if raw is False:
        active = {
            "A_ONLY_FAIL": {"C": True, "A": False},
            "C_ONLY_FAIL": {"C": False, "A": True},
            "CA_BOTH_FAIL": {"C": False, "A": False},
        }[exit_type]
    return {
        "security_id": security,
        "trading_date": f"2026-01-{(day if day is not None else sequence + 1):02d}",
        "observation_sequence": sequence,
        "expected_observation_status": status,
        "joint_validity_status": validity,
        "joint_ready": ready,
        "joint_reason_codes": reasons,
        "raw_state": raw,
        "confirmed_state_v1": confirmed,
        "confirmed_interval_ordinal": interval,
        "dimension_active": active,
    }


def _path(
    values: list[bool | None], *, quality_at: int | None = None
) -> list[dict[str, Any]]:
    rows = []
    for sequence, value in enumerate(values):
        quality = "selected_dimension_blocked" if sequence == quality_at else None
        rows.append(_row(sequence, value, quality=quality))
    return rows


@pytest.mark.parametrize(
    ("values", "expected"),
    (
        (
            [True, True, False, True],
            {1: "EXIT_RECOGNIZED", 2: "CANCELLED", 3: "CANCELLED"},
        ),
        (
            [True, True, False, False, True],
            {1: "EXIT_RECOGNIZED", 2: "EXIT_RECOGNIZED", 3: "CANCELLED"},
        ),
        (
            [True, True, False, False, False],
            {1: "EXIT_RECOGNIZED", 2: "EXIT_RECOGNIZED", 3: "EXIT_RECOGNIZED"},
        ),
        (
            [True, True, False, False, False, False],
            {1: "EXIT_RECOGNIZED", 2: "EXIT_RECOGNIZED", 3: "EXIT_RECOGNIZED"},
        ),
    ),
)
def test_fixed_false_run_paths(values, expected) -> None:
    for m in (1, 2, 3):
        result = build_exit_lifecycle(
            _path(values), logical_request_name="CA_q20_k5", exit_confirmation_m=m
        )
        assert result["trigger_rows"][0]["disposition"] == expected[m]
        recognized = [
            row
            for row in result["trigger_rows"]
            if row["disposition"] == "EXIT_RECOGNIZED"
        ]
        if recognized:
            assert recognized[0]["recognition_lag"] == m - 1


@pytest.mark.parametrize("m", (1, 2, 3))
@pytest.mark.parametrize("false_count", (1, 2))
def test_quality_interruption_is_immediate_for_every_m(
    m: int, false_count: int
) -> None:
    values = [True, True] + [False] * false_count + [None]
    result = build_exit_lifecycle(
        _path(values, quality_at=len(values) - 1),
        logical_request_name="CA_q20_k5",
        exit_confirmation_m=m,
    )
    quality_rows = [
        row
        for row in result["observation_rows"]
        if row["lifecycle_state"] == "QUALITY_TERMINATED"
    ]
    if false_count < m:
        assert len(quality_rows) == 1
        assert quality_rows[0]["observation_sequence"] == len(values) - 1
    else:
        assert not quality_rows


@pytest.mark.parametrize("m", (1, 2, 3))
@pytest.mark.parametrize("false_count", (1, 2))
def test_pending_input_end_is_right_censored(m: int, false_count: int) -> None:
    result = build_exit_lifecycle(
        _path([True, True] + [False] * false_count),
        logical_request_name="CA_q20_k5",
        exit_confirmation_m=m,
    )
    pending = false_count < m
    assert any(row["right_censored"] for row in result["observation_rows"]) is pending
    if pending:
        assert result["trigger_rows"][0]["disposition"] == "PENDING_RIGHT_CENSORED"


def test_false_before_confirmed_active_is_not_an_exit() -> None:
    rows = [
        _row(0, False, confirmed=False),
        _row(1, True, confirmed=True),
        _row(2, False),
    ]
    result = build_exit_lifecycle(
        rows, logical_request_name="CA_q20_k5", exit_confirmation_m=1
    )
    assert len(result["trigger_rows"]) == 1
    assert result["trigger_rows"][0]["exit_trigger_observation_sequence"] == 2


def test_security_isolation_calendar_gaps_and_episode_ordinals() -> None:
    rows = [
        _row(0, True, security="S2", day=1),
        _row(1, False, security="S2", day=20),
        _row(0, True, security="S1", day=2),
        _row(1, False, security="S1", day=28),
        _row(2, True, security="S1", interval=1, day=29),
        _row(3, False, security="S1", day=30),
    ]
    result = build_exit_lifecycle(
        rows, logical_request_name="CA_q20_k5", exit_confirmation_m=1
    )
    s1 = [row for row in result["episode_rows"] if row["security_id"] == "S1"]
    assert [row["episode_ordinal"] for row in s1] == [0, 1]
    assert len(result["episode_rows"]) == 3


@pytest.mark.parametrize(
    "quality",
    (
        "expected_observation_missing",
        "expected_observation_listing_pause",
        "selected_dimension_blocked",
        "selected_dimension_diagnostic_required",
        "selected_dimension_unknown",
        "selected_dimension_not_eligible",
        "selected_dimension_score_non_finite",
    ),
)
def test_all_quality_classes_terminate_active_episode(quality: str) -> None:
    rows = [_row(0, True), _row(1, None, quality=quality)]
    result = build_exit_lifecycle(
        rows, logical_request_name="CA_q20_k5", exit_confirmation_m=3
    )
    assert result["episode_rows"][0]["termination_class"] == "QUALITY_TERMINATED"
    assert result["episode_rows"][0]["quality_reason"] == quality


@pytest.mark.parametrize("exit_type", ("A_ONLY_FAIL", "C_ONLY_FAIL", "CA_BOTH_FAIL"))
def test_exit_type_is_derived_from_dimension_facts(exit_type: str) -> None:
    result = build_exit_lifecycle(
        [_row(0, True), _row(1, False, exit_type=exit_type)],
        logical_request_name="CA_q20_k5",
        exit_confirmation_m=1,
    )
    assert result["trigger_rows"][0]["exit_type"] == exit_type


def test_sequence_gap_is_not_silently_skipped() -> None:
    with pytest.raises(T06Error, match="observation_sequence_gap"):
        build_exit_lifecycle(
            [_row(0, True), _row(2, False)],
            logical_request_name="CA_q20_k5",
            exit_confirmation_m=2,
        )


def test_forbidden_future_field_fails_closed() -> None:
    rows = [_row(0, True)]
    rows[0]["future_return"] = 0.10
    with pytest.raises(T06Error, match="forbidden_future_or_trading_field"):
        build_exit_lifecycle(
            rows, logical_request_name="CA_q20_k5", exit_confirmation_m=1
        )


def _panel(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {name: copy.deepcopy(rows) for name in REQUEST_ORDER}


def test_cross_q_panel_and_deterministic_ordering() -> None:
    rows = [_row(0, True), _row(1, False), _row(2, True, interval=1)]
    first = build_t06_candidate(_panel(rows))
    shuffled = _panel(list(reversed(rows)))
    second = build_t06_candidate(shuffled)
    assert candidate_to_json(first) == candidate_to_json(second)
    assert all(
        row["overall_status"] == "passed" for row in first["cross_q_nesting_validation"]
    )


def test_cross_q_raw_nesting_violation_fails_closed() -> None:
    panel = _panel([_row(0, True), _row(1, False)])
    panel["CA_q15_k5"][1] = _row(1, True)
    with pytest.raises(T06Error, match="cross_q_nesting_violation"):
        build_t06_candidate(panel)


def test_property_sets_and_accepted_facts_over_binary_paths() -> None:
    for tail in itertools.product((False, True), repeat=4):
        rows = _path([True, *tail])
        results = {
            m: build_exit_lifecycle(
                rows, logical_request_name="CA_q20_k5", exit_confirmation_m=m
            )
            for m in (1, 2, 3)
        }
        for m, result in results.items():
            assert [row["raw_state"] for row in result["observation_rows"]] == [
                row["raw_state"] for row in rows
            ]
            assert [
                row["confirmed_state_v1"] for row in result["observation_rows"]
            ] == [row["confirmed_state_v1"] for row in rows]
            assert all(
                trigger["recognition_lag"] == m - 1
                for trigger in result["trigger_rows"]
                if trigger["disposition"] == "EXIT_RECOGNIZED"
            )
        recognized = {
            m: {
                row["episode_identity"]
                for row in results[m]["trigger_rows"]
                if row["disposition"] == "EXIT_RECOGNIZED"
            }
            for m in (1, 2, 3)
        }
        assert recognized[3] <= recognized[2] <= recognized[1]
        cancelled_2 = {
            row["episode_identity"]
            for row in results[2]["trigger_rows"]
            if row["disposition"] == "CANCELLED"
        }
        cancelled_3 = {
            row["episode_identity"]
            for row in results[3]["trigger_rows"]
            if row["disposition"] == "CANCELLED"
        }
        assert cancelled_2 <= cancelled_3
