from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import duckdb
from jsonschema import Draft202012Validator

from src.r1.r1_t06_contemporaneous_retention_lift import (
    CONFIG_PATH,
    SCHEMA_PATH,
    _create_step_registry,
    _validate_config,
    _write_layer_step_profile,
    _write_nested_reconciliation,
)


class R1T06ContemporaneousRetentionLiftTest(unittest.TestCase):
    def test_config_schema_exact_steps_grid_and_k(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(config)
        self.assertEqual(config["task_id"], "R1-T06")
        self.assertEqual(config["protocol_version"], "R1.v0.3.R1-T06.v1")
        self.assertEqual(config["W"], [120, 250, 500])
        self.assertEqual(config["q"], [0.1, 0.2, 0.3])
        self.assertEqual(config["K"], "not_applicable")
        self.assertEqual(
            [row["step_id"] for row in config["steps"]],
            ["C_GIVEN_P", "T_GIVEN_PC", "V_GIVEN_PCT"],
        )

    def test_extra_step_or_k_change_is_rejected(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        config["steps"] = config["steps"] + [dict(config["steps"][0])]
        config["K"] = [2, 3, 5]
        errors = _validate_config(config, schema)
        self.assertTrue(any("config_schema" in error for error in errors))
        self.assertIn("step_registry_not_exact", errors)
        self.assertIn("k_not_applicable_violation", errors)

    def test_step_specific_denominator_does_not_require_all_four_dimensions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "profile.csv"
            con = duckdb.connect()
            _create_step_registry(con)
            con.execute(
                """
                CREATE TEMP TABLE dimension_wide (
                  security_id VARCHAR, trading_date VARCHAR, W INTEGER, q DOUBLE,
                  P_valid BOOLEAN, C_valid BOOLEAN, T_valid BOOLEAN, V_valid BOOLEAN,
                  P_active BOOLEAN, C_active BOOLEAN, T_active BOOLEAN, V_active BOOLEAN
                )
                """
            )
            rows = [
                (
                    "S1",
                    "20200101",
                    250,
                    0.2,
                    True,
                    True,
                    False,
                    False,
                    True,
                    True,
                    False,
                    False,
                ),
                (
                    "S2",
                    "20200101",
                    250,
                    0.2,
                    True,
                    True,
                    True,
                    False,
                    True,
                    False,
                    True,
                    False,
                ),
                (
                    "S3",
                    "20200101",
                    250,
                    0.2,
                    True,
                    False,
                    True,
                    True,
                    True,
                    False,
                    True,
                    True,
                ),
                (
                    "S4",
                    "20200101",
                    250,
                    0.2,
                    True,
                    True,
                    True,
                    True,
                    False,
                    True,
                    True,
                    True,
                ),
            ]
            con.executemany(
                "INSERT INTO dimension_wide VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            _write_layer_step_profile(con, output, "R1-T06-SYNTH", "a" * 40)
            con.close()
            result = {
                row["step_id"]: row
                for row in _read_rows(output)
                if row["W"] == "250" and row["q"] == "0.2"
            }
            self.assertEqual(result["C_GIVEN_P"]["N"], "3")
            self.assertEqual(result["C_GIVEN_P"]["n11"], "1")
            self.assertEqual(result["C_GIVEN_P"]["n10"], "1")
            self.assertEqual(result["C_GIVEN_P"]["n01"], "1")
            self.assertEqual(result["T_GIVEN_PC"]["N"], "2")
            self.assertEqual(result["V_GIVEN_PCT"]["N"], "1")

    def test_nested_reconciliation_preserves_null_instead_of_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested_db = root / "nested.duckdb"
            nested_con = duckdb.connect(str(nested_db))
            nested_con.execute(
                """
                CREATE TABLE r0_t06_nested_daily_state_results (
                  security_id VARCHAR,
                  trading_date VARCHAR,
                  percentile_window_W INTEGER,
                  q DOUBLE,
                  S_P_raw BOOLEAN,
                  S_PC_raw BOOLEAN,
                  S_PCT_raw BOOLEAN,
                  S_PCVT_raw BOOLEAN
                )
                """
            )
            nested_con.executemany(
                "INSERT INTO r0_t06_nested_daily_state_results VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("S1", "20200101", 120, 0.1, True, None, None, None),
                    ("S2", "20200101", 120, 0.1, None, None, None, None),
                ],
            )
            nested_con.close()
            con = duckdb.connect()
            con.execute(f"ATTACH '{nested_db.as_posix()}' AS nesteddb (READ_ONLY)")
            con.execute(
                """
                CREATE TEMP TABLE dimension_wide AS
                SELECT * FROM (VALUES
                  ('S1','20200101',120,0.1,true,false,false,false,true,false,false,false),
                  ('S2','20200101',120,0.1,false,false,false,false,false,false,false,false)
                ) AS t(
                  security_id,trading_date,W,q,
                  P_valid,C_valid,T_valid,V_valid,
                  P_active,C_active,T_active,V_active
                )
                """
            )
            output = root / "nested_recon.csv"
            _write_nested_reconciliation(con, output)
            con.close()
            rows = _read_rows(output)
            s_pc = next(row for row in rows if row["state_name"] == "S_PC")
            self.assertEqual(s_pc["row_mismatch_count"], "0")
            self.assertEqual(s_pc["derived_null_count"], "2")
            self.assertEqual(s_pc["r0_null_count"], "2")


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
