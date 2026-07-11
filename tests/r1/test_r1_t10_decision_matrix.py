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

    def test_q_vector_target_marginal_is_bound(self):
        row = next(
            r
            for r in self.rows
            if r["handoff_row_id"] == "q_W120_K3_P20_C20_T25_V20_S_PCT"
        )
        self.assertAlmostEqual(float(row["target_marginal"]), 0.20323319725411654)
        self.assertAlmostEqual(
            float(row["retention"]),
            float(row["association_lift"]) * float(row["target_marginal"]),
        )
        self.assertAlmostEqual(
            float(row["absolute_increment"]),
            float(row["retention"]) - float(row["target_marginal"]),
        )

    def test_pct_q_vector_uses_f4_nested_family(self):
        row = next(
            r
            for r in self.rows
            if r["handoff_row_id"] == "q_W120_K3_P20_C20_T25_V20_S_PCT"
        )
        self.assertAlmostEqual(float(row["nested_joint_lift"]), 1.7589168403073427)
        self.assertAlmostEqual(float(row["nested_joint_excess"]), 0.1559477341779861)
