from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[2]
    / "scripts"
    / "review"
    / "review_r2a_t01_formal_extract.py"
)
SPEC = importlib.util.spec_from_file_location("r2a_t01_independent_review", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _rows(count: int) -> list[dict[str, object]]:
    start = date(2020, 1, 1)
    return [
        {
            "security_id": "000001.SZ",
            "trading_date": start + timedelta(days=sequence),
            "observation_sequence": sequence,
            "dimension_id": "P",
            "component_id": "P1_TEST",
            "raw_value": float(sequence % 5),
            "validity_status": "valid",
        }
        for sequence in range(count)
    ]


def test_independent_w120_strict_past_boundary_and_midrank() -> None:
    rows = _rows(121)
    results = MODULE.independent_component_series(rows, role="pcvt")
    assert results[119]["eligible"] is False
    assert results[119]["reference_observation_count"] == 119
    assert results[119]["validity_status"] == "unknown"
    final = results[120]
    assert final["eligible"] is True
    assert final["reference_observation_count"] == 120
    assert final["reference_window_end"] == rows[119]["trading_date"]
    expected_less = sum(row["raw_value"] < rows[120]["raw_value"] for row in rows[:120])
    expected_equal = sum(
        row["raw_value"] == rows[120]["raw_value"] for row in rows[:120]
    )
    expected_percentile = (expected_less + 0.5 * expected_equal) / 120
    assert final["percentile"] == expected_percentile
    assert final["score"] == 1 - expected_percentile


def test_pcvt_and_a_nonvalid_reference_semantics_are_distinct() -> None:
    rows = _rows(122)
    rows[121]["raw_value"] = None
    rows[121]["validity_status"] = "blocked"
    pcvt = MODULE.independent_component_series(rows, role="pcvt")[-1]
    a = MODULE.independent_component_series(rows, role="a")[-1]
    assert pcvt["reference_observation_count"] == 0
    assert pcvt["reference_window_start"] is None
    assert pcvt["reference_window_end"] is None
    assert a["reference_observation_count"] == 120
    assert a["reference_window_start"] == rows[1]["trading_date"]
    assert a["reference_window_end"] == rows[120]["trading_date"]
    assert pcvt["eligible"] is False
    assert a["eligible"] is False


def test_nonvalid_observation_is_excluded_from_later_history() -> None:
    rows = _rows(121)
    rows[0]["raw_value"] = None
    rows[0]["validity_status"] = "unknown"
    pcvt = MODULE.independent_component_series(rows, role="pcvt")[-1]
    a = MODULE.independent_component_series(rows, role="a")[-1]
    assert pcvt["reference_observation_count"] == 119
    assert a["reference_observation_count"] == 119
    assert pcvt["eligible"] is False
    assert a["eligible"] is False
