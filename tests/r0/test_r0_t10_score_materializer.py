from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from src.r0.r0_t10_score_materializer import (
    COMMON_DUCKDB_NAME,
    DIMENSION_DUCKDB_NAME,
    INDICATOR_DUCKDB_NAME,
    MANIFEST_NAME,
    SUMMARY_NAME,
    R0T10ScoreMaterializationError,
    materialize_r0_t05_scores,
)

INPUT_IDS = (
    "P1_NATR14",
    "P2_LogRange20",
    "C1_LogMASpread_5_60",
    "C2_AdjVWAPSpread_5_60",
    "T1_ER20",
    "T2_AbsTrendT20",
    "V1_TurnoverShrink20_60",
    "V2_LogAmount20_base",
)


def write_r0_t04_duckdb(
    root: Path, securities: tuple[str, ...] = ("000001.SZ",)
) -> Path:
    path = (
        root
        / "data/generated/r0/r0_t10/R0-T10-TEST/r0_t04/r0_t04_raw_metric_results.duckdb"
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
        for security_id in securities:
            for day in range(1, 502):
                trading_date = f"2026-{day:04d}"
                for offset, indicator_id in enumerate(INPUT_IDS):
                    rows.append(
                        (
                            security_id,
                            trading_date,
                            indicator_id,
                            "LogAmount20"
                            if indicator_id == "V2_LogAmount20_base"
                            else indicator_id,
                            float(day + offset),
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


def write_evidence(path: Path, duckdb_path: Path) -> Path:
    conn = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        row_count, security_count, date_min, date_max = conn.execute(
            """
            SELECT
              count(*),
              count(DISTINCT security_id),
              min(trading_date),
              max(trading_date)
            FROM r0_t04_raw_metric_results
            """
        ).fetchone()
    finally:
        conn.close()
    import hashlib

    digest = hashlib.sha256(duckdb_path.read_bytes()).hexdigest()
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                "`task_id`: R0-T10-01",
                "`status`: completed",
                f"`output_duckdb_sha256`: `{digest}`",
                f"`row_count`: {row_count:,}",
                f"`security_count`: {security_count}",
                f"`date_min`: {date_min}",
                f"`date_max`: {date_max}",
                "`R0-T05_allowed_to_start`: true",
            ]
        ),
        encoding="utf-8",
    )
    return path


class R0T10ScoreMaterializerTest(unittest.TestCase):
    def test_max_workers_16_materializes_small_sample_without_row_payloads(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r0_t04 = write_r0_t04_duckdb(root, ("000001.SZ", "000002.SZ"))
            evidence = write_evidence(root / "docs/evidence/r0/r0_t04.md", r0_t04)
            output_dir = root / "data/generated/r0/r0_t10/R0-T10-02-TEST/r0_t05"

            summary = materialize_r0_t05_scores(
                r0_t04_evidence=evidence,
                r0_t04_duckdb=r0_t04,
                output_dir=output_dir,
                run_id="R0-T10-02-TEST",
                code_commit="abcdef",
                max_workers=16,
                chunk_size_securities=1,
            )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["max_workers"], 16)
            self.assertTrue((output_dir / INDICATOR_DUCKDB_NAME).is_file())
            self.assertTrue((output_dir / DIMENSION_DUCKDB_NAME).is_file())
            self.assertTrue((output_dir / COMMON_DUCKDB_NAME).is_file())
            self.assertTrue((output_dir / MANIFEST_NAME).is_file())
            self.assertFalse(_has_key(summary, "indicator_score_results"))

            manifest = json.loads(
                (output_dir / MANIFEST_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(set(manifest["W_coverage"]), {120, 250, 500})
            self.assertIn("V2_AmountLevel20Pct", manifest["indicator_coverage"])
            self.assertEqual(set(manifest["dimension_coverage"]), {"P", "C", "T", "V"})
            self.assertFalse(_has_key(manifest, "rows"))

    def test_max_workers_17_is_rejected(self) -> None:
        with self.assertRaisesRegex(R0T10ScoreMaterializationError, "between 1 and 16"):
            materialize_r0_t05_scores(
                r0_t04_evidence="missing.md",
                r0_t04_duckdb="missing.duckdb",
                output_dir="out",
                run_id="run",
                code_commit="abcdef",
                max_workers=17,
            )

    def test_uses_spawn_process_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r0_t04 = write_r0_t04_duckdb(root)
            evidence = write_evidence(root / "docs/evidence/r0/r0_t04.md", r0_t04)
            with patch(
                "src.r0.r0_t10_score_materializer.concurrent.futures.ProcessPoolExecutor"
            ) as pool:
                pool.return_value.__enter__.side_effect = RuntimeError("stop")
                with self.assertRaisesRegex(RuntimeError, "stop"):
                    materialize_r0_t05_scores(
                        r0_t04_evidence=evidence,
                        r0_t04_duckdb=r0_t04,
                        output_dir=root / "out",
                        run_id="run",
                        code_commit="abcdef",
                    )
            self.assertEqual(
                pool.call_args.kwargs["mp_context"].get_start_method(), "spawn"
            )

    def test_input_missing_or_hash_mismatch_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r0_t04 = write_r0_t04_duckdb(root)
            evidence = write_evidence(root / "docs/evidence/r0/r0_t04.md", r0_t04)
            missing = materialize_r0_t05_scores(
                r0_t04_evidence=evidence,
                r0_t04_duckdb=root / "missing.duckdb",
                output_dir=root / "out1",
                run_id="run",
                code_commit="abcdef",
            )
            self.assertEqual(missing["status"], "blocked")
            self.assertIn("r0_t04_duckdb_missing", missing["reason_codes"])

            evidence.write_text(
                evidence.read_text(encoding="utf-8").replace(
                    "output_duckdb_sha256`: `", "output_duckdb_sha256`: `bad"
                ),
                encoding="utf-8",
            )
            mismatch = materialize_r0_t05_scores(
                r0_t04_evidence=evidence,
                r0_t04_duckdb=r0_t04,
                output_dir=root / "out2",
                run_id="run",
                code_commit="abcdef",
            )
            self.assertEqual(mismatch["status"], "blocked")
            self.assertIn("r0_t04_duckdb_hash_mismatch", mismatch["reason_codes"])

    def test_resume_skips_done_and_partial_recomputes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r0_t04 = write_r0_t04_duckdb(root)
            evidence = write_evidence(root / "docs/evidence/r0/r0_t04.md", r0_t04)
            output_dir = root / "out"
            kwargs = {
                "r0_t04_evidence": evidence,
                "r0_t04_duckdb": r0_t04,
                "output_dir": output_dir,
                "run_id": "run",
                "code_commit": "abcdef",
                "max_workers": 1,
            }
            first = materialize_r0_t05_scores(**kwargs)
            resumed = materialize_r0_t05_scores(**kwargs, resume=True)
            self.assertEqual(resumed["skipped_chunk_count"], 1)

            indicator_path = Path(first["chunks"][0]["indicator_score"]["path"])
            indicator_path.with_name(indicator_path.name + ".partial").write_text(
                "x", encoding="utf-8"
            )
            recomputed = materialize_r0_t05_scores(**kwargs, resume=True)
            self.assertEqual(recomputed["completed_chunk_count"], 1)
            self.assertEqual(recomputed["skipped_chunk_count"], 0)

    def test_failed_chunk_blocks_final_duckdb_manifest_and_downstream_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r0_t04 = write_r0_t04_duckdb(root, ("000001.SZ", "000002.SZ"))
            evidence = write_evidence(root / "docs/evidence/r0/r0_t04.md", r0_t04)
            output_dir = root / "out"
            output_dir.mkdir()
            (output_dir / INDICATOR_DUCKDB_NAME).write_text("stale", encoding="utf-8")
            (output_dir / MANIFEST_NAME).write_text("stale", encoding="utf-8")
            chunks = [
                {
                    "schema_version": "r0_t10_02_chunk_done.v1",
                    "chunk_id": "ok",
                    "chunk_hash": "ok",
                    "security_count": 1,
                    "security_id_min": "000001.SZ",
                    "security_id_max": "000001.SZ",
                    "indicator_score": {
                        "row_count": 1,
                        "path": "a",
                        "content_sha256": "b",
                        "file_sha256": "c",
                    },
                    "dimension_score": {
                        "row_count": 1,
                        "path": "d",
                        "content_sha256": "e",
                        "file_sha256": "f",
                    },
                    "common_eligible": {
                        "row_count": 1,
                        "path": "g",
                        "content_sha256": "h",
                        "file_sha256": "i",
                    },
                    "status": "completed",
                },
                {
                    "schema_version": "r0_t10_02_chunk_failed.v1",
                    "chunk_id": "bad",
                    "chunk_hash": "bad",
                    "security_count": 1,
                    "security_id_min": "000002.SZ",
                    "security_id_max": "000002.SZ",
                    "status": "failed",
                },
            ]
            with patch(
                "src.r0.r0_t10_score_materializer._run_chunks", return_value=chunks
            ):
                summary = materialize_r0_t05_scores(
                    r0_t04_evidence=evidence,
                    r0_t04_duckdb=r0_t04,
                    output_dir=output_dir,
                    run_id="run",
                    code_commit="abcdef",
                    max_workers=2,
                )
            self.assertEqual(summary["status"], "failed")
            self.assertFalse(summary["downstream_gate_allowed"])
            self.assertFalse((output_dir / INDICATOR_DUCKDB_NAME).exists())
            self.assertFalse((output_dir / MANIFEST_NAME).exists())
            self.assertTrue((output_dir / SUMMARY_NAME).is_file())


def _has_key(payload: object, forbidden: str) -> bool:
    if isinstance(payload, dict):
        return any(
            key == forbidden or _has_key(value, forbidden)
            for key, value in payload.items()
        )
    if isinstance(payload, list):
        return any(_has_key(value, forbidden) for value in payload)
    return False


if __name__ == "__main__":
    unittest.main()
