from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import duckdb

from src.sidecar.exp_a03_candidate_intralayer_redundancy_selection import (
    _disposition,
    _rank_query,
    build_analysis,
    write_outputs,
)
from src.sidecar.exp_a03_candidate_intralayer_redundancy_selection_validator import (
    CONFIG_PATH,
    load_json,
)
from tests.sidecar.test_exp_a03_lineage import (
    build_synthetic_input_package,
    create_synthetic_raw,
)


class ExpA03ProducerTest(unittest.TestCase):
    def test_tie_aware_midrank_spearman_is_not_row_number_spearman(self) -> None:
        connection = duckdb.connect(":memory:")
        try:
            connection.execute(
                "CREATE TEMP TABLE a03_common (a1 DOUBLE,a2 DOUBLE,a2b DOUBLE)"
            )
            connection.executemany(
                "INSERT INTO a03_common VALUES (?,?,?)",
                [(1.0, 1.0, 0.0), (1.0, 2.0, 0.0), (2.0, 2.0, 1.0)],
            )
            rho = connection.execute(_rank_query("a1", "a2")).fetchone()[2]
            self.assertAlmostEqual(rho, 0.5, places=12)
        finally:
            connection.close()

    def test_compact_outputs_have_fixed_shapes_tail_ties_and_variance_reconciliation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_synthetic_input_package(root / "inputs")
            connection = duckdb.connect(str(inputs["raw"]), read_only=True)
            try:
                analysis = build_analysis(connection, load_json(CONFIG_PATH))
            finally:
                connection.close()
            self.assertEqual(len(analysis["pairwise_overall"]), 3)
            self.assertEqual(len(analysis["pairwise_year"]), 33)
            self.assertEqual(len(analysis["pairwise_security"]), 3)
            self.assertEqual(len(analysis["tail_overlap"]), 9)
            self.assertEqual(len(analysis["conditional_profile"]), 21)
            self.assertEqual(len(analysis["variance_decomposition"]), 1)
            self.assertEqual(len(analysis["stability_summary"]), 3)
            tail = next(
                row
                for row in analysis["tail_overlap"]
                if row["pair_id"] == "A2_A2b" and row["tail_fraction"] == 0.1
            )
            self.assertGreaterEqual(
                tail["right_selected_count"],
                tail["right_realized_rate"] * tail["union_count"],
            )
            variance = analysis["variance_decomposition"][0]
            self.assertLessEqual(
                abs(variance["reconciliation_residual"]),
                1e-9 * max(1.0, variance["total_ss"]),
            )
            self.assertEqual(
                analysis["candidate_disposition"]["decision_status"],
                "provisional_A03_recommendation",
            )
            self.assertFalse(analysis["candidate_disposition"]["A_layer_registered"])
            output = root / "outputs"
            write_outputs(output, analysis)
            self.assertEqual(len(list(output.glob("*.csv"))), 7)
            self.assertFalse(any(output.glob("*.duckdb")))

    def test_security_rows_below_minimum_remain_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary) / "small.duckdb"
            create_synthetic_raw(raw, years=(2016,))
            connection = duckdb.connect(str(raw), read_only=True)
            try:
                analysis = build_analysis(connection, load_json(CONFIG_PATH))
            finally:
                connection.close()
            for row in analysis["pairwise_security"]:
                self.assertFalse(row["eligible"])
                self.assertIsNone(row["spearman_midrank"])
                self.assertEqual(row["reason"], "insufficient_common_rows")

    def test_pre_registered_disposition_branches_and_a1_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            inputs = build_synthetic_input_package(Path(temporary) / "inputs")
            config = load_json(CONFIG_PATH)
            connection = duckdb.connect(str(inputs["raw"]), read_only=True)
            try:
                analysis = build_analysis(connection, config)
                base = _disposition(
                    connection,
                    config,
                    analysis["pairwise_overall"],
                    analysis["pairwise_year"],
                    analysis["pairwise_security"],
                    analysis["tail_overlap"],
                    analysis["conditional_profile"],
                    analysis["variance_decomposition"][0],
                )
                self.assertEqual(
                    base["recommended_candidate_set_for_A04"], ["A1", "A2"]
                )
                self.assertTrue(base["A1_collision_flags"]["A1_A2"])

                nonredundant = copy.deepcopy(analysis)
                next(
                    row
                    for row in nonredundant["pairwise_overall"]
                    if row["pair_id"] == "A2_A2b"
                )["spearman_midrank"] = 0.5
                for row in nonredundant["pairwise_year"]:
                    if row["pair_id"] == "A2_A2b":
                        row["spearman_midrank"] = 0.5
                for row in nonredundant["pairwise_security"]:
                    if row["pair_id"] == "A2_A2b":
                        row["spearman_midrank"] = 0.5
                for row in nonredundant["tail_overlap"]:
                    if row["pair_id"] == "A2_A2b" and row["tail_fraction"] in (
                        0.05,
                        0.1,
                    ):
                        row["jaccard"] = 0.5
                nonredundant["variance_decomposition"][0]["eta_squared"] = 0.5
                decision = _disposition(
                    connection,
                    config,
                    nonredundant["pairwise_overall"],
                    nonredundant["pairwise_year"],
                    nonredundant["pairwise_security"],
                    nonredundant["tail_overlap"],
                    nonredundant["conditional_profile"],
                    nonredundant["variance_decomposition"][0],
                )
                self.assertEqual(
                    decision["recommended_candidate_set_for_A04"], ["A1", "A2", "A2b"]
                )

                inadequate_config = copy.deepcopy(config)
                inadequate_config["representation_adequacy"][
                    "a2_unique_level_count"
                ] = 22
                decision = _disposition(
                    connection,
                    inadequate_config,
                    analysis["pairwise_overall"],
                    analysis["pairwise_year"],
                    analysis["pairwise_security"],
                    analysis["tail_overlap"],
                    analysis["conditional_profile"],
                    analysis["variance_decomposition"][0],
                )
                self.assertEqual(
                    decision["recommended_candidate_set_for_A04"], ["A1", "A2b"]
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
