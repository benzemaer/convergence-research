from __future__ import annotations

import random

import pytest

from src.r2a.score_engine import (
    A_COMPONENTS,
    ScoreContractError,
    compute_a_dimension_scores,
    compute_component_scores,
)


def _rows(count: int, indicator_id: str = A_COMPONENTS[0]) -> list[dict[str, object]]:
    return [
        {
            "security_id": "000001.SZ",
            "trading_date": f"2020-{sequence:04d}",
            "observation_sequence": sequence,
            "indicator_id": indicator_id,
            "raw_value": float(sequence % 11),
            "validity_status": "valid",
            "reason_codes": ["valid_no_blocker"],
        }
        for sequence in range(count)
    ]


def test_119_120_boundary_and_current_excluded() -> None:
    results = compute_component_scores(_rows(121))
    assert results[119].reference_observation_count == 119
    assert results[119].eligible is False
    assert results[120].reference_observation_count == 120
    assert results[120].eligible is True
    assert results[120].reference_sequence_start == 0
    assert results[120].reference_sequence_end == 119
    assert results[120].observation_sequence == 120
    assert results[120].current_observation_excluded is True


def test_midrank_ties_and_only_w120() -> None:
    rows = _rows(121)
    for row in rows:
        row["raw_value"] = 2.0
    result = compute_component_scores(rows)[-1]
    assert result.percentile == 0.5
    assert result.score == 0.5
    with pytest.raises(ScoreContractError, match="only_w120_allowed"):
        compute_component_scores(rows, percentile_window=250)


def test_invalid_history_is_skipped_and_disorder_is_deterministic() -> None:
    rows = _rows(122)
    rows[49]["validity_status"] = "unknown"
    rows[49]["raw_value"] = float("nan")
    rows[49]["reason_codes"] = ["listing_pause"]
    ordered = compute_component_scores(rows)
    shuffled_rows = list(rows)
    random.Random(7).shuffle(shuffled_rows)
    shuffled = compute_component_scores(shuffled_rows, worker_count=2)
    assert [row.as_dict() for row in ordered] == [row.as_dict() for row in shuffled]
    assert ordered[-2].eligible is False
    assert ordered[-1].eligible is True


def test_valid_nan_infinity_duplicate_and_sequence_gap_rejected() -> None:
    for value in (float("nan"), float("inf")):
        rows = _rows(2)
        rows[-1]["raw_value"] = value
        with pytest.raises(ScoreContractError, match="valid_raw_value_must_be_finite"):
            compute_component_scores(rows)
    rows = _rows(2)
    with pytest.raises(ScoreContractError, match="duplicate_component_observation_key"):
        compute_component_scores(rows + [dict(rows[-1])])
    rows = _rows(3)
    del rows[1]
    with pytest.raises(ScoreContractError, match="component_observation_sequence_gap"):
        compute_component_scores(rows)


def test_zero_based_sequence_accepted_and_negative_rejected() -> None:
    assert compute_component_scores(_rows(1))[0].observation_sequence == 0
    rows = _rows(1)
    rows[0]["observation_sequence"] = -1
    with pytest.raises(ScoreContractError, match="must_be_non_negative"):
        compute_component_scores(rows)


def test_a_mean_min_and_no_single_component_fallback() -> None:
    rows = _rows(121, A_COMPONENTS[0]) + _rows(121, A_COMPONENTS[1])
    scores = compute_component_scores(rows)
    dimension = compute_a_dimension_scores(scores)
    final = dimension[-1]
    component_final = [row.score for row in scores if row.observation_sequence == 120]
    assert final.eligible_dimension is True
    assert final.score_dimension == sum(component_final) / 2
    assert final.score_dimension_min == min(component_final)

    incomplete = [row for row in scores if row.indicator_id == A_COMPONENTS[0]]
    failed = compute_a_dimension_scores(incomplete)[-1]
    assert failed.eligible_dimension is False
    assert failed.score_dimension is None
    assert "missing_a_component_score" in failed.reason_codes
