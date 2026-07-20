from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from src.r2a.r2a_t04_real_data_audit import (
    canonical_table_profiles,
    compare_output_databases,
    evaluate_request_with_threads,
)
from src.r2a.r2a_t04_request_panel import build_request_panel, canonical_envelope
from src.r2a.r2a_t04_set_based_evaluator import (
    evaluate_request_set_based_with_threads,
)
from tests.r2a.r2a_t03_test_support import create_source


def _source(path: Path) -> None:
    source = create_source(str(path))
    source.execute(
        "INSERT INTO daily_dimension_scores SELECT score_release_id,security_id,"
        "trading_date,observation_sequence,'C',score_dimension,score_dimension_min,"
        "eligible_dimension,validity_status,reason_codes,available_time FROM "
        "daily_dimension_scores WHERE dimension_id='T'"
    )
    source.execute(
        "UPDATE daily_dimension_scores SET score_dimension=0.80,"
        "score_dimension_min=0.70 WHERE dimension_id='A' AND security_id='S1' "
        "AND observation_sequence BETWEEN 11 AND 14"
    )
    source.execute("CHECKPOINT")
    source.close()


@pytest.mark.parametrize("logical_name", ("CA_q15_k5", "CA_q25_k5"))
def test_set_based_transfer_is_logically_identical_to_t03(
    tmp_path: Path, logical_name: str
) -> None:
    score = tmp_path / "score.duckdb"
    _source(score)
    item = next(
        item
        for item in build_request_panel()
        if item["logical_request_name"] == logical_name
    )
    old_path = tmp_path / "old.duckdb"
    new_path = tmp_path / "new.duckdb"
    evaluate_request_with_threads(
        score_database=score,
        canonical_request=canonical_envelope(item),
        output_database=old_path,
        duckdb_thread_count=4,
        security_ids=None,
    )
    evaluate_request_set_based_with_threads(
        score_database=score,
        canonical_request=canonical_envelope(item),
        output_database=new_path,
        duckdb_thread_count=4,
        security_ids=None,
    )
    comparison = compare_output_databases(
        left_database=old_path,
        right_database=new_path,
        left_threads=4,
        right_threads=4,
    )
    assert comparison["status"] == "logically_equal"
    with (
        duckdb.connect(str(old_path), read_only=True) as old,
        duckdb.connect(str(new_path), read_only=True) as new,
    ):
        assert canonical_table_profiles(old) == canonical_table_profiles(new)


def test_set_based_transfer_static_boundary() -> None:
    source = Path("src/r2a/r2a_t04_set_based_evaluator.py").read_text(encoding="utf-8")
    assert "ATTACH '" in source
    assert "(READ_ONLY)" in source
    assert "fetchmany" not in source
    assert "fetchall" not in source
    assert "executemany" not in source
    assert "pandas" not in source
