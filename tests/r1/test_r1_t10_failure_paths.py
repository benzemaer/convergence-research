import csv
import tempfile
import unittest
from pathlib import Path

from src.r1.r1_t10_r1_gate_r2_decision_matrix_validator import validate

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/generated/r1/r1_t10/R1-T10-20260711T2000Z"


class FailClosed(unittest.TestCase):
    def _mutate(self, fn):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for name in ["r1_t10_r2_decision_matrix.csv", "r1_t10_anomaly_scan.json"]:
                (d / name).write_bytes((OUT / name).read_bytes())
            p = d / "r1_t10_r2_decision_matrix.csv"
            with p.open(encoding="utf-8-sig") as source:
                rows = list(csv.DictReader(source))
            fn(rows)
            h = p.open("w", encoding="utf-8", newline="")
            w = csv.DictWriter(h, fieldnames=rows[0])
            w.writeheader()
            w.writerows(rows)
            h.close()
            self.assertEqual(validate(d)["status"], "failed")

    def test_missing_row(self):
        self._mutate(lambda r: r.pop())

    def test_cross_window_parent(self):
        def f(rows):
            row = next(x for x in rows if x["state_line"] == "S_PCVT")
            row["same_parameter_parent_id"] = "W999_bad"

        self._mutate(f)

    def test_v25_upgrade(self):
        def f(rows):
            row = next(
                x
                for x in rows
                if x["request_role"] == "immediate_neighbor" and x["qV"] == "0.25"
            )
            row["overall_handoff_status"] = "review_candidate"

        self._mutate(f)
