from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.r2a.r2a_t06_formal_execution import FORMAL_REQUIRED_FILES
from src.r2a.r2a_t06_validator import (
    T06ValidationError,
    validate_t06_result_package,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (ROOT / "schemas/r2a/r2a_t06_result_package.schema.json").read_text(
        encoding="utf-8"
    )
)


def _files() -> list[dict[str, object]]:
    return [
        {
            "relative_path": name,
            "sha256": "0" * 64,
            "byte_size": 1,
            "storage_class": (
                "repository_local_detail"
                if name == "t06_detail.duckdb"
                else "compact_review"
            ),
        }
        for name in FORMAL_REQUIRED_FILES
    ]


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
        "accepted_run_id": "R2A-T06-SYNTHETIC" if formal else None,
        "reviewed_implementation_sha": (
            "2710d282fadcb998b80b9a482a5d55a4facc775a" if formal else None
        ),
        "reviewed_execution_sha": "2" * 40 if formal else None,
        "owner_result_review": "accepted" if accepted else "pending",
        "result_analysis_status": "completed_passed" if formal else "not_started",
        "blocking_anomaly_count": 0 if formal else None,
        "selected_exit_confirmation_m": 2 if accepted else None,
        "selection_principle": "minimum_sufficient_complexity",
        "selection_evidence": ["owner accepted M=2"] if accepted else [],
        "formal_run_executed": formal,
        "real_score_data_read": formal,
        "formal_artifacts_generated": formal,
        "R2A-T06_DONE": "present" if accepted else "absent",
        "R2A-T07_allowed_to_start": accepted,
        "R3_allowed_to_start": False,
        "files": _files() if formal else [],
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
    package = _package(status)
    Draft202012Validator(SCHEMA).validate(package)
    assert validate_t06_result_package(package)["status"] == "passed"


@pytest.mark.parametrize(
    "mutation",
    (
        lambda package: package.update({"selected_exit_confirmation_m": None}),
        lambda package: package.update({"files": []}),
        lambda package: package["files"].pop(),
        lambda package: package["files"].__setitem__(
            1, copy.deepcopy(package["files"][0])
        ),
        lambda package: package["validation"].update({"status": "failed"}),
        lambda package: package["validation"].update(
            {"independent_recalculation": False}
        ),
        lambda package: package["validation"].update(
            {"online_replay_equivalence": False}
        ),
        lambda package: package.update({"result_analysis_status": "completed_blocked"}),
        lambda package: package.update({"blocking_anomaly_count": 1}),
        lambda package: package.update({"owner_result_review": "pending"}),
    ),
)
def test_completed_accepted_rejects_incomplete_gate(mutation) -> None:
    package = _package("completed_accepted")
    mutation(package)
    assert list(Draft202012Validator(SCHEMA).iter_errors(package))
    with pytest.raises(T06ValidationError):
        validate_t06_result_package(package)


@pytest.mark.parametrize(
    "status", ("implementation_candidate", "formal_completed_pending_owner_review")
)
def test_preacceptance_stages_cannot_select_m(status: str) -> None:
    package = _package(status)
    package["selected_exit_confirmation_m"] = 2
    assert list(Draft202012Validator(SCHEMA).iter_errors(package))
