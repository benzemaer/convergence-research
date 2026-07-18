from __future__ import annotations

import duckdb

from src.r2a.r2a_t03_output_contract import OUTPUT_TABLE_ORDER
from tests.r2a.r2a_t03_test_support import (
    canonical_request,
    create_source,
    evaluate,
    table_fingerprint,
)


def _true_keys(
    output: duckdb.DuckDBPyConnection, column: str
) -> set[tuple[str, object]]:
    return set(
        output.execute(
            f"SELECT security_id, trading_date FROM daily_joint_states "
            f"WHERE {column} IS TRUE"
        ).fetchall()
    )


def _dimension_profile(
    output: duckdb.DuckDBPyConnection, dimension: str
) -> list[tuple[object, ...]]:
    return output.execute(
        "SELECT security_id, trading_date, q_bp, main_threshold, weak_threshold, "
        "dimension_active FROM daily_dimension_states WHERE dimension_id=? "
        "ORDER BY security_id, observation_sequence",
        [dimension],
    ).fetchall()


def _assert_independent_q_monotonicity(*, target: str, fixed: str) -> None:
    source = create_source()
    previous_dimension: set[tuple[str, object]] = set()
    previous_joint: set[tuple[str, object]] = set()
    fixed_profile: list[tuple[object, ...]] | None = None
    observed_target_sets: set[frozenset[tuple[str, object]]] = set()
    for q_bp in (1000, 1500, 2000, 2500):
        request_q = {target: q_bp, fixed: 1500}
        output = evaluate(source, canonical_request(q_bp=request_q))
        current_dimension = set(
            output.execute(
                "SELECT security_id, trading_date FROM daily_dimension_states "
                "WHERE dimension_id=? AND dimension_active",
                [target],
            ).fetchall()
        )
        current_joint = _true_keys(output, "raw_state")
        assert previous_dimension <= current_dimension
        assert previous_joint <= current_joint
        assert (
            output.execute(
                "SELECT count(*) FROM daily_dimension_states "
                "WHERE dimension_id=? AND q_bp<>?",
                [target, q_bp],
            ).fetchone()[0]
            == 0
        )
        assert (
            output.execute(
                "SELECT count(*) FROM daily_dimension_states "
                "WHERE dimension_id=? AND q_bp<>1500",
                [fixed],
            ).fetchone()[0]
            == 0
        )
        current_fixed_profile = _dimension_profile(output, fixed)
        if fixed_profile is None:
            fixed_profile = current_fixed_profile
        else:
            assert current_fixed_profile == fixed_profile
        observed_target_sets.add(frozenset(current_dimension))
        previous_dimension = current_dimension
        previous_joint = current_joint
    assert len(observed_target_sets) >= 2


def test_only_p_q_relaxes_while_a_is_fixed() -> None:
    _assert_independent_q_monotonicity(target="P", fixed="A")


def test_only_a_q_relaxes_while_p_is_fixed() -> None:
    _assert_independent_q_monotonicity(target="A", fixed="P")


def test_selected_dimension_true_set_only_contracts() -> None:
    source = create_source()
    smaller = evaluate(source, canonical_request(dimensions=("P",)))
    larger = evaluate(source, canonical_request(dimensions=("P", "A")))
    assert _true_keys(larger, "raw_state") <= _true_keys(smaller, "raw_state")


def test_k_response_confirmation_never_moves_earlier() -> None:
    source = create_source()
    previous_confirmed: set[tuple[str, object]] | None = None
    previous_confirmation: dict[str, object] = {}
    for confirmation_k in range(2, 8):
        output = evaluate(source, canonical_request(confirmation_k=confirmation_k))
        confirmed = _true_keys(output, "confirmed_state")
        confirmation = dict(
            output.execute(
                "SELECT security_id, min(trading_date) FROM daily_joint_states "
                "WHERE confirmation_event GROUP BY security_id"
            ).fetchall()
        )
        if previous_confirmed is not None:
            assert confirmed <= previous_confirmed
        for security_id, current_date in confirmation.items():
            if security_id in previous_confirmation:
                assert current_date >= previous_confirmation[security_id]
        previous_confirmed = confirmed
        previous_confirmation = confirmation


def test_determinism_across_insertion_order_scope_order_and_threads() -> None:
    first_source = create_source()
    second_source = create_source(reverse_insert_order=True)
    first = evaluate(first_source, security_ids=["S1", "S3"], threads=1)
    second = evaluate(second_source, security_ids=["S3", "S1"], threads=4)
    for table in OUTPUT_TABLE_ORDER:
        assert first.execute(f"PRAGMA table_info('{table}')").fetchall() == (
            second.execute(f"PRAGMA table_info('{table}')").fetchall()
        )
        assert first.execute(f"SELECT count(*) FROM {table}").fetchone() == (
            second.execute(f"SELECT count(*) FROM {table}").fetchone()
        )
        assert table_fingerprint(first, table) == table_fingerprint(second, table)
