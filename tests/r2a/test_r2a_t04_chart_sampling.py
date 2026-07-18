from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from src.r2a.r2a_t04_charting import deterministic_chart_sample


def test_deterministic_stratified_sample_deduplicates_and_caps_security() -> None:
    first = date(2016, 1, 1)
    rows = [
        {
            "security_id": f"S{index % 10}",
            "confirmation_date": first + timedelta(days=index * 130),
            "mfe20": index / 100,
            "mae20": -index / 200,
            "release_strength_atr": (30 - index) / 10,
            "confirmed_observation_count": index + 1,
        }
        for index in range(30)
    ]
    left = deterministic_chart_sample(rows, request_hash="a" * 64)
    right = deterministic_chart_sample(list(reversed(rows)), request_hash="a" * 64)
    left_keys = [(row["security_id"], row["confirmation_date"]) for row in left]
    right_keys = [(row["security_id"], row["confirmation_date"]) for row in right]
    assert left_keys == right_keys
    assert len(left_keys) == len(set(left_keys)) == 12
    assert max(Counter(row["security_id"] for row in left).values()) <= 2
    assert {row["sample_stratum"] for row in left}
