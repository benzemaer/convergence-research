# ruff: noqa: E501
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.r0.r0_t15_layer_q_vector_materialization_validator import (
    validate_r0_t15_layer_q_vector_materialization,
)
from src.r0.r0_t15_layer_q_vector_materializer import (
    CONFIG_PATH,
    _create_output_tables,
    _create_vector_tables,
    _drop_vector_tables,
    _insert_vector_outputs,
    _integrity_checks,
    _write_csv,
    build_formal_registry,
)
from src.r0.upstream_artifact_io import write_json_atomic

ROOT = Path(__file__).resolve().parents[2]


class R0T15LayerQVectorMaterializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        request_path = (
            ROOT / cls.config["upstream_binding"]["materialization_request_path"]
        )
        cls.request = json.loads(request_path.read_text(encoding="utf-8"))

    def test_registry_consumes_request_without_add_or_drop(self) -> None:
        registry = build_formal_registry(self.request, self.config)
        self.assertEqual(len(registry), 10)
        self.assertEqual(sum(row["materialize"] for row in registry), 8)
        self.assertEqual(sum(row["baseline_reuse"] for row in registry), 2)
        self.assertEqual(
            {row["candidate_q_vector_id"] for row in registry},
            {row["candidate_q_vector_id"] for row in self.request["frozen_registry"]},
        )
        self.assertEqual(len({row["formal_vector_id"] for row in registry}), 10)

    def test_small_formal_materialization_preserves_k3_and_parent_child(self) -> None:
        registry = build_formal_registry(self.request, self.config)
        vector = next(
            row
            for row in registry
            if row["candidate_q_vector_id"] == "W120_K3_P20_C20_T25_V20"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            con = duckdb.connect()
            try:
                con.execute("ATTACH ':memory:' AS scoredb")
                con.execute(
                    """
                    CREATE TABLE scoredb.r0_t05_dimension_score_results(
                      component_indicator_ids VARCHAR[],dimension VARCHAR,eligible_dimension BOOLEAN,
                      percentile_window_W INTEGER,reason_codes VARCHAR[],score_dimension DOUBLE,
                      score_dimension_min DOUBLE,score_engine_version VARCHAR,security_id VARCHAR,
                      trading_date VARCHAR,validity_status VARCHAR
                    )
                    """
                )
                dates = ["20200101", "20200102", "20200103", "20200104", "20200105"]
                rows = []
                for index, date in enumerate(dates):
                    score = 0.95 if index < 4 else 0.1
                    for dimension in ("P", "C", "T", "V"):
                        rows.append(
                            (
                                [dimension + "1", dimension + "2"],
                                dimension,
                                True,
                                120,
                                ["valid_no_blocker"],
                                score,
                                score,
                                "score.v1",
                                "A",
                                date,
                                "valid",
                            )
                        )
                con.executemany(
                    "INSERT INTO scoredb.r0_t05_dimension_score_results VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                for alias, filename in (
                    ("dimout", "d.duckdb"),
                    ("nestedout", "n.duckdb"),
                    ("dailyout", "c.duckdb"),
                    ("intervalout", "i.duckdb"),
                ):
                    con.execute(f"ATTACH '{(root / filename).as_posix()}' AS {alias}")
                _create_output_tables(con)
                _create_vector_tables(con, vector)
                values = con.execute(
                    "SELECT trading_date,confirmed_PCT,confirmed_PCVT FROM vector_daily ORDER BY trading_date"
                ).fetchall()
                self.assertEqual(
                    values[0:3],
                    [
                        ("20200101", False, False),
                        ("20200102", False, False),
                        ("20200103", True, True),
                    ],
                )
                self.assertEqual(values[-1], ("20200105", False, False))
                _insert_vector_outputs(con, vector, self.request["request_id"])
                self.assertEqual(
                    con.execute(
                        "SELECT count(*) FROM dimout.r0_t15_dimension_state_results"
                    ).fetchone()[0],
                    20,
                )
                self.assertEqual(
                    con.execute(
                        "SELECT count(*) FROM nestedout.r0_t15_nested_daily_state_results"
                    ).fetchone()[0],
                    5,
                )
                self.assertEqual(
                    con.execute(
                        "SELECT count(*) FROM dailyout.r0_t15_daily_confirmation_results"
                    ).fetchone()[0],
                    20,
                )
                self.assertEqual(
                    con.execute(
                        "SELECT count(*) FROM intervalout.r0_t15_confirmed_interval_results"
                    ).fetchone()[0],
                    4,
                )
                summaries = {
                    key: {"vector_count": 1}
                    for key in (
                        "dimension_state",
                        "nested_daily_state",
                        "daily_confirmation",
                        "confirmed_interval",
                    )
                }
                integrity = _integrity_checks(
                    con, [{**vector, "materialize": True}], summaries
                )
                self.assertEqual(integrity["schema_status"], "passed")
                self.assertEqual(integrity["primary_key_status"], "passed")
                _drop_vector_tables(con)
            finally:
                con.close()

    def test_validator_failure_path_records_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate_r0_t15_layer_q_vector_materialization(run_dir=directory)
        self.assertEqual(result["status"], "failed")
        self.assertGreater(result["error_count"], 0)

    def test_text_artifacts_use_repository_lf_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_path = root / "artifact.json"
            csv_path = root / "artifact.csv"
            write_json_atomic(json_path, {"status": "passed"})
            _write_csv(csv_path, [{"status": "passed"}, {"status": "pending"}])
            self.assertNotIn(b"\r\n", json_path.read_bytes())
            self.assertNotIn(b"\r\n", csv_path.read_bytes())
            self.assertEqual(csv_path.read_bytes().count(b"\n"), 3)


if __name__ == "__main__":
    unittest.main()
