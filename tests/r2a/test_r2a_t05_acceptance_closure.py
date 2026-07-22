from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "R2A-T05-20260722T012719685Z"
CLOSURE_ROOT = ROOT / "data/generated/r2a/r2a_t05" / RUN_ID
HANDOFF_PATH = CLOSURE_ROOT / "r2a_t05_accepted_result_handoff.json"
DONE_PATH = CLOSURE_ROOT / "DONE"
SCHEMA_PATH = ROOT / "schemas/r2a/r2a_t05_accepted_result_handoff.schema.json"
EXPECTED_HANDOFF_SHA256 = (
    "6d69a6526d14f4844fdc1f5b888bb87768c7eedb58b65ea76445eede3d1a6881"
)
EXPECTED_COUNTS = {
    "CA_q10_k5": (20559, 1916, 751, 473),
    "CA_q15_k5": (46651, 7125, 2426, 734),
    "CA_q20_k5": (81535, 17642, 5372, 775),
    "CA_q25_k5": (124893, 35098, 9107, 788),
}
EXPECTED_REQUESTS = {
    "CA_q10_k5": (
        "pcavt-dynreq-v1-d07aae4bbbd98f88",
        "d07aae4bbbd98f88989cf6b50c3b808935f237cd69f56271f6a210aa90f7ac8f",
        1000,
    ),
    "CA_q15_k5": (
        "pcavt-dynreq-v1-cf420e9c025374d1",
        "cf420e9c025374d19bbc4e83bd75fee96d10d0c322605826ae5cffcf4029674f",
        1500,
    ),
    "CA_q20_k5": (
        "pcavt-dynreq-v1-21bd144aaed98d9e",
        "21bd144aaed98d9e7d404aaa8d2fa0685f7ec29a3deb714d0d1df99c05d5e971",
        2000,
    ),
    "CA_q25_k5": (
        "pcavt-dynreq-v1-b210f9e5211c46db",
        "b210f9e5211c46db6cbc41ca1da9ff340018b4ef69e56df07ae22cecafbad3e9",
        2500,
    ),
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_accepted_handoff_matches_schema_and_done_hash_chain() -> None:
    schema = _load(SCHEMA_PATH)
    handoff = _load(HANDOFF_PATH)
    handoff_bytes = HANDOFF_PATH.read_bytes()
    done = _load(DONE_PATH)

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(handoff)
    actual_sha = hashlib.sha256(handoff_bytes).hexdigest()

    assert actual_sha == EXPECTED_HANDOFF_SHA256
    assert done["accepted_handoff_sha256"] == actual_sha
    assert done["accepted_handoff_filename"] == HANDOFF_PATH.name
    assert done["status"] == handoff["status"] == "completed_accepted"
    assert done["accepted_run_id"] == handoff["accepted_run_id"] == RUN_ID
    assert handoff["accepted_execution_head"] == (
        "260c3e1fe040eb9a44ee64f54a01142e6c3d8efa"
    )


def test_attempt_acceptance_remediation_and_validation_are_exact() -> None:
    handoff = _load(HANDOFF_PATH)
    done = _load(DONE_PATH)
    lifecycle = handoff["formal_attempt_lifecycle"]
    acceptance = handoff["formal_result_acceptance"]
    remediation = handoff["post_run_artifact_remediation"]
    validation = handoff["validation"]

    assert lifecycle["formal_run_attempt_limit"] == 2
    assert lifecycle["formal_run_attempts_consumed"] == 2
    assert lifecycle["additional_formal_run_allowed"] is False
    assert [
        (row["attempt_number"], row["status"]) for row in lifecycle["attempts"]
    ] == [
        (1, "failed_closed"),
        (2, "completed_accepted"),
    ]
    assert acceptance == {
        "blocking_anomalies": [],
        "formal_result_candidate_status": "passed",
        "formal_technical_acceptance": "passed",
        "owner_acceptance_status": "accepted",
        "owner_result_review": "accepted",
        "scientific_review_status": "passed",
    }
    assert remediation["status"] == "owner_authorized_completed"
    assert remediation["normalized_csv_count"] == 11
    assert remediation["authorized_RunRoot_changed_file_count"] == 13
    assert remediation["unauthorized_RunRoot_changed_file_count"] == 0
    assert remediation["scientific_recomputation"] is False
    assert remediation["formal_reexecution"] is False
    assert remediation["formal_attempt_consumed"] is False
    assert (
        remediation["formal_package_modified_between_execution_and_acceptance"] is True
    )
    assert remediation["CSV_parse_equivalence"] == "passed"
    assert remediation["text_contract_after_remediation"] == "passed"
    assert validation == {
        "T04_reconciliation_match": True,
        "artifact_identity_match": True,
        "blocking_reasons": [],
        "cross_q_mapping_unique": True,
        "daily_identity_conservation": True,
        "deterministic_output": True,
        "forbidden_input_fields_absent": True,
        "request_identity_match": True,
        "result_package_schema_match": True,
        "status": "passed",
        "text_contract_match": True,
    }
    assert done["formal_run_attempt_limit"] == 2
    assert done["formal_run_attempts_consumed"] == 2
    assert done["additional_formal_run_allowed"] is False


def test_package_request_and_scientific_facts_are_exact() -> None:
    handoff = _load(HANDOFF_PATH)
    identities = handoff["evidence_identities"]
    assert identities["artifact_manifest"] == {
        "storage_class": "formal_run_root",
        "relative_locator": (
            "data/generated/r2a/r2a_t05/formal-runs/"
            "R2A-T05-20260722T012719685Z/artifact_manifest.json"
        ),
        "sha256": "1f61296fa97337f9735b42ba2301fa58380712c6c721a7083d7004535acb22e0",
        "byte_size": 6936,
    }
    assert identities["result_package"] == {
        "storage_class": "formal_run_root",
        "relative_locator": (
            "data/generated/r2a/r2a_t05/formal-runs/"
            "R2A-T05-20260722T012719685Z/result_package.json"
        ),
        "sha256": "1cafc65beed826a3cf5e08b4237656e36f32a768197dd19ee57d9eb7cb913913",
        "byte_size": 9649,
    }

    assert [
        row["logical_request_name"] for row in handoff["request_reconciliation"]
    ] == list(EXPECTED_COUNTS)
    for row in handoff["request_reconciliation"]:
        name = row["logical_request_name"]
        request_id, request_hash, q = EXPECTED_REQUESTS[name]
        assert (
            row["raw_true"],
            row["confirmed_true"],
            row["intervals"],
            row["securities_with_interval"],
        ) == EXPECTED_COUNTS[name]
        assert row["request_id"] == request_id
        assert row["request_hash"] == request_hash
        assert row["selected_dimensions"] == ["C", "A"]
        assert row["q_by_dimension"] == {"C": q, "A": q}
        assert row["confirmation_k"] == 5
        assert row["selection_status"] == "evaluated_not_selected"

    scientific = handoff["scientific_result_summary"]
    assert scientific["total_confirmed_intervals"] == 5372
    assert scientific["termination_primary"] == {
        "raw_false": 5363,
        "quality_or_availability_termination": 8,
        "input_end_open_right_censored": 1,
    }
    assert scientific["raw_false_decomposition"] == {
        "A_ONLY_FAIL": 5244,
        "C_ONLY_FAIL": 46,
        "CA_BOTH_FAIL": 73,
    }
    assert all(
        scientific[key] == "passed"
        for key in (
            "quick_reentry_analysis_status",
            "cross_q_parent_mapping_status",
            "cross_q_daily_identity_conservation",
            "q20_fragmentation_analysis_status",
            "q25_shell_conservation_status",
        )
    )


def test_selection_boundaries_and_t06_gate_remain_closed() -> None:
    handoff = _load(HANDOFF_PATH)
    done = _load(DONE_PATH)
    assert handoff["selection"] == {
        "q_selection_status": "not_selected",
        "canonical_dynamic_request_selected": False,
        "selected_request_id": None,
        "selected_request_hash": None,
        "selected_q_by_dimension": None,
        "dynamic_state_registered": False,
    }
    assert all(value is False for value in handoff["scientific_boundaries"].values())
    assert done["release_label_generated"] is False
    assert done["trading_signal_generated"] is False
    assert done["backtest_executed"] is False
    assert done["R2A_T06_allowed_to_start"] == "true_after_PR_115_merge"
    assert handoff["downstream_gate"] == {
        "R2A-T05_DONE": "present",
        "R2A-T06_allowed_to_start": "true_after_PR_115_merge",
        "R2A-T06_started": False,
    }


def test_committed_closure_contains_only_repository_relative_posix_locators() -> None:
    handoff = _load(HANDOFF_PATH)
    for identity in handoff["evidence_identities"].values():
        locator = identity["relative_locator"]
        assert not locator.startswith("/")
        assert re.match(r"^[A-Za-z]:", locator) is None
        assert "\\" not in locator
        assert "file://" not in locator
        assert ".." not in Path(locator).parts

    for path in (
        HANDOFF_PATH,
        DONE_PATH,
        ROOT
        / "docs/evidence/r2a/R2A-T05_CA_exit_mechanism_formal_result_acceptance.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert re.search(r"[A-Za-z]:\\", text) is None
        assert "file://" not in text
