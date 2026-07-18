from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from src.r2a.r2a_t01_input_manifest import (
    build_synthetic_input_manifest,
    sha256_file,
    write_json_atomic,
)
from src.r2a.r2a_t01_score_release import ScoreReleaseError, materialize_score_release
from src.r2a.r2a_t01_validator import validate_score_release
from tests.r2a._fixtures import build_package, synthetic_inputs, write_json


def _refresh_database_identity(package: Path) -> None:
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["score_data_sha256"] = sha256_file(package / "score_data.duckdb")
    manifest["database_byte_size"] = (package / "score_data.duckdb").stat().st_size
    write_json_atomic(manifest_path, manifest)


def test_validator_independently_recomputes_and_passes_valid_package(
    tmp_path: Path,
) -> None:
    package, input_manifest, _ = build_package(tmp_path)
    receipt = validate_score_release(package, authorized_input_manifest=input_manifest)
    assert receipt["status"] == "passed"
    assert receipt["checks"]["a_raw_score_independent_recomputation"] is True
    assert receipt["checks"]["pcvt_raw_score_independent_recomputation"] is True
    assert receipt["checks"]["all_dimension_mean_min_recomputed"] is True
    assert receipt["checks"]["pcvt_component_source_keyset_reconciled"] is True
    assert receipt["checks"]["component_availability_policy_exact"] is True
    assert receipt["metrics"]["pcvt_independent_mismatch_count"] == 0


def test_validator_accepts_role_specific_nonvalid_reference_semantics(
    tmp_path: Path,
) -> None:
    input_manifest, paths = synthetic_inputs(tmp_path / "inputs")
    component_id = "P1_NATR14"
    target_date = max(
        row["trading_date"]
        for row in json.loads(paths["pcvt_validation_raw"].read_text(encoding="utf-8"))
        if row["component_id"] == component_id
    )

    validation_rows = json.loads(
        paths["pcvt_validation_raw"].read_text(encoding="utf-8")
    )
    validation_target = next(
        row
        for row in validation_rows
        if row["component_id"] == component_id and row["trading_date"] == target_date
    )
    validation_target.update(
        raw_value=None,
        validity_status="blocked",
        reason_codes=["daily_vwap_range_fail"],
    )
    write_json(paths["pcvt_validation_raw"], validation_rows)

    component_rows = json.loads(
        paths["pcvt_component_scores"].read_text(encoding="utf-8")
    )
    component_target = next(
        row
        for row in component_rows
        if row["component_id"] == component_id and row["trading_date"] == target_date
    )
    component_target.update(
        raw_value=None,
        percentile=None,
        score=None,
        eligible=False,
        validity_status="blocked",
        reason_codes=["raw_metric_not_valid", "daily_vwap_range_fail"],
        reference_observation_count=0,
        reference_window_start=None,
        reference_window_end=None,
    )
    write_json(paths["pcvt_component_scores"], component_rows)

    dimension_rows = json.loads(
        paths["pcvt_dimension_scores"].read_text(encoding="utf-8")
    )
    dimension_target = next(
        row
        for row in dimension_rows
        if row["dimension_id"] == "P" and row["trading_date"] == target_date
    )
    dimension_target.update(
        score_dimension=None,
        score_dimension_min=None,
        eligible_dimension=False,
        validity_status="blocked",
        reason_codes=["component_not_eligible"],
    )
    write_json(paths["pcvt_dimension_scores"], dimension_rows)

    a_rows = json.loads(paths["a_raw_observations"].read_text(encoding="utf-8"))
    a_target = next(
        row
        for row in a_rows
        if row["component_id"] == "A1_LogBodyCenterToMACloudCenter_5_60"
        and row["trading_date"] == target_date
    )
    a_target.update(
        raw_value=None,
        validity_status="blocked",
        reason_codes=["current_observation_not_valid"],
    )
    write_json(paths["a_raw_observations"], a_rows)

    build_synthetic_input_manifest(
        output_path=input_manifest,
        run_id="role-specific-nonvalid-reference",
        synthetic_root=paths["pcvt_validation_raw"].parent,
        inputs=paths,
    )
    package = tmp_path / "package"
    materialize_score_release(
        authorized_input_manifest=input_manifest,
        output_dir=package,
        run_id="role-specific-nonvalid-reference",
    )

    receipt = validate_score_release(package, authorized_input_manifest=input_manifest)
    assert receipt["status"] == "passed"
    assert receipt["checks"]["pcvt_raw_score_independent_recomputation"] is True
    assert receipt["checks"]["a_raw_score_independent_recomputation"] is True
    assert receipt["metrics"]["pcvt_independent_mismatch_count"] == 0
    assert receipt["metrics"]["a_independent_mismatch_count"] == 0


def test_validator_detects_availability_mismatch(tmp_path: Path) -> None:
    package, input_manifest, _ = build_package(tmp_path)
    with duckdb.connect(str(package / "score_data.duckdb")) as connection:
        connection.execute(
            "UPDATE daily_component_scores SET available_time=available_time+INTERVAL '1 second'"
        )
        connection.execute("CHECKPOINT")
    _refresh_database_identity(package)
    receipt = validate_score_release(package, authorized_input_manifest=input_manifest)
    assert receipt["status"] == "failed"
    assert "component_availability_policy_exact" in receipt["reason_codes"]


@pytest.mark.parametrize(
    ("name", "sql", "expected_reason"),
    [
        (
            "all_zero",
            "UPDATE daily_component_scores SET score=0,percentile=1 WHERE eligible; "
            "UPDATE daily_dimension_scores SET score_dimension=0,score_dimension_min=0 "
            "WHERE eligible_dimension",
            "component_scores_not_all_zero",
        ),
        (
            "all_one",
            "UPDATE daily_component_scores SET score=1,percentile=0 WHERE eligible; "
            "UPDATE daily_dimension_scores SET score_dimension=1,score_dimension_min=1 "
            "WHERE eligible_dimension",
            "component_scores_not_all_one",
        ),
        (
            "all_null",
            "UPDATE daily_component_scores SET eligible=false,validity_status='unknown',"
            "score=NULL,percentile=NULL; UPDATE daily_dimension_scores SET "
            "eligible_dimension=false,validity_status='unknown',score_dimension=NULL,"
            "score_dimension_min=NULL",
            "component_scores_not_all_null",
        ),
        (
            "component_count",
            "DELETE FROM daily_component_scores WHERE rowid IN "
            "(SELECT rowid FROM daily_component_scores LIMIT 1)",
            "component_cardinality",
        ),
        (
            "pcvt_component_source_mismatch",
            "UPDATE daily_component_scores SET score=score+0.001,"
            "percentile=percentile-0.001 WHERE component_id='P1_NATR14' AND eligible",
            "pcvt_component_source_values_reconciled",
        ),
        (
            "pcvt_component_sequence_mismatch",
            "UPDATE daily_component_scores SET observation_sequence=observation_sequence+1000 "
            "WHERE component_id='P1_NATR14' AND trading_date=(SELECT min(trading_date) FROM daily_component_scores)",
            "pcvt_component_source_values_reconciled",
        ),
        (
            "pcvt_component_reason_mismatch",
            "UPDATE daily_component_scores SET reason_codes=['mutated_reason'] "
            "WHERE component_id='P1_NATR14' AND eligible",
            "pcvt_component_source_values_reconciled",
        ),
        (
            "pcvt_component_engine_mismatch",
            "UPDATE daily_component_scores SET score_engine_version='mutated_engine' "
            "WHERE component_id='P1_NATR14'",
            "pcvt_component_source_values_reconciled",
        ),
        (
            "pcvt_component_run_mismatch",
            "UPDATE daily_component_scores SET source_run_id='mutated_run' "
            "WHERE component_id='P1_NATR14'",
            "pcvt_component_source_values_reconciled",
        ),
        (
            "pcvt_component_reference_mismatch",
            "UPDATE daily_component_scores SET reference_window_start=reference_window_start+INTERVAL '1 day' "
            "WHERE component_id='P1_NATR14' AND eligible",
            "pcvt_component_source_values_reconciled",
        ),
        (
            "pcvt_component_to_dimension_mismatch",
            "UPDATE daily_dimension_scores SET score_dimension=score_dimension+0.001 "
            "WHERE dimension_id='P' AND eligible_dimension",
            "all_dimension_mean_min_recomputed",
        ),
    ],
)
def test_validator_negative_output_mutations(
    tmp_path: Path, name: str, sql: str, expected_reason: str
) -> None:
    package, input_manifest, _ = build_package(tmp_path / name)
    with duckdb.connect(str(package / "score_data.duckdb")) as connection:
        connection.execute(sql)
        connection.execute("CHECKPOINT")
    _refresh_database_identity(package)
    receipt = validate_score_release(package, authorized_input_manifest=input_manifest)
    assert receipt["status"] == "failed"
    assert expected_reason in receipt["reason_codes"]


def test_expected_empty_rows_are_omitted_upstream_but_blocked_downstream(
    tmp_path: Path,
) -> None:
    package, input_manifest, paths = build_package(tmp_path)
    component_rows = json.loads(
        paths["pcvt_component_scores"].read_text(encoding="utf-8")
    )
    assert all(
        row["trading_date"] not in {"2020-02-19", "2020-02-29"}
        for row in component_rows
    )
    receipt = validate_score_release(package, authorized_input_manifest=input_manifest)
    assert receipt["checks"]["pcvt_component_source_keyset_reconciled"] is True
    assert receipt["checks"]["expected_empty_component_blocked"] is True
    assert receipt["checks"]["expected_empty_dimension_blocked"] is True


def test_expected_empty_blocked_cardinality_fails_independently(tmp_path: Path) -> None:
    package, input_manifest, _ = build_package(tmp_path)
    with duckdb.connect(str(package / "score_data.duckdb")) as connection:
        connection.execute(
            "DELETE FROM daily_component_scores WHERE trading_date='2020-02-19' "
            "AND component_id='P1_NATR14'"
        )
        connection.execute("CHECKPOINT")
    _refresh_database_identity(package)
    receipt = validate_score_release(package, authorized_input_manifest=input_manifest)
    assert receipt["checks"]["pcvt_component_source_keyset_reconciled"] is True
    assert receipt["checks"]["expected_empty_component_blocked"] is False
    assert "expected_empty_component_blocked" in receipt["reason_codes"]


def test_pcvt_raw_to_score_mismatch_fails_closed(tmp_path: Path) -> None:
    package, input_manifest, paths = build_package(tmp_path)
    rows = json.loads(paths["pcvt_validation_raw"].read_text(encoding="utf-8"))
    rows[-1]["raw_value"] = float(rows[-1]["raw_value"]) + 1000.0
    write_json(paths["pcvt_validation_raw"], rows)
    build_synthetic_input_manifest(
        output_path=input_manifest,
        run_id="mutated-validation-raw",
        synthetic_root=paths["pcvt_validation_raw"].parent,
        inputs=paths,
    )
    receipt = validate_score_release(package, authorized_input_manifest=input_manifest)
    assert receipt["status"] == "failed"
    assert receipt["checks"]["pcvt_raw_score_independent_recomputation"] is False


def test_present_source_row_missing_rejected_before_materialization(
    tmp_path: Path,
) -> None:
    input_manifest, paths = synthetic_inputs(tmp_path / "inputs")
    rows = json.loads(paths["pcvt_component_scores"].read_text(encoding="utf-8"))
    rows.pop(0)
    write_json(paths["pcvt_component_scores"], rows)
    build_synthetic_input_manifest(
        output_path=input_manifest,
        run_id="missing-present-source",
        synthetic_root=paths["pcvt_component_scores"].parent,
        inputs=paths,
    )
    with pytest.raises(
        ScoreReleaseError, match="present_source_row_missing:pcvt_component_scores"
    ):
        materialize_score_release(
            authorized_input_manifest=input_manifest,
            output_dir=tmp_path / "package",
            run_id="missing-present-source",
        )
