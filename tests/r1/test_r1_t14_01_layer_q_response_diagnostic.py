from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.r1.r1_t14_01_layer_q_response_diagnostic import (
    CONFIG_PATH,
    _attach_inputs,
    _create_vector_daily,
    _create_vector_intervals,
    _dominates,
    _immediate_q_neighbors,
    _selection_sort_key,
    build_grid_registry,
    vector_id,
)
from src.r1.r1_t14_01_layer_q_response_diagnostic_validator import (
    validate_r1_t14_01_layer_q_response_diagnostic,
)


class R1T1401LayerQResponseDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_frozen_ofat_grid_has_17_vectors_per_window(self) -> None:
        rows = build_grid_registry(self.config)
        self.assertEqual(len(rows), 34)
        self.assertEqual(len({row["candidate_q_vector_id"] for row in rows}), 34)
        for window in (120, 250):
            selected = [row for row in rows if row["W"] == window]
            self.assertEqual(len(selected), 17)
            self.assertEqual(sum(row["role"] == "baseline" for row in selected), 1)
            for row in selected:
                changed = sum(
                    abs(float(row[key]) - 0.2) > 1e-12
                    for key in ("qP", "qC", "qT", "qV")
                )
                self.assertEqual(changed, 0 if row["role"] == "baseline" else 1)

    def test_vector_id_and_immediate_neighbors_are_deterministic(self) -> None:
        self.assertEqual(vector_id(250, 0.2, 0.15, 0.2, 0.2), "W250_K3_P20_C15_T20_V20")
        self.assertEqual(_immediate_q_neighbors(0.1), (0.15,))
        self.assertEqual(_immediate_q_neighbors(0.15), (0.1, 0.2))
        self.assertEqual(_immediate_q_neighbors(0.25), (0.2, 0.3))
        self.assertEqual(_immediate_q_neighbors(0.3), (0.25,))

    def test_pareto_and_tie_break_do_not_select_by_coverage_alone(self) -> None:
        balanced = {
            "confirmed_coverage": 0.02,
            "affected_delta": 0.12,
            "affected_lift_excess": 0.3,
            "baseline_retention": 0.8,
            "max_year_share": 0.2,
            "fragment_rate": 0.1,
        }
        coverage_only = {
            **balanced,
            "confirmed_coverage": 0.03,
            "affected_delta": 0.01,
            "affected_lift_excess": 0.01,
        }
        self.assertFalse(_dominates(coverage_only, balanced))
        near = {
            "qP": 0.2,
            "qC": 0.15,
            "qT": 0.2,
            "qV": 0.2,
            "baseline_retention": 0.8,
            "max_year_share": 0.2,
            "fragment_rate": 0.1,
            "affected_delta": 0.1,
            "candidate_q_vector_id": "near",
        }
        far = {**near, "qC": 0.1, "candidate_q_vector_id": "far"}
        self.assertLess(_selection_sort_key(near), _selection_sort_key(far))

    def test_confirmation_and_interval_semantics_match_k3(self) -> None:
        con = duckdb.connect()
        try:
            con.execute(
                """
                CREATE TEMP TABLE base_scores(
                  security_id VARCHAR,trading_date VARCHAR,W INTEGER,
                  score_P DOUBLE,min_P DOUBLE,score_C DOUBLE,min_C DOUBLE,
                  score_T DOUBLE,min_T DOUBLE,score_V DOUBLE,min_V DOUBLE,
                  valid_P BOOLEAN,valid_C BOOLEAN,valid_T BOOLEAN,valid_V BOOLEAN,
                  status_P VARCHAR,status_C VARCHAR,status_T VARCHAR,status_V VARCHAR,
                  dimension_rows INTEGER,next_date VARCHAR
                )
                """
            )
            dates = ["20200101", "20200102", "20200103", "20200104", "20200105"]
            rows = []
            for index, date in enumerate(dates):
                active = index < 4
                score = 0.95 if active else 0.1
                rows.append(
                    (
                        "A",
                        date,
                        120,
                        score,
                        score,
                        score,
                        score,
                        score,
                        score,
                        score,
                        score,
                        True,
                        True,
                        True,
                        True,
                        "valid",
                        "valid",
                        "valid",
                        "valid",
                        4,
                        dates[index + 1] if index + 1 < len(dates) else None,
                    )
                )
            con.executemany(
                """
                INSERT INTO base_scores VALUES (
                  ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                )
                """,
                rows,
            )
            registry = next(
                row
                for row in build_grid_registry(self.config)
                if row["W"] == 120 and row["role"] == "baseline"
            )
            _create_vector_daily(con, registry)
            values = con.execute(
                """
                SELECT trading_date,confirmed_PCT
                FROM vector_daily ORDER BY trading_date
                """
            ).fetchall()
            self.assertEqual(
                values,
                [
                    ("20200101", False),
                    ("20200102", False),
                    ("20200103", True),
                    ("20200104", True),
                    ("20200105", False),
                ],
            )
            _create_vector_intervals(con)
            interval = con.execute(
                """
                SELECT raw_start_date,confirmation_date,last_true_date,
                  raw_duration,confirmed_duration,is_open_interval
                FROM vector_intervals WHERE state_name='S_PCT'
                """
            ).fetchone()
            self.assertEqual(
                interval, ("20200101", "20200103", "20200104", 4, 2, False)
            )
        finally:
            con.close()

    def test_validator_failure_path_is_nonzero_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate_r1_t14_01_layer_q_response_diagnostic(
                run_dir=Path(directory)
            )
        self.assertEqual(result["status"], "failed")
        self.assertIn("exactly_one_decision_artifact_required", result["errors"])

    def test_attach_inputs_accepts_read_only_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for name in (
                "dimension_score",
                "baseline_daily_confirmation",
                "baseline_confirmed_interval",
            ):
                path = root / f"{name}.duckdb"
                connection = duckdb.connect(str(path))
                connection.execute("CREATE TABLE marker(value INTEGER)")
                connection.close()
                paths[name] = {"absolute_path": str(path)}
            con = duckdb.connect()
            try:
                _attach_inputs(con, paths)
                names = {row[0] for row in con.execute("SHOW DATABASES").fetchall()}
                self.assertTrue({"scoredb", "dailydb", "intervaldb"}.issubset(names))
            finally:
                con.close()


if __name__ == "__main__":
    unittest.main()
