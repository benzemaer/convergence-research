from __future__ import annotations

import copy
from pathlib import Path

import duckdb
import pytest

from src.r2a.r2a_t02_request_identity import DynamicRequestError
from src.r2a.r2a_t03_dynamic_evaluator import (
    DynamicEvaluationError,
    evaluate_confirmation_sequence,
    evaluate_dynamic_request,
    evaluate_dynamic_request_connections,
)
from tests.r2a.r2a_t03_test_support import (
    canonical_request,
    create_source,
    evaluate,
)


def test_streak_confirmation_intervals_and_no_backfill() -> None:
    output = evaluate(create_source())
    rows = output.execute(
        "SELECT observation_sequence, raw_state, raw_streak, confirmation_event, "
        "confirmed_state, confirmed_interval_ordinal FROM daily_joint_states "
        "WHERE security_id='S1' ORDER BY observation_sequence"
    ).fetchall()
    assert rows[:4] == [
        (0, True, 1, False, False, None),
        (1, True, 2, False, False, None),
        (2, True, 3, True, True, 0),
        (3, False, 0, False, False, None),
    ]
    intervals = output.execute(
        "SELECT interval_ordinal, raw_start_observation_sequence, "
        "confirmation_observation_sequence, last_confirmed_end_observation_sequence, "
        "termination_observation_sequence, termination_reason, right_censored "
        "FROM confirmed_intervals WHERE security_id='S1' ORDER BY interval_ordinal"
    ).fetchall()
    assert intervals == [
        (0, 0, 2, 2, 3, "raw_false", False),
        (1, 7, 9, 9, 10, "selected_dimension_blocked", False),
        (2, 11, 13, 13, None, "input_end_open_right_censored", True),
    ]


@pytest.mark.parametrize(
    ("spine_status", "dimension_update", "expected_reason"),
    [
        ("missing", "", "expected_observation_missing"),
        ("listing_pause", "", "expected_observation_listing_pause"),
        ("present", "validity_status='blocked'", "selected_dimension_blocked"),
        (
            "present",
            "validity_status='diagnostic_required'",
            "selected_dimension_diagnostic_required",
        ),
        ("present", "validity_status='unknown'", "selected_dimension_unknown"),
        (
            "present",
            "eligible_dimension=false",
            "selected_dimension_not_eligible",
        ),
        (
            "present",
            "score_dimension=NULL",
            "selected_dimension_score_non_finite",
        ),
        ("present", "score_dimension=0.4", "raw_false"),
    ],
)
def test_primary_termination_reason_priority(
    spine_status: str, dimension_update: str, expected_reason: str
) -> None:
    source = create_source()
    source.execute(
        "UPDATE security_observation_spine SET expected_observation_status=? "
        "WHERE security_id='S1' AND observation_sequence=3",
        [spine_status],
    )
    source.execute(
        "UPDATE daily_dimension_scores SET score_dimension=0.9 "
        "WHERE security_id='S1' AND observation_sequence=3 AND dimension_id='P'"
    )
    if dimension_update:
        source.execute(
            f"UPDATE daily_dimension_scores SET {dimension_update} "
            "WHERE security_id='S1' AND observation_sequence=3 AND dimension_id='A'"
        )
    output = evaluate(source, security_ids=["S1"])
    reason = output.execute(
        "SELECT termination_reason FROM confirmed_intervals "
        "WHERE security_id='S1' AND interval_ordinal=0"
    ).fetchone()[0]
    assert reason == expected_reason


def test_complete_case_reason_order_and_unselected_isolation() -> None:
    source = create_source()
    source.execute(
        "UPDATE daily_dimension_scores SET validity_status='blocked', "
        "reason_codes=['must_not_leak'] WHERE security_id='S1' "
        "AND observation_sequence=0 AND dimension_id='T'"
    )
    output = evaluate(source)
    first = output.execute(
        "SELECT raw_state, joint_reason_codes FROM daily_joint_states "
        "WHERE security_id='S1' AND observation_sequence=0"
    ).fetchone()
    assert first == (True, [])
    missing = output.execute(
        "SELECT joint_validity_status, joint_ready, raw_state, joint_reason_codes "
        "FROM daily_joint_states WHERE security_id='S2' AND observation_sequence=0"
    ).fetchone()
    assert missing[:3] == ("blocked", False, None)
    assert missing[3][0] == "expected_observation_missing"
    assert all("T:" not in reason for reason in missing[3])
    assert missing[3] == [
        "expected_observation_missing",
        "P:dimension_not_eligible",
        "P:score_non_finite",
        "P:validity_blocked",
        "A:dimension_not_eligible",
        "A:score_non_finite",
        "A:validity_blocked",
    ]


@pytest.mark.parametrize("sequence", [2, 3, 4, 5, 6, 7, 8, 9])
def test_every_non_ready_category_is_raw_null(sequence: int) -> None:
    output = evaluate(create_source())
    row = output.execute(
        "SELECT joint_ready, raw_state, raw_streak, confirmed_state "
        "FROM daily_joint_states WHERE security_id='S2' AND observation_sequence=?",
        [sequence],
    ).fetchone()
    assert row == (False, None, None, None)


def test_false_does_not_hide_another_dimension_failure() -> None:
    source = create_source()
    source.execute(
        "UPDATE daily_dimension_scores SET score_dimension=0.4, "
        "score_dimension_min=0.3 WHERE security_id='S2' "
        "AND observation_sequence=5 AND dimension_id='P'"
    )
    output = evaluate(source)
    row = output.execute(
        "SELECT raw_state, joint_reason_codes FROM daily_joint_states "
        "WHERE security_id='S2' AND observation_sequence=5"
    ).fetchone()
    assert row[0] is None
    assert "A:validity_blocked" in row[1]


def test_threshold_epsilon_and_both_component_conditions() -> None:
    source = create_source()
    source.execute(
        "UPDATE daily_dimension_scores SET score_dimension=?, score_dimension_min=? "
        "WHERE security_id='S1' AND observation_sequence=0 AND dimension_id='P'",
        [0.85 - 1e-12, 0.75 - 1e-12],
    )
    source.execute(
        "UPDATE daily_dimension_scores SET score_dimension=0.9, "
        "score_dimension_min=0.74 "
        "WHERE security_id='S1' AND observation_sequence=1 AND dimension_id='P'"
    )
    source.execute(
        "UPDATE daily_dimension_scores SET score_dimension=0.84, "
        "score_dimension_min=0.8 "
        "WHERE security_id='S1' AND observation_sequence=2 AND dimension_id='P'"
    )
    output = evaluate(source)
    active = output.execute(
        "SELECT observation_sequence, dimension_active FROM daily_dimension_states "
        "WHERE security_id='S1' AND dimension_id='P' AND observation_sequence<3 "
        "ORDER BY observation_sequence"
    ).fetchall()
    assert active == [(0, True), (1, False), (2, False)]


def test_explicit_scope_is_sorted_and_does_not_change_request_identity() -> None:
    source = create_source()
    all_output = evaluate(source)
    explicit = evaluate(source, security_ids=["S3", "S1"])
    assert all_output.execute("SELECT request_id FROM dynamic_request").fetchone() == (
        explicit.execute("SELECT request_id FROM dynamic_request").fetchone()
    )
    scope = explicit.execute(
        "SELECT security_scope, requested_security_ids, evaluated_security_count "
        "FROM evaluation_scope"
    ).fetchone()
    assert scope == ("explicit", ["S1", "S3"], 2)
    assert explicit.execute(
        "SELECT DISTINCT security_id FROM daily_joint_states ORDER BY 1"
    ).fetchall() == [("S1",), ("S3",)]


@pytest.mark.parametrize(
    ("security_ids", "reason"),
    [
        ([], "explicit_security_scope_empty"),
        (["S1", "S1"], "duplicate_security_id"),
        (["NOPE"], "unknown_security_id"),
    ],
)
def test_invalid_explicit_scope_rejected(security_ids: list[str], reason: str) -> None:
    source = create_source()
    output = duckdb.connect(":memory:")
    with pytest.raises(DynamicEvaluationError, match=reason):
        evaluate_dynamic_request_connections(
            source=source,
            output=output,
            canonical_request=canonical_request(),
            security_ids=security_ids,
        )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            "UPDATE security_observation_spine SET score_release_id='wrong'",
            "score_release_id_mismatch",
        ),
        ("DROP TABLE security_observation_spine", "source_table_missing"),
        ("DROP TABLE daily_dimension_scores", "source_table_missing"),
        (
            "ALTER TABLE daily_dimension_scores DROP COLUMN available_time",
            "source_column_missing",
        ),
        (
            "INSERT INTO security_observation_spine "
            "SELECT * FROM security_observation_spine "
            "WHERE security_id='S1' LIMIT 1",
            "spine_primary_key_duplicate",
        ),
        (
            "UPDATE security_observation_spine SET observation_sequence=99 "
            "WHERE security_id='S3' AND observation_sequence=5",
            "observation_sequence_not_contiguous",
        ),
        (
            "UPDATE security_observation_spine "
            "SET trading_date=trading_date-INTERVAL 10 DAY "
            "WHERE security_id='S3' AND observation_sequence=5",
            "trading_date_not_strictly_increasing",
        ),
        (
            "DELETE FROM daily_dimension_scores WHERE security_id='S1' "
            "AND observation_sequence=0 AND dimension_id='A'",
            "selected_dimension_cardinality_mismatch",
        ),
        (
            "INSERT INTO daily_dimension_scores SELECT * "
            "FROM daily_dimension_scores WHERE security_id='S1' "
            "AND observation_sequence=0 AND dimension_id='A'",
            "selected_dimension_cardinality_mismatch",
        ),
        (
            "UPDATE daily_dimension_scores SET observation_sequence=42 "
            "WHERE security_id='S1' AND observation_sequence=0 "
            "AND dimension_id='A'",
            "dimension_spine_reconciliation_mismatch",
        ),
        (
            "UPDATE daily_dimension_scores "
            "SET available_time=available_time+INTERVAL 1 SECOND "
            "WHERE security_id='S1' AND observation_sequence=0 "
            "AND dimension_id='A'",
            "dimension_spine_reconciliation_mismatch",
        ),
    ],
)
def test_source_contract_failures(mutation: str, reason: str) -> None:
    source = create_source()
    source.execute(mutation)
    output = duckdb.connect(":memory:")
    with pytest.raises(DynamicEvaluationError, match=reason):
        evaluate_dynamic_request_connections(
            source=source,
            output=output,
            canonical_request=canonical_request(),
        )


def test_raw_request_tampered_hash_and_illegal_k_are_rejected() -> None:
    source = create_source()
    raw = canonical_request()["spec"]
    for invalid in (raw, {**canonical_request(), "request_hash": "0" * 64}):
        with pytest.raises(DynamicRequestError):
            evaluate_dynamic_request_connections(
                source=source,
                output=duckdb.connect(":memory:"),
                canonical_request=invalid,
            )
    illegal = copy.deepcopy(canonical_request())
    illegal["spec"]["confirmation_k"] = 1
    with pytest.raises(DynamicRequestError):
        evaluate_dynamic_request_connections(
            source=source,
            output=duckdb.connect(":memory:"),
            canonical_request=illegal,
        )


def test_pure_state_machine_k1_boundary_and_null_interrupt() -> None:
    assert evaluate_confirmation_sequence([True], 1) == ((1, True, True),)
    assert evaluate_confirmation_sequence([True, None, True, False], 2) == (
        (1, False, False),
        (None, False, None),
        (1, False, False),
        (0, False, False),
    )


def test_path_entrypoint_is_atomic_and_rejects_conflicts(tmp_path: Path) -> None:
    source_path = tmp_path / "source.duckdb"
    create_source(str(source_path)).close()
    request = canonical_request()
    output_path = tmp_path / "output.duckdb"
    summary = evaluate_dynamic_request(
        score_database=source_path,
        canonical_request=request,
        output_database=output_path,
    )
    assert summary.confirmed_interval_count == 3
    with pytest.raises(DynamicEvaluationError, match="output_already_exists"):
        evaluate_dynamic_request(
            score_database=source_path,
            canonical_request=request,
            output_database=output_path,
        )
    with pytest.raises(DynamicEvaluationError, match="source_output_path_same"):
        evaluate_dynamic_request(
            score_database=source_path,
            canonical_request=request,
            output_database=source_path,
        )


def test_failure_leaves_no_output_database(tmp_path: Path) -> None:
    source_path = tmp_path / "bad.duckdb"
    source = create_source(str(source_path))
    source.execute(
        "UPDATE daily_dimension_scores SET available_time=available_time+INTERVAL 1 DAY"
    )
    source.close()
    output_path = tmp_path / "must_not_exist.duckdb"
    with pytest.raises(DynamicEvaluationError):
        evaluate_dynamic_request(
            score_database=source_path,
            canonical_request=canonical_request(),
            output_database=output_path,
        )
    assert not output_path.exists()
    assert not list(tmp_path.glob(".must_not_exist.duckdb.*.tmp.duckdb"))
