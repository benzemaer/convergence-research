from __future__ import annotations

from pathlib import Path

import pytest

from src.r2a.r2a_t01_result_analysis import (
    ResultAnalysisError,
    analyze_score_release,
)
from src.r2a.r2a_t01_validator import validate_score_release
from tests.r2a._fixtures import build_package


def test_analysis_requires_passed_actual_validation_receipt(tmp_path: Path) -> None:
    package, _, _ = build_package(tmp_path)
    with pytest.raises(ResultAnalysisError, match="missing_required_file"):
        analyze_score_release(package)
    validate_score_release(package)
    target = analyze_score_release(package)
    text = target.read_text(encoding="utf-8")
    assert "Actual artifact inspection" in text
    assert "Score distributions" in text
    assert "daily_component_scores" in text
    assert "validation_status: `passed`" in text
    assert "does not authorize a formal run" in text


def test_analysis_refuses_failed_receipt(tmp_path: Path) -> None:
    package, _, _ = build_package(tmp_path)
    receipt = validate_score_release(package, formal=True)
    assert receipt["status"] == "failed"
    with pytest.raises(ResultAnalysisError, match="validation_receipt_not_passed"):
        analyze_score_release(package)
