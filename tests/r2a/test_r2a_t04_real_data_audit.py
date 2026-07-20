from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa
import pytest
from jsonschema import Draft202012Validator

from scripts.r2a.preflight_r2a_t04_real_data_audit import _result_exit_code
from src.r2a.r2a_t03_output_contract import ColumnSpec, TableSpec
from src.r2a.r2a_t04_real_data_audit import (
    R2AT04AuditError,
    ThreadBenchmarkRun,
    canonical_profile_from_batches,
    canonical_table_profile,
    canonical_table_profiles,
    compare_output_databases,
    evaluate_request_with_threads,
    finalize_thread_benchmark_outputs,
    validate_market_source,
    verify_file_identity,
)
from tests.r2a.r2a_t03_test_support import canonical_request
from tests.r2a.r2a_t04_test_support import (
    create_market_database,
    create_score_database,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_thread_benchmark_receipt(receipt: dict[str, object]) -> None:
    schema = json.loads(
        Path("schemas/r2a/r2a_t04_thread_benchmark_receipt.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(receipt)


def _physical_batches(table: pa.Table, row_count: int):
    for offset in range(0, table.num_rows, row_count):
        yield table.slice(offset, row_count).to_batches()[0]


def _rich_arrow_table(row_count: int = 65_537) -> tuple[pa.Table, TableSpec]:
    first = date(2020, 1, 1)
    table = pa.table(
        {
            "id": pa.array([f"S{index:06d}" for index in range(row_count)]),
            "day": pa.array(
                [first + timedelta(days=index % 365) for index in range(row_count)],
                type=pa.date32(),
            ),
            "available": pa.array(
                [
                    datetime(2020, 1, 1, tzinfo=UTC) + timedelta(minutes=index)
                    for index in range(row_count)
                ],
                type=pa.timestamp("us", tz="UTC"),
            ),
            "value": pa.array(
                [None if index % 11 == 0 else index / 10 for index in range(row_count)],
                type=pa.float64(),
            ),
            "flag": pa.array([index % 2 == 0 for index in range(row_count)]),
            "tags": pa.array([["P", str(index % 5)] for index in range(row_count)]),
            "nullable_text": pa.array([None] * row_count, type=pa.string()),
        }
    )
    contract = TableSpec(
        (
            ColumnSpec("id", "VARCHAR"),
            ColumnSpec("day", "DATE"),
            ColumnSpec("available", "TIMESTAMP WITH TIME ZONE"),
            ColumnSpec("value", "DOUBLE", True),
            ColumnSpec("flag", "BOOLEAN"),
            ColumnSpec("tags", "VARCHAR[]"),
            ColumnSpec("nullable_text", "VARCHAR", True),
        ),
        ("id",),
    )
    return table, contract


def _synthetic_thread_outputs(
    tmp_path: Path,
) -> tuple[dict[int, Path], list[ThreadBenchmarkRun], dict[str, object]]:
    score = tmp_path / "score.duckdb"
    create_score_database(score)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    request = canonical_request()
    base = scratch / "threads-4.duckdb"
    evaluate_request_with_threads(
        score_database=score,
        canonical_request=request,
        output_database=base,
        duckdb_thread_count=4,
        security_ids=["S1", "S2", "S3"],
    )
    outputs = {
        4: base,
        8: scratch / "threads-8.duckdb",
        16: scratch / "threads-16.duckdb",
    }
    shutil.copyfile(base, outputs[8])
    shutil.copyfile(base, outputs[16])
    runs: list[ThreadBenchmarkRun] = []
    for threads, wall in ((4, 10.0), (8, 9.5), (16, 11.0)):
        with duckdb.connect(str(outputs[threads]), read_only=True) as connection:
            profiles = canonical_table_profiles(connection)
        runs.append(
            ThreadBenchmarkRun(
                duckdb_thread_count=threads,
                wall_seconds=wall,
                peak_rss_bytes=1000 + threads,
                temporary_output_bytes=outputs[threads].stat().st_size,
                validator_status="passed",
                output_tables=profiles,
            )
        )
    return outputs, runs, request


def test_score_identity_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "score_data.duckdb"
    path.write_bytes(b"not-the-accepted-score")
    with pytest.raises(R2AT04AuditError, match="bound_file_sha256_mismatch"):
        verify_file_identity(
            path,
            expected_sha256="0" * 64,
            expected_byte_size=path.stat().st_size,
        )


def test_fixed_logical_chunk_fingerprint_is_batch_boundary_invariant() -> None:
    table, contract = _rich_arrow_table()
    profiles = [
        canonical_profile_from_batches(
            table_name="rich_table",
            contract=contract,
            batches=_physical_batches(table, physical_size),
        )
        for physical_size in (1, 7, 2048, 65_536)
    ]
    assert {profile["row_count"] for profile in profiles} == {65_537}
    assert {profile["schema_fingerprint"] for profile in profiles} == {
        profiles[0]["schema_fingerprint"]
    }
    assert {tuple(profile["canonical_chunk_fingerprints"]) for profile in profiles} == {
        tuple(profiles[0]["canonical_chunk_fingerprints"])
    }
    assert {profile["canonical_fingerprint"] for profile in profiles} == {
        profiles[0]["canonical_fingerprint"]
    }
    assert profiles[0]["canonical_chunk_count"] == 2


def test_canonical_profile_is_insertion_and_thread_independent(tmp_path: Path) -> None:
    contract = TableSpec(
        (ColumnSpec("id", "BIGINT"), ColumnSpec("value_text", "VARCHAR", True)),
        ("id",),
    )
    profiles = []
    for ordinal, (threads, direction) in enumerate(((4, "ASC"), (16, "DESC"))):
        path = tmp_path / f"insertion-{ordinal}.duckdb"
        with duckdb.connect(str(path)) as connection:
            connection.execute(f"SET threads={threads}")
            connection.execute(
                "CREATE TABLE logical_rows AS SELECT i id,"
                "CASE WHEN i%13=0 THEN NULL ELSE 'V'||i::VARCHAR END AS value_text "
                f"FROM range(70000) t(i) ORDER BY i {direction}"
            )
            profiles.append(
                canonical_table_profile(
                    connection,
                    table_name="logical_rows",
                    contract=contract,
                    physical_batch_row_count=7 if threads == 4 else 2048,
                )
            )
    assert profiles[0] == profiles[1]


def test_pairwise_logical_comparison_reports_exact_mutated_column(
    tmp_path: Path,
) -> None:
    outputs, _, _ = _synthetic_thread_outputs(tmp_path)
    with duckdb.connect(str(outputs[16])) as connection:
        connection.execute(
            "UPDATE dynamic_request SET floating_comparison_epsilon=2e-12"
        )
        connection.execute("CHECKPOINT")
    comparison = compare_output_databases(
        left_database=outputs[4],
        right_database=outputs[16],
        left_threads=4,
        right_threads=16,
    )
    table = comparison["tables"]["dynamic_request"]
    assert comparison["status"] == "logical_value_mismatch"
    assert table["value_comparison"]["value_mismatch_row_count"] == 1
    assert (
        table["value_comparison"]["per_column_mismatch_count"][
            "floating_comparison_epsilon"
        ]
        == 1
    )
    assert len(table["primary_key_comparison"]["first_mismatch_keys"]) == 1


def test_pairwise_logical_comparison_reports_primary_key_set_difference(
    tmp_path: Path,
) -> None:
    outputs, _, _ = _synthetic_thread_outputs(tmp_path)
    with duckdb.connect(str(outputs[8])) as connection:
        mismatch_key = connection.execute(
            "SELECT request_id,security_id,trading_date,dimension_id "
            "FROM daily_dimension_states ORDER BY ALL LIMIT 1"
        ).fetchone()
        connection.execute(
            "DELETE FROM daily_dimension_states WHERE request_id=? AND security_id=? "
            "AND trading_date=? AND dimension_id=?",
            mismatch_key,
        )
        connection.execute("CHECKPOINT")
    comparison = compare_output_databases(
        left_database=outputs[4],
        right_database=outputs[8],
        left_threads=4,
        right_threads=8,
    )
    table = comparison["tables"]["daily_dimension_states"]
    assert comparison["status"] == "primary_key_mismatch"
    assert table["primary_key_comparison"]["left_only_key_count"] == 1
    assert table["primary_key_comparison"]["right_only_key_count"] == 0
    assert table["primary_key_comparison"]["first_mismatch_keys"] == [
        {
            "request_id": mismatch_key[0],
            "security_id": mismatch_key[1],
            "trading_date": mismatch_key[2].isoformat(),
            "dimension_id": mismatch_key[3],
        }
    ]


def test_fingerprint_mismatch_writes_blocked_receipt_before_cleanup(
    tmp_path: Path,
) -> None:
    outputs, runs, request = _synthetic_thread_outputs(tmp_path)
    altered = list(runs)
    changed_profiles = deepcopy(altered[1].output_tables)
    changed_profiles["dynamic_request"]["canonical_fingerprint"] = "f" * 64
    altered[1] = ThreadBenchmarkRun(
        **{**asdict(altered[1]), "output_tables": changed_profiles}
    )
    receipt_path = tmp_path / "preflight" / "thread_benchmark_receipt.json"
    receipt = finalize_thread_benchmark_outputs(
        runs=altered,
        output_databases=outputs,
        scratch_directory=outputs[4].parent,
        receipt_path=receipt_path,
        failure_evidence_root=tmp_path / "preflight" / "failure-evidence",
        implementation_head="1" * 40,
        score_release_id="pcavt-score-w120-v1-c7e04f11a2cd09aa",
        score_database_sha256="2" * 64,
        score_database_byte_size=123,
        canonical_request=request,
        security_ids=["S1", "S2", "S3", "S4"],
    )
    assert _result_exit_code(receipt) != 0
    assert receipt_path.is_file()
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == (
        "fingerprint_algorithm_mismatch_without_logical_difference"
    )
    assert receipt["formal_run_attempt_consumed"] is False
    assert not outputs[4].parent.exists()
    _validate_thread_benchmark_receipt(receipt)


def test_logical_mismatch_preserves_failure_evidence_and_receipt(
    tmp_path: Path,
) -> None:
    outputs, runs, request = _synthetic_thread_outputs(tmp_path)
    with duckdb.connect(str(outputs[16])) as connection:
        connection.execute(
            "UPDATE dynamic_request SET floating_comparison_epsilon=2e-12"
        )
        connection.execute("CHECKPOINT")
    with duckdb.connect(str(outputs[16]), read_only=True) as connection:
        changed_profiles = canonical_table_profiles(connection)
    runs[-1] = ThreadBenchmarkRun(
        **{**asdict(runs[-1]), "output_tables": changed_profiles}
    )
    receipt_path = tmp_path / "preflight" / "thread_benchmark_receipt.json"
    evidence_root = tmp_path / "preflight" / "failure-evidence"
    receipt = finalize_thread_benchmark_outputs(
        runs=runs,
        output_databases=outputs,
        scratch_directory=outputs[4].parent,
        receipt_path=receipt_path,
        failure_evidence_root=evidence_root,
        implementation_head="1" * 40,
        score_release_id="pcavt-score-w120-v1-c7e04f11a2cd09aa",
        score_database_sha256="2" * 64,
        score_database_byte_size=123,
        canonical_request=request,
        security_ids=["S1", "S2", "S3", "S4"],
    )
    assert receipt["reason_code"] == "thread_dependent_logical_output_mismatch"
    assert len(receipt["failure_evidence_files"]) == 3
    diagnostic = receipt["failure_evidence_diagnostic_id"]
    assert len(list((evidence_root / diagnostic).glob("*.duckdb"))) == 3
    mismatches = [
        table["primary_key_comparison"]["first_mismatch_keys"]
        for pair in receipt["pairwise_comparisons"]
        for table in pair["tables"].values()
        if table["status"] != "logically_equal"
    ]
    assert any(mismatches)
    assert receipt_path.is_file()
    _validate_thread_benchmark_receipt(receipt)


def test_passed_benchmark_receipt_precedes_cleanup_and_uses_ten_percent_rule(
    tmp_path: Path,
) -> None:
    outputs, runs, request = _synthetic_thread_outputs(tmp_path)
    receipt_path = tmp_path / "preflight" / "thread_benchmark_receipt.json"
    receipt = finalize_thread_benchmark_outputs(
        runs=runs,
        output_databases=outputs,
        scratch_directory=outputs[4].parent,
        receipt_path=receipt_path,
        failure_evidence_root=tmp_path / "preflight" / "failure-evidence",
        implementation_head="1" * 40,
        score_release_id="pcavt-score-w120-v1-c7e04f11a2cd09aa",
        score_database_sha256="2" * 64,
        score_database_byte_size=123,
        canonical_request=request,
        security_ids=["S1", "S2", "S3", "S4"],
    )
    assert receipt["status"] == "passed"
    assert receipt["selected_duckdb_thread_count"] == 4
    assert receipt_path.is_file()
    assert not outputs[4].parent.exists()
    _validate_thread_benchmark_receipt(receipt)


def test_market_source_full_present_coverage_and_integrity(tmp_path: Path) -> None:
    score = tmp_path / "score.duckdb"
    market = tmp_path / "market.duckdb"
    create_score_database(score)
    spec = create_market_database(market, score)
    result = validate_market_source(
        score_database=score,
        market_database=market,
        source_spec=spec,
        scratch_directory=tmp_path / "market-validation",
    )
    assert result["validator_status"] == "passed"
    assert result["present_key_missing_count"] == 0


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            "INSERT INTO market_data SELECT * FROM market_data LIMIT 1",
            "market_duplicate_key",
        ),
        (
            "UPDATE market_data SET raw_high=raw_close*0.5 WHERE rowid="
            "(SELECT min(rowid) FROM market_data)",
            "market_value_integrity_failed",
        ),
        (
            "DELETE FROM market_data WHERE rowid=(SELECT min(rowid) FROM market_data)",
            "market_present_key_coverage_missing",
        ),
    ],
)
def test_market_source_fail_closed_mutations(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    score = tmp_path / "score.duckdb"
    market = tmp_path / "market.duckdb"
    create_score_database(score)
    spec = create_market_database(market, score)
    with duckdb.connect(str(market)) as connection:
        connection.execute(mutation)
        connection.execute("CHECKPOINT")
    spec["database_sha256"] = _sha(market)
    spec["database_byte_size"] = market.stat().st_size
    with pytest.raises(R2AT04AuditError, match=reason):
        validate_market_source(
            score_database=score,
            market_database=market,
            source_spec=spec,
            scratch_directory=tmp_path / "market-validation",
        )


def test_market_unit_mapping_schema_rejects_wrong_units(tmp_path: Path) -> None:
    score = tmp_path / "score.duckdb"
    market = tmp_path / "market.duckdb"
    create_score_database(score)
    spec = create_market_database(market, score)
    spec["unit_mapping"]["volume_shares"] = "lots"
    schema = json.loads(
        Path("schemas/r2a/r2a_t04_local_source_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert list(Draft202012Validator(schema).iter_errors(spec))
