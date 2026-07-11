from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.r0.candidate_artifact_engine import build_candidate_configs
from src.r0.r0_t10_full_grid_materializer import (
    R0T10FullGridMaterializationError,
    _run_one_config,
    materialize_full_grid,
)
from src.r0.upstream_artifact_io import sha256_file

FULL_SHA = "4f50d1d8d343b4b35fbb21c97d3a7a03b8c80292"
BASELINE_ID = "R0_W250_Q20_K3_WEAK_D010"
NON_BASELINE_ID = "R0_W120_Q10_K2_WEAK_D010"
FORBIDDEN_TOKENS = ("future", "return", "backtest", "portfolio", "signal")


class R0T10FullGridMaterializerSmokeTest(unittest.TestCase):
    def test_baseline_and_non_baseline_single_config_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest = _smoke_manifest(root)
            configs = {
                config.candidate_config_id: config.as_dict()
                for config in build_candidate_configs()
            }

            results = []
            for config_id in (BASELINE_ID, NON_BASELINE_ID):
                result = _run_one_config(
                    {
                        "config": configs[config_id],
                        "authorized_input_manifest_path": str(manifest_path),
                        "authorized_input_manifest_hash": _sha256(manifest_path),
                        "authorized_input_manifest": manifest,
                        "output_dir": str(root / "smoke"),
                        "run_id": "R0-T10-smoke",
                        "code_commit": FULL_SHA,
                        "duckdb_threads": 1,
                        "duckdb_memory_limit_per_worker": "1GB",
                        "resume": False,
                    }
                )
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["candidate_config_id"], config_id)
                self.assertEqual(
                    result["config_hash"], configs[config_id]["config_hash"]
                )
                results.append(result)

            self.assertNotEqual(results[0]["config_hash"], results[1]["config_hash"])
            self._assert_minimum_output_schema(root / "smoke", results)

    def test_short_commit_fails_closed_before_full_grid_execution(self) -> None:
        with self.assertRaises(R0T10FullGridMaterializationError) as ctx:
            materialize_full_grid(
                authorized_input_manifest="missing.json",
                output_dir="unused",
                run_id="smoke",
                code_commit="short",
                max_workers=1,
            )
        self.assertIn("short_code_commit_forbidden", str(ctx.exception))

    def _assert_minimum_output_schema(
        self, output_dir: Path, results: list[dict[str, object]]
    ) -> None:
        required = {
            "candidate_config_id",
            "config_hash",
            "daily_row_count",
            "interval_row_count",
            "status",
        }
        for result in results:
            self.assertTrue(required.issubset(result))
            config_dir = output_dir / "configs" / str(result["candidate_config_id"])
            daily = config_dir / "candidate_daily_state.duckdb"
            parquet = config_dir / "candidate_daily_state.parquet"
            self.assertTrue(daily.is_file())
            self.assertTrue(parquet.is_file())
            with duckdb.connect(str(daily), read_only=True) as con:
                columns = {
                    row[1].lower()
                    for row in con.execute(
                        "PRAGMA table_info('candidate_daily_state')"
                    ).fetchall()
                }
            self.assertTrue({"candidate_config_id", "config_hash"}.issubset(columns))
            self.assertFalse(
                any(token in column for token in FORBIDDEN_TOKENS for column in columns)
            )


def _smoke_manifest(root: Path) -> tuple[Path, dict[str, object]]:
    daily = root / "daily.duckdb"
    interval = root / "interval.duckdb"
    with duckdb.connect(str(daily)) as con:
        con.execute(
            """
            CREATE TABLE r0_t07_daily_confirmation_results(
              security_id TEXT, trading_date TEXT, percentile_window_W INTEGER,
              q DOUBLE, weak_delta DOUBLE, state_name TEXT, confirmation_k INTEGER,
              raw_state BOOLEAN, raw_streak INTEGER, raw_streak_start_date TEXT,
              confirmed_state BOOLEAN, confirmation_start_date TEXT,
              confirmation_date TEXT, validity_status TEXT, reason_codes TEXT,
              confirmation_engine_version TEXT
            )
            """
        )
        for w, q, k in ((250, 0.20, 3), (120, 0.10, 2)):
            con.execute(
                """
                INSERT INTO r0_t07_daily_confirmation_results
                VALUES ('000001.SZ','20260101',?,?,0.10,'S_P',?,true,3,
                '20260101',true,'20260101','20260101','valid','[]','smoke')
                """,
                [w, q, k],
            )
    with duckdb.connect(str(interval)) as con:
        con.execute(
            """
            CREATE TABLE r0_t07_confirmed_interval_results(
              interval_id TEXT, security_id TEXT, percentile_window_W INTEGER,
              q DOUBLE, weak_delta DOUBLE, state_name TEXT, confirmation_k INTEGER,
              raw_start_date TEXT, confirmation_date TEXT, confirmed_start_date TEXT,
              interval_end_date TEXT, last_observed_date TEXT,
              raw_duration_observations INTEGER,
              confirmed_duration_observations INTEGER, is_open_interval BOOLEAN,
              termination_reason TEXT, validity_status TEXT, reason_codes TEXT,
              confirmation_engine_version TEXT
            )
            """
        )
        for index, (w, q, k) in enumerate(((250, 0.20, 3), (120, 0.10, 2)), 1):
            con.execute(
                """
                INSERT INTO r0_t07_confirmed_interval_results
                VALUES (?, '000001.SZ',?,?,0.10,'S_P',?,'20260101','20260101',
                '20260101',NULL,'20260101',3,1,true,NULL,'valid','[]','smoke')
                """,
                [f"i{index}", w, q, k],
            )
    manifest = {
        "run_id": "R0-T10-smoke-input",
        "input_artifacts": {
            "r0_t07_daily_confirmation": {
                "path": str(daily),
                "sha256": sha256_file(daily),
                "table": "r0_t07_daily_confirmation_results",
            },
            "r0_t07_confirmed_interval": {
                "path": str(interval),
                "sha256": sha256_file(interval),
                "table": "r0_t07_confirmed_interval_results",
            },
        },
    }
    path = root / "smoke_manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return path, manifest


def _sha256(path: Path) -> str:
    return sha256_file(path)


if __name__ == "__main__":
    unittest.main()
