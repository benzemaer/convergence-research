from __future__ import annotations

import random

import pytest

from src.r2a.r2a_t06_consecutive_failure_exit import build_exit_lifecycle
from src.r2a.r2a_t06_online_replay import replay_exit_lifecycle
from tests.r2a.test_r2a_t06_consecutive_failure_exit import _row


def _chunks(count: int, seed: int) -> list[int]:
    generator = random.Random(seed)
    output = []
    remaining = count
    while remaining:
        size = min(generator.randint(1, 3), remaining)
        output.append(size)
        remaining -= size
    return output


@pytest.mark.parametrize("m", (1, 2, 3))
@pytest.mark.parametrize(
    "rows",
    (
        [_row(0, True), _row(1, True), _row(2, False), _row(3, True, interval=1)],
        [
            _row(0, True),
            _row(1, True),
            _row(2, False),
            _row(3, False),
            _row(4, True, interval=1),
        ],
        [_row(0, True), _row(1, True), _row(2, False), _row(3, False), _row(4, False)],
        [
            _row(0, True),
            _row(1, False),
            _row(2, None, quality="selected_dimension_blocked"),
        ],
        [
            _row(0, True),
            _row(1, False),
            _row(2, False),
            _row(3, None, quality="selected_dimension_blocked"),
        ],
        [_row(0, True), _row(1, False)],
        [_row(0, True), _row(1, False), _row(2, False)],
    ),
)
def test_batch_equals_one_row_fixed_random_and_boundary_chunks(m: int, rows) -> None:
    batch = build_exit_lifecycle(
        rows, logical_request_name="CA_q20_k5", exit_confirmation_m=m
    )
    partitions = [[1] * len(rows), [len(rows)], _chunks(len(rows), 7)]
    partitions.extend([[split, len(rows) - split] for split in range(1, len(rows))])
    for partition in partitions:
        replay = replay_exit_lifecycle(
            rows,
            logical_request_name="CA_q20_k5",
            exit_confirmation_m=m,
            chunk_sizes=partition,
        )
        assert replay == batch


@pytest.mark.parametrize("m", (1, 2, 3))
def test_multi_security_interleaved_replay_has_isolated_carry_state(m: int) -> None:
    rows = [
        _row(0, True, security="S1"),
        _row(0, True, security="S2"),
        _row(1, False, security="S1"),
        _row(1, False, security="S2"),
        _row(2, True, security="S1", interval=1),
        _row(2, False, security="S2"),
    ]
    batch = build_exit_lifecycle(
        rows, logical_request_name="CA_q20_k5", exit_confirmation_m=m
    )
    replay = replay_exit_lifecycle(
        rows,
        logical_request_name="CA_q20_k5",
        exit_confirmation_m=m,
        chunk_sizes=[1, 2, 1, 2],
    )
    assert replay == batch
    assert {row["security_id"] for row in replay["episode_rows"]} == {"S1", "S2"}
