import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/generated/r1/r1_t10/R1-T10-20260711T2000Z"


class Matrix(unittest.TestCase):
    def setUp(self):
        with (OUT / "r1_t10_r2_decision_matrix.csv").open(
            encoding="utf-8-sig", newline=""
        ) as h:
            self.rows = list(csv.DictReader(h))

    def test_cardinality_and_distribution(self):
        self.assertEqual(len(self.rows), 12)
        self.assertEqual(
            sum(r["overall_handoff_status"] == "freeze_candidate" for r in self.rows), 4
        )
        self.assertEqual(
            sum(r["overall_handoff_status"] == "review_candidate" for r in self.rows), 6
        )
        self.assertEqual(
            sum(r["overall_handoff_status"] == "do_not_freeze" for r in self.rows), 2
        )

    def test_roles(self):
        self.assertEqual(
            sum(r["primary_role"] == "q_revalidation" for r in self.rows), 4
        )
        self.assertEqual(sum(r["primary_role"] == "sidecar" for r in self.rows), 4)
