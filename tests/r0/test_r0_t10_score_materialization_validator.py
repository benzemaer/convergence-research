import tempfile
import unittest
from pathlib import Path

import duckdb

from src.r0.r0_t10_score_materialization_validator import (
    R0T10ScoreValidationError,
    validate_materialization,
)
from src.r0.r0_t10_score_materializer import (
    INDICATOR_DUCKDB_NAME,
    INDICATOR_TABLE_NAME,
    materialize_r0_t05_scores,
)
from tests.r0.test_r0_t10_score_materializer import (
    INPUT_IDS,
    write_evidence,
    write_r0_t04_duckdb,
)


class R0T10ScoreMaterializationValidatorTest(unittest.TestCase):
    def test_deterministic_recompute_passes_for_regular_and_v2_indicators(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r0_t04 = write_r0_t04_duckdb(root)
            output_dir = _materialize_fixture(root, r0_t04)

            result = validate_materialization(output_dir, r0_t04_duckdb=r0_t04)

            self.assertEqual(result["strict_past_recompute_check"], "passed")
            self.assertEqual(result["strict_past_recompute_mismatch_count"], 0)
            self.assertGreaterEqual(result["strict_past_recompute_sample_count"], 6)
            self.assertEqual(
                set(result["strict_past_recompute_W_coverage"]), {120, 250, 500}
            )
            self.assertIn(
                "P1_NATR14", result["strict_past_recompute_indicator_coverage"]
            )
            self.assertIn(
                "V2_AmountLevel20Pct",
                result["strict_past_recompute_indicator_coverage"],
            )

    def test_deterministic_recompute_passes_for_midrank_tie_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r0_t04 = write_tie_r0_t04_duckdb(root)
            output_dir = _materialize_fixture(root, r0_t04)

            result = validate_materialization(output_dir, r0_t04_duckdb=r0_t04)

            self.assertEqual(result["strict_past_recompute_check"], "passed")
            self.assertEqual(result["midrank_tie_recompute_check"], "passed")

    def test_deterministic_recompute_fails_on_percentile_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r0_t04 = write_r0_t04_duckdb(root)
            output_dir = _materialize_fixture(root, r0_t04)
            _corrupt_first_eligible_indicator_value(
                output_dir,
                "percentile = 0.123456789, score = 0.876543211",
            )

            with self.assertRaisesRegex(
                R0T10ScoreValidationError, "strict_past_recompute_mismatch"
            ):
                validate_materialization(output_dir, r0_t04_duckdb=r0_t04)

    def test_validator_fails_when_reference_window_contains_current_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r0_t04 = write_r0_t04_duckdb(root)
            output_dir = _materialize_fixture(root, r0_t04)
            _corrupt_first_eligible_indicator_value(
                output_dir,
                "reference_window_end = trading_date",
            )

            with self.assertRaisesRegex(
                R0T10ScoreValidationError,
                "future_leakage_hit_count|strict_past_recompute_mismatch",
            ):
                validate_materialization(output_dir, r0_t04_duckdb=r0_t04)


def _materialize_fixture(root: Path, r0_t04: Path) -> Path:
    evidence = write_evidence(root / "docs/evidence/r0/r0_t04.md", r0_t04)
    output_dir = root / "data/generated/r0/r0_t10/R0-T10-02-TEST/r0_t05"
    summary = materialize_r0_t05_scores(
        r0_t04_evidence=evidence,
        r0_t04_duckdb=r0_t04,
        output_dir=output_dir,
        run_id="R0-T10-02-TEST",
        code_commit="abcdef",
        max_workers=1,
        chunk_size_securities=1,
    )
    if summary["status"] != "completed":
        raise AssertionError(summary)
    return output_dir


def _corrupt_first_eligible_indicator_value(output_dir: Path, set_clause: str) -> None:
    conn = duckdb.connect(str(output_dir / INDICATOR_DUCKDB_NAME))
    try:
        conn.execute(
            f"""
            UPDATE {INDICATOR_TABLE_NAME}
            SET {set_clause}
            WHERE rowid = (
              SELECT rowid
              FROM {INDICATOR_TABLE_NAME}
              WHERE eligible = true
                AND indicator_id = 'P1_NATR14'
                AND percentile_window_W = 120
              ORDER BY security_id, trading_date
              LIMIT 1
            )
            """
        )
    finally:
        conn.close()


def write_tie_r0_t04_duckdb(root: Path) -> Path:
    path = (
        root / "data/generated/r0/r0_t10/R0-T10-TIE/r0_t04/"
        "r0_t04_raw_metric_results.duckdb"
    )
    path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(path))
    try:
        conn.execute(
            """
            CREATE TABLE r0_t04_raw_metric_results (
              security_id TEXT,
              trading_date TEXT,
              indicator_id TEXT,
              raw_metric_name TEXT,
              raw_value DOUBLE,
              validity_status TEXT,
              reason_codes TEXT[],
              input_window_start TEXT,
              input_window_end TEXT,
              required_observation_count INTEGER,
              actual_valid_observation_count INTEGER,
              source_field_names TEXT[],
              metric_engine_version TEXT
            )
            """
        )
        rows = []
        for day in range(1, 502):
            trading_date = f"2026-{day:04d}"
            for offset, indicator_id in enumerate(INPUT_IDS):
                rows.append(
                    (
                        "000001.SZ",
                        trading_date,
                        indicator_id,
                        "LogAmount20"
                        if indicator_id == "V2_LogAmount20_base"
                        else indicator_id,
                        float((day + offset) % 5),
                        "valid",
                        ["valid_no_blocker"],
                        "2026-0001",
                        trading_date,
                        20,
                        20,
                        ["synthetic"],
                        "r0_t04_raw_metric_engine.v1",
                    )
                )
        conn.executemany(
            """
            INSERT INTO r0_t04_raw_metric_results
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    finally:
        conn.close()
    return path


if __name__ == "__main__":
    unittest.main()
