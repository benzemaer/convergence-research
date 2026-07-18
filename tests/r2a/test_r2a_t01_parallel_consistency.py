from __future__ import annotations

from pathlib import Path

import duckdb

from src.r2a.r2a_t01_artifact_manifest import TABLE_ORDER
from tests.r2a._fixtures import build_package


def test_single_and_multi_worker_outputs_are_relationally_identical(
    tmp_path: Path,
) -> None:
    package_one, manifest, _ = build_package(
        tmp_path / "one", worker_count=1, security_ids=("000001.SZ", "000002.SZ")
    )
    # Reuse the exact bound inputs to isolate worker-count behavior.
    from src.r2a.r2a_t01_score_release import materialize_score_release

    package_many = tmp_path / "many" / "package-w4"
    materialize_score_release(
        authorized_input_manifest=manifest,
        output_dir=package_many,
        run_id="R2A-T01-SYNTHETIC",
        score_release_id="R2A-T01-SYNTHETIC-RELEASE",
        worker_count=4,
    )
    with (
        duckdb.connect(str(package_one / "score_data.duckdb"), read_only=True) as left,
        duckdb.connect(
            str(package_many / "score_data.duckdb"), read_only=True
        ) as right,
    ):
        for table in TABLE_ORDER:
            left_rows = left.execute(f'SELECT * FROM "{table}" ORDER BY ALL').fetchall()
            right_rows = right.execute(
                f'SELECT * FROM "{table}" ORDER BY ALL'
            ).fetchall()
            assert left_rows == right_rows, table
