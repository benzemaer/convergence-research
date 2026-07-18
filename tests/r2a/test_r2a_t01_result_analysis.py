from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from src.r2a.r2a_t01_input_manifest import sha256_file, write_json_atomic
from src.r2a.r2a_t01_result_analysis import ResultAnalysisError, analyze_score_release
from src.r2a.r2a_t01_validator import validate_score_release
from tests.r2a._fixtures import build_package


def _refresh_database_identity(package: Path) -> None:
    path = package / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["score_data_sha256"] = sha256_file(package / "score_data.duckdb")
    manifest["database_byte_size"] = (package / "score_data.duckdb").stat().st_size
    write_json_atomic(path, manifest)


def test_passed_receipt_generates_complete_analysis(tmp_path: Path) -> None:
    package, input_manifest, _ = build_package(tmp_path)
    with pytest.raises(ResultAnalysisError, match="missing_required_file"):
        analyze_score_release(package)
    validate_score_release(package, authorized_input_manifest=input_manifest)
    target = analyze_score_release(package)
    text = target.read_text(encoding="utf-8")
    assert "analysis_status = `passed`" in text
    assert "validator_status = `passed`" in text
    assert "release_recommendation = `publish_candidate`" in text
    assert "Seven-table row counts" in text
    assert "Component Score distributions" in text
    assert "Yearly coverage" in text
    assert "Independent reconciliation evidence" in text
    assert (
        "| dimension | component | total_rows | eligible_rows | null_score_rows | "
        "valid_rows | unknown_rows | diagnostic_required_rows | blocked_rows | min | max | mean |"
        in text
    )
    assert (
        "| dimension | total_rows | eligible_rows | null_score_rows | valid_rows | "
        "unknown_rows | diagnostic_required_rows | blocked_rows | min | max | mean |"
        in text
    )
    assert "| P | P1_NATR14 | 123 | 1 | 122 | 121 | 0 | 0 | 2 |" in text
    assert "| P | 123 | 1 | 122 | 121 | 0 | 0 | 2 |" in text


def test_failed_receipt_still_generates_blocked_analysis(tmp_path: Path) -> None:
    package, input_manifest, _ = build_package(tmp_path)
    receipt = validate_score_release(
        package, authorized_input_manifest=input_manifest, formal=True
    )
    assert receipt["status"] == "failed"
    target = analyze_score_release(package)
    text = target.read_text(encoding="utf-8")
    assert "analysis_status = `blocked`" in text
    assert "validator_status = `failed`" in text
    assert "release_recommendation = `do_not_publish`" in text
    assert "validator_failed" in text


@pytest.mark.parametrize(
    ("name", "sql", "anomaly"),
    [
        (
            "component_all_null",
            "UPDATE daily_component_scores SET eligible=false,validity_status='unknown',"
            "score=NULL,percentile=NULL WHERE component_id='P1_NATR14'",
            "component_all_null:P1_NATR14",
        ),
        (
            "component_all_zero",
            "UPDATE daily_component_scores SET score=0,percentile=1 "
            "WHERE component_id='P1_NATR14' AND score IS NOT NULL",
            "component_all_zero:P1_NATR14",
        ),
        (
            "component_all_one",
            "UPDATE daily_component_scores SET score=1,percentile=0 "
            "WHERE component_id='P1_NATR14' AND score IS NOT NULL",
            "component_all_one:P1_NATR14",
        ),
        (
            "dimension_all_null",
            "UPDATE daily_dimension_scores SET eligible_dimension=false,"
            "validity_status='unknown',score_dimension=NULL,score_dimension_min=NULL "
            "WHERE dimension_id='A'",
            "dimension_all_null:A",
        ),
        (
            "dimension_all_zero",
            "UPDATE daily_dimension_scores SET score_dimension=0,score_dimension_min=0 "
            "WHERE dimension_id='A' AND score_dimension IS NOT NULL",
            "dimension_all_zero:A",
        ),
        (
            "dimension_all_one",
            "UPDATE daily_dimension_scores SET score_dimension=1,score_dimension_min=1 "
            "WHERE dimension_id='A' AND score_dimension IS NOT NULL",
            "dimension_all_one:A",
        ),
        (
            "a_mean_mismatch",
            "UPDATE daily_dimension_scores SET score_dimension=score_dimension+0.01 "
            "WHERE dimension_id='A' AND eligible_dimension",
            "component_to_dimension_mismatch",
        ),
        (
            "availability_mismatch",
            "UPDATE daily_dimension_scores SET available_time=available_time+INTERVAL '1 second'",
            "availability_mismatch",
        ),
    ],
)
def test_actual_anomalies_block_analysis(
    tmp_path: Path, name: str, sql: str, anomaly: str
) -> None:
    package, input_manifest, _ = build_package(tmp_path / name)
    with duckdb.connect(str(package / "score_data.duckdb")) as connection:
        connection.execute(sql)
        connection.execute("CHECKPOINT")
    _refresh_database_identity(package)
    validate_score_release(package, authorized_input_manifest=input_manifest)
    target = analyze_score_release(package)
    text = target.read_text(encoding="utf-8")
    assert "analysis_status = `blocked`" in text
    assert anomaly in text


def test_source_coverage_drop_blocks_analysis(tmp_path: Path) -> None:
    package, input_manifest, _ = build_package(tmp_path)
    receipt = validate_score_release(package, authorized_input_manifest=input_manifest)
    receipt["status"] = "failed"
    receipt["checks"]["source_valid_output_coverage"] = False
    receipt["reason_codes"] = ["source_valid_output_coverage"]
    receipt["metrics"]["pcvt_source_valid_rows"] += 1
    write_json_atomic(package / "validation_receipt.json", receipt)
    text = analyze_score_release(package).read_text(encoding="utf-8")
    assert "source_coverage_drop" in text
    assert "release_recommendation = `do_not_publish`" in text
