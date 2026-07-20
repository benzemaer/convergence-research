from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "R2A-T04-20260720T002158508Z"
HANDOFF = (
    ROOT
    / "data"
    / "generated"
    / "r2a"
    / "r2a_t04"
    / RUN_ID
    / "r2a_t04_accepted_result_handoff.json"
)
DONE = HANDOFF.parent / "DONE"
HANDOFF_SCHEMA = (
    ROOT / "schemas" / "r2a" / "r2a_t04_accepted_result_handoff.schema.json"
)
CONFIG = ROOT / "configs" / "r2a" / "r2a_t04_real_data_audit.v1.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_r2a_t04_accepted_handoff_matches_schema_and_hash_chain() -> None:
    handoff = _load(HANDOFF)
    schema = _load(HANDOFF_SCHEMA)
    Draft202012Validator(schema).validate(handoff)

    handoff_sha = _sha256(HANDOFF)
    config = _load(CONFIG)
    done = _load(DONE)
    assert config["accepted_handoff_sha256"] == handoff_sha
    assert done["accepted_handoff_sha256"] == handoff_sha
    assert config["accepted_run_id"] == RUN_ID
    assert config["accepted_execution_head"] == (
        "1d34cf49b9816aac92837213fa668356d5c7b45d"
    )


def test_r2a_t04_acceptance_retains_review_chain_and_no_selection() -> None:
    handoff = _load(HANDOFF)
    review = handoff["independent_review"]
    selection = handoff["selection"]
    assert review["attempt_count"] == 2
    assert review["formal_reexecution_between_attempts"] is False
    assert review["formal_package_modified_between_attempts"] is False
    assert review["attempts"][0]["receipt_storage_class"] == "operator_log_archive"
    assert review["attempts"][1]["receipt_storage_class"] == "formal_run_root"
    assert review["attempts"][1]["mismatch_count"] == 0
    assert selection == {
        "q_selection_status": "not_selected",
        "canonical_dynamic_request_selected": False,
        "selected_request_id": None,
        "selected_request_hash": None,
        "selected_q_by_dimension": None,
    }
    assert all(
        request["selection_status"] == "evaluated_not_selected"
        for request in handoff["requests"]
    )
    assert [
        (
            request["logical_request_name"],
            request["request_id"],
            request["request_hash"],
        )
        for request in handoff["requests"]
    ] == [
        (
            "CA_q10_k5",
            "pcavt-dynreq-v1-d07aae4bbbd98f88",
            "d07aae4bbbd98f88989cf6b50c3b808935f237cd69f56271f6a210aa90f7ac8f",
        ),
        (
            "CA_q15_k5",
            "pcavt-dynreq-v1-cf420e9c025374d1",
            "cf420e9c025374d19bbc4e83bd75fee96d10d0c322605826ae5cffcf4029674f",
        ),
        (
            "CA_q20_k5",
            "pcavt-dynreq-v1-21bd144aaed98d9e",
            "21bd144aaed98d9e7d404aaa8d2fa0685f7ec29a3deb714d0d1df99c05d5e971",
        ),
        (
            "CA_q25_k5",
            "pcavt-dynreq-v1-b210f9e5211c46db",
            "b210f9e5211c46db6cbc41ca1da9ff340018b4ef69e56df07ae22cecafbad3e9",
        ),
    ]
    assert {check["check_id"] for check in handoff["response_checks"]} == {
        "ca_q_joint_ready_equality",
        "ca_q_raw_subset_q10_q15",
        "ca_q_raw_subset_q15_q20",
        "ca_q_raw_subset_q20_q25",
        "ca_q_confirmed_subset_q10_q15",
        "ca_q_confirmed_subset_q15_q20",
        "ca_q_confirmed_subset_q20_q25",
        "ca_q_ladder_non_degenerate",
    }
    assert all(check["passed"] for check in handoff["response_checks"])
    assert all(check["violation_count"] == 0 for check in handoff["response_checks"])


def test_r2a_t04_committed_acceptance_contains_no_absolute_paths() -> None:
    for path in (HANDOFF, DONE, CONFIG):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:\\", text)
        assert "file://" not in text
