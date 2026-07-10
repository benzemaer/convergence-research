# ruff: noqa: E501

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import duckdb
from jsonschema import Draft202012Validator

from src.r1.r1_t07_p_onset_fixed_lag_relations import (
    CONFIG_PATH,
    SCHEMA_PATH,
    _add_bootstrap_intervals,
    _create_full_sequence,
    _create_registries,
    _projection_sql,
    _validate_config,
    _write_anchor_funnel,
    _write_fixed_lag_profile,
    _write_state_reconciliation,
)


class R1T07POnsetFixedLagRelationsTest(unittest.TestCase):
    def test_config_schema_exact_grid_lags_paths_and_k(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(config)
        self.assertEqual(config["task_id"], "R1-T07")
        self.assertEqual(config["W"], [120, 250, 500])
        self.assertEqual(config["q"], [0.1, 0.2, 0.3])
        self.assertEqual(config["lag_set"], [1, 3, 5, 10, 20])
        self.assertEqual(config["K"], "not_applicable")
        self.assertEqual(
            [row["transition_path"] for row in config["transition_paths"]],
            ["P_TO_C", "P_TO_T", "P_TO_V", "P_TO_PCT", "P_TO_PCVT"],
        )

    def test_extra_lag_or_confirmed_k_is_rejected(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        config["lag_set"] = [0, 1, 3, 5, 10, 20]
        config["K"] = [2, 3, 5]
        errors = _validate_config(config, schema)
        self.assertTrue(any("config_schema" in error for error in errors))
        self.assertIn("lag_set_not_preregistered", errors)
        self.assertIn("k_not_applicable_violation", errors)

    def test_onset_requires_immediate_valid_false_to_valid_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            con = _synthetic_sequence(Path(tmp))
            rows = con.execute(
                "SELECT trading_date, P_raw, prev_P_raw, P_ONSET, STAY_OUT, continuing_P FROM full_sequence ORDER BY trading_date"
            ).fetchall()
            con.close()
        by_date = {row[0]: row for row in rows}
        self.assertTrue(by_date["20200102"][3])
        self.assertFalse(by_date["20200103"][3])
        self.assertTrue(by_date["20200103"][5])
        self.assertTrue(by_date["20200105"][3])
        self.assertFalse(by_date["20200106"][3])

    def test_full_sequence_lead_does_not_skip_unknown_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            con = _synthetic_sequence(Path(tmp))
            projected = _projection_sql()
            row = con.execute(
                f"""
                SELECT anchor_date, target_date, target_raw, target_valid
                FROM ({projected})
                WHERE transition_path='P_TO_C' AND lag_k=1 AND anchor_date='20200102'
                """
            ).fetchone()
            con.close()
        self.assertEqual(row[1], "20200103")
        self.assertFalse(row[2])
        self.assertTrue(row[3])

    def test_p_exit_and_reentry_is_active_at_k_but_not_surviving_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            con = _synthetic_sequence(Path(tmp))
            projected = _projection_sql()
            row = con.execute(
                f"""
                SELECT P_active_at_k, p_run_survived, p_path_complete
                FROM ({projected})
                WHERE transition_path='P_TO_C' AND lag_k=3 AND anchor_date='20200102'
                """
            ).fetchone()
            con.close()
        self.assertTrue(row[0])
        self.assertFalse(row[1])
        self.assertTrue(row[2])

    def test_projection_uses_exact_lag_not_first_passage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = _synthetic_sequence(root)
            projected = _projection_sql()
            k1, k3 = con.execute(
                f"""
                SELECT
                  max(CASE WHEN lag_k=1 THEN target_raw ELSE NULL END),
                  max(CASE WHEN lag_k=3 THEN target_raw ELSE NULL END)
                FROM ({projected})
                WHERE transition_path='P_TO_C' AND anchor_date='20200102'
                """
            ).fetchone()
            con.close()
        self.assertFalse(k1)
        self.assertTrue(k3)

    def test_anchor_funnel_is_exact_partition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = _synthetic_sequence(root)
            out = root / "funnel.csv"
            _write_anchor_funnel(con, out)
            con.close()
            for row in _read_rows(out):
                category_sum = sum(
                    int(row[key])
                    for key in (
                        "previous_absent_count",
                        "previous_invalid_count",
                        "current_invalid_count",
                        "onset_count",
                        "stay_out_count",
                        "continuing_P_count",
                        "exit_count",
                        "other_count",
                    )
                )
                self.assertEqual(category_sum, int(row["total_rows"]))

    def test_state_reconciliation_is_row_level_not_constructive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = _synthetic_sequence(root)
            con.execute(
                """
                UPDATE dimension_wide
                SET C_raw_from_dimension=true, T_raw_from_dimension=true
                WHERE security_id='S1' AND trading_date='20200102'
                """
            )
            out = root / "state_reconciliation.csv"
            _write_state_reconciliation(con, out)
            con.close()
            rows = _read_rows(out)
        self.assertTrue(
            any(
                row["state_name"] == "S_PCT" and int(row["row_mismatch_count"]) > 0
                for row in rows
            )
        )

    def test_bootstrap_is_reproducible_for_fixed_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            con = _synthetic_sequence(root)
            first = root / "first.csv"
            second = root / "second.csv"
            _write_fixed_lag_profile(con, first, "R1-T07-SYNTH", "a" * 40)
            _write_fixed_lag_profile(con, second, "R1-T07-SYNTH", "a" * 40)
            config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            first_diagnostic = _add_bootstrap_intervals(con, first, config)
            second_diagnostic = _add_bootstrap_intervals(con, second, config)
            con.close()
            self.assertEqual(first_diagnostic, second_diagnostic)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_diagnostic["B_boot"], 2000)
            self.assertEqual(first_diagnostic["interval_rows_written"], 25)


def _synthetic_sequence(root: Path) -> duckdb.DuckDBPyConnection:
    nested_db = root / "nested.duckdb"
    ncon = duckdb.connect(str(nested_db))
    ncon.execute(
        """
        CREATE TABLE r0_t06_nested_daily_state_results (
          security_id VARCHAR, trading_date VARCHAR, percentile_window_W INTEGER, q DOUBLE, weak_delta DOUBLE,
          P_raw BOOLEAN, C_raw BOOLEAN, T_raw BOOLEAN, V_raw BOOLEAN,
          S_P_raw BOOLEAN, S_PC_raw BOOLEAN, S_PCT_raw BOOLEAN, S_PCVT_raw BOOLEAN,
          S_P_validity_status VARCHAR, S_P_reason_codes VARCHAR[],
          S_PC_validity_status VARCHAR, S_PC_reason_codes VARCHAR[],
          S_PCT_validity_status VARCHAR, S_PCT_reason_codes VARCHAR[],
          S_PCVT_validity_status VARCHAR, S_PCVT_reason_codes VARCHAR[],
          exclusive_state_layer VARCHAR, eligible_state BOOLEAN, validity_status VARCHAR, reason_codes VARCHAR[], state_engine_version VARCHAR
        )
        """
    )
    rows = [
        ("S1", "20200101", 250, 0.2, 0.1, False, False, False, False),
        ("S1", "20200102", 250, 0.2, 0.1, True, False, False, False),
        ("S1", "20200103", 250, 0.2, 0.1, True, False, False, False),
        ("S1", "20200104", 250, 0.2, 0.1, False, True, False, False),
        ("S1", "20200105", 250, 0.2, 0.1, True, True, False, False),
        ("S1", "20200106", 250, 0.2, 0.1, True, True, False, False),
        ("S1", "20200107", 250, 0.2, 0.1, None, True, False, False),
        ("S1", "20200108", 250, 0.2, 0.1, True, True, False, False),
    ]
    ncon.executemany(
        """
        INSERT INTO r0_t06_nested_daily_state_results
        SELECT ?,?,?,?,?,?,?,?,?, ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        """,
        [
            row
            + (
                row[5],
                row[5] and row[6],
                row[5] and row[6] and row[7],
                row[5] and row[6] and row[7] and row[8],
                "valid" if row[5] is not None else "unknown",
                [],
                "valid",
                [],
                "valid",
                [],
                "valid",
                [],
                "SYNTH",
                True,
                "valid",
                [],
                "synthetic",
            )
            for row in rows
        ],
    )
    ncon.close()
    con = duckdb.connect()
    con.execute(f"ATTACH '{nested_db.as_posix()}' AS nesteddb (READ_ONLY)")
    con.execute(
        """
        CREATE TEMP TABLE dimension_wide AS
        SELECT security_id, trading_date, percentile_window_W AS W, q,
          P_raw IS NOT NULL AS P_valid, true AS C_valid, true AS T_valid, true AS V_valid,
          P_raw AS P_raw_from_dimension,
          C_raw AS C_raw_from_dimension,
          T_raw AS T_raw_from_dimension,
          V_raw AS V_raw_from_dimension
        FROM nesteddb.r0_t06_nested_daily_state_results
        """
    )
    _create_registries(con)
    _create_full_sequence(con)
    return con


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
