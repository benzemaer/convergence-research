from __future__ import annotations

from src.r2a.r2a_t06_result_analysis import (
    false_run_length_profile,
    recovery_hazard_profile,
    render_result_analysis_skeleton,
)


def _row(sequence: int, raw_state: bool, security_id: str = "S1") -> dict[str, object]:
    return {
        "security_id": security_id,
        "observation_sequence": sequence,
        "raw_state": raw_state,
        "quality_reason": None,
        "exit_type": "A_ONLY_FAIL",
    }


def test_false_run_length_uses_observation_sequence_runs() -> None:
    rows = [
        _row(0, True),
        _row(1, False),
        _row(2, True),
        _row(3, False),
        _row(4, False),
    ]
    assert false_run_length_profile(rows) == [
        {"exit_type": "A_ONLY_FAIL", "false_run_length": 1, "run_count": 1},
        {"exit_type": "A_ONLY_FAIL", "false_run_length": 2, "run_count": 1},
    ]


def test_recovery_hazard_h1_h2_h3_has_observable_denominators() -> None:
    rows = [
        _row(0, True),
        _row(1, False),
        _row(2, True),
        _row(3, False),
        _row(4, False),
        _row(5, True),
    ]
    profile = recovery_hazard_profile(rows)
    assert profile[0] == {
        "false_streak": 1,
        "observable_denominator": 2,
        "recovery_count": 1,
        "hazard": 0.5,
    }
    assert profile[1]["hazard"] == 1.0
    assert profile[2]["hazard"] is None


def test_analysis_skeleton_refuses_to_select_candidate() -> None:
    text = render_result_analysis_skeleton({"candidate_exit_summary": []})
    assert "no formal result exists" in text
    assert "No future price" in text
    assert "or M winner is part of this document" in text
