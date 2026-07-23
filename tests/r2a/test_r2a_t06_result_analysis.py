from __future__ import annotations

import pytest

from src.r2a.r2a_t06_consecutive_failure_exit import build_exit_lifecycle
from src.r2a.r2a_t06_result_analysis import (
    T06AnalysisError,
    build_false_run_inventory,
    false_run_length_profile,
    recovery_hazard_profile,
    render_result_analysis_skeleton,
)
from tests.r2a.test_r2a_t06_consecutive_failure_exit import _row


def _inventory(rows, m: int = 1):
    result = build_exit_lifecycle(
        rows, logical_request_name="CA_q20_k5", exit_confirmation_m=m
    )
    return build_false_run_inventory(result["observation_rows"], result["trigger_rows"])


def test_preconfirmation_and_post_exit_false_are_not_triggers() -> None:
    rows = [
        _row(0, False, confirmed=False),
        _row(1, True, confirmed=True, interval=0),
        _row(2, False),
        _row(3, True, confirmed=False),
        _row(4, False, confirmed=False),
    ]
    inventory = _inventory(rows)
    assert len(inventory) == 1
    assert inventory[0]["trigger_observation_sequence"] == 2
    assert inventory[0]["false_run_length"] == 1


def test_legal_trigger_false_run_lengths_and_hazards() -> None:
    one = _inventory([_row(0, True), _row(1, False), _row(2, True, confirmed=False)])
    two = _inventory(
        [_row(0, True), _row(1, False), _row(2, False), _row(3, True, confirmed=False)]
    )
    inventory = one + two
    assert false_run_length_profile(inventory) == [
        {"trigger_exit_type": "A_ONLY_FAIL", "false_run_length": 1, "run_count": 1},
        {"trigger_exit_type": "A_ONLY_FAIL", "false_run_length": 2, "run_count": 1},
    ]
    assert recovery_hazard_profile(inventory) == [
        {
            "false_streak": 1,
            "observable_denominator": 2,
            "recovery_count": 1,
            "hazard": 0.5,
        },
        {
            "false_streak": 2,
            "observable_denominator": 1,
            "recovery_count": 1,
            "hazard": 1.0,
        },
        {
            "false_streak": 3,
            "observable_denominator": 0,
            "recovery_count": 0,
            "hazard": None,
        },
    ]


def test_quality_and_input_end_censoring() -> None:
    quality = _inventory(
        [
            _row(0, True),
            _row(1, False),
            _row(2, None, quality="selected_dimension_blocked"),
        ],
        m=3,
    )[0]
    censored = _inventory([_row(0, True), _row(1, False)], m=3)[0]
    assert quality["run_end_class"] == "QUALITY_INTERRUPTION"
    assert quality["quality_reason"] == "selected_dimension_blocked"
    assert quality["right_censored"] is False
    assert censored["run_end_class"] == "INPUT_END"
    assert censored["right_censored"] is True
    assert (
        recovery_hazard_profile([quality, censored])[0]["observable_denominator"] == 0
    )


def test_trigger_exit_type_is_not_overwritten_by_later_false() -> None:
    inventory = _inventory(
        [
            _row(0, True),
            _row(1, False, exit_type="A_ONLY_FAIL"),
            _row(2, False, exit_type="CA_BOTH_FAIL"),
            _row(3, True, confirmed=False),
        ],
        m=3,
    )
    assert inventory[0]["trigger_exit_type"] == "A_ONLY_FAIL"
    assert inventory[0]["false_run_length"] == 2


def test_sequence_gap_fails_closed() -> None:
    observations = [
        {
            "security_id": "S1",
            "observation_sequence": 0,
            "raw_state": False,
            "quality_reason": None,
        },
        {
            "security_id": "S1",
            "observation_sequence": 2,
            "raw_state": True,
            "quality_reason": None,
        },
    ]
    trigger = {
        "trigger_id": "T",
        "episode_identity": "E",
        "security_id": "S1",
        "logical_request_name": "CA_q20_k5",
        "exit_trigger_observation_sequence": 0,
        "exit_type": "A_ONLY_FAIL",
    }
    with pytest.raises(T06AnalysisError, match="observation_sequence_gap"):
        build_false_run_inventory(observations, [trigger])


def test_multiple_securities_are_independent() -> None:
    rows = [
        _row(0, True, security="S1"),
        _row(1, False, security="S1"),
        _row(0, True, security="S2"),
        _row(1, False, security="S2"),
        _row(2, False, security="S2"),
    ]
    inventory = _inventory(rows, m=3)
    assert [(row["security_id"], row["false_run_length"]) for row in inventory] == [
        ("S1", 1),
        ("S2", 2),
    ]


def test_analysis_skeleton_refuses_to_select_candidate() -> None:
    text = render_result_analysis_skeleton({"candidate_exit_summary": []})
    assert "no formal result exists" in text
    assert "No future price" in text
    assert "or M winner is part of this document" in text
