from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from src.r2a.r2a_t03_dynamic_evaluator import (
    NON_GOALS,
    SECURITY_SCOPE_CONTRACT,
    TERMINATION_PRIORITY,
    ZERO_EVENT_BEHAVIOR,
    algorithm_contract_as_json,
    source_contract_as_json,
)
from src.r2a.r2a_t03_output_contract import (
    EVALUATOR_VERSION,
    OUTPUT_SCHEMA_VERSION,
    DynamicOutputValidationError,
    contract_as_json,
    validate_dynamic_evaluation_output,
)
from tests.r2a.r2a_t03_test_support import create_source, evaluate

ROOT = Path(__file__).resolve().parents[2]


def test_config_schema_and_python_contract_are_identical() -> None:
    config = json.loads(
        (ROOT / "configs/r2a/r2a_t03_dynamic_evaluator.v1.json").read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(
        (ROOT / "schemas/r2a/r2a_t03_dynamic_evaluator.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(config)
    assert config["evaluator_version"] == EVALUATOR_VERSION
    assert config["output_schema_version"] == OUTPUT_SCHEMA_VERSION
    assert config["input_contract"] == source_contract_as_json()
    assert config["security_scope_contract"] == SECURITY_SCOPE_CONTRACT
    assert config["algorithms"] == algorithm_contract_as_json()
    assert config["termination_priority"] == TERMINATION_PRIORITY
    assert config["zero_event_behavior"] == ZERO_EVENT_BEHAVIOR
    assert config["non_goals"] == NON_GOALS
    assert config["output_contract"] == contract_as_json()
    changed_algorithm = copy.deepcopy(config)
    changed_algorithm["algorithms"]["joint_formula"] = "tampered"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(changed_algorithm)
    changed_input = copy.deepcopy(config)
    changed_input["input_contract"]["tables"]["daily_dimension_scores"][0] = (
        "wrong:VARCHAR"
    )
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(changed_input)


def test_output_validator_accepts_complete_and_zero_event_outputs() -> None:
    source = create_source()
    complete = evaluate(source)
    assert validate_dynamic_evaluation_output(complete).confirmed_interval_count == 3
    zero = evaluate(source, security_ids=["S3"])
    summary = validate_dynamic_evaluation_output(zero)
    assert summary.confirmed_interval_count == 0
    assert zero.execute("SELECT count(*) FROM confirmed_intervals").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            "UPDATE daily_dimension_states SET dimension_active=NULL "
            "WHERE security_id='S1' AND observation_sequence=0 AND dimension_id='P'",
            "dimension_active_readiness_mismatch",
        ),
        (
            "UPDATE daily_joint_states SET raw_streak=99 "
            "WHERE security_id='S1' AND observation_sequence=0",
            "raw_streak_mismatch",
        ),
        (
            "UPDATE daily_joint_states SET confirmation_event=true "
            "WHERE security_id='S1' AND observation_sequence=0",
            "confirmation_event_mismatch",
        ),
        (
            "UPDATE confirmed_intervals SET termination_date=NULL "
            "WHERE security_id='S1' AND interval_ordinal=0",
            "interval_boundary_mismatch",
        ),
    ],
)
def test_output_validator_independently_rejects_mutations(
    mutation: str, reason: str
) -> None:
    output = evaluate(create_source())
    output.execute(mutation)
    with pytest.raises(DynamicOutputValidationError, match=reason):
        validate_dynamic_evaluation_output(output)


def test_output_validator_rejects_an_extra_table() -> None:
    output = evaluate(create_source())
    output.execute("CREATE TABLE unexpected(value INTEGER)")
    with pytest.raises(
        DynamicOutputValidationError, match="output_table_inventory_mismatch"
    ):
        validate_dynamic_evaluation_output(output)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            "UPDATE daily_dimension_states SET q_bp=q_bp+500 "
            "WHERE security_id='S1' AND observation_sequence=0 "
            "AND dimension_id='P'",
            "dimension_q_mismatch",
        ),
        (
            "UPDATE daily_dimension_states SET main_threshold=main_threshold+0.01 "
            "WHERE security_id='S1' AND observation_sequence=0 "
            "AND dimension_id='P'",
            "dimension_threshold_mismatch",
        ),
        (
            "UPDATE daily_dimension_states SET weak_threshold=weak_threshold+0.01 "
            "WHERE security_id='S1' AND observation_sequence=0 "
            "AND dimension_id='P'",
            "dimension_threshold_mismatch",
        ),
        (
            "UPDATE daily_dimension_states SET dimension_active=false "
            "WHERE security_id='S1' AND observation_sequence=0 "
            "AND dimension_id='P'",
            "dimension_active_semantics_mismatch",
        ),
        (
            "UPDATE daily_dimension_states SET dimension_ready=false, "
            "dimension_active=NULL WHERE security_id='S1' "
            "AND observation_sequence=0 AND dimension_id='P'",
            "dimension_ready_semantics_mismatch",
        ),
        (
            "UPDATE daily_dimension_states SET dimension_reason_codes=['tampered'] "
            "WHERE security_id='S1' AND observation_sequence=0 "
            "AND dimension_id='P'",
            "dimension_reason_codes_mismatch",
        ),
        (
            "UPDATE daily_dimension_states SET dimension_active=false "
            "WHERE security_id='S1' AND observation_sequence=0 "
            "AND dimension_id='P'; UPDATE daily_joint_states SET raw_state=false "
            "WHERE security_id='S1' AND observation_sequence=0",
            "dimension_active_semantics_mismatch",
        ),
        (
            "UPDATE daily_joint_states SET joint_ready=false, raw_state=NULL "
            "WHERE security_id='S1' AND observation_sequence=0",
            "joint_ready_semantics_mismatch",
        ),
        (
            "UPDATE daily_joint_states SET joint_validity_status='blocked' "
            "WHERE security_id='S1' AND observation_sequence=0",
            "joint_validity_mismatch",
        ),
        (
            "UPDATE daily_joint_states SET joint_reason_codes=['tampered'] "
            "WHERE security_id='S1' AND observation_sequence=0",
            "joint_reason_codes_mismatch",
        ),
        (
            "UPDATE daily_joint_states SET raw_state=false "
            "WHERE security_id='S1' AND observation_sequence=0",
            "raw_state_semantics_mismatch",
        ),
        (
            "UPDATE daily_joint_states SET raw_streak_start_date=trading_date+1 "
            "WHERE security_id='S1' AND observation_sequence=0",
            "raw_streak_start_mismatch",
        ),
        (
            "UPDATE daily_joint_states SET confirmed_interval_ordinal=9 "
            "WHERE security_id='S1' AND observation_sequence=2",
            "confirmed_interval_ordinal_mismatch",
        ),
        (
            "UPDATE daily_joint_states SET confirmed_interval_ordinal=0 "
            "WHERE security_id='S1' AND observation_sequence=0",
            "confirmed_interval_ordinal_mismatch",
        ),
        (
            "UPDATE daily_joint_states SET confirmed_interval_ordinal=0 "
            "WHERE security_id='S1' AND confirmed_interval_ordinal=1",
            "confirmed_interval_ordinal_mismatch",
        ),
        (
            "UPDATE confirmed_intervals SET raw_start_date=confirmation_date "
            "WHERE security_id='S1' AND interval_ordinal=0",
            "interval_raw_start_mismatch",
        ),
        (
            "UPDATE confirmed_intervals SET raw_start_observation_sequence="
            "confirmation_observation_sequence WHERE security_id='S1' "
            "AND interval_ordinal=0",
            "interval_raw_start_mismatch",
        ),
        (
            "UPDATE confirmed_intervals SET selected_dimensions=['P'] "
            "WHERE security_id='S1' AND interval_ordinal=0",
            "interval_request_parameters_mismatch",
        ),
        (
            "UPDATE confirmed_intervals SET q_by_dimension='{}' "
            "WHERE security_id='S1' AND interval_ordinal=0",
            "interval_request_parameters_mismatch",
        ),
        (
            "UPDATE confirmed_intervals SET confirmation_k=2 "
            "WHERE security_id='S1' AND interval_ordinal=0",
            "interval_request_parameters_mismatch",
        ),
        (
            "UPDATE confirmed_intervals SET right_censored=true, "
            "termination_date=NULL, termination_observation_sequence=NULL, "
            "termination_reason='input_end_open_right_censored', "
            "termination_reason_codes=[]::VARCHAR[] "
            "WHERE security_id='S1' AND interval_ordinal=0",
            "right_censored_not_at_input_end",
        ),
        (
            "UPDATE evaluation_scope SET date_min=date_min+1",
            "scope_date_coverage_mismatch",
        ),
        (
            "UPDATE evaluation_scope SET date_max=date_max-1",
            "scope_date_coverage_mismatch",
        ),
    ],
)
def test_independent_validator_rejects_coupled_mutations(
    mutation: str, reason: str
) -> None:
    output = evaluate(create_source())
    for statement in mutation.split("; "):
        output.execute(statement)
    with pytest.raises(DynamicOutputValidationError, match=reason):
        validate_dynamic_evaluation_output(output)


def test_scope_security_set_and_canonical_q_are_independently_validated() -> None:
    explicit = evaluate(create_source(), security_ids=["S1", "S3"])
    explicit.execute("UPDATE evaluation_scope SET requested_security_ids=['S1','S2']")
    with pytest.raises(
        DynamicOutputValidationError, match="scope_security_set_mismatch"
    ):
        validate_dynamic_evaluation_output(explicit)

    for q_text in (
        '{"A": 1500, "P": 1500}',
        '{"A":1500,"A":1500,"P":1500}',
    ):
        output = evaluate(create_source())
        output.execute("UPDATE dynamic_request SET q_by_dimension=?", [q_text])
        with pytest.raises(
            DynamicOutputValidationError, match="q_by_dimension_not_canonical"
        ):
            validate_dynamic_evaluation_output(output)
