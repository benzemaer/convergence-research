from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import duckdb

from scripts.generate_d3_t11_volume_amount_share_turnover_candidate import (
    OUTPUT_TABLE,
    ensure_d3_t07_source_available,
    generate_d3_t11_volume_amount_share_turnover_candidate,
    load_env_file,
    read_security_universe_as_tnskhdata_codes,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeDailyBasicClient:
    def daily_basic(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        return [
            {
                "ts_code": ts_code,
                "trade_date": start_date,
                "close": 10.0,
                "turnover_rate": 1.0,
                "turnover_rate_f": 2.0,
                "volume_ratio": 1.1,
                "total_share": 200.0,
                "float_share": 100.0,
                "free_share": 50.0,
                "total_mv": 2000.0,
                "circ_mv": 1000.0,
                "limit_status": "0",
            }
        ]


class ZeroVolumeClient:
    def daily_basic(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        return [
            {
                "ts_code": ts_code,
                "trade_date": start_date,
                "close": 10.0,
                "turnover_rate": 0.0,
                "turnover_rate_f": 0.0,
                "volume_ratio": 0.0,
                "total_share": 200.0,
                "float_share": 100.0,
                "free_share": 50.0,
                "total_mv": 2000.0,
                "circ_mv": 1000.0,
                "limit_status": "",
            }
        ]


class FailingClient:
    def daily_basic(
        self, *, ts_code: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        raise AssertionError("provider should not be called")


class D3T11VolumeAmountShareTurnoverGenerationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        d3_dir = self.base / "data/generated/d3/d3_t07_candidate_daily_observation"
        d3_dir.mkdir(parents=True)
        self.d3_db = d3_dir / "d3_t07_candidate_daily_observation.duckdb"
        self.securities_file = self.base / "securities.txt"
        self.securities_file.write_text("000001.SZ\n", encoding="utf-8")
        self.output_dir = (
            self.base
            / "data/generated/d3/d3_t11_volume_amount_share_turnover_candidate"
        )
        self.universe_path = (
            self.base / "configs/d2/csi800_static_2026_06_membership_alignment.v1.json"
        )
        self.universe_path.parent.mkdir(parents=True)
        self.universe_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {"security_id": "CN.SZSE.000001"},
                        {"security_id": "CN.SSE.600000"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        self._write_source_duckdb(vol=100.0, amount=100.0)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_source_duckdb(self, *, vol: float, amount: float) -> None:
        conn = duckdb.connect(str(self.d3_db))
        conn.execute(
            """
            CREATE TABLE d3_candidate_daily_observation (
              ts_code TEXT,
              trade_date TEXT,
              open DOUBLE,
              high DOUBLE,
              low DOUBLE,
              close DOUBLE,
              vol DOUBLE,
              amount DOUBLE,
              trading_status TEXT,
              price_limit_status TEXT,
              is_limit_up BOOLEAN,
              is_limit_down BOOLEAN,
              is_listing_pause BOOLEAN,
              source_task_id TEXT,
              generated_by_task TEXT,
              row_provenance TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO d3_candidate_daily_observation VALUES (
              '000001.SZ', '20260601', 10, 11, 9, 10, ?, ?,
              'normal', 'none', false, false, false,
              'D2-T20', 'D3-T07', 'synthetic'
            )
            """,
            [vol, amount],
        )
        conn.close()

    def test_token_missing_runner_clean_exit_without_traceback(self) -> None:
        env = os.environ.copy()
        for key in ("TNSKHDATA_TOKEN", "TUSHARE_TOKEN", "TNS_TOKEN"):
            env.pop(key, None)
        result = subprocess.run(
            [
                sys.executable,
                "scripts/generate_d3_t11_volume_amount_share_turnover_candidate.py",
                "--env-file",
                str(self.base / "missing.env"),
                "--securities-file",
                str(self.securities_file),
                "--start-date",
                "20260601",
                "--end-date",
                "20260601",
                "--d3-t07-duckdb",
                str(self.d3_db),
                "--output-dir",
                str(self.output_dir),
            ],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("blocked_missing_tnskhdata_token", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_security_universe_resolves_tnskhdata_codes(self) -> None:
        self.assertEqual(
            read_security_universe_as_tnskhdata_codes(self.universe_path),
            ["000001.SZ", "600000.SH"],
        )

    def test_env_file_loads_token_without_report_echo(self) -> None:
        old_value = os.environ.pop("TNSKHDATA_TOKEN", None)
        env_file = self.base / ".env.local"
        env_file.write_text("TNSKHDATA_TOKEN=fake-token\n", encoding="utf-8")
        try:
            load_env_file(env_file)
            self.assertEqual(os.environ["TNSKHDATA_TOKEN"], "fake-token")
            summary = generate_d3_t11_volume_amount_share_turnover_candidate(
                securities_file=self.securities_file,
                start_date="20260601",
                end_date="20260601",
                d3_t07_duckdb=self.d3_db,
                output_dir=self.output_dir,
                dry_run=True,
            )
            self.assertNotIn("fake-token", json.dumps(summary))
            self.assertNotIn(
                "fake-token",
                (self.output_dir / "d3_t11_generation_summary.json").read_text(
                    encoding="utf-8"
                ),
            )
        finally:
            os.environ.pop("TNSKHDATA_TOKEN", None)
            if old_value is not None:
                os.environ["TNSKHDATA_TOKEN"] = old_value

    def test_default_cli_dry_run_uses_security_universe(self) -> None:
        env_file = self.base / ".env.local"
        env_file.write_text("TNSKHDATA_TOKEN=fake-token\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "scripts/generate_d3_t11_volume_amount_share_turnover_candidate.py",
                "--dry-run",
                "--env-file",
                str(env_file),
                "--security-universe",
                str(self.universe_path),
                "--d3-t07-duckdb",
                str(self.d3_db),
                "--output-dir",
                str(self.output_dir),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertFalse(summary["remote_provider_called"])
        self.assertEqual(summary["planned_security_count"], 2)
        self.assertEqual(summary["configured_security_count"], 2)
        self.assertEqual(summary["resolved_tnskhdata_security_count"], 2)
        self.assertFalse(summary["pcvt_values_generated"])
        self.assertFalse(summary["r0_state_generated"])
        self.assertFalse(summary["formal_data_version_published"])

    def test_d3_t07_existing_source_preflight_is_available(self) -> None:
        result = ensure_d3_t07_source_available(
            d3_t07_duckdb=self.d3_db,
            auto_generate_d3_t07_from_d2_t20=True,
            d2_t20_duckdb=self.base / "missing.duckdb",
            d2_t20_acceptance_report=self.base / "missing_acceptance.json",
            d2_t20_handoff_report=self.base / "missing_handoff.json",
            start_date="20260601",
            end_date="20260601",
            sample_securities=None,
        )
        self.assertEqual(result["d3_t07_source_status"], "available")
        self.assertFalse(result["d3_t07_auto_generated"])

    def test_missing_d3_t07_and_d2_t20_inputs_blocks_before_provider_call(self) -> None:
        self.d3_db.unlink()
        summary = generate_d3_t11_volume_amount_share_turnover_candidate(
            security_universe=self.universe_path,
            start_date="20260601",
            end_date="20260601",
            d3_t07_duckdb=self.d3_db,
            output_dir=self.output_dir,
            d2_t20_duckdb=self.base / "missing.duckdb",
            d2_t20_acceptance_report=self.base / "missing_acceptance.json",
            d2_t20_handoff_report=self.base / "missing_handoff.json",
            provider_client=FailingClient(),
            allow_low_security_count=True,
        )
        self.assertEqual(
            summary["d3_t11_generation_decision"],
            "blocked_missing_d2_t20_inputs",
        )
        self.assertFalse(summary["remote_provider_called"])
        self.assertFalse(summary["candidate_generated"])

    def test_missing_d3_t07_source_blocks_before_provider_call(self) -> None:
        self.d3_db.unlink()
        summary = generate_d3_t11_volume_amount_share_turnover_candidate(
            security_universe=self.universe_path,
            start_date="20260601",
            end_date="20260601",
            d3_t07_duckdb=self.d3_db,
            output_dir=self.output_dir,
            auto_generate_d3_t07_from_d2_t20=False,
            provider_client=FailingClient(),
            allow_low_security_count=True,
        )
        self.assertEqual(
            summary["d3_t11_generation_decision"],
            "blocked_missing_d3_t07_source",
        )
        self.assertFalse(summary["remote_provider_called"])
        self.assertFalse(summary["candidate_generated"])

    def test_auto_generates_d3_t07_then_continues_d3_t11_fake_provider(self) -> None:
        self.d3_db.unlink()
        d2_duckdb = (
            self.base / "data/generated/d2/d2_t20/d2_t15_tnskhdata_staging.duckdb"
        )
        d2_acceptance = self.base / "data/generated/d2/d2_t20/acceptance.json"
        d2_handoff = self.base / "data/generated/d2/d2_t20/handoff.json"
        d2_duckdb.parent.mkdir(parents=True)
        d2_duckdb.write_text("synthetic d2 placeholder", encoding="utf-8")
        d2_acceptance.write_text("{}", encoding="utf-8")
        d2_handoff.write_text("{}", encoding="utf-8")

        def fake_d3_t07_generator(**_kwargs: Any) -> dict[str, Any]:
            self._write_source_duckdb(vol=100.0, amount=100.0)
            return {
                "task_id": "D3-T07",
                "d3_t07_generation_decision": "accepted_candidate_observation",
                "d3_rows_generated": True,
                "data_version_published": False,
                "r0_state_generated": False,
                "output_duckdb": str(self.d3_db),
            }

        with patch(
            (
                "scripts.generate_d3_t11_volume_amount_share_turnover_candidate."
                "generate_d3_t07_candidate_daily_observation"
            ),
            side_effect=fake_d3_t07_generator,
        ):
            summary = generate_d3_t11_volume_amount_share_turnover_candidate(
                securities_file=self.securities_file,
                start_date="20260601",
                end_date="20260601",
                d3_t07_duckdb=self.d3_db,
                output_dir=self.output_dir,
                d2_t20_duckdb=d2_duckdb,
                d2_t20_acceptance_report=d2_acceptance,
                d2_t20_handoff_report=d2_handoff,
                provider_client=FakeDailyBasicClient(),
                code_commit="synthetic",
            )

        self.assertGreater(summary["candidate_row_count"], 0)
        self.assertEqual(summary["d3_t07_source_status"], "auto_generated_from_d2_t20")
        self.assertTrue(summary["d3_t07_auto_generated"])
        provider = json.loads(
            (self.output_dir / "d3_t11_provider_call_summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(provider["remote_provider_called"])
        self.assertFalse(summary["pcvt_values_generated"])
        self.assertFalse(summary["r0_state_generated"])
        self.assertFalse(summary["formal_data_version_published"])

    def test_output_duckdb_does_not_replace_d2_t20_source(self) -> None:
        d2_source = (
            self.base / "data/generated/d2/d2_t20/d2_t15_tnskhdata_staging.duckdb"
        )
        d2_source.parent.mkdir(parents=True)
        d2_source.write_text("synthetic d2 source", encoding="utf-8")
        before = d2_source.read_bytes()
        generate_d3_t11_volume_amount_share_turnover_candidate(
            securities_file=self.securities_file,
            start_date="20260601",
            end_date="20260601",
            d3_t07_duckdb=self.d3_db,
            output_dir=self.output_dir,
            provider_client=FakeDailyBasicClient(),
            code_commit="synthetic",
        )
        self.assertEqual(d2_source.read_bytes(), before)
        conn = duckdb.connect(
            str(
                self.output_dir / "d3_t11_volume_amount_share_turnover_candidate.duckdb"
            ),
            read_only=True,
        )
        try:
            tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
        finally:
            conn.close()
        self.assertEqual(tables, {OUTPUT_TABLE})

    def test_fake_provider_generates_standardized_candidate_rows(self) -> None:
        summary = generate_d3_t11_volume_amount_share_turnover_candidate(
            securities_file=self.securities_file,
            start_date="20260601",
            end_date="20260601",
            d3_t07_duckdb=self.d3_db,
            output_dir=self.output_dir,
            provider_client=FakeDailyBasicClient(),
            code_commit="synthetic",
        )
        self.assertEqual(summary["candidate_row_count"], 1)
        conn = duckdb.connect(
            str(
                self.output_dir / "d3_t11_volume_amount_share_turnover_candidate.duckdb"
            ),
            read_only=True,
        )
        try:
            row = conn.execute(f"SELECT * FROM {OUTPUT_TABLE}").fetchdf().iloc[0]
            columns = set(
                conn.execute(f"PRAGMA table_info('{OUTPUT_TABLE}')").fetchdf()["name"]
            )
        finally:
            conn.close()
        self.assertEqual(row["volume_shares"], 10000)
        self.assertEqual(row["amount_yuan"], 100000)
        self.assertEqual(row["daily_vwap"], 10)
        self.assertEqual(row["daily_vwap_range_status"], "valid")
        self.assertEqual(row["total_share_shares"], 2000000)
        self.assertEqual(row["float_share_shares"], 1000000)
        self.assertEqual(row["free_share_shares"], 500000)
        self.assertEqual(row["turnover_float"], 0.01)
        self.assertEqual(row["turnover_free"], 0.02)
        self.assertEqual(row["provider_turnover_crosscheck_status"], "valid")
        self.assertTrue(
            {
                "adjusted_vwap_policy",
                "common_share_basis_policy",
                "volume_comparability_policy",
                "source_snapshot_id",
                "run_id",
                "code_commit",
            }.issubset(columns)
        )

    def test_zero_volume_is_not_low_participation(self) -> None:
        self.d3_db.unlink()
        self._write_source_duckdb(vol=0.0, amount=0.0)
        generate_d3_t11_volume_amount_share_turnover_candidate(
            securities_file=self.securities_file,
            start_date="20260601",
            end_date="20260601",
            d3_t07_duckdb=self.d3_db,
            output_dir=self.output_dir,
            provider_client=ZeroVolumeClient(),
            code_commit="synthetic",
        )
        conn = duckdb.connect(
            str(
                self.output_dir / "d3_t11_volume_amount_share_turnover_candidate.duckdb"
            ),
            read_only=True,
        )
        try:
            row = conn.execute(
                f"""
                SELECT zero_volume_flag, daily_vwap, daily_vwap_range_status,
                       turnover_float, turnover_free
                FROM {OUTPUT_TABLE}
                """
            ).fetchone()
        finally:
            conn.close()
        self.assertTrue(row[0])
        self.assertIsNone(row[1])
        self.assertEqual(row[2], "not_applicable_zero_or_missing_volume")
        self.assertEqual(row[3], 0.0)
        self.assertEqual(row[4], 0.0)

    def test_reports_do_not_generate_forbidden_outputs(self) -> None:
        generate_d3_t11_volume_amount_share_turnover_candidate(
            securities_file=self.securities_file,
            start_date="20260601",
            end_date="20260601",
            d3_t07_duckdb=self.d3_db,
            output_dir=self.output_dir,
            provider_client=FakeDailyBasicClient(),
            code_commit="synthetic",
        )
        forbidden = {
            "data_version.json",
            "labels.csv",
            "returns.csv",
            "backtest.csv",
            "portfolio.csv",
            "pcvt_values.csv",
            "r0_state.csv",
        }
        self.assertTrue(
            all(not (self.output_dir / name).exists() for name in forbidden)
        )
        handoff = json.loads(
            (self.output_dir / "d3_t11_r0_handoff_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(handoff["pcvt_values_generated"])
        self.assertFalse(handoff["r0_state_generated"])
        self.assertFalse(handoff["formal_data_version_published"])

    def test_direct_cli_help_works(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/generate_d3_t11_volume_amount_share_turnover_candidate.py",
                "--help",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
