from __future__ import annotations

import csv
import json
from pathlib import Path

import duckdb
import pytest

from src.r2a.r2a_t06_formal_result_analysis import (
    analyze_persisted_formal_artifacts,
    render_persisted_result_analysis,
)
from tests.r2a.test_r2a_t06_formal_result_package import _package_stage


def _csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


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


@pytest.mark.parametrize(
    ("field", "replacement", "anomaly"),
    (
        ("raw_reentry_1_reentered_count", "999", "reentry_compact_detail_mismatch"),
        ("raw_reentry_1_rate", "0.987", "reentry_rate_mismatch"),
        (
            "raw_reentry_1_clean_denominator",
            "999",
            "reentry_clean_denominator_mismatch",
        ),
    ),
)
def test_reentry_compact_mutation_blocks(
    tmp_path: Path, field: str, replacement: str, anomaly: str
) -> None:
    _stage, scientific, _candidate, _validation, _manifest = _package_stage(tmp_path)
    path = scientific / "post_recognition_reentry.csv"
    rows, fields = _csv_rows(path)
    rows[0][field] = replacement
    _write_csv(path, rows, fields)
    analysis = analyze_persisted_formal_artifacts(scientific)
    assert analysis["result_analysis_status"] == "completed_blocked"
    assert anomaly in analysis["blocking_anomalies"]


@pytest.mark.parametrize(
    ("field", "replacement", "anomaly"),
    (
        ("episode_count", "999", "fragmentation_episode_count_mismatch"),
        ("max_span", "999", "fragmentation_span_mismatch"),
    ),
)
def test_fragmentation_compact_mutation_blocks(
    tmp_path: Path, field: str, replacement: str, anomaly: str
) -> None:
    _stage, scientific, _candidate, _validation, _manifest = _package_stage(tmp_path)
    path = scientific / "episode_fragmentation_profile.csv"
    rows, fields = _csv_rows(path)
    rows[0][field] = replacement
    _write_csv(path, rows, fields)
    analysis = analyze_persisted_formal_artifacts(scientific)
    assert anomaly in analysis["blocking_anomalies"]


def test_missing_margin_combination_blocks(tmp_path: Path) -> None:
    _stage, scientific, _candidate, _validation, _manifest = _package_stage(tmp_path)
    path = scientific / "exit_type_margin_profile.csv"
    rows, fields = _csv_rows(path)
    rows.pop()
    _write_csv(path, rows, fields)
    analysis = analyze_persisted_formal_artifacts(scientific)
    assert "margin_combination_inventory_invalid" in analysis["blocking_anomalies"]


def test_observable_margin_with_null_statistics_blocks(tmp_path: Path) -> None:
    _stage, scientific, _candidate, _validation, _manifest = _package_stage(tmp_path)
    path = scientific / "exit_type_margin_profile.csv"
    rows, fields = _csv_rows(path)
    observed = rows[0]
    observed["observable_count"] = "1"
    for field in ("mean_margin", "min_margin", "max_margin"):
        observed[field] = ""
    _write_csv(path, rows, fields)
    analysis = analyze_persisted_formal_artifacts(scientific)
    assert "margin_observed_statistic_null" in analysis["blocking_anomalies"]


def test_duplicate_deterministic_sample_hash_blocks(tmp_path: Path) -> None:
    _stage, scientific, _candidate, _validation, _manifest = _package_stage(tmp_path)
    path = scientific / "deterministic_episode_samples.csv"
    rows, fields = _csv_rows(path)
    assert len(rows) >= 2
    rows[1]["sample_hash"] = rows[0]["sample_hash"]
    _write_csv(path, rows, fields)
    analysis = analyze_persisted_formal_artifacts(scientific)
    assert "deterministic_sample_hash_duplicate" in analysis["blocking_anomalies"]


def test_reentry_detail_compact_mismatch_blocks(tmp_path: Path) -> None:
    _stage, scientific, _candidate, _validation, _manifest = _package_stage(tmp_path)
    detail_path = scientific / "t06_detail.duckdb"
    with duckdb.connect(str(detail_path)) as connection:
        rowid, payload = connection.execute(
            "SELECT rowid, payload FROM post_recognition_outcomes LIMIT 1"
        ).fetchone()
        item = json.loads(payload)
        item["outcome"] = (
            "CLEAN_NOT_REENTERED"
            if item["outcome"] != "CLEAN_NOT_REENTERED"
            else "INPUT_END_CENSORED"
        )
        connection.execute(
            "UPDATE post_recognition_outcomes SET payload = ? WHERE rowid = ?",
            [json.dumps(item, sort_keys=True), rowid],
        )
    analysis = analyze_persisted_formal_artifacts(scientific)
    assert "reentry_compact_detail_mismatch" in analysis["blocking_anomalies"]
