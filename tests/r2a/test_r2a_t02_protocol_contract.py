from __future__ import annotations

import ast
import itertools
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.r2a.r2a_t02_request_identity import canonicalize_request_spec

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r2a/r2a_t02_dynamic_state_protocol.v1.json"
SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t02_dynamic_state_protocol.schema.json"
IDENTITY_PATH = ROOT / "src/r2a/r2a_t02_request_identity.py"
CLI_PATH = ROOT / "scripts/r2a/build_r2a_t02_dynamic_request.py"
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
    for selected in subsets:
        for q_values in itertools.product(Q_VALUES, repeat=len(selected)):
            canonical = canonicalize_request_spec(make_spec(selected, q_values))
            assert canonical["selected_dimensions"] == list(selected)
            q_spec_count += 1
    assert q_spec_count == 3124
    assert q_spec_count * len(range(2, 8)) == 18744


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


def _joint_state(
    selected: tuple[str, ...], rows: dict[str, dict[str, object]]
) -> tuple[bool, bool | None, list[str]]:
    reasons: list[str] = []
    active: list[bool] = []
    for dimension in selected:
        row = rows[dimension]
        dimension_reasons: list[str] = []
        if row["validity"] != "valid":
            dimension_reasons.append(str(row["validity"]))
        if not row["eligible"]:
            dimension_reasons.append("dimension_not_eligible")
        if not math.isfinite(float(row["score"])) or not math.isfinite(
            float(row["score_min"])
        ):
            dimension_reasons.append("score_non_finite")
        reasons.extend(
            f"{dimension}:{reason}" for reason in sorted(set(dimension_reasons))
        )
        ready = not dimension_reasons
        if ready:
            active.append(_active(float(row["score"]), float(row["score_min"]), 1500))
    joint_ready = not reasons
    return joint_ready, all(active) if joint_ready else None, reasons


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
    ready, raw, reasons = _joint_state(("P", "A", "V"), rows)
    assert ready is False and raw is None
    assert reasons == [
        "A:blocked",
        "A:dimension_not_eligible",
        "V:dimension_not_eligible",
        "V:score_non_finite",
        "V:unknown",
    ]
    isolated_ready, isolated_raw, isolated_reasons = _joint_state(("P",), rows)
    assert isolated_ready is True and isolated_raw is False
    assert isolated_reasons == []
    eligible_ready, eligible_raw, eligible_reasons = _joint_state(("C",), rows)
    assert eligible_ready is False and eligible_raw is None
    assert eligible_reasons == ["C:dimension_not_eligible"]
    assert all(not reason.startswith("T:") for reason in reasons)


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
    assert config["zero_event"]["request_status"] == "completed"
    assert config["zero_event"]["confirmed_interval_count"] == 0
    assert config["zero_event"]["interval_table"] == "valid_zero_row_table"


def test_production_surface_has_no_duckdb_or_evaluator_and_no_t02_done() -> None:
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
    assert not list((ROOT / "data/generated/r2a/r2a_t02").glob("**/DONE"))
