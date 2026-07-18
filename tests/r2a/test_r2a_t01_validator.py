from __future__ import annotations

import json
from pathlib import Path

import duckdb

from src.r2a.r2a_t01_input_manifest import sha256_file, write_json_atomic
from src.r2a.r2a_t01_validator import validate_score_release
from tests.r2a._fixtures import build_package


def _refresh_database_hash(package: Path) -> None:
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["score_data_sha256"] = sha256_file(package / "score_data.duckdb")
    write_json_atomic(manifest_path, manifest)


def test_validator_independently_recomputes_and_passes_valid_package(
    tmp_path: Path,
) -> None:
    package, _, _ = build_package(tmp_path)
    receipt = validate_score_release(package)
    assert receipt["status"] == "passed"
    assert receipt["checks"]["a_component_independent_recomputation"] is True
    assert receipt["checks"]["a_dimension_mean_min_independent_recomputation"] is True
    assert receipt["checks"]["pcvt_component_source_reconciled"] is True
    assert receipt["checks"]["availability_policy_exact"] is True


def test_validator_detects_availability_mismatch(tmp_path: Path) -> None:
    package, _, _ = build_package(tmp_path)
    database = package / "score_data.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "UPDATE daily_component_scores SET available_time=available_time+INTERVAL '1 second'"
        )
        connection.execute("CHECKPOINT")
    _refresh_database_hash(package)
    receipt = validate_score_release(package)
    assert receipt["status"] == "failed"
    assert "component_availability_policy_exact" in receipt["reason_codes"]


def test_validator_detects_all_zero_anomaly(tmp_path: Path) -> None:
    package, _, _ = build_package(tmp_path)
    database = package / "score_data.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "UPDATE daily_component_scores SET score=0,percentile=1 WHERE eligible"
        )
        connection.execute(
            "UPDATE daily_dimension_scores SET score_dimension=0,score_dimension_min=0 "
            "WHERE eligible_dimension"
        )
        connection.execute("CHECKPOINT")
    _refresh_database_hash(package)
    receipt = validate_score_release(package)
    assert receipt["status"] == "failed"
    assert "component_scores_not_all_zero" in receipt["reason_codes"]
    assert "dimension_scores_not_all_zero" in receipt["reason_codes"]


def test_formal_cardinality_is_validator_only(tmp_path: Path) -> None:
    package, _, _ = build_package(tmp_path)
    receipt = validate_score_release(package, formal=True)
    assert receipt["status"] == "failed"
    assert "formal_security_count_800" in receipt["reason_codes"]
    assert "formal_calendar_year_domain" in receipt["reason_codes"]


def test_validator_scans_all_one_all_null_counts_and_source_mismatch(
    tmp_path: Path,
) -> None:
    mutations = {
        "all_one": (
            "UPDATE daily_component_scores SET score=1,percentile=0 WHERE eligible; "
            "UPDATE daily_dimension_scores SET score_dimension=1,score_dimension_min=1 "
            "WHERE eligible_dimension",
            "component_scores_not_all_one",
        ),
        "all_null": (
            "UPDATE daily_component_scores SET eligible=false,validity_status='unknown',"
            "score=NULL,percentile=NULL; UPDATE daily_dimension_scores SET "
            "eligible_dimension=false,validity_status='unknown',score_dimension=NULL,"
            "score_dimension_min=NULL",
            "component_scores_not_all_null",
        ),
        "component_count": (
            "DELETE FROM daily_component_scores WHERE rowid IN "
            "(SELECT rowid FROM daily_component_scores LIMIT 1)",
            "component_cardinality",
        ),
        "source_mismatch": (
            "UPDATE daily_component_scores SET score=score+0.001,"
            "percentile=percentile-0.001 WHERE indicator_id='P1_NATR14' AND eligible",
            "pcvt_component_source_reconciled",
        ),
    }
    for name, (sql, expected_reason) in mutations.items():
        package, _, _ = build_package(tmp_path / name)
        with duckdb.connect(str(package / "score_data.duckdb")) as connection:
            connection.execute(sql)
            connection.execute("CHECKPOINT")
        _refresh_database_hash(package)
        receipt = validate_score_release(package)
        assert receipt["status"] == "failed", name
        assert expected_reason in receipt["reason_codes"], name
