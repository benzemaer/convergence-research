import unittest

from src.r2.r2_t02_event_rule_contract import (
    R2T02ContractError,
    _maximum_lexicographic_matching_pairs,
    build_confirmed_intervals,
    compute_event_geometry_metrics,
    compute_window_overlap_metrics,
    confirm_k3_without_backfill,
    group_qualified_intervals_by_g,
    qualify_intervals_by_d,
    validate_trading_row_completeness,
)


def rows(states, qualities=None):
    qualities = qualities or ["valid"] * len(states)
    return [
        {
            "route_id": "r",
            "security_id": "s",
            "trade_date": f"2026-01-{i:02d}",
            "expected_trade_index": i,
            "available_time": f"2026-01-{i:02d}T16:00:00+08:00",
            "eligible": q not in ("ineligible",),
            "quality_state": q,
            "raw_state": v,
        }
        for i, (v, q) in enumerate(zip(states, qualities), 1)
    ]


def expected_registry(data):
    grouped = {}
    for row in data:
        grouped.setdefault((row["route_id"], row["security_id"]), []).append(row)
    result = []
    for (route_id, security_id), items in grouped.items():
        ordered = sorted(items, key=lambda item: item["trade_date"])
        result.extend(
            {
                "route_id": route_id,
                "security_id": security_id,
                "trade_date": item["trade_date"],
                "expected_trade_index": index,
                "expected_first_index": 1,
                "expected_last_index": len(ordered),
            }
            for index, item in enumerate(ordered, 1)
        )
    return result


class EventSemanticsTest(unittest.TestCase):
    def test_k3_no_backfill_and_breaks(self):
        data = rows([True, True, True, True])
        out = confirm_k3_without_backfill(data, expected_registry(data))
        self.assertEqual(
            [x["confirmed_state"] for x in out], [False, False, True, True]
        )
        data = rows([True, True, True, True], ["valid", "unknown", "valid", "valid"])
        out = confirm_k3_without_backfill(data, expected_registry(data))
        self.assertFalse(any(x["confirmed_state"] for x in out))

    def test_missing_expected_trading_row_fails_confirmation_and_grouping(self):
        incomplete = rows([True, True, True, True])
        registry = expected_registry(incomplete)
        del incomplete[1]
        with self.assertRaisesRegex(R2T02ContractError, "missing_expected_trading_row"):
            confirm_k3_without_backfill(incomplete, registry)
        complete = rows([False, False, False])
        registry = expected_registry(complete)
        for item, state in zip(complete, [True, False, True]):
            item["confirmed_state"] = state
        intervals = qualify_intervals_by_d(build_confirmed_intervals(complete), 1)
        del complete[1]
        with self.assertRaisesRegex(R2T02ContractError, "missing_expected_trading_row"):
            group_qualified_intervals_by_g(
                intervals, complete, 0, expected_key_registry=registry
            )

    def test_authoritative_registry_rejects_boundary_and_mapping_attacks(self):
        baseline = rows([True] * 4)
        registry = expected_registry(baseline)
        for removed in (0, 1, 3):
            observed = [dict(row) for row in baseline]
            del observed[removed]
            with self.assertRaisesRegex(
                R2T02ContractError, "missing_expected_trading_row"
            ):
                validate_trading_row_completeness(observed, registry)

        renumbered = [dict(row) for row in baseline[1:]]
        for index, row in enumerate(renumbered, 1):
            row["expected_trade_index"] = index
        with self.assertRaisesRegex(R2T02ContractError, "missing_expected_trading_row"):
            validate_trading_row_completeness(renumbered, registry)

        mismatched = [dict(row) for row in baseline]
        mismatched[1]["expected_trade_index"] = 3
        with self.assertRaisesRegex(R2T02ContractError, "trade_date_index_mismatch"):
            validate_trading_row_completeness(mismatched, registry)

        duplicate_index = [dict(item) for item in registry]
        duplicate_index[1]["expected_trade_index"] = 1
        with self.assertRaisesRegex(
            R2T02ContractError, "duplicate_expected_trade_index"
        ):
            validate_trading_row_completeness(baseline, duplicate_index)

        extra = [*baseline, dict(baseline[-1], trade_date="2026-01-05")]
        with self.assertRaisesRegex(R2T02ContractError, "unexpected_trading_row"):
            validate_trading_row_completeness(extra, registry)

        other = [dict(row, security_id="s2") for row in baseline[:2]]
        with self.assertRaisesRegex(R2T02ContractError, "unexpected_trading_row"):
            validate_trading_row_completeness(baseline + other, registry)

    def test_d_uses_greater_equal(self):
        confirmed = rows([True] * 6)
        [x.update(confirmed_state=i >= 2) for i, x in enumerate(confirmed)]
        ints = build_confirmed_intervals(confirmed)
        self.assertTrue(qualify_intervals_by_d(ints, 3)[0]["qualified"])
        self.assertEqual(
            qualify_intervals_by_d(ints, 3)[0]["event_qualification_time"],
            "2026-01-05T16:00:00+08:00",
        )

    def test_qualification_uses_actual_row_availability(self):
        confirmed = rows([True] * 5)
        for index, item in enumerate(confirmed):
            item["confirmed_state"] = index >= 2
        confirmed[4]["available_time"] = "2026-01-05T21:37:00+08:00"
        interval = build_confirmed_intervals(confirmed)[0]
        qualified = qualify_intervals_by_d([interval], 3)[0]
        self.assertEqual(
            qualified["event_qualification_time"], "2026-01-05T21:37:00+08:00"
        )

    def test_g_bridges_only_ordinary_false(self):
        data = rows([True] * 7)
        states = [True, True, False, True, True, False, False]
        for item, state in zip(data, states):
            item["confirmed_state"] = state
        ints = qualify_intervals_by_d(build_confirmed_intervals(data), 2)
        registry = expected_registry(data)
        self.assertEqual(
            len(
                group_qualified_intervals_by_g(
                    ints, data, 0, expected_key_registry=registry
                )
            ),
            2,
        )
        zone = group_qualified_intervals_by_g(
            ints, data, 1, expected_key_registry=registry
        )[0]
        self.assertEqual(len(zone["bridge_rows"]), 1)

    def test_g_waits_for_irreversible_finalization(self):
        data = rows([False] * 4)
        for item, state in zip(data, [True, True, False, False]):
            item["confirmed_state"] = state
        intervals = qualify_intervals_by_d(build_confirmed_intervals(data), 1)
        registry = expected_registry(data)
        zone_g2 = group_qualified_intervals_by_g(
            intervals, data, 2, expected_key_registry=registry
        )[0]
        zone_g1 = group_qualified_intervals_by_g(
            intervals, data, 1, expected_key_registry=registry
        )[0]
        self.assertEqual(zone_g2["event_status"], "open")
        self.assertIsNone(zone_g2["zone_finalization_time"])
        self.assertEqual(zone_g1["event_status"], "closed")
        self.assertEqual(
            zone_g1["zone_finalization_reason"], "g_plus_one_false_observed"
        )

    def test_bridge_segments_and_overlap_are_computed(self):
        data = rows([False] * 9)
        states = [True, True, False, True, True, False, True, True, False]
        for item, state in zip(data, states):
            item["confirmed_state"] = state
        intervals = build_confirmed_intervals(data)
        qualified = qualify_intervals_by_d(intervals, 2)
        zones = group_qualified_intervals_by_g(
            qualified, data, 1, expected_key_registry=expected_registry(data)
        )
        metrics = compute_event_geometry_metrics(intervals, qualified, zones, len(data))
        self.assertEqual(metrics["bridged_gap_count"], 2)
        self.assertEqual(metrics["bridged_day_count"], 2)
        self.assertEqual(metrics["within_route_overlapping_event_count"], 0)

    def test_window_overlap_metrics_use_exact_confirmed_keys(self):
        left = {("s", "2026-01-01"), ("s", "2026-01-02")}
        right = {("s", "2026-01-02"), ("s", "2026-01-03")}
        metrics = compute_window_overlap_metrics(left, right, [], [])
        self.assertEqual(metrics["intersection_confirmed_days"], 1)
        self.assertEqual(metrics["W120_only_confirmed_days"], 1)
        self.assertEqual(metrics["W250_only_confirmed_days"], 1)
        self.assertEqual(metrics["confirmed_day_jaccard"], 1 / 3)

    def test_event_matching_is_global_not_greedy(self):
        def zone(event_id, dates, hour):
            return {
                "event_id": event_id,
                "security_id": "s",
                "first_qualification_time": f"2026-01-01T{hour:02d}:00:00+08:00",
                "intervals": [{"confirmed_dates": dates}],
            }

        a = [f"A{i}" for i in range(10)]
        b = [f"B{i}" for i in range(9)]
        c = [f"C{i}" for i in range(9)]
        left = [zone("L1", a + c, 10), zone("L2", b, 11)]
        right = [zone("R1", a + b, 10), zone("R2", c, 11)]
        metrics = compute_window_overlap_metrics(set(), set(), left, right)
        self.assertEqual(metrics["overlapping_event_count"], 3)
        self.assertEqual(metrics["matched_event_count"], 2)

    def test_event_matching_uses_overlap_distance_and_id_objective_order(self):
        overlap_wins = [(5, 100.0, "L1", "R1"), (4, 0.0, "L1", "R2")]
        self.assertEqual(
            _maximum_lexicographic_matching_pairs(overlap_wins), {("L1", "R1")}
        )
        distance_wins = [(5, 10.0, "L1", "R1"), (5, 1.0, "L1", "R2")]
        self.assertEqual(
            _maximum_lexicographic_matching_pairs(distance_wins), {("L1", "R2")}
        )
        id_tie = [(5, 1.0, "L1", "R2"), (5, 1.0, "L1", "R1")]
        self.assertEqual(_maximum_lexicographic_matching_pairs(id_tie), {("L1", "R1")})


if __name__ == "__main__":
    unittest.main()
