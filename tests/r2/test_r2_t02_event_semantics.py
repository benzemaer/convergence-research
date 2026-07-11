import unittest

from src.r2.r2_t02_event_rule_contract import (
    build_confirmed_intervals,
    compute_event_geometry_metrics,
    compute_window_overlap_metrics,
    confirm_k3_without_backfill,
    group_qualified_intervals_by_g,
    qualify_intervals_by_d,
)


def rows(states, qualities=None):
    qualities = qualities or ["valid"] * len(states)
    return [
        {
            "route_id": "r",
            "security_id": "s",
            "trade_date": f"2026-01-{i:02d}",
            "available_time": f"2026-01-{i:02d}T16:00:00+08:00",
            "eligible": q not in ("ineligible",),
            "quality_state": q,
            "raw_state": v,
        }
        for i, (v, q) in enumerate(zip(states, qualities), 1)
    ]


class EventSemanticsTest(unittest.TestCase):
    def test_k3_no_backfill_and_breaks(self):
        out = confirm_k3_without_backfill(rows([True, True, True, True]))
        self.assertEqual(
            [x["confirmed_state"] for x in out], [False, False, True, True]
        )
        out = confirm_k3_without_backfill(
            rows([True, True, True, True], ["valid", "unknown", "valid", "valid"])
        )
        self.assertFalse(any(x["confirmed_state"] for x in out))

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
        self.assertEqual(len(group_qualified_intervals_by_g(ints, data, 0)), 2)
        zone = group_qualified_intervals_by_g(ints, data, 1)[0]
        self.assertEqual(len(zone["bridge_rows"]), 1)

    def test_g_waits_for_irreversible_finalization(self):
        data = rows([False] * 4)
        for item, state in zip(data, [True, True, False, False]):
            item["confirmed_state"] = state
        intervals = qualify_intervals_by_d(build_confirmed_intervals(data), 1)
        zone_g2 = group_qualified_intervals_by_g(intervals, data, 2)[0]
        zone_g1 = group_qualified_intervals_by_g(intervals, data, 1)[0]
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
        zones = group_qualified_intervals_by_g(qualified, data, 1)
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


if __name__ == "__main__":
    unittest.main()
