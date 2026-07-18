from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from src.r2a.r2a_t01_score_release import ScoreReleaseError, materialize_score_release
from src.r2a.score_engine import ALL_COMPONENTS, DIMENSION_ORDER
from tests.r2a._fixtures import build_package, synthetic_inputs, write_json


def test_complete_spine_left_expansion_and_release_tables(tmp_path: Path) -> None:
    package, _, _ = build_package(tmp_path)
    with duckdb.connect(
        str(package / "score_data.duckdb"), read_only=True
    ) as connection:
        tables = [row[0] for row in connection.execute("SHOW TABLES").fetchall()]
        assert tables == sorted(
            [
                "securities",
                "trading_sessions",
                "security_observation_spine",
                "dimension_definitions",
                "dimension_components",
                "daily_component_scores",
                "daily_dimension_scores",
            ]
        )
        spine_count = connection.execute(
            "SELECT count(*) FROM security_observation_spine"
        ).fetchone()[0]
        assert (
            connection.execute(
                "SELECT count(*) FROM daily_component_scores"
            ).fetchone()[0]
            == spine_count * 10
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM daily_dimension_scores"
            ).fetchone()[0]
            == spine_count * 5
        )
        assert connection.execute(
            "SELECT list(dimension_id ORDER BY dimension_order) "
            "FROM dimension_definitions"
        ).fetchone()[0] == list(DIMENSION_ORDER)
        assert connection.execute(
            "SELECT list(indicator_id ORDER BY dimension_id,component_order) "
            "FROM dimension_components"
        ).fetchone()[0]
        assert (
            connection.execute(
                "SELECT count(*) FROM dimension_components WHERE indicator_id ILIKE '%A2b%'"
            ).fetchone()[0]
            == 0
        )
        assert set(
            row[0]
            for row in connection.execute(
                "SELECT indicator_id FROM dimension_components"
            ).fetchall()
        ) == set(ALL_COMPONENTS)


def test_missing_and_listing_pause_rows_are_explicit_nulls(tmp_path: Path) -> None:
    package, _, _ = build_package(tmp_path)
    with duckdb.connect(
        str(package / "score_data.duckdb"), read_only=True
    ) as connection:
        statuses = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT observation_status FROM security_observation_spine"
            ).fetchall()
        }
        assert statuses == {"present", "missing", "listing_pause"}
        for status in ("missing", "listing_pause"):
            row = connection.execute(
                "SELECT trading_date FROM security_observation_spine "
                "WHERE observation_status=?",
                [status],
            ).fetchone()
            assert row is not None
            component = connection.execute(
                "SELECT count(*),count(score),bool_and(NOT eligible) "
                "FROM daily_component_scores WHERE trading_date=?",
                row,
            ).fetchone()
            dimension = connection.execute(
                "SELECT count(*),count(score_dimension),"
                "bool_and(NOT eligible_dimension) FROM daily_dimension_scores "
                "WHERE trading_date=?",
                row,
            ).fetchone()
            assert component == (10, 0, True)
            assert dimension == (5, 0, True)


def test_availability_policy_is_exact_non_null_timestamptz(tmp_path: Path) -> None:
    package, _, _ = build_package(tmp_path)
    with duckdb.connect(
        str(package / "score_data.duckdb"), read_only=True
    ) as connection:
        for table, column in (
            ("trading_sessions", "available_time"),
            ("security_observation_spine", "observation_available_time"),
            ("daily_component_scores", "available_time"),
            ("daily_dimension_scores", "available_time"),
        ):
            info = {
                row[1]: row[2]
                for row in connection.execute(
                    f'PRAGMA table_info("{table}")'
                ).fetchall()
            }
            assert info[column] == "TIMESTAMP WITH TIME ZONE"
            assert (
                connection.execute(
                    f'SELECT count(*) FROM "{table}" WHERE "{column}" IS NULL'
                ).fetchone()[0]
                == 0
            )
            assert (
                connection.execute(
                    f'SELECT count(*) FROM "{table}" WHERE '
                    f"({column} AT TIME ZONE 'Asia/Shanghai')::TIME<>TIME '15:00:00'"
                ).fetchone()[0]
                == 0
            )


def test_atomic_failure_leaves_no_candidate_package(tmp_path: Path) -> None:
    manifest, paths = synthetic_inputs(tmp_path / "inputs")
    rows = json.loads(paths["security_observation_spine"].read_text(encoding="utf-8"))
    rows.append(dict(rows[-1]))
    write_json(paths["security_observation_spine"], rows)
    # Rebind the intentionally invalid fixture so failure occurs in materialization.
    from src.r2a.r2a_t01_input_manifest import build_synthetic_input_manifest

    build_synthetic_input_manifest(
        output_path=manifest,
        run_id="invalid",
        synthetic_root=tmp_path / "inputs",
        inputs=paths,
    )
    package = tmp_path / "candidate"
    with pytest.raises(ScoreReleaseError, match="invalid_or_duplicate_spine_key"):
        materialize_score_release(
            authorized_input_manifest=manifest,
            output_dir=package,
            run_id="invalid",
            score_release_id="invalid",
        )
    assert not package.exists()
    assert not list(tmp_path.glob(".candidate.tmp-*"))


def test_formal_path_and_non_synthetic_execution_fail_closed(tmp_path: Path) -> None:
    manifest, _ = synthetic_inputs(tmp_path / "inputs")
    with pytest.raises(ScoreReleaseError, match="formal_run_not_authorized"):
        materialize_score_release(
            authorized_input_manifest=manifest,
            output_dir=tmp_path / "package",
            run_id="formal",
            score_release_id="formal",
            synthetic_only=False,
        )
