from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.r2.r2_t03_event_zone_scan import R2T03Error, load_config
from src.r2.r2_t03_independent_validator import _equal
from src.r2.r2_t03_runtime_gates import (
    R2T03GateError,
    _compare,
    _threshold,
    validate_runtime_gates,
)


class R2T03FailurePathTest(unittest.TestCase):
    def test_load_config_fails_closed_on_wrong_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"task_id": "R2-T02"}), encoding="utf-8")
            with self.assertRaisesRegex(R2T03Error, "config_task_id_mismatch"):
                load_config(path)

    def test_frozen_gate_comparison_fails_closed(self) -> None:
        self.assertTrue(_compare(3, ">=", 3))
        self.assertFalse(_compare(3, "<=", 2))
        self.assertFalse(_compare(None, ">=", 0))

    def test_dynamic_thresholds_use_upstream_denominators(self) -> None:
        self.assertEqual(
            _threshold(
                "s_pct_qualified_event_count",
                "qualified_event_count",
                (6000, 0),
                900,
            ),
            300,
        )
        self.assertEqual(
            _threshold("s_pcvt_unique_securities", "unique_securities", (0, 0), 1000),
            150,
        )

    def test_independent_numeric_comparison(self) -> None:
        self.assertTrue(_equal(0.3, 0.1 + 0.2))
        self.assertFalse(_equal(1, 2))
        self.assertFalse(_equal(None, 0))

    def test_runtime_validator_rejects_missing_contract_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "broken.duckdb"
            with duckdb.connect(str(database)) as con:
                con.execute("CREATE TABLE cell_registry(candidate_cell_id VARCHAR)")
            registry = root / "gates.csv"
            registry.write_text("implementation_stage\n", encoding="utf-8")
            with self.assertRaises(duckdb.Error):
                validate_runtime_gates(database, root, registry)

    def test_runtime_error_type_is_dedicated(self) -> None:
        self.assertTrue(issubclass(R2T03GateError, RuntimeError))


if __name__ == "__main__":
    unittest.main()
