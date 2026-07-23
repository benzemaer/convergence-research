from __future__ import annotations

import csv
from pathlib import Path

from src.r2a.r2a_t06_formal_result_analysis import (
    analyze_persisted_formal_artifacts,
    render_persisted_result_analysis,
)
from tests.r2a.test_r2a_t06_formal_result_package import _package_stage


def test_analysis_reads_persisted_files_and_keeps_winner_null(tmp_path: Path) -> None:
    _stage, scientific, candidate, _validation, _manifest = _package_stage(tmp_path)
    candidate["candidate_exit_summary"] = []
    analysis = analyze_persisted_formal_artifacts(scientific)
    assert analysis["selected_exit_confirmation_m"] is None
    assert analysis["winner_selected"] is False
    assert analysis["blocking_anomaly_count"] == 0
    report = render_persisted_result_analysis(analysis)
    assert "persisted artifacts" in report
    assert "selected_exit_confirmation_m=null" in report
    assert "不得根据未来收益" in report


def test_corrupt_persisted_summary_triggers_anomaly_gate(tmp_path: Path) -> None:
    _stage, scientific, _candidate, _validation, _manifest = _package_stage(tmp_path)
    path = scientific / "candidate_exit_summary.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    rows[0]["provisional_exit_count"] = "999"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    analysis = analyze_persisted_formal_artifacts(scientific)
    assert analysis["result_analysis_status"] == "completed_blocked"
    assert "false_run_inventory_not_trigger_anchored" in analysis["blocking_anomalies"]
    assert analysis["selected_exit_confirmation_m"] is None


def test_cross_q_mapping_anomaly_blocks(tmp_path: Path) -> None:
    _stage, scientific, _candidate, _validation, _manifest = _package_stage(tmp_path)
    path = scientific / "cross_q_nesting_validation.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    rows[0]["unmapped_child_episode_count"] = "1"
    rows[0]["mapping_status"] = "failed"
    rows[0]["overall_status"] = "failed"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    analysis = analyze_persisted_formal_artifacts(scientific)
    assert "unmapped_child_episode" in analysis["blocking_anomalies"]
    assert "cross_q_mapping_failed" in analysis["blocking_anomalies"]
