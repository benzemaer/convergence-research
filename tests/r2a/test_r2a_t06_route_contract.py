from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.r2a.r2a_t06_consecutive_failure_exit import T06Error
from src.r2a.r2a_t06_formal_execution import (
    FORMAL_REQUIRED_FILES,
    run_formal,
)

ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_route_is_implementation_only_and_successors_are_blocked() -> None:
    config = json.loads(_text("configs/r2a/r2a_t06_consecutive_failure_exit.v1.json"))
    assert config["q20_role"] == "research_anchor_only"
    assert config["q_selection_status"] == "not_selected"
    assert config["canonical_dynamic_request_selected"] is False
    assert config["winner_selected"] is False
    assert config["selected_exit_confirmation_m"] is None
    assert config["owner_implementation_review_status"] == "pending_successor_review"
    assert config["approved_implementation_sha"] == "absent"
    assert config["formal_run_allowed"] is False
    assert config["formal_run_executed"] is False
    assert config["real_score_data_read"] is False
    assert config["formal_artifacts_generated"] is False
    assert config["R2A-T06_DONE"] == "absent"
    assert config["R2A-T07_allowed_to_start"] is False
    assert config["R3_allowed_to_start"] is False


def test_formal_runner_fails_before_input_discovery() -> None:
    with pytest.raises(T06Error, match="formal_run_not_authorized"):
        run_formal(None)


def test_future_formal_file_contract_is_complete() -> None:
    expected = json.loads(
        _text("configs/r2a/r2a_t06_consecutive_failure_exit.v1.json")
    )["future_formal_required_files"]
    assert list(FORMAL_REQUIRED_FILES) == expected


def test_task_and_handoff_expose_current_stop() -> None:
    task = _text("docs/tasks/R2A-T06_CA连续失效退出确认与迟滞规则选择.md")
    handoff = _text("HANDOFF.md")
    index = _text("docs/tasks/README.md")
    assert (
        "status: implementation_candidate_remediation_pending_successor_review" in task
    )
    assert "formal_run_executed: false" in task
    assert "real_score_data_read: false" in task
    assert "R2A-T06_DONE: absent" in task
    assert "owner_implementation_review_required: true" in handoff
    assert "R2A-T06_approved_implementation_sha: absent" in handoff
    assert "R2A-T07_allowed_to_start: false" in index
