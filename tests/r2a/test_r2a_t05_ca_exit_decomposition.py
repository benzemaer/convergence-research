from __future__ import annotations

import copy
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from src.r2a.r2a_t02_request_identity import (
    DYNAMIC_PROTOCOL_VERSION,
    REQUEST_SPEC_SCHEMA_VERSION,
    SCORE_RELEASE_ID,
    build_canonical_request,
)
from src.r2a.r2a_t03_dynamic_evaluator import evaluate_dynamic_request
from src.r2a.r2a_t05_ca_exit_decomposition import (
    T05Error,
    _followup_metrics,
    build_t05_candidate,
    candidate_to_json,
    load_t05_config,
)
from src.r2a.r2a_t05_validator import validate_t05_candidate

ROOT = Path(__file__).resolve().parents[2]


def _profile(
    security_id: str, sequence: int, dimension: str
) -> tuple[str, float | None]:
    if security_id == "S1":
        if sequence <= 7:
            return "present", 0.96
        if sequence == 8:
            return "present", 0.76
        if sequence <= 15:
            return "present", 0.82
        if sequence == 16:
            return "present", 0.60
        if sequence == 17:
            return "present", 0.96
        return "present", 0.60
    if security_id == "S2":
        return "present", 0.96
    if security_id == "S3":
        if sequence <= 6:
            return "present", 0.96
        if sequence == 7:
            return "present", 0.76 if dimension == "C" else 0.81
        if sequence == 8:
            return "present", 0.81
        if sequence == 9:
            return "present", 0.60
        if sequence <= 15:
            return "present", 0.96
        if sequence == 16:
            return "present", 0.81 if dimension == "C" else 0.76
        return "present", 0.60
    if sequence == 7:
        return "present", 0.60
    if sequence == 8:
        return "listing_pause", None
    if 9 <= sequence <= 13:
        return "present", 0.96
    if sequence >= 14:
        return "listing_pause", None
    if sequence <= 6:
        return "present", 0.96
    raise AssertionError(sequence)


def _create_score_fixture(path: Path, *, gapped_s1_dates: bool = True) -> None:
    connection = duckdb.connect(str(path))
    connection.execute(
        "CREATE TABLE security_observation_spine("
        "score_release_id VARCHAR,security_id VARCHAR,trading_date DATE,"
        "observation_sequence BIGINT,expected_observation_status VARCHAR,"
        "observation_available_time TIMESTAMP WITH TIME ZONE)"
    )
    connection.execute(
        "CREATE TABLE daily_dimension_scores("
        "score_release_id VARCHAR,security_id VARCHAR,trading_date DATE,"
        "observation_sequence BIGINT,dimension_id VARCHAR,score_dimension DOUBLE,"
        "score_dimension_min DOUBLE,eligible_dimension BOOLEAN,"
        "validity_status VARCHAR,reason_codes VARCHAR[],"
        "available_time TIMESTAMP WITH TIME ZONE)"
    )
    connection.execute(
        "CREATE TABLE daily_component_scores("
        "score_release_id VARCHAR,security_id VARCHAR,trading_date DATE,"
        "observation_sequence BIGINT,dimension_id VARCHAR,component_id VARCHAR,"
        "score DOUBLE,eligible BOOLEAN,validity_status VARCHAR,reason_codes VARCHAR[])"
    )
    first = date(2026, 1, 2)
    lengths = {"S1": 20, "S2": 7, "S3": 18, "S4": 15}
    spine: list[tuple[object, ...]] = []
    dimensions: list[tuple[object, ...]] = []
    components: list[tuple[object, ...]] = []
    timezone = ZoneInfo("Asia/Shanghai")
    for security_id, length in lengths.items():
        for sequence in range(length):
            day_offset = (
                sequence * 2 if gapped_s1_dates and security_id == "S1" else sequence
            )
            trading_date = first + timedelta(days=day_offset)
            status, _ = _profile(security_id, sequence, "C")
            available = datetime.combine(trading_date, time(15), timezone)
            spine.append(
                (
                    SCORE_RELEASE_ID,
                    security_id,
                    trading_date,
                    sequence,
                    status,
                    available,
                )
            )
            for dimension in ("C", "A"):
                row_status, score = _profile(security_id, sequence, dimension)
                eligible = row_status == "present" and score is not None
                validity = "valid" if eligible else "blocked"
                reasons = [] if eligible else ["synthetic_quality"]
                dimensions.append(
                    (
                        SCORE_RELEASE_ID,
                        security_id,
                        trading_date,
                        sequence,
                        dimension,
                        score,
                        score,
                        eligible,
                        validity,
                        reasons,
                        available,
                    )
                )
                for component_id in (f"{dimension}1", f"{dimension}2"):
                    components.append(
                        (
                            SCORE_RELEASE_ID,
                            security_id,
                            trading_date,
                            sequence,
                            dimension,
                            component_id,
                            score,
                            eligible,
                            validity,
                            reasons,
                        )
                    )
    connection.executemany(
        "INSERT INTO security_observation_spine VALUES (?,?,?,?,?,?)", spine
    )
    connection.executemany(
        "INSERT INTO daily_dimension_scores VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        dimensions,
    )
    connection.executemany(
        "INSERT INTO daily_component_scores VALUES (?,?,?,?,?,?,?,?,?,?)",
        components,
    )
    connection.execute("CHECKPOINT")
    connection.close()


def _request(name: str, config: dict[str, object]) -> dict[str, object]:
    item = next(
        item for item in config["requests"] if item["logical_request_name"] == name
    )
    return build_canonical_request(
        {
            "request_schema_version": REQUEST_SPEC_SCHEMA_VERSION,
            "dynamic_protocol_version": DYNAMIC_PROTOCOL_VERSION,
            "score_release_id": SCORE_RELEASE_ID,
            "selected_dimensions": item["selected_dimensions"],
            "q_by_dimension": item["q_by_dimension"],
            "confirmation_k": item["confirmation_k"],
        }
    )


def _fixture(tmp_path: Path) -> tuple[dict[str, object], Path, dict[str, Path]]:
    config = copy.deepcopy(load_t05_config())
    score = tmp_path / "synthetic_score.duckdb"
    _create_score_fixture(score)
    outputs: dict[str, Path] = {}
    for name in ("CA_q10_k5", "CA_q15_k5", "CA_q20_k5", "CA_q25_k5"):
        output = tmp_path / f"{name}.duckdb"
        evaluate_dynamic_request(
            score_database=score,
            canonical_request=_request(name, config),
            output_database=output,
        )
        outputs[name] = output
    with duckdb.connect(str(outputs["CA_q10_k5"]), read_only=True) as connection:
        config["accepted_t04_counts"] = {
            name: {
                "raw_true": int(
                    connection.execute(
                        "SELECT count(*) FROM daily_joint_states "
                        "WHERE raw_state IS TRUE"
                    ).fetchone()[0]
                ),
                "confirmed_true": int(
                    connection.execute(
                        "SELECT count(*) FROM daily_joint_states "
                        "WHERE confirmed_state IS TRUE"
                    ).fetchone()[0]
                ),
                "intervals": int(
                    connection.execute(
                        "SELECT count(*) FROM confirmed_intervals"
                    ).fetchone()[0]
                ),
                "securities_with_interval": int(
                    connection.execute(
                        "SELECT count(DISTINCT security_id) FROM confirmed_intervals"
                    ).fetchone()[0]
                ),
            }
            for name in outputs
        }
    # Recompute counts per request, not from the q10 output reused above.
    for name, output in outputs.items():
        with duckdb.connect(str(output), read_only=True) as connection:
            config["accepted_t04_counts"][name] = {
                "raw_true": int(
                    connection.execute(
                        "SELECT count(*) FROM daily_joint_states "
                        "WHERE raw_state IS TRUE"
                    ).fetchone()[0]
                ),
                "confirmed_true": int(
                    connection.execute(
                        "SELECT count(*) FROM daily_joint_states "
                        "WHERE confirmed_state IS TRUE"
                    ).fetchone()[0]
                ),
                "intervals": int(
                    connection.execute(
                        "SELECT count(*) FROM confirmed_intervals"
                    ).fetchone()[0]
                ),
                "securities_with_interval": int(
                    connection.execute(
                        "SELECT count(DISTINCT security_id) FROM confirmed_intervals"
                    ).fetchone()[0]
                ),
            }
    return config, score, outputs


def _mutate_q25_child_across_parent(path: Path) -> None:
    """Split one q20 confirmed interval across two synthetic q25 parents."""

    with duckdb.connect(str(path)) as connection:
        columns = [
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info('confirmed_intervals')"
            ).fetchall()
        ]
        interval_ordinal_index = columns.index("interval_ordinal")
        count_index = columns.index("confirmed_observation_count")
        template = list(
            connection.execute(
                "SELECT * FROM confirmed_intervals "
                "WHERE security_id='S1' AND interval_ordinal=0"
            ).fetchone()
        )
        template[interval_ordinal_index] = 1
        template[count_index] = 1
        connection.execute(
            "UPDATE confirmed_intervals SET confirmed_observation_count=11 "
            "WHERE security_id='S1' AND interval_ordinal=0"
        )
        quoted_columns = ",".join(f'"{column}"' for column in columns)
        placeholders = ",".join("?" for _ in columns)
        connection.execute(
            f"INSERT INTO confirmed_intervals ({quoted_columns}) "
            f"VALUES ({placeholders})",
            template,
        )
        connection.execute(
            "UPDATE daily_joint_states SET confirmed_interval_ordinal=1 "
            "WHERE security_id='S1' AND observation_sequence=7"
        )
        connection.execute("CHECKPOINT")


def test_candidate_covers_exit_reentry_margin_and_cross_q_structure(
    tmp_path: Path,
) -> None:
    config, score, outputs = _fixture(tmp_path)
    candidate = build_t05_candidate(outputs, score, config=config)
    repeat = build_t05_candidate(outputs, score, config=config)
    assert candidate_to_json(repeat) == candidate_to_json(candidate)
    reasons = {
        row["primary_termination_reason"] for row in candidate["termination_records"]
    }
    assert reasons == {
        "raw_false",
        "quality_or_availability_termination",
        "input_end_open_right_censored",
    }
    subclasses = {
        row["raw_false_subclass"]
        for row in candidate["termination_records"]
        if row["raw_false_subclass"] is not None
    }
    assert {"A_ONLY_FAIL", "C_ONLY_FAIL", "CA_BOTH_FAIL"} <= subclasses
    assert any(
        row["reentry"]["next_raw_true_lag"] == 1
        and row["reentry"]["next_confirmed_true_lag"] == 5
        for row in candidate["termination_records"]
    )
    assert any(
        row["reentry"]["next_raw_true_status"] == "reentered"
        and row["reentry"]["next_raw_true_lag"] is not None
        and row["reentry"]["next_confirmed_true_lag"] is None
        for row in candidate["termination_records"]
        if not row["right_censored"]
    )
    gapped = next(
        row
        for row in candidate["termination_records"]
        if row["logical_request_name"] == "CA_q20_k5"
        and row["security_id"] == "S1"
        and row["termination_observation_sequence"] == 8
    )
    first_followup = next(
        row
        for row in gapped["reentry"]["followup_observations"]
        if row["observation_sequence"] == 9
    )
    assert first_followup["observation_lag"] == 1
    assert (
        date.fromisoformat(first_followup["trading_date"])
        - date.fromisoformat(gapped["termination_observation_date"])
    ) == timedelta(days=2)
    assert any(
        row["reentry"]["next_confirmed_true_status"] == "insufficient_followup_censored"
        for row in candidate["termination_records"]
        if not row["right_censored"]
    )
    assert any(
        row["reentry"]["next_confirmed_true_status"] == "quality_interrupted"
        for row in candidate["termination_records"]
        if not row["right_censored"]
    )
    q25_rows = candidate["cross_q_structure_summary"]
    assert q25_rows
    assert all(row["logical_request_name"] == "CA_q25_k5" for row in q25_rows)
    assert any(row["q20_fragmented_within_q25_parent"] for row in q25_rows)
    assert all(
        row["q25_only_shell_day_count"]
        == row["q25_parent_confirmed_day_count"]
        - row["q20_confirmed_day_count_inside_parent"]
        for row in q25_rows
    )
    assert len(candidate["daily_level_identities"]) == sum(
        row["q25_parent_confirmed_day_count"] for row in q25_rows
    )
    daily_keys = {
        (
            row["security_id"],
            row["observation_sequence"],
            row["q25_parent_interval_ordinal"],
        )
        for row in candidate["daily_level_identities"]
    }
    assert len(daily_keys) == len(candidate["daily_level_identities"])
    required_profile_fields = {
        "total_non_right_censored_termination_count",
        "observable_denominator",
        "reentered_count",
        "clean_not_reentered_count",
        "insufficient_followup_censored_count",
        "quality_interrupted_count",
        "reentry_rate",
    }
    assert all(
        required_profile_fields <= set(row)
        for row in candidate["quick_reentry_profile"]
    )
    assert all(
        row["observable_denominator"]
        == row["reentered_count"] + row["clean_not_reentered_count"]
        for row in candidate["quick_reentry_profile"]
    )
    child_rows = candidate["cross_q_child_structure_summary"]
    s1_children = [row for row in child_rows if row["security_id"] == "S1"]
    assert len(s1_children) == 2
    s1_parent = next(row for row in q25_rows if row["security_id"] == "S1")
    assert s1_parent["q25_parent_confirmed_day_count"] == 12
    assert s1_parent["q20_confirmed_day_count_inside_parent"] == 7
    assert s1_parent["q25_only_shell_day_count"] == 5
    assert [
        (
            row["q25_local_leading_shell_days"],
            row["q25_local_trailing_shell_days"],
        )
        for row in sorted(s1_children, key=lambda item: item["q20_interval_ordinal"])
    ] == [(0, 5), (5, 0)]
    assert all(
        row["q25_local_adjacent_shell_days"]
        == row["q25_local_leading_shell_days"] + row["q25_local_trailing_shell_days"]
        for row in s1_children
    )
    identities = {row["identity"] for row in candidate["daily_level_identities"]}
    assert identities <= {
        "Q10_CORE",
        "Q15_NOT_Q10_CORE",
        "Q20_NOT_Q15_ANCHOR",
        "Q25_NOT_Q20_SHELL",
    }
    signed = [
        row["min"]
        for row in candidate["threshold_margin_summary"]
        if row["min"] is not None
    ]
    assert any(value < 0 for value in signed)
    assert any(value > 0 for value in signed)
    assert all(
        metric["component_count"] == 2
        for record in candidate["termination_records"]
        for endpoint in (
            "last_confirmed_end_metrics",
            "termination_observation_metrics",
        )
        for metric in record[endpoint].values()
        if metric["observation_sequence"] is not None
    )


def test_validator_recomputes_and_blocks_mutations(tmp_path: Path) -> None:
    config, score, outputs = _fixture(tmp_path)
    candidate = build_t05_candidate(outputs, score, config=config)
    receipt = validate_t05_candidate(
        candidate, request_sources=outputs, score_source=score, config=config
    )
    assert receipt["status"] == "passed", receipt
    mutated = copy.deepcopy(candidate)
    next(
        row
        for row in mutated["termination_records"]
        if row["primary_termination_reason"] == "raw_false"
    )["raw_false_subclass"] = "raw_false_unclassified"
    blocked = validate_t05_candidate(
        mutated, request_sources=outputs, score_source=score, config=config
    )
    assert blocked["status"] == "blocked"
    assert any(
        reason.startswith("raw_false_subclass_mismatch")
        for reason in blocked["blocking_reasons"]
    )

    margin_mutation = copy.deepcopy(candidate)
    margin_mutation["termination_records"][0]["last_confirmed_end_metrics"]["C"][
        "mean_margin"
    ] *= -1
    blocked_margin = validate_t05_candidate(
        margin_mutation, request_sources=outputs, score_source=score, config=config
    )
    assert blocked_margin["status"] == "blocked"
    assert any(
        reason == "threshold_margin_formula_mismatch"
        or reason.startswith("threshold_margin_formula_mismatch:")
        for reason in blocked_margin["blocking_reasons"]
    )

    count_mutation = copy.deepcopy(candidate)
    count_mutation["request_reconciliation"][0]["actual"]["raw_true"] += 1
    blocked_count = validate_t05_candidate(
        count_mutation, request_sources=outputs, score_source=score, config=config
    )
    assert blocked_count["status"] == "blocked"
    assert (
        "independent_count_reconciliation_mismatch:CA_q10_k5"
        in blocked_count["blocking_reasons"]
    )

    profile_mutation = copy.deepcopy(candidate)
    profile_mutation["quick_reentry_profile"][0]["observable_denominator"] += 1
    blocked_profile = validate_t05_candidate(
        profile_mutation, request_sources=outputs, score_source=score, config=config
    )
    assert blocked_profile["status"] == "blocked"
    assert any(
        reason.startswith("quick_reentry_profile_count_mismatch")
        for reason in blocked_profile["blocking_reasons"]
    )

    rate_mutation = copy.deepcopy(candidate)
    rate_mutation["quick_reentry_profile"][0]["reentry_rate"] = 1.0
    blocked_rate = validate_t05_candidate(
        rate_mutation, request_sources=outputs, score_source=score, config=config
    )
    assert blocked_rate["status"] == "blocked"
    assert any(
        reason.startswith("quick_reentry_profile_rate_mismatch")
        for reason in blocked_rate["blocking_reasons"]
    )

    status_mutation = copy.deepcopy(candidate)
    non_right = next(
        row
        for row in status_mutation["termination_records"]
        if row["right_censored"] is False
    )
    non_right["reentry"]["raw_thresholds"]["1"]["status"] = "reentered"
    blocked_status = validate_t05_candidate(
        status_mutation, request_sources=outputs, score_source=score, config=config
    )
    assert blocked_status["status"] == "blocked"
    assert any(
        reason.startswith("reentry_threshold_observation_mismatch")
        for reason in blocked_status["blocking_reasons"]
    )


def _synthetic_followup_row(
    lag: int,
    *,
    raw_state: bool = False,
    confirmed_state: bool = False,
    quality: bool = False,
) -> dict[str, object]:
    return {
        "observation_sequence": lag,
        "trading_date": f"2026-02-{lag + 1:02d}",
        "raw_state": raw_state,
        "confirmed_state": confirmed_state,
        "expected_observation_status": "listing_pause" if quality else "present",
        "joint_ready": False if quality else True,
        "joint_validity_status": "blocked" if quality else "valid",
    }


def test_quick_reentry_thresholds_keep_observability_per_threshold() -> None:
    only_lag3 = [_synthetic_followup_row(3)]
    metrics = _followup_metrics(only_lag3, 0, 5, "raw_state", (1, 3, 5))
    assert metrics["thresholds"]["1"]["status"] == "not_reentered_within_window"
    assert metrics["thresholds"]["3"]["status"] == "not_reentered_within_window"
    assert metrics["thresholds"]["5"]["status"] == "insufficient_followup_censored"

    quality_lag4 = [_synthetic_followup_row(4, quality=True)]
    metrics = _followup_metrics(quality_lag4, 0, 5, "raw_state", (1, 3, 5))
    assert metrics["thresholds"]["1"]["status"] == "not_reentered_within_window"
    assert metrics["thresholds"]["3"]["status"] == "not_reentered_within_window"
    assert metrics["thresholds"]["5"]["status"] == "quality_interrupted"

    event_lag2_quality_lag4 = [
        _synthetic_followup_row(2, raw_state=True),
        _synthetic_followup_row(4, quality=True),
    ]
    metrics = _followup_metrics(event_lag2_quality_lag4, 0, 5, "raw_state", (1, 3, 5))
    assert metrics["thresholds"]["1"]["status"] == "not_reentered_within_window"
    assert metrics["thresholds"]["3"] == {"lag": 2, "status": "reentered"}
    assert metrics["thresholds"]["5"] == {"lag": 2, "status": "reentered"}

    quality_lag2_event_lag4 = [
        _synthetic_followup_row(2, quality=True),
        _synthetic_followup_row(4, raw_state=True),
    ]
    metrics = _followup_metrics(quality_lag2_event_lag4, 0, 5, "raw_state", (1, 3, 5))
    assert metrics["thresholds"]["1"]["status"] == "not_reentered_within_window"
    assert metrics["thresholds"]["3"]["status"] == "quality_interrupted"
    assert metrics["thresholds"]["5"]["status"] == "quality_interrupted"

    confirmed_lag5 = [_synthetic_followup_row(lag) for lag in range(1, 6)]
    metrics = _followup_metrics(confirmed_lag5, 0, 10, "confirmed_state", (5, 10))
    assert metrics["thresholds"]["5"]["status"] == "not_reentered_within_window"
    assert metrics["thresholds"]["10"]["status"] == "insufficient_followup_censored"


def test_forbidden_input_field_injection_is_rejected(tmp_path: Path) -> None:
    config, score, outputs = _fixture(tmp_path)
    with duckdb.connect(str(score)) as connection:
        connection.execute("ALTER TABLE daily_component_scores ADD COLUMN close DOUBLE")
        connection.execute("CHECKPOINT")
    with pytest.raises(T05Error, match="score_schema_contains_unapproved_field"):
        build_t05_candidate(outputs, score, config=config)


def test_subset_violation_fails_closed(tmp_path: Path) -> None:
    config, score, outputs = _fixture(tmp_path)
    with duckdb.connect(str(outputs["CA_q10_k5"])) as connection:
        connection.execute(
            "UPDATE daily_joint_states SET confirmed_state=true "
            "WHERE security_id='S1' AND observation_sequence=8"
        )
        connection.execute("CHECKPOINT")
    with pytest.raises(T05Error, match="cross_q_confirmed_subset_violation"):
        build_t05_candidate(outputs, score, config=config)


def test_child_crossing_two_parents_fails_closed(tmp_path: Path) -> None:
    config, score, outputs = _fixture(tmp_path)
    _mutate_q25_child_across_parent(outputs["CA_q25_k5"])
    with pytest.raises(T05Error, match="cross_q_parent_mapping_not_unique"):
        build_t05_candidate(outputs, score, config=config)
