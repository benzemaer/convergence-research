from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t05_result_package.schema.json"


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _package(
    status: str,
    *,
    formal_run_started: bool,
    real_score_data_read: bool,
    formal_artifacts_generated: bool,
    done: str,
    t06_allowed: bool,
) -> dict[str, object]:
    return {
        "$schema": "../../schemas/r2a/r2a_t05_result_package.schema.json",
        "task_id": "R2A-T05",
        "package_schema_version": "r2a_t05_result_package.v1",
        "status": status,
        "scope_id": "r2a_t05_ca_exit_mechanism_decomposition.v1",
        "research_anchor_q": 2000,
        "research_anchor_role": "exit_mechanism_decomposition",
        "q_selection_status": "not_selected",
        "canonical_dynamic_request_selected": False,
        "formal_run_started": formal_run_started,
        "real_score_data_read": real_score_data_read,
        "formal_artifacts_generated": formal_artifacts_generated,
        "R2A-T05_DONE": done,
        "R2A-T06_allowed_to_start": t06_allowed,
        "request_identities": [
            {
                "logical_request_name": name,
                "request_id": f"pcavt-dynreq-v1-{index:016x}",
                "request_hash": "0" * 64,
                "selected_dimensions": ["C", "A"],
                "q_by_dimension": {"C": q, "A": q},
                "confirmation_k": 5,
                "selection_status": "evaluated_not_selected",
            }
            for index, (name, q) in enumerate(
                (
                    ("CA_q10_k5", 1000),
                    ("CA_q15_k5", 1500),
                    ("CA_q20_k5", 2000),
                    ("CA_q25_k5", 2500),
                ),
                start=1,
            )
        ],
        "files": [
            {
                "relative_path": "validation_receipt.json",
                "sha256": "0" * 64,
                "byte_size": 1,
                "storage_class": "repository_artifact",
            }
        ],
        "validation": {
            "status": "pending",
            "independent_recalculation": False,
            "request_identity_match": False,
            "t04_reconciliation_match": False,
            "cross_q_mapping_unique": False,
            "daily_identity_conservation": False,
            "forbidden_input_fields_absent": False,
            "deterministic_output": False,
        },
    }


VALID_STATES = (
    _package(
        "implementation_candidate",
        formal_run_started=False,
        real_score_data_read=False,
        formal_artifacts_generated=False,
        done="absent",
        t06_allowed=False,
    ),
    _package(
        "formal_completed_pending_owner_review",
        formal_run_started=True,
        real_score_data_read=True,
        formal_artifacts_generated=True,
        done="absent",
        t06_allowed=False,
    ),
    _package(
        "completed_accepted",
        formal_run_started=True,
        real_score_data_read=True,
        formal_artifacts_generated=True,
        done="present",
        t06_allowed=True,
    ),
)


@pytest.mark.parametrize("package", VALID_STATES)
def test_result_package_accepts_only_the_three_explicit_lifecycle_states(
    package: dict[str, object],
) -> None:
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(package)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda package: package.update({"status": "candidate"}),
        lambda package: package.update(
            {
                "status": "formal_completed_pending_owner_review",
                "formal_run_started": False,
            }
        ),
        lambda package: package.update(
            {"status": "completed_accepted", "R2A-T05_DONE": "absent"}
        ),
        lambda package: package.update(
            {
                "status": "formal_completed_pending_owner_review",
                "R2A-T06_allowed_to_start": True,
            }
        ),
        lambda package: package.update(
            {"status": "implementation_candidate", "real_score_data_read": True}
        ),
    ),
)
def test_result_package_rejects_lifecycle_mutations(mutation) -> None:
    package = deepcopy(VALID_STATES[0])
    mutation(package)
    validator = Draft202012Validator(_schema())
    assert list(validator.iter_errors(package))
