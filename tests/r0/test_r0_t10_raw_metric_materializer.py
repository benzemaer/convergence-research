from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import duckdb

from src.r0.r0_t10_raw_metric_materializer import (
    OUTPUT_MANIFEST_NAME,
    OUTPUT_SUMMARY_NAME,
    R0T10MaterializationError,
    materialize_r0_t04_raw_metrics,
)


def has_key(payload: object, forbidden: str) -> bool:
    if isinstance(payload, dict):
        return any(
            key == forbidden or has_key(value, forbidden)
            for key, value in payload.items()
        )
    if isinstance(payload, list):
        return any(has_key(value, forbidden) for value in payload)
    return False


def write_d3_source(
    root: Path, *, securities: tuple[str, ...] = ("000001.SZ",)
) -> Path:
    d3_dir = root / "data/generated/d3/d3_t11_volume_amount_share_turnover_candidate"
    d3_dir.mkdir(parents=True)
    db_path = d3_dir / "d3_t11_volume_amount_share_turnover_candidate.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE d3_candidate_daily_observation (
              security_id TEXT,
              trading_date TEXT,
              adjusted_open DOUBLE,
              adjusted_high DOUBLE,
              adjusted_low DOUBLE,
              adjusted_close DOUBLE,
              daily_vwap DOUBLE,
              daily_vwap_range_status TEXT,
              volume_shares DOUBLE,
              amount_yuan DOUBLE,
              amount_unit TEXT,
              amount_volume_unit_status TEXT,
              zero_amount_flag BOOLEAN,
              turnover_float DOUBLE,
              turnover_field_status TEXT,
              share_field_status TEXT,
              provider_turnover_crosscheck_status TEXT,
              float_share_shares DOUBLE,
              trading_status TEXT,
              corporate_action_flag BOOLEAN,
              suspension_flag BOOLEAN,
              corporate_action_types_in_window TEXT,
              share_comparability_corporate_action_in_window BOOLEAN,
              common_share_basis_policy TEXT,
              volume_comparability_policy TEXT,
              adjustment_status TEXT
            )
            """
        )
        rows = []
        start = date(2026, 1, 1)
        for security_id in securities:
            for index in range(85):
                close = 10.0 + index / 100.0
                trading_date = (start + timedelta(days=index)).isoformat()
                rows.append(
                    (
                        security_id,
                        trading_date,
                        close,
                        close * 1.01,
                        close * 0.99,
                        close,
                        close,
                        "valid",
                        1000.0,
                        close * 1000.0,
                        "yuan",
                        "valid",
                        False,
                        0.02 if index < 65 else 0.01,
                        "valid",
                        "valid",
                        "valid",
                        100000000.0,
                        "normal",
                        False,
                        False,
                        "",
                        False,
                        "same",
                        "same",
                        "valid",
                    )
                )
        conn.executemany(
            """
            INSERT INTO d3_candidate_daily_observation VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            rows,
        )
    finally:
        conn.close()
    return db_path


class R0T10RawMetricMaterializerTest(unittest.TestCase):
    def test_max_workers_8_materializes_small_sample_without_row_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d3_db = write_d3_source(root, securities=("000001.SZ", "000002.SZ"))
            output_dir = root / "data/generated/r0/r0_t10/R0-T10-TEST/r0_t04"

            summary = materialize_r0_t04_raw_metrics(
                d3_duckdb=d3_db,
                output_dir=output_dir,
                run_id="R0-T10-TEST",
                code_commit="abcdef",
                max_workers=8,
                chunk_size_securities=1,
            )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["max_workers"], 8)
            self.assertEqual(summary["row_count"], 2 * 85 * 8)
            self.assertEqual(summary["chunk_count"], 2)
            self.assertTrue((output_dir / OUTPUT_MANIFEST_NAME).is_file())
            self.assertTrue((output_dir / OUTPUT_SUMMARY_NAME).is_file())
            self.assertFalse(has_key(summary, "raw_metric_results"))
            self.assertFalse(has_key(summary, "rows"))
            for chunk in summary["chunks"]:
                self.assertIn("row_count", chunk)
                self.assertIn("artifact_path", chunk)
                self.assertIn("content_sha256", chunk)
                self.assertNotIn("rows", chunk)
                self.assertNotIn("raw_metric_results", chunk)

            manifest = json.loads(
                (output_dir / OUTPUT_MANIFEST_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["row_count"], 2 * 85 * 8)
            self.assertFalse(manifest["memory_boundary"]["worker_returns_rows"])
            self.assertFalse(manifest["memory_boundary"]["parent_holds_upstream_rows"])
            self.assertTrue(
                manifest["memory_boundary"]["duckdb_written_by_stream_append"]
            )

    def test_max_workers_9_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d3_db = write_d3_source(root)
            with self.assertRaisesRegex(R0T10MaterializationError, "between 1 and 8"):
                materialize_r0_t04_raw_metrics(
                    d3_duckdb=d3_db,
                    output_dir=root / "data/generated/r0/r0_t10/run/r0_t04",
                    run_id="R0-T10-TEST",
                    code_commit="abcdef",
                    max_workers=9,
                )

    def test_resume_skips_done_chunk_by_hash_without_row_payload_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d3_db = write_d3_source(root)
            output_dir = root / "data/generated/r0/r0_t10/R0-T10-TEST/r0_t04"
            kwargs = {
                "d3_duckdb": d3_db,
                "output_dir": output_dir,
                "run_id": "R0-T10-TEST",
                "code_commit": "abcdef",
                "max_workers": 1,
                "chunk_size_securities": 1,
            }

            first = materialize_r0_t04_raw_metrics(**kwargs)
            resumed = materialize_r0_t04_raw_metrics(**kwargs, resume=True)

            self.assertEqual(first["completed_chunk_count"], 1)
            self.assertEqual(resumed["skipped_chunk_count"], 1)
            self.assertEqual(resumed["chunks"][0]["status"], "skipped")
            self.assertNotIn("rows", resumed["chunks"][0])

    def test_resume_recomputes_when_partial_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d3_db = write_d3_source(root)
            output_dir = root / "data/generated/r0/r0_t10/R0-T10-TEST/r0_t04"
            kwargs = {
                "d3_duckdb": d3_db,
                "output_dir": output_dir,
                "run_id": "R0-T10-TEST",
                "code_commit": "abcdef",
                "max_workers": 1,
                "chunk_size_securities": 1,
            }

            first = materialize_r0_t04_raw_metrics(**kwargs)
            artifact_path = Path(first["chunks"][0]["artifact_path"])
            artifact_path.with_name(artifact_path.name + ".partial").write_text(
                "partial", encoding="utf-8"
            )
            resumed = materialize_r0_t04_raw_metrics(**kwargs, resume=True)

            self.assertEqual(resumed["completed_chunk_count"], 1)
            self.assertEqual(resumed["skipped_chunk_count"], 0)
            self.assertFalse(
                artifact_path.with_name(artifact_path.name + ".partial").exists()
            )


if __name__ == "__main__":
    unittest.main()
