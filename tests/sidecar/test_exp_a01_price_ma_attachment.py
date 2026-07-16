from __future__ import annotations

import copy
import math
import unittest
from datetime import date, timedelta

from src.sidecar.exp_a01_price_ma_attachment import (
    A1_ID,
    A2_ID,
    A2B_ID,
    OUTPUT_FIELDS,
    InputContractError,
    compute_a01_metrics,
)


def make_rows(
    count: int,
    *,
    body_offsets: dict[int, float] | None = None,
    body_endpoints: dict[int, tuple[float, float]] | None = None,
) -> list[dict[str, object]]:
    body_offsets = body_offsets or {}
    body_endpoints = body_endpoints or {}
    rows: list[dict[str, object]] = []
    for index in range(count):
        close = 100.0
        open_price = 100.0 * math.exp(2.0 * body_offsets.get(index, 0.0))
        if index in body_endpoints:
            open_price, close = body_endpoints[index]
        rows.append(
            {
                "security_id": "SEC001",
                "trading_date": (date(2020, 1, 1) + timedelta(days=index)).isoformat(),
                "adjusted_open": open_price,
                "adjusted_close": close,
                "trading_status": "normal_trading",
                "adjustment_factor": 1.0,
                "adjustment_method": "identity_no_adjustment",
                "factor_as_of_time": "2020-01-01T00:00:00Z",
                "continuous_ohlc_integrity_status": "valid",
            }
        )
    return rows


def metric_at(
    results: list[dict[str, object]], indicator_id: str, index: int
) -> dict[str, object]:
    return results[
        index * 3
        + next(
            position
            for position, candidate in enumerate((A1_ID, A2_ID, A2B_ID))
            if candidate == indicator_id
        )
    ]


class ExpA01PriceMaAttachmentTest(unittest.TestCase):
    def test_a1_center_and_log_symmetry(self) -> None:
        centered = compute_a01_metrics(make_rows(60))
        self.assertEqual(metric_at(centered, A1_ID, 59)["raw_value"], 0.0)

        above = compute_a01_metrics(make_rows(60, body_offsets={59: 0.2}))
        below = compute_a01_metrics(make_rows(60, body_offsets={59: -0.2}))
        self.assertAlmostEqual(float(metric_at(above, A1_ID, 59)["raw_value"]), 0.2)
        self.assertAlmostEqual(
            float(metric_at(above, A1_ID, 59)["raw_value"]),
            float(metric_at(below, A1_ID, 59)["raw_value"]),
        )

    def test_all_candidates_are_invariant_to_positive_price_scaling(self) -> None:
        rows = make_rows(
            90,
            body_offsets={index: 0.02 * math.sin(index) for index in range(90)},
        )
        scaled = copy.deepcopy(rows)
        for row in scaled:
            row["adjusted_open"] = float(row["adjusted_open"]) * 17.5
            row["adjusted_close"] = float(row["adjusted_close"]) * 17.5
        original_results = compute_a01_metrics(rows)
        scaled_results = compute_a01_metrics(scaled)
        self.assertEqual(len(original_results), len(scaled_results))
        for original, scaled_row in zip(original_results, scaled_results, strict=True):
            self.assertEqual(original["validity_status"], scaled_row["validity_status"])
            self.assertEqual(original["reason_codes"], scaled_row["reason_codes"])
            if original["validity_status"] == "valid":
                self.assertAlmostEqual(
                    float(original["raw_value"]),
                    float(scaled_row["raw_value"]),
                    places=12,
                )

    def test_a2_boundary_inside_outside_and_mixing(self) -> None:
        inside = compute_a01_metrics(make_rows(79))
        self.assertEqual(metric_at(inside, A2_ID, 78)["raw_value"], 0.0)

        outside = compute_a01_metrics(
            make_rows(79, body_offsets={index: 0.1 for index in range(59, 79)})
        )
        self.assertEqual(metric_at(outside, A2_ID, 78)["raw_value"], 1.0)

        mixed = compute_a01_metrics(
            make_rows(
                79,
                body_offsets={index: 0.1 for index in range(69, 79)},
            )
        )
        self.assertEqual(metric_at(mixed, A2_ID, 78)["raw_value"], 0.5)

        lower_boundary = compute_a01_metrics(make_rows(79, body_offsets={78: 0.0}))
        upper_boundary = compute_a01_metrics(make_rows(79, body_offsets={78: 0.0}))
        self.assertEqual(metric_at(lower_boundary, A2_ID, 78)["raw_value"], 0.0)
        self.assertEqual(metric_at(upper_boundary, A2_ID, 78)["raw_value"], 0.0)

    def test_a2b_intersection_endpoints_and_mirror(self) -> None:
        intersecting_endpoints = {
            index: (100.0 * math.exp(0.2), 100.0) for index in range(59, 79)
        }
        intersecting = compute_a01_metrics(
            make_rows(79, body_endpoints=intersecting_endpoints)
        )
        self.assertEqual(metric_at(intersecting, A2B_ID, 78)["raw_value"], 0.0)

        above_endpoints = {
            index: (100.0 * math.exp(0.4), 100.0 * math.exp(0.2))
            for index in range(59, 79)
        }
        below_endpoints = {
            index: (100.0 * math.exp(-0.4), 100.0 * math.exp(-0.2))
            for index in range(59, 79)
        }
        above_rows = make_rows(79, body_endpoints=above_endpoints)
        below_rows = make_rows(79, body_endpoints=below_endpoints)
        above = compute_a01_metrics(above_rows)
        below = compute_a01_metrics(below_rows)

        def expected_gap(rows: list[dict[str, object]]) -> float:
            from src.sidecar.exp_a01_price_ma_attachment import _cloud_point

            gaps = []
            for point_index in range(59, 79):
                body, cloud_low, cloud_high, _center = _cloud_point(
                    [
                        type(
                            "Row",
                            (),
                            {
                                "is_valid": True,
                                "adjusted_open": float(item["adjusted_open"]),
                                "adjusted_close": float(item["adjusted_close"]),
                            },
                        )()
                        for item in rows
                    ],
                    point_index,
                )
                body_low = min(
                    math.log(float(rows[point_index]["adjusted_open"])),
                    math.log(float(rows[point_index]["adjusted_close"])),
                )
                body_high = max(
                    math.log(float(rows[point_index]["adjusted_open"])),
                    math.log(float(rows[point_index]["adjusted_close"])),
                )
                gaps.append(
                    cloud_low - body_high
                    if body_high < cloud_low
                    else body_low - cloud_high
                    if body_low > cloud_high
                    else 0.0
                )
            return sum(gaps) / len(gaps)

        self.assertAlmostEqual(
            float(metric_at(above, A2B_ID, 78)["raw_value"]), expected_gap(above_rows)
        )
        self.assertAlmostEqual(
            float(metric_at(below, A2B_ID, 78)["raw_value"]), expected_gap(below_rows)
        )
        self.assertAlmostEqual(
            0.2,
            max(0.0, math.log(100.0 * math.exp(0.2)) - math.log(100.0)),
        )

    def test_future_mutation_does_not_change_past_result(self) -> None:
        rows = make_rows(90, body_offsets={79: 0.15, 89: -0.2})
        before = compute_a01_metrics(rows)
        past = [row for row in before if row["trading_date"] == "2020-03-19"]
        rows[-1]["adjusted_open"] = 1000.0
        rows[-1]["adjusted_close"] = 1000.0
        after = compute_a01_metrics(rows)
        future_independent = [
            row for row in after if row["trading_date"] == "2020-03-19"
        ]
        self.assertEqual(past, future_independent)

    def test_minimum_history_and_invalid_window_values_fail_closed(self) -> None:
        for count, indicator_id in ((59, A1_ID), (78, A2_ID), (78, A2B_ID)):
            results = compute_a01_metrics(make_rows(count))
            row = results[(count - 1) * 3 + (A1_ID, A2_ID, A2B_ID).index(indicator_id)]
            self.assertNotEqual(row["validity_status"], "valid")
            self.assertIsNone(row["raw_value"])
            self.assertIn("window_insufficient", row["reason_codes"])

        nonpositive = make_rows(79)
        nonpositive[-1]["adjusted_open"] = 0.0
        for row in (
            metric_at(compute_a01_metrics(nonpositive), A1_ID, 78),
            metric_at(compute_a01_metrics(nonpositive), A2_ID, 78),
        ):
            self.assertIsNone(row["raw_value"])
            self.assertIn("nonpositive_adjusted_open", row["reason_codes"])

        suspended = make_rows(79)
        suspended[40]["trading_status"] = "suspended"
        suspended_results = compute_a01_metrics(suspended)
        self.assertIn(
            "suspension_in_required_window",
            metric_at(suspended_results, A2_ID, 78)["reason_codes"],
        )

    def test_duplicate_and_non_monotonic_inputs_fail_closed(self) -> None:
        duplicate = make_rows(60)
        duplicate.append(copy.deepcopy(duplicate[-1]))
        with self.assertRaisesRegex(InputContractError, "duplicate_security_date"):
            compute_a01_metrics(duplicate)

        non_monotonic = make_rows(60)
        non_monotonic[0], non_monotonic[1] = non_monotonic[1], non_monotonic[0]
        results = compute_a01_metrics(non_monotonic)
        self.assertEqual(
            [row["trading_date"] for row in results[::3]],
            sorted(row["trading_date"] for row in non_monotonic),
        )
        self.assertIn("non_monotonic_security_date", results[0]["reason_codes"])

    def test_input_rows_are_not_mutated_and_output_has_no_prohibited_fields(
        self,
    ) -> None:
        rows = make_rows(80)
        snapshot = copy.deepcopy(rows)
        results = compute_a01_metrics(rows)
        self.assertEqual(rows, snapshot)
        self.assertTrue(results)
        for row in results:
            self.assertEqual(set(row), set(OUTPUT_FIELDS))
            self.assertFalse(any("future" in field for field in row))
            self.assertFalse(any(field in row for field in ("state", "winner")))


if __name__ == "__main__":
    unittest.main()
