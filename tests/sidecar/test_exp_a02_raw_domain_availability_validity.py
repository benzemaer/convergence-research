from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb

from src.sidecar.exp_a02_raw_domain_availability_validity import (
    A1_ID,
    A2_ID,
    A2B_ID,
    CSV_FIELDS,
    build_anomaly_scan,
    build_profiles,
    write_profiles,
)
from tests.sidecar.test_exp_a02_lineage import build_synthetic_input_package


class ExpA02ProducerTest(unittest.TestCase):
    def test_all_nine_profiles_are_set_based_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_package = build_synthetic_input_package(root / "inputs")
            first = root / "first"
            second = root / "second"
            connection = duckdb.connect(str(input_package["raw"]), read_only=True)
            try:
                profiles = build_profiles(
                    connection, expected_row_count=int(input_package["row_count"] / 3)
                )
            finally:
                connection.close()
            write_profiles(first, profiles)

            connection = duckdb.connect(str(input_package["raw"]), read_only=True)
            try:
                repeated = build_profiles(
                    connection, expected_row_count=int(input_package["row_count"] / 3)
                )
            finally:
                connection.close()
            write_profiles(second, repeated)

            self.assertEqual(set(profiles), set(CSV_FIELDS))
            for filename in (
                "exp_a02_raw_domain_profile.csv",
                "exp_a02_indicator_availability.csv",
                "exp_a02_common_valid_availability.csv",
                "exp_a02_validity_status_profile.csv",
                "exp_a02_reason_code_profile.csv",
                "exp_a02_reason_combination_profile.csv",
                "exp_a02_year_availability.csv",
                "exp_a02_security_availability.csv",
                "exp_a02_extreme_value_sample.csv",
            ):
                self.assertEqual(
                    (first / filename).read_bytes(), (second / filename).read_bytes()
                )

            raw_domain = {
                row["indicator_id"]: row for row in profiles["raw_domain_profile"]
            }
            for indicator_id in (A1_ID, A2_ID, A2B_ID):
                self.assertEqual(raw_domain[indicator_id]["total_row_count"], 24)
                self.assertEqual(raw_domain[indicator_id]["valid_count"], 20)
            self.assertAlmostEqual(float(raw_domain[A2_ID]["discrete_grid_step"]), 0.05)
            self.assertEqual(raw_domain[A2_ID]["grid_violation_count"], 0)
            self.assertEqual(raw_domain[A2_ID]["zero_count"], 1)
            self.assertEqual(raw_domain[A1_ID]["zero_count"], 1)
            self.assertEqual(raw_domain[A2B_ID]["zero_count"], 1)

            connection = duckdb.connect(str(input_package["raw"]), read_only=True)
            try:
                a2_values = {
                    float(row[0])
                    for row in connection.execute(
                        """SELECT DISTINCT raw_value FROM exp_a01_raw_metrics
                        WHERE indicator_id=? AND validity_status='valid'""",
                        [A2_ID],
                    ).fetchall()
                }
            finally:
                connection.close()
            self.assertTrue({0.0, 0.05, 0.50, 1.0}.issubset(a2_values))

            availability = {
                row["indicator_id"]: row for row in profiles["indicator_availability"]
            }
            self.assertEqual(availability[A1_ID]["expected_row_count"], 24)
            self.assertEqual(availability[A1_ID]["present_row_count"], 20)
            self.assertEqual(availability[A1_ID]["native_valid_count"], 20)

            common = {
                row["set_id"]: row for row in profiles["common_valid_availability"]
            }
            self.assertEqual(set(common), {"A1_A2", "A1_A2b", "A2_A2b", "A1_A2_A2b"})
            self.assertTrue(
                all(row["common_valid_count"] == 20 for row in common.values())
            )
            self.assertEqual(len(profiles["validity_status_profile"]), 12)
            self.assertEqual(len(profiles["reason_code_profile"]), 39)
            self.assertEqual(len(profiles["extreme_value_sample"]), 120)

    def test_status_reason_and_forbidden_field_contracts_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            input_package = build_synthetic_input_package(Path(temporary) / "inputs")
            connection = duckdb.connect(str(input_package["raw"]), read_only=True)
            try:
                profiles = build_profiles(connection, expected_row_count=24)
            finally:
                connection.close()
            status_rows = profiles["validity_status_profile"]
            by_key = {
                (row["indicator_id"], row["validity_status"]): row
                for row in status_rows
            }
            for indicator_id in (A1_ID, A2_ID, A2B_ID):
                self.assertEqual(by_key[(indicator_id, "valid")]["row_count"], 20)
                self.assertEqual(by_key[(indicator_id, "unknown")]["row_count"], 2)
                self.assertEqual(by_key[(indicator_id, "blocked")]["row_count"], 1)
                self.assertEqual(
                    by_key[(indicator_id, "diagnostic_required")]["row_count"], 1
                )
            anomaly = build_anomaly_scan(profiles)
            self.assertIn(
                anomaly["status"], {"passed", "passed_with_investigation_items"}
            )
            for fields in CSV_FIELDS.values():
                self.assertTrue(fields)
                self.assertFalse(any(field == "state" for field in fields))


if __name__ == "__main__":
    unittest.main()
