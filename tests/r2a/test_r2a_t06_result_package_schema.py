from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (ROOT / "schemas/r2a/r2a_t06_result_package.schema.json").read_text(
        encoding="utf-8"
    )
)


def _package(status: str) -> dict[str, object]:
    formal = status != "implementation_candidate"
    accepted = status == "completed_accepted"
    return {
        "task_id": "R2A-T06",
        "package_schema_version": "r2a_t06_result_package.v1",
        "status": status,
        "scope_id": "r2a_t06_consecutive_failure_exit_confirmation.v1",
        "q_selection_status": "not_selected",
        "canonical_dynamic_request_selected": False,
        "winner_selected": accepted,
        "formal_run_executed": formal,
        "real_score_data_read": formal,
        "formal_artifacts_generated": formal,
        "R2A-T06_DONE": "present" if accepted else "absent",
        "R2A-T07_allowed_to_start": accepted,
        "R3_allowed_to_start": False,
        "files": [],
        "validation": {
            "status": "passed" if formal else "pending",
            "independent_recalculation": formal,
            "accepted_daily_fact_immutability": formal,
            "online_replay_equivalence": formal,
            "deterministic_output": formal,
            "parallel_consistency": formal,
            "cross_q_nesting": formal,
        },
    }


@pytest.mark.parametrize(
    "status",
    (
        "implementation_candidate",
        "formal_completed_pending_owner_review",
        "completed_accepted",
    ),
)
def test_explicit_result_package_lifecycle_states(status: str) -> None:
    Draft202012Validator.check_schema(SCHEMA)
    Draft202012Validator(SCHEMA).validate(_package(status))


def test_implementation_package_cannot_claim_formal_or_done() -> None:
    package = copy.deepcopy(_package("implementation_candidate"))
    package["formal_run_executed"] = True
    assert list(Draft202012Validator(SCHEMA).iter_errors(package))
