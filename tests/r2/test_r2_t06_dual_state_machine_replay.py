from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from src.r2.r2_t06_dual_state_machine_replay import (
    T06Blocked,
    _daily_asof,
    _event_rows_for_security,
    _source_to_timeline,
    canonical_event_id,
    check_merged_pr_binding,
    replay_confirmation_rows,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r2/r2_t06_canonical_dual_state_machine_replay.v1.json"


def _rows(
    states: list[bool | None], *, quality: str = "valid"
) -> list[dict[str, object]]:
    return [
        {
            "security_id": "S1",
            "trade_date": date(2020, 1, index + 1),
            "available_time": f"2020-01-{index + 1:02d}T15:00:00+08:00",
            "eligible": True,
            "quality_state": quality,
            "raw_state": state,
            "source_row_present": True,
            "expected_empty_reason": None,
        }
        for index, state in enumerate(states)
    ]


def test_k3_confirmation_has_no_backfill() -> None:
    replay = replay_confirmation_rows(_rows([True, True, False, True, True, True]))
    assert [row.confirmed_state for row in replay] == [
        False,
        False,
        False,
        False,
        False,
        True,
    ]
    assert replay[-1].confirmation_time is not None
    assert replay[-1].confirmed_start_date == date(2020, 1, 6)


def test_false_true_true_true_confirms_on_third_true() -> None:
    replay = replay_confirmation_rows(_rows([False, True, True, True]))
    assert [row.confirmed_state for row in replay] == [False, False, False, True]
    assert replay[-1].confirmation_time is not None
    assert replay[-1].confirmation_time.date() == date(2020, 1, 4)


def test_missing_source_row_resets_confirmation_streak() -> None:
    rows = _rows([True, True, True, True])
    rows[1]["source_row_present"] = False
    replay = replay_confirmation_rows(rows)
    assert [row.confirmed_state for row in replay] == [False, False, False, False]
    assert replay[1].hard_break is True


def test_quality_break_and_natural_exit_are_distinct() -> None:
    natural = replay_confirmation_rows(_rows([True, True, True, False]))
    quality = replay_confirmation_rows(_rows([True, True, True, None]))
    assert natural[-1].hard_break is False
    assert quality[-1].hard_break is True
    assert natural[-1].confirmed_state is False
    assert quality[-1].confirmed_state is False


def test_daily_overlay_uses_visible_source_row_before_retrospective_membership(
) -> None:
    con = duckdb.connect()
    try:
        con.execute("CREATE SCHEMA src")
        con.execute(
            """
            CREATE TABLE src.event_zone_membership_daily(
              candidate_cell_id VARCHAR,security_id VARCHAR,trade_date DATE,
              available_time TIMESTAMPTZ,evaluation_time TIMESTAMPTZ,
              scan_event_id VARCHAR,zone_status_as_of VARCHAR,
              event_zone_member BOOLEAN,is_raw_false_bridge BOOLEAN,
              prequalification_member BOOLEAN,unqualified_reentry_member BOOLEAN
            )
            """
        )
        con.execute(
            """
            CREATE TABLE r2_t06_replayed_event_membership(
              state_version_id VARCHAR,event_id VARCHAR,security_id VARCHAR,
              trade_date DATE,component_qualified_as_of BOOLEAN,
              event_zone_member BOOLEAN,is_prequalification_confirmed_day BOOLEAN,
              is_bridged_gap BOOLEAN,is_unqualified_reentry_day BOOLEAN,
              event_status_as_of VARCHAR,membership_available_time TIMESTAMPTZ
            )
            """
        )
        con.execute(
            """
            CREATE TABLE t06_route_daily(
              route_id VARCHAR,security_id VARCHAR,trade_date DATE,
              available_time TIMESTAMPTZ,eligible BOOLEAN,raw_state BOOLEAN,
              confirmed_state BOOLEAN,confirmation_time TIMESTAMPTZ,
              state_risk_set_eligible BOOLEAN,quality_state VARCHAR
            )
            """
        )
        con.execute(
            """
            CREATE TABLE src.cell_registry(candidate_cell_id VARCHAR,route_id VARCHAR)
            """
        )
        con.executemany(
            "INSERT INTO src.cell_registry VALUES (?,?)",
            [("primary", "route"), ("strict", "route")],
        )
        con.executemany(
            "INSERT INTO t06_route_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "route",
                    "S1",
                    date(2020, 1, day),
                    f"2020-01-{day:02d} 15:00:00+08:00",
                    True,
                    True,
                    True,
                    None,
                    True,
                    "valid",
                )
                for day in (21, 22, 23)
            ],
        )
        con.execute(
            "INSERT INTO src.event_zone_membership_daily "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "primary",
                "S1",
                date(2020, 1, 21),
                "2020-01-21 15:00:00+08:00",
                "2020-01-24 15:00:00+08:00",
                "source-event",
                "COMPONENT_FORMING",
                True,
                False,
                True,
                False,
            ),
        )
        con.executemany(
            "INSERT INTO r2_t06_replayed_event_membership "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "v",
                    "canonical-event",
                    "S1",
                    date(2020, 1, 21),
                    False,
                    True,
                    True,
                    False,
                    False,
                    "COMPONENT_FORMING",
                    "2020-01-24 15:00:00+08:00",
                ),
                (
                    "v",
                    "canonical-event",
                    "S1",
                    date(2020, 1, 22),
                    False,
                    False,
                    False,
                    False,
                    False,
                    "FINALIZED",
                    "2020-01-22 15:00:00+08:00",
                ),
            ],
        )
        _daily_asof(
            con,
            [
                {
                    "state_version_id": "v",
                    "state_line": "S_PCT",
                    "source_candidate_cell_id": "primary",
                    "strict_core_source_candidate_cell_id": "strict",
                }
            ],
            "test-run",
        )
        rows = con.execute(
            """
            SELECT trade_date,event_status_as_of,active_event_id_as_of,
                   component_qualified_as_of
            FROM r2_t06_replayed_daily_state
            ORDER BY trade_date
            """
        ).fetchall()
        assert rows == [
            (date(2020, 1, 21), "COMPONENT_FORMING", "canonical-event", False),
            (date(2020, 1, 22), "FINALIZED", None, False),
            (date(2020, 1, 23), "FINALIZED", None, False),
        ]
    finally:
        con.close()


def test_d2_qualification_and_accepted_reentry_first_day_are_false() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    version = config["selected_versions"][0]
    rows = _rows(
        [True, True, True, True, False, True, True, True, True, False, False]
    )
    timeline = _source_to_timeline(rows, 3)
    _, _, events, memberships, _ = _event_rows_for_security(timeline, "route", version)
    assert events
    qualified = [row for row in memberships if row["qualified_event_risk_set_eligible"]]
    assert all(not row["is_prequalification_confirmed_day"] for row in qualified)
    assert all(
        row["membership_available_time"].date() >= row["trade_date"]
        for row in qualified
    )


def test_event_id_changes_when_identity_changes() -> None:
    first = canonical_event_id(
        "v1",
        "cell",
        "S1",
        "component_001",
        date(2020, 1, 1),
        replay_confirmation_rows(_rows([True, True, True]))[-1].available_time,
    )[0]
    second = canonical_event_id(
        "v2",
        "cell",
        "S1",
        "component_001",
        date(2020, 1, 1),
        replay_confirmation_rows(_rows([True, True, True]))[-1].available_time,
    )[0]
    assert first != second


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("t05_binding", "t05_scientific_review_id"), "mutated"),
        (("t05_binding", "t05_authoritative_run"), "R2-T05-mutated"),
        (("t05_artifacts", "database_sha256"), "0" * 64),
        (("selected_versions", 0, "state_version_id"), "mutated"),
    ],
)
def test_startup_binding_mutations_fail_closed(
    path: tuple[object, ...], value: str
) -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    mutated = copy.deepcopy(config)
    cursor: object = mutated
    for key in path[:-1]:
        cursor = cursor[key]  # type: ignore[index]
    cursor[path[-1]] = value  # type: ignore[index]
    with pytest.raises(T06Blocked):
        check_merged_pr_binding(ROOT, mutated)
