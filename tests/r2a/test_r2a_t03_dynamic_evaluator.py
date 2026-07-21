from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import duckdb
import pytest

from src.r2a import r2a_t03_dynamic_evaluator as evaluator_module
from src.r2a.r2a_t02_request_identity import DynamicRequestError
from src.r2a.r2a_t03_dynamic_evaluator import (
    DynamicEvaluationError,
    _duckdb_string_literal,
    evaluate_confirmation_sequence,
    evaluate_dynamic_request,
    evaluate_dynamic_request_connections,
)
from src.r2a.r2a_t03_output_contract import validate_dynamic_evaluation_output
from tests.r2a.r2a_t03_test_support import (
    canonical_request,
    create_source,
    evaluate,
)

PERSISTENT_OUTPUT_TABLES = (
    "dynamic_request",
    "evaluation_scope",
    "daily_dimension_states",
    "daily_joint_states",
    "confirmed_intervals",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_legacy_and_bulk_outputs_equal(
    source_path: Path,
    request: dict[str, object],
    security_ids: list[str] | None,
    tmp_path: Path,
) -> None:
    source_before = _sha256(source_path)
    legacy_path = tmp_path / "legacy.duckdb"
    bulk_path = tmp_path / "bulk.duckdb"
    with duckdb.connect(str(source_path), read_only=True) as source:
        with duckdb.connect(str(legacy_path)) as legacy:
            legacy_summary = evaluate_dynamic_request_connections(
                source=source,
                output=legacy,
                canonical_request=request,
                security_ids=security_ids,
            )
    bulk_summary = evaluate_dynamic_request(
        score_database=source_path,
        canonical_request=request,
        output_database=bulk_path,
        security_ids=security_ids,
    )
    assert _sha256(source_path) == source_before
    with duckdb.connect(str(legacy_path), read_only=True) as legacy:
        legacy_validator = validate_dynamic_evaluation_output(legacy)
        legacy.execute(
            f"ATTACH {_duckdb_string_literal(str(bulk_path.resolve()))} "
            "AS bulk_compare (READ_ONLY)"
        )
        try:
            for table in PERSISTENT_OUTPUT_TABLES:
                assert (
                    legacy.execute(f"PRAGMA table_info('{table}')").fetchall()
                    == legacy.execute(
                        f"PRAGMA table_info('bulk_compare.{table}')"
                    ).fetchall()
                )
                assert (
                    legacy.execute(f"SELECT count(*) FROM {table}").fetchone()
                    == legacy.execute(
                        f"SELECT count(*) FROM bulk_compare.{table}"
                    ).fetchone()
                )
                assert legacy.execute(
                    f"SELECT count(*) FROM (SELECT * FROM {table} EXCEPT ALL "
                    f"SELECT * FROM bulk_compare.{table})"
                ).fetchone() == (0,)
                assert legacy.execute(
                    f"SELECT count(*) FROM (SELECT * FROM bulk_compare.{table} "
                    f"EXCEPT ALL SELECT * FROM {table})"
                ).fetchone() == (0,)
        finally:
            legacy.execute("DETACH bulk_compare")
    with duckdb.connect(str(bulk_path), read_only=True) as bulk:
        bulk_validator = validate_dynamic_evaluation_output(bulk)
    assert legacy_summary == bulk_summary
    assert legacy_validator == bulk_validator == legacy_summary


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
        (2, 11, 13, 14, None, "input_end_open_right_censored", True),
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


@pytest.mark.parametrize("security_ids", [None, ["S3", "S1"]])
def test_legacy_and_bulk_file_evaluation_are_fully_equivalent(
    tmp_path: Path, security_ids: list[str] | None
) -> None:
    source_path = tmp_path / "score'fixture.duckdb"
    create_source(str(source_path)).close()
    _assert_legacy_and_bulk_outputs_equal(
        source_path, canonical_request(), security_ids, tmp_path
    )


def test_bulk_path_escapes_quotes_and_rejects_nul() -> None:
    quoted = r"C:\score's\score.duckdb"
    assert _duckdb_string_literal(quoted) == "'C:\\score''s\\score.duckdb'"
    with pytest.raises(DynamicEvaluationError, match="source_database_path_invalid"):
        _duckdb_string_literal("bad\x00path")


def test_file_entrypoint_uses_bulk_copy_without_streaming(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_path = tmp_path / "source.duckdb"
    create_source(str(source_path)).close()

    def fail_stream(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("file entrypoint must not use streaming copy")

    monkeypatch.setattr(evaluator_module, "_stream_query", fail_stream)
    evaluate_dynamic_request(
        score_database=source_path,
        canonical_request=canonical_request(),
        output_database=tmp_path / "bulk.duckdb",
    )


def test_connection_entrypoint_retains_legacy_oracle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_source()
    output = duckdb.connect(":memory:")

    def fail_bulk(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("connection entrypoint must retain legacy copy")

    monkeypatch.setattr(evaluator_module, "_copy_selected_source_bulk", fail_bulk)
    evaluate_dynamic_request_connections(
        source=source,
        output=output,
        canonical_request=canonical_request(),
    )
