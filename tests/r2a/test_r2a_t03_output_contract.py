from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

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
    assert config["output_contract"] == contract_as_json()


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
