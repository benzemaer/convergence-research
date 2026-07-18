from __future__ import annotations

import ast
import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from src.r2a.r2a_t02_request_identity import canonicalize_request_spec

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r2a/r2a_t02_dynamic_state_protocol.v1.json"
SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t02_dynamic_state_protocol.schema.json"
IDENTITY_PATH = ROOT / "src/r2a/r2a_t02_request_identity.py"
CLI_PATH = ROOT / "scripts/r2a/build_r2a_t02_dynamic_request.py"
R2A_T02_ACCEPTED_ROOT = (
    ROOT / "data/generated/r2a/r2a_t02" / "pcavt_dynamic_state_protocol.v1"
)
R2A_T02_HANDOFF_PATH = R2A_T02_ACCEPTED_ROOT / "r2a_t02_accepted_protocol_handoff.json"
R2A_T02_DONE_PATH = R2A_T02_ACCEPTED_ROOT / "DONE"
DIMENSIONS = ("P", "C", "A", "V", "T")
Q_VALUES = (1000, 1500, 2000, 2500)


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def make_spec(
    selected: tuple[str, ...], q_values: tuple[int, ...], confirmation_k: int = 2
) -> dict[str, object]:
    return {
        "request_schema_version": "r2a_t02_dynamic_request_spec.v1",
        "dynamic_protocol_version": "pcavt_dynamic_state_protocol.v1",
        "score_release_id": "pcavt-score-w120-v1-c7e04f11a2cd09aa",
        "selected_dimensions": list(reversed(selected)),
        "q_by_dimension": dict(zip(selected, q_values, strict=True)),
        "confirmation_k": confirmation_k,
    }


def all_nonempty_subsets() -> list[tuple[str, ...]]:
    return [
        subset
        for count in range(1, len(DIMENSIONS) + 1)
        for subset in itertools.combinations(DIMENSIONS, count)
    ]


def test_protocol_config_schema_and_frozen_versions() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    config = load_config()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(config)
    assert config["dynamic_protocol_version"] == "pcavt_dynamic_state_protocol.v1"
    assert config["protocol_config_version"] == "r2a_t02_dynamic_state_protocol.v1"
    assert config["request_schemas"] == {
        "request_spec_schema_version": "r2a_t02_dynamic_request_spec.v1",
        "canonical_request_schema_version": "r2a_t02_dynamic_request.v1",
    }
    assert config["bound_score_release"]["accepted_handoff_sha256"] == (
        "142fa9f022025c6097a2651013a1434dae2eb153dc42da8d6450523571c192ad"
    )


def test_31_subsets_3124_q_specs_and_18744_q_k_specs() -> None:
    subsets = all_nonempty_subsets()
    assert len(subsets) == 31
    q_spec_count = 0
    scientific_spec_count = 0
    for selected in subsets:
        for q_values in itertools.product(Q_VALUES, repeat=len(selected)):
            q_spec_count += 1
            for confirmation_k in range(2, 8):
                canonical = canonicalize_request_spec(
                    make_spec(selected, q_values, confirmation_k)
                )
                assert canonical["selected_dimensions"] == list(selected)
                assert set(canonical["q_by_dimension"]) == set(selected)
                assert canonical["confirmation_k"] == confirmation_k
                assert (
                    canonical["dynamic_protocol_version"]
                    == "pcavt_dynamic_state_protocol.v1"
                )
                assert (
                    canonical["score_release_id"]
                    == "pcavt-score-w120-v1-c7e04f11a2cd09aa"
                )
                scientific_spec_count += 1
    assert q_spec_count == 3124
    assert scientific_spec_count == 18744


@pytest.mark.parametrize("confirmation_k", range(2, 8))
def test_each_formal_confirmation_k_is_accepted(confirmation_k: int) -> None:
    canonical = canonicalize_request_spec(
        make_spec(("P", "A"), (1000, 2500), confirmation_k)
    )
    assert canonical["confirmation_k"] == confirmation_k


def _active(score: float, score_min: float, q_bp: int) -> bool:
    epsilon = 1e-12
    main = 1 - q_bp / 10000
    weak = main - 0.10
    return score >= main - epsilon and score_min >= weak - epsilon


def test_main_and_weak_threshold_boundaries_plus_minus_epsilon() -> None:
    main = 0.85
    weak = 0.75
    assert _active(main - 1e-12, weak - 1e-12, 1500)
    assert not _active(main - 1.0001e-12, weak, 1500)
    assert not _active(main, weak - 1.0001e-12, 1500)


def _score_is_finite(value: object) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _joint_state(
    selected: tuple[str, ...],
    rows: dict[str, dict[str, object]],
    expected_status: str = "present",
) -> dict[str, object]:
    canonical_selected = [
        dimension for dimension in DIMENSIONS if dimension in selected
    ]
    joint_reasons: list[str] = []
    if expected_status == "missing":
        joint_reasons.append("expected_observation_missing")
    elif expected_status == "listing_pause":
        joint_reasons.append("expected_observation_listing_pause")

    active: list[bool] = []
    readiness: list[bool] = []
    validities: list[str] = []
    any_ineligible = False
    any_non_finite = False
    for dimension in canonical_selected:
        row = rows[dimension]
        validity = str(row["validity"])
        validities.append(validity)
        dimension_reasons = {str(reason) for reason in (row.get("reason_codes") or [])}
        if validity == "blocked":
            dimension_reasons.add("validity_blocked")
        elif validity == "diagnostic_required":
            dimension_reasons.add("validity_diagnostic_required")
        elif validity == "unknown":
            dimension_reasons.add("validity_unknown")
        ineligible = row["eligible"] is not True
        non_finite = not _score_is_finite(row["score"]) or not _score_is_finite(
            row["score_min"]
        )
        if ineligible:
            dimension_reasons.add("dimension_not_eligible")
        if non_finite:
            dimension_reasons.add("score_non_finite")
        joint_reasons.extend(
            f"{dimension}:{reason}" for reason in sorted(dimension_reasons)
        )
        ready = validity == "valid" and not ineligible and not non_finite
        readiness.append(ready)
        any_ineligible = any_ineligible or ineligible
        any_non_finite = any_non_finite or non_finite
        if ready:
            active.append(_active(float(row["score"]), float(row["score_min"]), 1500))
    joint_validity = next(
        status
        for status in ("blocked", "diagnostic_required", "unknown", "valid")
        if status in validities
    )
    joint_ready = expected_status == "present" and all(readiness)
    raw_state = all(active) if joint_ready else None
    if expected_status == "missing":
        primary = "expected_observation_missing"
    elif expected_status == "listing_pause":
        primary = "expected_observation_listing_pause"
    elif "blocked" in validities:
        primary = "selected_dimension_blocked"
    elif "diagnostic_required" in validities:
        primary = "selected_dimension_diagnostic_required"
    elif "unknown" in validities:
        primary = "selected_dimension_unknown"
    elif any_ineligible:
        primary = "selected_dimension_not_eligible"
    elif any_non_finite:
        primary = "selected_dimension_score_non_finite"
    elif raw_state is False:
        primary = "raw_false"
    else:
        primary = None
    return {
        "joint_validity": joint_validity,
        "joint_ready": joint_ready,
        "raw_state": raw_state,
        "reasons": joint_reasons,
        "primary": primary,
    }


def test_complete_case_no_short_circuit_and_unselected_isolation() -> None:
    rows = {
        "P": {"validity": "valid", "eligible": True, "score": 0.80, "score_min": 0.80},
        "C": {"validity": "valid", "eligible": False, "score": 0.90, "score_min": 0.80},
        "A": {"validity": "blocked", "eligible": False, "score": 0.0, "score_min": 0.0},
        "V": {
            "validity": "unknown",
            "eligible": False,
            "score": float("nan"),
            "score_min": 0.0,
        },
        "T": {"validity": "blocked", "eligible": False, "score": 0.0, "score_min": 0.0},
    }
    result = _joint_state(("P", "A", "V"), rows)
    assert result["joint_ready"] is False and result["raw_state"] is None
    assert result["joint_validity"] == "blocked"
    assert result["primary"] == "selected_dimension_blocked"
    assert result["reasons"] == [
        "A:dimension_not_eligible",
        "A:validity_blocked",
        "V:dimension_not_eligible",
        "V:score_non_finite",
        "V:validity_unknown",
    ]
    isolated = _joint_state(("P",), rows)
    assert isolated == {
        "joint_validity": "valid",
        "joint_ready": True,
        "raw_state": False,
        "reasons": [],
        "primary": "raw_false",
    }
    ineligible = _joint_state(("C",), rows)
    assert ineligible["joint_validity"] == "valid"
    assert ineligible["joint_ready"] is False
    assert ineligible["raw_state"] is None
    assert ineligible["reasons"] == ["C:dimension_not_eligible"]
    assert ineligible["primary"] == "selected_dimension_not_eligible"
    assert all(not reason.startswith("T:") for reason in result["reasons"])


def test_null_startup_row_is_valid_but_non_ready_without_exception() -> None:
    result = _joint_state(
        ("A",),
        {
            "A": {
                "validity": "valid",
                "eligible": False,
                "score": None,
                "score_min": None,
            }
        },
    )
    assert result == {
        "joint_validity": "valid",
        "joint_ready": False,
        "raw_state": None,
        "reasons": ["A:dimension_not_eligible", "A:score_non_finite"],
        "primary": "selected_dimension_not_eligible",
    }


@pytest.mark.parametrize("non_finite", [None, math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("field", ["score", "score_min"])
def test_all_null_nan_and_infinite_scores_are_non_finite(
    non_finite: float | None, field: str
) -> None:
    row: dict[str, object] = {
        "validity": "valid",
        "eligible": True,
        "score": 0.90,
        "score_min": 0.80,
    }
    row[field] = non_finite
    result = _joint_state(("V",), {"V": row})
    assert result["joint_validity"] == "valid"
    assert result["joint_ready"] is False
    assert result["raw_state"] is None
    assert result["reasons"] == ["V:score_non_finite"]
    assert result["primary"] == "selected_dimension_score_non_finite"


def test_upstream_reasons_are_prefixed_deduplicated_and_merged() -> None:
    result = _joint_state(
        ("A",),
        {
            "A": {
                "validity": "blocked",
                "eligible": False,
                "score": None,
                "score_min": None,
                "reason_codes": ["raw_metric_not_valid", "raw_metric_not_valid"],
            }
        },
    )
    assert result["reasons"] == [
        "A:dimension_not_eligible",
        "A:raw_metric_not_valid",
        "A:score_non_finite",
        "A:validity_blocked",
    ]
    assert result["primary"] == "selected_dimension_blocked"


def test_all_selected_failures_are_retained_and_blocked_has_priority() -> None:
    result = _joint_state(
        ("P", "A", "V"),
        {
            "P": {
                "validity": "valid",
                "eligible": True,
                "score": 0.20,
                "score_min": 0.20,
            },
            "A": {
                "validity": "blocked",
                "eligible": False,
                "score": None,
                "score_min": None,
                "reason_codes": ["raw_metric_not_valid"],
            },
            "V": {
                "validity": "unknown",
                "eligible": False,
                "score": None,
                "score_min": None,
                "reason_codes": ["source_missing"],
            },
        },
    )
    assert result["raw_state"] is None
    assert result["joint_validity"] == "blocked"
    assert result["primary"] == "selected_dimension_blocked"
    assert result["reasons"] == [
        "A:dimension_not_eligible",
        "A:raw_metric_not_valid",
        "A:score_non_finite",
        "A:validity_blocked",
        "V:dimension_not_eligible",
        "V:score_non_finite",
        "V:source_missing",
        "V:validity_unknown",
    ]


@pytest.mark.parametrize(
    ("expected_status", "joint_reason", "primary"),
    [
        ("missing", "expected_observation_missing", "expected_observation_missing"),
        (
            "listing_pause",
            "expected_observation_listing_pause",
            "expected_observation_listing_pause",
        ),
    ],
)
def test_expected_observation_reason_precedes_dimension_failures(
    expected_status: str, joint_reason: str, primary: str
) -> None:
    result = _joint_state(
        ("C",),
        {
            "C": {
                "validity": "blocked",
                "eligible": False,
                "score": None,
                "score_min": None,
            }
        },
        expected_status,
    )
    assert result["primary"] == primary
    assert result["reasons"][0] == joint_reason
    assert result["reasons"][1:] == [
        "C:dimension_not_eligible",
        "C:score_non_finite",
        "C:validity_blocked",
    ]


def test_unselected_dimension_failures_are_fully_isolated() -> None:
    rows = {
        "P": {
            "validity": "valid",
            "eligible": True,
            "score": 0.90,
            "score_min": 0.80,
        },
        "A": {
            "validity": "blocked",
            "eligible": False,
            "score": None,
            "score_min": math.inf,
            "reason_codes": ["must_not_escape"],
        },
        "V": {
            "validity": "unknown",
            "eligible": False,
            "score": math.nan,
            "score_min": -math.inf,
            "reason_codes": ["also_isolated"],
        },
    }
    assert _joint_state(("P",), rows) == {
        "joint_validity": "valid",
        "joint_ready": True,
        "raw_state": True,
        "reasons": [],
        "primary": None,
    }


@pytest.mark.parametrize(
    ("row", "primary", "reason"),
    [
        (
            {
                "validity": "blocked",
                "eligible": True,
                "score": 0.90,
                "score_min": 0.80,
            },
            "selected_dimension_blocked",
            "C:validity_blocked",
        ),
        (
            {
                "validity": "diagnostic_required",
                "eligible": True,
                "score": 0.90,
                "score_min": 0.80,
            },
            "selected_dimension_diagnostic_required",
            "C:validity_diagnostic_required",
        ),
        (
            {
                "validity": "unknown",
                "eligible": True,
                "score": 0.90,
                "score_min": 0.80,
            },
            "selected_dimension_unknown",
            "C:validity_unknown",
        ),
        (
            {
                "validity": "valid",
                "eligible": False,
                "score": 0.90,
                "score_min": 0.80,
            },
            "selected_dimension_not_eligible",
            "C:dimension_not_eligible",
        ),
        (
            {
                "validity": "valid",
                "eligible": True,
                "score": None,
                "score_min": 0.80,
            },
            "selected_dimension_score_non_finite",
            "C:score_non_finite",
        ),
        (
            {
                "validity": "valid",
                "eligible": True,
                "score": 0.20,
                "score_min": 0.20,
            },
            "raw_false",
            None,
        ),
    ],
)
def test_each_selected_dimension_primary_termination_category(
    row: dict[str, object], primary: str, reason: str | None
) -> None:
    result = _joint_state(("C",), {"C": row})
    assert result["primary"] == primary
    if reason is None:
        assert result["reasons"] == []
    else:
        assert reason in result["reasons"]


def _protocol_oracle(
    raw_states: list[bool | None], statuses: list[str], k: int
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    daily: list[dict[str, object]] = []
    intervals: list[dict[str, object]] = []
    streak = 0
    open_start: int | None = None
    last_confirmed: int | None = None
    for index, (raw, status) in enumerate(zip(raw_states, statuses, strict=True)):
        if status != "present":
            raw = None
        if raw is True:
            streak = streak + 1 if daily and daily[-1]["raw"] is True else 1
            confirmed: bool | None = streak >= k
        elif raw is False:
            streak = 0
            confirmed = False
        else:
            streak = None
            confirmed = None
        if confirmed is True:
            if open_start is None:
                open_start = index
            last_confirmed = index
        elif open_start is not None:
            if status == "missing":
                reason = "expected_observation_missing"
            elif status == "listing_pause":
                reason = "expected_observation_listing_pause"
            elif raw is None:
                reason = "selected_dimension_unknown"
            else:
                reason = "raw_false"
            intervals.append(
                {"start": open_start, "end": last_confirmed, "reason": reason}
            )
            open_start = None
            last_confirmed = None
        daily.append({"raw": raw, "streak": streak, "confirmed": confirmed})
        if streak is None:
            streak = 0
    if open_start is not None:
        intervals.append(
            {
                "start": open_start,
                "end": last_confirmed,
                "reason": "input_end_open_right_censored",
            }
        )
    return daily, intervals


def test_streak_k_confirmation_no_backfill_and_false_termination() -> None:
    daily, intervals = _protocol_oracle(
        [True, True, True, True, False], ["present"] * 5, 3
    )
    assert [row["streak"] for row in daily] == [1, 2, 3, 4, 0]
    assert [row["confirmed"] for row in daily] == [False, False, True, True, False]
    assert intervals == [{"start": 2, "end": 3, "reason": "raw_false"}]


def test_null_missing_and_listing_pause_interrupt_without_skipping() -> None:
    daily, intervals = _protocol_oracle(
        [True, True, None, True, True, True], ["present"] * 6, 3
    )
    assert [row["streak"] for row in daily] == [1, 2, None, 1, 2, 3]
    assert intervals == [
        {"start": 5, "end": 5, "reason": "input_end_open_right_censored"}
    ]
    for status, reason in (
        ("missing", "expected_observation_missing"),
        ("listing_pause", "expected_observation_listing_pause"),
    ):
        daily, intervals = _protocol_oracle(
            [True, True, True, True], ["present", "present", "present", status], 2
        )
        assert daily[-1] == {"raw": None, "streak": None, "confirmed": None}
        assert intervals == [{"start": 1, "end": 2, "reason": reason}]


def test_open_right_censored_zero_interval_and_k1_math_boundary() -> None:
    daily, intervals = _protocol_oracle([True, True, True], ["present"] * 3, 2)
    assert intervals == [
        {"start": 1, "end": 2, "reason": "input_end_open_right_censored"}
    ]
    _, zero = _protocol_oracle([False, False, True], ["present"] * 3, 3)
    assert zero == []
    k1_daily, _ = _protocol_oracle([True], ["present"], 1)
    assert k1_daily[0]["confirmed"] is True


def test_termination_priority_and_zero_event_contract() -> None:
    config = load_config()
    assert config["joint_state"]["validity_priority"] == [
        "blocked",
        "diagnostic_required",
        "unknown",
        "valid",
    ]
    assert config["termination"]["primary_reason_priority"] == [
        "expected_observation_missing",
        "expected_observation_listing_pause",
        "selected_dimension_blocked",
        "selected_dimension_diagnostic_required",
        "selected_dimension_unknown",
        "selected_dimension_not_eligible",
        "selected_dimension_score_non_finite",
        "raw_false",
    ]
    assert [
        item["primary"] for item in config["termination"]["primary_reason_derivation"]
    ] == config["termination"]["primary_reason_priority"]
    assert (
        config["termination"]["input_end_open_interval_primary"]
        == "input_end_open_right_censored"
    )
    assert config["termination"]["input_end_derivation_is_separate_from_priority"]
    derivation = config["joint_non_ready_reason_derivation"]
    assert derivation["null_safe_score_check"] is True
    assert derivation["derived_reason_vocabulary"] == [
        "validity_blocked",
        "validity_diagnostic_required",
        "validity_unknown",
        "dimension_not_eligible",
        "score_non_finite",
    ]
    assert derivation["joint_validity_and_joint_ready_are_distinct"] is True
    assert config["json_input_policy"]["duplicate_object_member_behavior"] == "reject"
    assert (
        config["json_input_policy"]["duplicate_object_member_reason_code"]
        == "duplicate_json_object_key"
    )
    assert config["zero_event"]["request_status"] == "completed"
    assert config["zero_event"]["confirmed_interval_count"] == 0
    assert config["zero_event"]["interval_table"] == "valid_zero_row_table"


def test_t02_production_surface_has_no_duckdb_or_evaluator() -> None:
    for path in (IDENTITY_PATH, CLI_PATH):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert "duckdb" not in imports
        assert ".duckdb" not in source
    identity_functions = {
        node.name
        for node in ast.parse(IDENTITY_PATH.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
    }
    assert not identity_functions.intersection(
        {"dimension_active", "evaluate", "evaluate_state", "build_intervals"}
    )


def test_t02_done_matches_protocol_acceptance_state() -> None:
    config = load_config()
    status = config["status"]
    if status == "protocol_freeze_candidate_pending_review":
        assert not R2A_T02_HANDOFF_PATH.exists()
        assert not R2A_T02_DONE_PATH.exists()
        return
    if status != "accepted":
        pytest.fail(f"unknown R2A-T02 protocol status: {status!r}")

    assert R2A_T02_HANDOFF_PATH.is_file()
    assert R2A_T02_DONE_PATH.is_file()
    accepted_root_done_files = list(R2A_T02_ACCEPTED_ROOT.rglob("DONE"))
    assert accepted_root_done_files == [R2A_T02_DONE_PATH]
    accepted_versions = list(
        R2A_T02_ACCEPTED_ROOT.parent.glob("*/r2a_t02_accepted_protocol_handoff.json")
    )
    assert accepted_versions == [R2A_T02_HANDOFF_PATH]

    handoff = json.loads(R2A_T02_HANDOFF_PATH.read_text(encoding="utf-8"))
    done = json.loads(R2A_T02_DONE_PATH.read_text(encoding="utf-8"))
    assert handoff["status"] == "completed_accepted"
    assert handoff["protocol_review_status"] == "accepted"
    assert handoff["dynamic_protocol_version"] == ("pcavt_dynamic_state_protocol.v1")
    assert done["acceptance_status"] == "completed_accepted"

    handoff_sha256 = hashlib.sha256(R2A_T02_HANDOFF_PATH.read_bytes()).hexdigest()
    config_sha256 = hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()
    assert done["accepted_protocol_handoff_sha256"] == handoff_sha256
    assert done["accepted_protocol_config_sha256"] == config_sha256
    assert done["dynamic_protocol_version"] == handoff["dynamic_protocol_version"]
    assert done["reviewed_protocol_head"] == handoff["reviewed_protocol_head"]
    assert done["golden_request_hash"] == handoff["golden_identity"]["request_hash"]
