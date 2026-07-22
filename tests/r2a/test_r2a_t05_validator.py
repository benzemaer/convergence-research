from __future__ import annotations

import copy

from src.r2a.r2a_t05_ca_exit_decomposition import build_t05_candidate
from src.r2a.r2a_t05_result_analysis import (
    render_result_analysis,
    scan_candidate_results,
)
from src.r2a.r2a_t05_validator import validate_t05_candidate
from tests.r2a.test_r2a_t05_ca_exit_decomposition import _fixture


def test_result_analysis_stays_candidate_pending_and_scans_actual_rows(
    tmp_path,
) -> None:
    config, score, outputs = _fixture(tmp_path)
    candidate = build_t05_candidate(outputs, score, config=config)
    receipt = validate_t05_candidate(
        candidate, request_sources=outputs, score_source=score, config=config
    )
    analysis = scan_candidate_results(candidate)
    assert receipt["status"] == "passed", receipt
    assert analysis["status"] == "candidate_review_pending"
    assert (
        analysis["scientific_review_status"]
        == "not_applicable_implementation_candidate"
    )
    assert analysis["formal_run_executed"] is False
    assert analysis["R2A-T05_DONE"] == "absent"
    rendered = render_result_analysis(candidate, validation_receipt=receipt)
    assert "Research question and registered definitions" in rendered
    assert "not selected, optimal, canonical" in rendered
    assert "analysis_status=candidate_review_pending" in rendered


def test_validator_blocks_daily_identity_mutation(tmp_path) -> None:
    config, score, outputs = _fixture(tmp_path)
    candidate = build_t05_candidate(outputs, score, config=config)
    mutated = copy.deepcopy(candidate)
    mutated["daily_level_identities"][0]["identity"] = "Q25_NOT_Q20_SHELL"
    receipt = validate_t05_candidate(
        mutated, request_sources=outputs, score_source=score, config=config
    )
    assert receipt["status"] == "blocked"
    assert any(
        reason.startswith("daily_identity_membership_mismatch")
        for reason in receipt["blocking_reasons"]
    )
