import unittest

from src.r2.r2_t02_event_rule_contract import (
    build_confirmed_intervals,
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

    def test_g_bridges_only_ordinary_false(self):
        data = rows([True] * 7)
        states = [True, True, False, True, True, False, False]
        for item, state in zip(data, states):
            item["confirmed_state"] = state
        ints = qualify_intervals_by_d(build_confirmed_intervals(data), 2)
        self.assertEqual(len(group_qualified_intervals_by_g(ints, data, 0)), 2)
        zone = group_qualified_intervals_by_g(ints, data, 1)[0]
        self.assertEqual(len(zone["bridge_rows"]), 1)


if __name__ == "__main__":
    unittest.main()
