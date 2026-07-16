from __future__ import annotations

import copy
import math
import unittest
from datetime import date, timedelta

from src.sidecar.exp_a01_price_ma_attachment import (
    A1_ID,
    A2_ID,
    A2B_ID,
    INDEX_SOURCE_CONTRACT,
    OUTPUT_FIELDS,
    InputContractError,
    build_dense_price_rows,
    compute_a01_metrics,
)


def make_rows(
    count: int,
    *,
    body_offsets: dict[int, float] | None = None,
    body_endpoints: dict[int, tuple[float, float]] | None = None,
    close_values: dict[int, float] | None = None,
) -> list[dict[str, object]]:
    body_offsets = body_offsets or {}
    body_endpoints = body_endpoints or {}
    close_values = close_values or {}
    rows: list[dict[str, object]] = []
    for index in range(count):
        close = float(close_values.get(index, 100.0))
        open_price = close * math.exp(2.0 * body_offsets.get(index, 0.0))
        if index in body_endpoints:
            open_price, close = body_endpoints[index]
        trading_date = (date(2020, 1, 1) + timedelta(days=index)).isoformat()
        rows.append(
            {
                "security_id": "SEC001",
                "trading_date": trading_date,
                "observation_sequence": index,
                "expected_observation_status": "present",
                "adjusted_open": open_price,
                "adjusted_close": close,
                "trading_status": "normal_trading",
                "daily_status": "resolved",
                "effective_adj_factor": 1.0,
                "adjustment_factor_status": "resolved",
                "is_listing_pause": False,
                "source_task_id": "D2-T20",
                "generated_by_task": "D3-T07",
                "row_provenance": f"d3-t07:SEC001:{index}",
                "source_contract": INDEX_SOURCE_CONTRACT,
                "source_ref": f"calendar-v1:SEC001:{index}",
            }
        )
    return rows


def make_expected(
    count: int,
    *,
    status_overrides: dict[int, str] | None = None,
) -> list[dict[str, object]]:
    status_overrides = status_overrides or {}
    return [
        {
            "security_id": "SEC001",
            "trading_date": (date(2020, 1, 1) + timedelta(days=index)).isoformat(),
            "observation_sequence": index,
            "expected_observation_status": status_overrides.get(index, "present"),
            "source_contract": INDEX_SOURCE_CONTRACT,
            "source_ref": f"calendar-v1:SEC001:{index}",
        }
        for index in range(count)
    ]


def make_observations(
    count: int,
    *,
    body_offsets: dict[int, float] | None = None,
    body_endpoints: dict[int, tuple[float, float]] | None = None,
    close_values: dict[int, float] | None = None,
) -> list[dict[str, object]]:
    rows = make_rows(
        count,
        body_offsets=body_offsets,
        body_endpoints=body_endpoints,
        close_values=close_values,
    )
    for row in rows:
        row["ts_code"] = row.pop("security_id")
        row["trade_date"] = row.pop("trading_date")
        row.pop("expected_observation_status")
        row.pop("observation_sequence")
        row.pop("source_contract")
        row.pop("source_ref")
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


def independent_cloud_bounds(
    rows: list[dict[str, object]], index: int
) -> tuple[float, float, float]:
    """Test oracle for cloud bounds; it does not call production helpers."""

    log_mas: list[float] = []
    for window_size in (5, 10, 20, 30, 60):
        closes = [
            float(rows[position]["adjusted_close"])
            for position in range(index - window_size + 1, index + 1)
        ]
        log_mas.append(math.log(sum(closes) / window_size))
    return min(log_mas), max(log_mas), sum(log_mas) / len(log_mas)


def set_body_center(
    rows: list[dict[str, object]], index: int, target_log_center: float
) -> None:
    close = float(rows[index]["adjusted_close"])
    rows[index]["adjusted_open"] = math.exp(2.0 * target_log_center - math.log(close))


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

    def test_a2_non_degenerate_cloud_strict_boundaries_and_outside_sides(self) -> None:
        close_values = {index: 90.0 + index * 0.25 for index in range(79)}
        inside_rows = make_rows(79, close_values=close_values)
        for index in range(59, 79):
            _low, _high, center = independent_cloud_bounds(inside_rows, index)
            set_body_center(inside_rows, index, center)
        inside = compute_a01_metrics(inside_rows)
        self.assertEqual(metric_at(inside, A2_ID, 78)["raw_value"], 0.0)

        lower_rows = copy.deepcopy(inside_rows)
        lower, upper, _center = independent_cloud_bounds(lower_rows, 78)
        set_body_center(lower_rows, 78, lower)
        lower_result = compute_a01_metrics(lower_rows)
        self.assertEqual(metric_at(lower_result, A2_ID, 78)["raw_value"], 0.0)

        upper_rows = copy.deepcopy(inside_rows)
        _lower, upper, _center = independent_cloud_bounds(upper_rows, 78)
        set_body_center(upper_rows, 78, upper)
        upper_result = compute_a01_metrics(upper_rows)
        self.assertEqual(metric_at(upper_result, A2_ID, 78)["raw_value"], 0.0)

        below_rows = copy.deepcopy(inside_rows)
        lower, _upper, _center = independent_cloud_bounds(below_rows, 78)
        set_body_center(below_rows, 78, lower - 0.05)
        below_result = compute_a01_metrics(below_rows)
        self.assertGreater(float(metric_at(below_result, A2_ID, 78)["raw_value"]), 0.0)

        above_rows = copy.deepcopy(inside_rows)
        _lower, upper, _center = independent_cloud_bounds(above_rows, 78)
        set_body_center(above_rows, 78, upper + 0.05)
        above_result = compute_a01_metrics(above_rows)
        self.assertGreater(float(metric_at(above_result, A2_ID, 78)["raw_value"]), 0.0)

    def test_a2b_uses_independent_gap_oracle_for_above_below_and_intersection(
        self,
    ) -> None:
        intersect_rows = make_rows(
            79,
            body_endpoints={
                index: (100.0 * math.exp(0.2), 100.0) for index in range(59, 79)
            },
        )
        above_rows = make_rows(
            79, close_values={index: 100.0 * (1.5**index) for index in range(79)}
        )
        below_rows = make_rows(
            79, close_values={index: 1000.0 * (0.5**index) for index in range(79)}
        )
        for index in range(59, 79):
            _low, high, _center = independent_cloud_bounds(above_rows, index)
            above_rows[index]["adjusted_open"] = math.exp(high + 0.2)
            low, _high, _center = independent_cloud_bounds(below_rows, index)
            below_rows[index]["adjusted_open"] = math.exp(low - 0.2)
        cases = {
            "intersect": intersect_rows,
            "above": above_rows,
            "below": below_rows,
        }
        values: dict[str, float] = {}
        for name, rows in cases.items():
            expected_gaps: list[float] = []
            for index in range(59, 79):
                low, high, _center = independent_cloud_bounds(rows, index)
                body_low = min(
                    math.log(float(rows[index]["adjusted_open"])),
                    math.log(float(rows[index]["adjusted_close"])),
                )
                body_high = max(
                    math.log(float(rows[index]["adjusted_open"])),
                    math.log(float(rows[index]["adjusted_close"])),
                )
                expected_gaps.append(
                    low - body_high
                    if body_high < low
                    else body_low - high
                    if body_low > high
                    else 0.0
                )
            expected = sum(expected_gaps) / len(expected_gaps)
            result = compute_a01_metrics(rows)
            actual = float(metric_at(result, A2B_ID, 78)["raw_value"])
            self.assertAlmostEqual(actual, expected, places=12)
            values[name] = actual
        self.assertEqual(values["intersect"], 0.0)
        self.assertGreater(values["above"], 0.0)
        self.assertGreater(values["below"], 0.0)
        self.assertAlmostEqual(values["above"], values["below"], places=12)

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

    def test_d3_status_vocab_and_adjustment_fail_closed(self) -> None:
        listed_open = make_rows(100)
        for row in listed_open:
            row["trading_status"] = "listed_open_resolved_daily"
        listed_results = compute_a01_metrics(listed_open)
        for indicator_id in (A1_ID, A2_ID, A2B_ID):
            listed_result = metric_at(listed_results, indicator_id, 99)
            self.assertEqual(listed_result["validity_status"], "valid")
            self.assertNotIn("invalid_trading_status", listed_result["reason_codes"])

        reopen = make_rows(79)
        reopen[40]["trading_status"] = "reopen_after_suspension"
        reopen_result = metric_at(compute_a01_metrics(reopen), A2_ID, 78)
        self.assertEqual(reopen_result["validity_status"], "diagnostic_required")
        self.assertIn("reopen_after_suspension", reopen_result["reason_codes"])

        for trading_status in ("unknown", "zero_volume", "unregistered_status"):
            invalid_status = make_rows(79)
            invalid_status[40]["trading_status"] = trading_status
            result = metric_at(compute_a01_metrics(invalid_status), A2_ID, 78)
            self.assertEqual(result["validity_status"], "blocked")
            self.assertIn("invalid_trading_status", result["reason_codes"])

        unknown_daily = make_rows(79)
        unknown_daily[40]["daily_status"] = "unknown"
        daily_result = metric_at(compute_a01_metrics(unknown_daily), A2_ID, 78)
        self.assertNotEqual(daily_result["validity_status"], "valid")
        self.assertIn("missing_required_history", daily_result["reason_codes"])

        ambiguous_factor = make_rows(79)
        ambiguous_factor[40]["adjustment_factor_status"] = "ambiguous"
        factor_result = metric_at(compute_a01_metrics(ambiguous_factor), A2_ID, 78)
        self.assertEqual(factor_result["validity_status"], "blocked")
        self.assertIn("adjustment_failure", factor_result["reason_codes"])

    def test_dense_placeholders_for_listing_pause_missing_and_unresolved_are_nonvalid(
        self,
    ) -> None:
        for status, reason in (
            ("listing_pause", "listing_pause_in_required_window"),
            ("missing", "missing_required_history"),
            ("unresolved", "adjustment_failure"),
        ):
            expected = make_expected(79, status_overrides={40: status})
            dense = build_dense_price_rows(
                expected, make_observations(79)[:40] + make_observations(79)[41:]
            )
            results = compute_a01_metrics(dense)
            for indicator_id in (A2_ID, A2B_ID):
                result = metric_at(results, indicator_id, 78)
                self.assertIsNone(result["raw_value"])
                self.assertIn(reason, result["reason_codes"])
                self.assertNotEqual(result["validity_status"], "valid")

    def test_deleting_expected_slot_from_a1_a2_and_a2b_fails_closed(self) -> None:
        for count, index in ((60, 30), (79, 30), (79, 40)):
            expected = make_expected(count)
            observations = make_observations(count)
            del observations[index]
            with self.assertRaisesRegex(
                InputContractError, "expected_present_row_missing_from_main"
            ):
                build_dense_price_rows(expected, observations)

    def test_older_present_row_is_not_used_after_a_missing_slot(self) -> None:
        expected = make_expected(81, status_overrides={30: "missing"})
        observations = make_observations(81)
        del observations[30]
        dense = build_dense_price_rows(expected, observations)
        result = metric_at(compute_a01_metrics(dense), A2_ID, 80)
        self.assertIsNone(result["raw_value"])
        self.assertIn("missing_required_history", result["reason_codes"])
        self.assertEqual(result["input_window_start"], "2020-01-03")

    def test_sequence_gap_and_non_monotonic_inputs_raise_input_contract_error(
        self,
    ) -> None:
        rows = make_rows(60)
        del rows[10]
        with self.assertRaisesRegex(InputContractError, "sequence_gap"):
            compute_a01_metrics(rows)

        non_monotonic = make_rows(60)
        non_monotonic[0], non_monotonic[1] = non_monotonic[1], non_monotonic[0]
        with self.assertRaisesRegex(InputContractError, "non_monotonic_input_sequence"):
            compute_a01_metrics(non_monotonic)

        duplicate_sequence = make_rows(60)
        duplicate_sequence[1]["observation_sequence"] = 0
        with self.assertRaisesRegex(InputContractError, "duplicate_security_sequence"):
            compute_a01_metrics(duplicate_sequence)

        expected = make_expected(60)
        observations = make_observations(60)
        observations[0], observations[1] = observations[1], observations[0]
        with self.assertRaisesRegex(InputContractError, "non_monotonic_input_sequence"):
            build_dense_price_rows(expected, observations)

    def test_duplicate_date_and_invalid_date_raise_input_contract_error(self) -> None:
        duplicate = make_rows(60)
        duplicate.append(copy.deepcopy(duplicate[-1]))
        duplicate[-1]["observation_sequence"] = 60
        with self.assertRaisesRegex(InputContractError, "duplicate_security_date"):
            compute_a01_metrics(duplicate)

        invalid = make_rows(60)
        invalid[0]["trading_date"] = "2020-02-31"
        with self.assertRaises(InputContractError):
            compute_a01_metrics(invalid)

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
