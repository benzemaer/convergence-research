from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from src.r0.percentile_score_engine import ACTIVE_INDICATORS, PERCENTILE_WINDOWS
from src.r0.r0_t10_nested_state_materialization_validator import (
    R0T10NestedStateValidationError,
    validate_materialization,
)
from src.r0.r0_t10_nested_state_materializer import (
    DIMENSION_STATE_DUCKDB_NAME,
    INDICATOR_STATE_DUCKDB_NAME,
    MANIFEST_NAME,
    NESTED_DAILY_DUCKDB_NAME,
    R0T10NestedStateMaterializationError,
    materialize_r0_t06_nested_states,
)
from src.r0.r0_t10_score_materializer import (
    COMMON_DUCKDB_NAME,
    COMMON_TABLE_NAME,
    DIMENSION_DUCKDB_NAME,
    DIMENSION_TABLE_NAME,
    INDICATOR_DUCKDB_NAME,
    INDICATOR_TABLE_NAME,
)
from src.r0.upstream_artifact_io import quote_ident, sha256_file


def write_r0_t05_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    source_dir = root / "r0_t05"
    source_dir.mkdir(parents=True)
    indicator_path = source_dir / INDICATOR_DUCKDB_NAME
    dimension_path = source_dir / DIMENSION_DUCKDB_NAME
    common_path = source_dir / COMMON_DUCKDB_NAME

    _write_indicator_scores(indicator_path)
    _write_dimension_scores(dimension_path)
    _write_common_scores(common_path)
    evidence = _write_evidence(root / "docs/evidence/r0/r0_t05.md", source_dir)
    return evidence, indicator_path, dimension_path, common_path


def _write_indicator_scores(path: Path) -> None:
    conn = duckdb.connect(str(path))
    try:
        conn.execute(
            f"""
            CREATE TABLE {quote_ident(INDICATOR_TABLE_NAME)} (
              security_id TEXT,
              trading_date TEXT,
              percentile_window_W INTEGER,
              indicator_id TEXT,
              score DOUBLE,
              eligible BOOLEAN,
              validity_status TEXT,
              reason_codes TEXT[]
            )
            """
        )
        rows = []
        for security_id in ("000001.SZ", "000002.SZ"):
            for window in PERCENTILE_WINDOWS:
                for offset, indicator_id in enumerate(ACTIVE_INDICATORS):
                    rows.append(
                        (
                            security_id,
                            "2026-06-30",
                            window,
                            indicator_id,
                            0.90 if offset % 2 == 0 else 0.70,
                            True,
                            "valid",
                            ["valid_no_blocker"],
                        )
                    )
        conn.executemany(
            f"INSERT INTO {quote_ident(INDICATOR_TABLE_NAME)} "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    finally:
        conn.close()


def _write_dimension_scores(path: Path) -> None:
    conn = duckdb.connect(str(path))
    try:
        conn.execute(
            f"""
            CREATE TABLE {quote_ident(DIMENSION_TABLE_NAME)} (
              security_id TEXT,
              trading_date TEXT,
              percentile_window_W INTEGER,
              dimension TEXT,
              score_dimension DOUBLE,
              score_dimension_min DOUBLE,
              eligible_dimension BOOLEAN,
              validity_status TEXT,
              reason_codes TEXT[],
              component_indicator_ids TEXT[]
            )
            """
        )
        rows = []
        for security_id in ("000001.SZ", "000002.SZ"):
            for window in PERCENTILE_WINDOWS:
                rows.extend(
                    [
                        _dimension_row(security_id, window, "P", 0.92, 0.85),
                        _dimension_row(security_id, window, "C", 0.86, 0.80),
                        _dimension_row(security_id, window, "T", 0.79, 0.71),
                        _dimension_row(security_id, window, "V", 0.95, 0.88),
                    ]
                )
        conn.executemany(
            f"INSERT INTO {quote_ident(DIMENSION_TABLE_NAME)} "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    finally:
        conn.close()


def _dimension_row(
    security_id: str,
    window: int,
    dimension: str,
    score: float,
    score_min: float,
) -> tuple[object, ...]:
    return (
        security_id,
        "2026-06-30",
        window,
        dimension,
        score,
        score_min,
        True,
        "valid",
        ["valid_no_blocker"],
        [f"{dimension}_component"],
    )


def _write_common_scores(path: Path) -> None:
    conn = duckdb.connect(str(path))
    try:
        conn.execute(
            f"""
            CREATE TABLE {quote_ident(COMMON_TABLE_NAME)} (
              security_id TEXT,
              trading_date TEXT,
              percentile_window_W INTEGER,
              common_eligible BOOLEAN
            )
            """
        )
        rows = [
            (security_id, "2026-06-30", window, True)
            for security_id in ("000001.SZ", "000002.SZ")
            for window in PERCENTILE_WINDOWS
        ]
        conn.executemany(
            f"INSERT INTO {quote_ident(COMMON_TABLE_NAME)} VALUES (?, ?, ?, ?)",
            rows,
        )
    finally:
        conn.close()


def _write_evidence(path: Path, source_dir: Path) -> Path:
    indicator_path = source_dir / INDICATOR_DUCKDB_NAME
    dimension_path = source_dir / DIMENSION_DUCKDB_NAME
    common_path = source_dir / COMMON_DUCKDB_NAME
    conn = duckdb.connect(str(dimension_path), read_only=True)
    try:
        dimension_rows, security_count, date_min, date_max = conn.execute(
            f"""
            SELECT count(*), count(DISTINCT security_id), min(trading_date),
                   max(trading_date)
            FROM {quote_ident(DIMENSION_TABLE_NAME)}
            """
        ).fetchone()
    finally:
        conn.close()
    conn = duckdb.connect(str(indicator_path), read_only=True)
    try:
        indicator_rows = conn.execute(
            f"SELECT count(*) FROM {quote_ident(INDICATOR_TABLE_NAME)}"
        ).fetchone()[0]
    finally:
        conn.close()
    conn = duckdb.connect(str(common_path), read_only=True)
    try:
        common_rows = conn.execute(
            f"SELECT count(*) FROM {quote_ident(COMMON_TABLE_NAME)}"
        ).fetchone()[0]
    finally:
        conn.close()

    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                "`task_id`: R0-T10-02",
                "`status`: completed",
                f"`indicator_score_duckdb_sha256`: `{sha256_file(indicator_path)}`",
                f"`dimension_score_duckdb_sha256`: `{sha256_file(dimension_path)}`",
                f"`common_eligible_duckdb_sha256`: `{sha256_file(common_path)}`",
                f"`indicator_score_row_count`: {indicator_rows:,}",
                f"`dimension_score_row_count`: {dimension_rows:,}",
                f"`common_eligible_row_count`: {common_rows:,}",
                f"`security_count`: {security_count}",
                f"`date_min`: {date_min}",
                f"`date_max`: {date_max}",
                "`R0-T06_allowed_to_start`: true",
            ]
        ),
        encoding="utf-8",
    )
    return path


class R0T10NestedStateMaterializerTest(unittest.TestCase):
    def test_max_workers_16_materializes_nested_state_without_row_payloads(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence, indicator, dimension, common = write_r0_t05_fixture(root)
            output_dir = root / "out"

            summary = materialize_r0_t06_nested_states(
                r0_t05_evidence=evidence,
                indicator_score_duckdb=indicator,
                dimension_score_duckdb=dimension,
                common_eligible_duckdb=common,
                output_dir=output_dir,
                run_id="R0-T10-03-TEST",
                code_commit="abcdef",
                max_workers=16,
                chunk_size_securities=1,
            )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["max_workers"], 16)
            self.assertTrue((output_dir / INDICATOR_STATE_DUCKDB_NAME).is_file())
            self.assertTrue((output_dir / DIMENSION_STATE_DUCKDB_NAME).is_file())
            self.assertTrue((output_dir / NESTED_DAILY_DUCKDB_NAME).is_file())
            self.assertTrue((output_dir / MANIFEST_NAME).is_file())
            self.assertFalse(_has_key(summary, "rows"))

            manifest = json.loads(
                (output_dir / MANIFEST_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(set(manifest["W_coverage"]), set(PERCENTILE_WINDOWS))
            self.assertEqual(set(manifest["q_coverage"]), {0.1, 0.2, 0.3})
            self.assertEqual(set(manifest["dimension_coverage"]), {"P", "C", "T", "V"})
            self.assertEqual(manifest["R0-T07_allowed_to_start"], True)
            self.assertFalse(_has_key(manifest, "rows"))

    def test_max_workers_17_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            R0T10NestedStateMaterializationError, "between 1 and 16"
        ):
            materialize_r0_t06_nested_states(
                r0_t05_evidence="missing.md",
                indicator_score_duckdb="missing_indicator.duckdb",
                dimension_score_duckdb="missing_dimension.duckdb",
                common_eligible_duckdb="missing_common.duckdb",
                output_dir="out",
                run_id="run",
                code_commit="abcdef",
                max_workers=17,
            )

    def test_uses_spawn_process_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence, indicator, dimension, common = write_r0_t05_fixture(root)
            with patch(
                "src.r0.r0_t10_nested_state_materializer.concurrent.futures.ProcessPoolExecutor"
            ) as pool:
                pool.return_value.__enter__.side_effect = RuntimeError("stop")
                with self.assertRaisesRegex(RuntimeError, "stop"):
                    materialize_r0_t06_nested_states(
                        r0_t05_evidence=evidence,
                        indicator_score_duckdb=indicator,
                        dimension_score_duckdb=dimension,
                        common_eligible_duckdb=common,
                        output_dir=root / "out",
                        run_id="run",
                        code_commit="abcdef",
                    )
            self.assertEqual(
                pool.call_args.kwargs["mp_context"].get_start_method(), "spawn"
            )

    def test_input_hash_mismatch_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence, indicator, dimension, common = write_r0_t05_fixture(root)
            evidence.write_text(
                evidence.read_text(encoding="utf-8").replace(
                    "dimension_score_duckdb_sha256`: `",
                    "dimension_score_duckdb_sha256`: `bad",
                ),
                encoding="utf-8",
            )

            summary = materialize_r0_t06_nested_states(
                r0_t05_evidence=evidence,
                indicator_score_duckdb=indicator,
                dimension_score_duckdb=dimension,
                common_eligible_duckdb=common,
                output_dir=root / "out",
                run_id="run",
                code_commit="abcdef",
            )

            self.assertEqual(summary["status"], "blocked")
            self.assertIn(
                "r0_t05_dimension_duckdb_hash_mismatch", summary["reason_codes"]
            )
            self.assertFalse((root / "out" / MANIFEST_NAME).exists())

    def test_failed_chunk_blocks_final_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence, indicator, dimension, common = write_r0_t05_fixture(root)
            output_dir = root / "out"
            with patch(
                "src.r0.r0_t10_nested_state_materializer._run_chunks",
                return_value=[
                    {
                        "chunk_id": "chunk-00000",
                        "status": "failed",
                        "error_type": "RuntimeError",
                        "error_message": "boom",
                    }
                ],
            ):
                summary = materialize_r0_t06_nested_states(
                    r0_t05_evidence=evidence,
                    indicator_score_duckdb=indicator,
                    dimension_score_duckdb=dimension,
                    common_eligible_duckdb=common,
                    output_dir=output_dir,
                    run_id="run",
                    code_commit="abcdef",
                    max_workers=1,
                )

            self.assertEqual(summary["status"], "failed")
            self.assertFalse((output_dir / MANIFEST_NAME).exists())
            self.assertFalse((output_dir / NESTED_DAILY_DUCKDB_NAME).exists())
            self.assertEqual(summary["R0-T07_allowed_to_start"], False)

    def test_validator_recomputes_nested_state_and_fails_on_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence, indicator, dimension, common = write_r0_t05_fixture(root)
            output_dir = root / "out"
            materialize_r0_t06_nested_states(
                r0_t05_evidence=evidence,
                indicator_score_duckdb=indicator,
                dimension_score_duckdb=dimension,
                common_eligible_duckdb=common,
                output_dir=output_dir,
                run_id="R0-T10-03-TEST",
                code_commit="abcdef",
                max_workers=1,
                chunk_size_securities=2,
            )

            result = validate_materialization(
                output_dir=output_dir,
                r0_t05_evidence=evidence,
                indicator_score_duckdb=indicator,
                dimension_score_duckdb=dimension,
                common_eligible_duckdb=common,
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["nested_recompute_check"], "passed")
            self.assertGreaterEqual(result["nested_recompute_sample_count"], 9)
            self.assertTrue(result["exclusive_layer_recompute_coverage"])
            self.assertGreater(result["exclusive_layer_non_none_sample_count"], 0)

            conn = duckdb.connect(str(output_dir / NESTED_DAILY_DUCKDB_NAME))
            try:
                conn.execute(
                    """
                    UPDATE r0_t06_nested_daily_state_results
                    SET exclusive_state_layer = 'PCVT'
                    WHERE security_id = '000001.SZ'
                      AND percentile_window_W = 120
                      AND abs(q - 0.10) < 0.000000001
                    """
                )
            finally:
                conn.close()

            with self.assertRaisesRegex(
                R0T10NestedStateValidationError, "nested_recompute_mismatch"
            ):
                validate_materialization(
                    output_dir=output_dir,
                    r0_t05_evidence=evidence,
                    indicator_score_duckdb=indicator,
                    dimension_score_duckdb=dimension,
                    common_eligible_duckdb=common,
                )

    def test_validator_blocks_when_non_none_layer_exists_but_sample_misses_it(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence, indicator, dimension, common = write_r0_t05_fixture(root)
            output_dir = root / "out"
            materialize_r0_t06_nested_states(
                r0_t05_evidence=evidence,
                indicator_score_duckdb=indicator,
                dimension_score_duckdb=dimension,
                common_eligible_duckdb=common,
                output_dir=output_dir,
                run_id="R0-T10-03-TEST",
                code_commit="abcdef",
                max_workers=1,
                chunk_size_securities=2,
            )

            with (
                patch(
                    "src.r0.r0_t10_nested_state_materialization_validator."
                    "_select_nested_recompute_samples",
                    return_value=[],
                ),
                self.assertRaisesRegex(
                    R0T10NestedStateValidationError,
                    "exclusive_layer_recompute_non_none_missing",
                ),
            ):
                validate_materialization(
                    output_dir=output_dir,
                    r0_t05_evidence=evidence,
                    indicator_score_duckdb=indicator,
                    dimension_score_duckdb=dimension,
                    common_eligible_duckdb=common,
                )


def _has_key(payload: object, key: str) -> bool:
    if isinstance(payload, dict):
        return key in payload or any(_has_key(value, key) for value in payload.values())
    if isinstance(payload, list):
        return any(_has_key(value, key) for value in payload)
    return False


if __name__ == "__main__":
    unittest.main()
