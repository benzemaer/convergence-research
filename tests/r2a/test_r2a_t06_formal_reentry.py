from __future__ import annotations

from src.r2a.r2a_t06_result_package import (
    _post_recognition,
    _post_recognition_outcomes,
)


def _candidate(following: list[dict]) -> list[dict]:
    observations = [
        {
            "security_id": "S1",
            "observation_sequence": 0,
            "joint_ready": True,
            "raw_state": False,
            "confirmed_state_v1": False,
            "quality_reason": None,
        },
        *following,
    ]
    return [
        {
            "logical_request_name": "CA_q10_k5",
            "exit_confirmation_m": 1,
            "observation_rows": observations,
            "trigger_rows": [
                {
                    "trigger_id": "T1",
                    "episode_identity": "E1",
                    "security_id": "S1",
                    "disposition": "EXIT_RECOGNIZED",
                    "exit_recognition_observation_sequence": 0,
                }
            ],
        }
    ]


def _row(sequence: int, *, raw=False, confirmed=False, quality=None) -> dict:
    return {
        "security_id": "S1",
        "observation_sequence": sequence,
        "joint_ready": quality is None,
        "raw_state": raw if quality is None else None,
        "confirmed_state_v1": confirmed if quality is None else None,
        "quality_reason": quality,
    }


def _outcomes(following: list[dict]) -> dict[tuple[str, int], dict]:
    return {
        (row["metric"], row["horizon"]): row
        for row in _post_recognition_outcomes(_candidate(following))
    }


def test_three_followups_use_horizon_specific_censoring() -> None:
    rows = [_row(index) for index in range(1, 4)]
    outcomes = _outcomes(rows)
    assert outcomes[("raw_reentry", 1)]["outcome"] == "CLEAN_NOT_REENTERED"
    assert outcomes[("raw_reentry", 3)]["outcome"] == "CLEAN_NOT_REENTERED"
    for key in (
        ("raw_reentry", 5),
        ("confirmed_reentry", 5),
        ("confirmed_reentry", 10),
    ):
        assert outcomes[key]["outcome"] == "INPUT_END_CENSORED"


def test_quality_on_day_four_only_interrupts_longer_horizons() -> None:
    rows = [_row(index) for index in range(1, 4)] + [
        _row(4, quality="selected_dimension_unknown")
    ]
    outcomes = _outcomes(rows)
    assert outcomes[("raw_reentry", 1)]["outcome"] == "CLEAN_NOT_REENTERED"
    assert outcomes[("raw_reentry", 3)]["outcome"] == "CLEAN_NOT_REENTERED"
    for key in (
        ("raw_reentry", 5),
        ("confirmed_reentry", 5),
        ("confirmed_reentry", 10),
    ):
        assert outcomes[key]["outcome"] == "QUALITY_INTERRUPTED"


def test_reentry_before_later_quality_is_retained() -> None:
    rows = [
        _row(1),
        _row(2, raw=True),
        _row(3),
        _row(4, quality="selected_dimension_unknown"),
    ]
    assert _outcomes(rows)[("raw_reentry", 3)]["outcome"] == "REENTERED"


def test_confirmed_reentry_has_independent_five_and_ten_day_results() -> None:
    rows = [_row(index, confirmed=index == 6) for index in range(1, 11)]
    outcomes = _outcomes(rows)
    assert outcomes[("confirmed_reentry", 5)]["outcome"] == "CLEAN_NOT_REENTERED"
    assert outcomes[("confirmed_reentry", 10)]["outcome"] == "REENTERED"


def test_complete_ten_day_window_without_reentry_is_clean() -> None:
    outcomes = _outcomes([_row(index) for index in range(1, 11)])
    assert {row["outcome"] for row in outcomes.values()} == {"CLEAN_NOT_REENTERED"}


def test_reentry_after_quality_is_not_counted_and_denominators_are_independent() -> (
    None
):
    rows = [
        _row(1),
        _row(2, quality="selected_dimension_unknown"),
        _row(3, raw=True, confirmed=True),
    ]
    outcomes = _outcomes(rows)
    assert outcomes[("raw_reentry", 3)]["outcome"] == "QUALITY_INTERRUPTED"
    compact = _post_recognition(_candidate(rows))[0]
    assert compact["raw_reentry_1_clean_denominator"] == 1
    assert compact["raw_reentry_3_clean_denominator"] == 0
    assert compact["raw_reentry_3_quality_interrupted_count"] == 1
