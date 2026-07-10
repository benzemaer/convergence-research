from __future__ import annotations

import unittest
from collections.abc import Mapping

from src.r0.confirmation_interval_engine import (
    BLOCKED,
    DIAGNOSTIC_REQUIRED,
    UNKNOWN,
    VALID,
    assert_no_forbidden_confirmation_outputs,
    check_confirmation_lineage,
    compute_confirmed_intervals,
    compute_daily_confirmations,
)


def daily_state(
    day: int,
    *,
    trading_date: str | None = None,
    s_p: bool | None = True,
    s_pc: bool | None = True,
    s_pct: bool | None = True,
    s_pcvt: bool | None = True,
    security_id: str = "000001.SZ",
    window: int = 120,
    q: float = 0.20,
    status: str = VALID,
    reasons: tuple[str, ...] = ("valid_no_blocker",),
    state_validity: Mapping[str, str] | None = None,
    state_reasons: Mapping[str, tuple[str, ...]] | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "security_id": security_id,
        "trading_date": trading_date or f"2026-{day:04d}",
        "percentile_window_W": window,
        "q": q,
        "weak_delta": 0.10,
        "P_raw": s_p,
        "C_raw": s_pc,
        "T_raw": s_pct,
        "V_raw": s_pcvt,
        "S_P_raw": s_p,
        "S_PC_raw": s_pc,
        "S_PCT_raw": s_pct,
        "S_PCVT_raw": s_pcvt,
        "exclusive_state_layer": "PCVT" if s_pcvt is True else "UNKNOWN",
        "eligible_state": status == VALID,
        "validity_status": status,
        "reason_codes": list(reasons),
        "state_engine_version": "r0_t06_weak_dimension_nested_state.v1",
    }
    state_validity = state_validity or {}
    state_reasons = state_reasons or {}
    for state_name in ("S_P", "S_PC", "S_PCT", "S_PCVT"):
        row[f"{state_name}_validity_status"] = state_validity.get(state_name, status)
        row[f"{state_name}_reason_codes"] = list(state_reasons.get(state_name, reasons))
    return row


def result_for(
    results, day: int | str, state_name: str, k: int, security_id: str = "000001.SZ"
):
    trading_date = day if isinstance(day, str) else f"2026-{day:04d}"
    for result in results:
        if (
            result.security_id == security_id
            and result.trading_date == trading_date
            and result.state_name == state_name
            and result.confirmation_k == k
        ):
            return result
    raise AssertionError(f"missing {security_id} {trading_date} {state_name} K={k}")


class R0T07ConfirmationIntervalEngineTest(unittest.TestCase):
    def test_streak_confirmation_and_no_backfill_for_k_values(self) -> None:
        rows = [daily_state(day) for day in range(1, 6)]
        results = compute_daily_confirmations(rows)

        day1_k2 = result_for(results, 1, "S_PCVT", 2)
        day2_k2 = result_for(results, 2, "S_PCVT", 2)
        self.assertFalse(day1_k2.confirmed_state)
        self.assertIsNone(day1_k2.confirmation_date)
        self.assertTrue(day2_k2.confirmed_state)
        self.assertEqual(day2_k2.confirmation_start_date, "2026-0001")
        self.assertEqual(day2_k2.confirmation_date, "2026-0002")

        day2_k3 = result_for(results, 2, "S_PCVT", 3)
        day3_k3 = result_for(results, 3, "S_PCVT", 3)
        self.assertFalse(day2_k3.confirmed_state)
        self.assertTrue(day3_k3.confirmed_state)
        self.assertEqual(day3_k3.confirmation_start_date, "2026-0001")
        self.assertEqual(day3_k3.confirmation_date, "2026-0003")

        day4_k5 = result_for(results, 4, "S_PCVT", 5)
        day5_k5 = result_for(results, 5, "S_PCVT", 5)
        self.assertFalse(day4_k5.confirmed_state)
        self.assertTrue(day5_k5.confirmed_state)
        self.assertEqual(day5_k5.confirmation_start_date, "2026-0001")
        self.assertEqual(day5_k5.confirmation_date, "2026-0005")

    def test_false_and_unknown_interrupt_streak_without_false_conversion(self) -> None:
        rows = [
            daily_state(1),
            daily_state(2, s_pcvt=False),
            daily_state(3),
            daily_state(
                4,
                s_p=None,
                s_pc=None,
                s_pct=None,
                s_pcvt=None,
                status=UNKNOWN,
                reasons=("upstream_unknown",),
            ),
            daily_state(5),
        ]
        results = compute_daily_confirmations(rows, confirmation_k_values=(2,))

        false_day = result_for(results, 2, "S_PCVT", 2)
        self.assertEqual(false_day.raw_streak, 0)
        self.assertFalse(false_day.confirmed_state)

        restarted = result_for(results, 3, "S_PCVT", 2)
        self.assertEqual(restarted.raw_streak, 1)
        self.assertFalse(restarted.confirmed_state)

        unknown = result_for(results, 4, "S_PCVT", 2)
        self.assertIsNone(unknown.raw_streak)
        self.assertIsNone(unknown.confirmed_state)
        self.assertEqual(unknown.validity_status, UNKNOWN)
        self.assertIn("upstream_unknown", unknown.reason_codes)

        after_unknown = result_for(results, 5, "S_PCVT", 2)
        self.assertEqual(after_unknown.raw_streak, 1)

    def test_stable_sorting_and_group_isolation(self) -> None:
        rows = [
            daily_state(2, security_id="000002.SZ", window=250),
            daily_state(1, security_id="000001.SZ", q=0.10),
            daily_state(2, security_id="000001.SZ", q=0.10),
            daily_state(1, security_id="000002.SZ", window=250),
        ]
        normal = compute_daily_confirmations(rows, confirmation_k_values=(2,))
        shuffled = compute_daily_confirmations(
            list(reversed(rows)), confirmation_k_values=(2,)
        )
        self.assertEqual(
            [item.as_dict() for item in normal], [item.as_dict() for item in shuffled]
        )
        self.assertTrue(result_for(normal, 2, "S_PCVT", 2, "000001.SZ").confirmed_state)
        self.assertTrue(result_for(normal, 2, "S_PCVT", 2, "000002.SZ").confirmed_state)

    def test_confirmed_intervals_closed_unconfirmed_and_open(self) -> None:
        rows = [
            daily_state(1),
            daily_state(2),
            daily_state(3),
            daily_state(4, s_pcvt=False),
            daily_state(5),
            daily_state(6, s_pcvt=False),
            daily_state(7),
            daily_state(8),
        ]
        daily = compute_daily_confirmations(rows, confirmation_k_values=(2, 3))
        intervals = [
            item
            for item in compute_confirmed_intervals(daily)
            if item.state_name == "S_PCVT"
        ]

        closed_k2 = next(
            item
            for item in intervals
            if item.confirmation_k == 2 and not item.is_open_interval
        )
        self.assertEqual(closed_k2.raw_start_date, "2026-0001")
        self.assertEqual(closed_k2.confirmation_date, "2026-0002")
        self.assertEqual(closed_k2.interval_end_date, "2026-0003")
        self.assertEqual(closed_k2.last_observed_date, "2026-0004")
        self.assertEqual(closed_k2.duration_raw_days, 3)
        self.assertEqual(closed_k2.duration_confirmed_days, 2)
        self.assertEqual(closed_k2.termination_reason, "raw_state_false")

        open_k2 = next(
            item
            for item in intervals
            if item.confirmation_k == 2 and item.is_open_interval
        )
        self.assertEqual(open_k2.raw_start_date, "2026-0007")
        self.assertEqual(open_k2.confirmation_date, "2026-0008")
        self.assertIsNone(open_k2.interval_end_date)
        self.assertEqual(open_k2.termination_reason, "end_of_input_open")

        k3_intervals = [item for item in intervals if item.confirmation_k == 3]
        self.assertEqual(len(k3_intervals), 1)
        self.assertEqual(k3_intervals[0].raw_start_date, "2026-0001")

    def test_interval_terminates_on_unknown_diagnostic_and_blocked(self) -> None:
        cases = [
            (UNKNOWN, "raw_state_unknown", "upstream_unknown"),
            (
                DIAGNOSTIC_REQUIRED,
                "raw_state_diagnostic_required",
                "upstream_diagnostic_required",
            ),
            (BLOCKED, "raw_state_blocked", "upstream_blocked"),
        ]
        for status, expected_reason, reason_code in cases:
            with self.subTest(status=status):
                rows = [
                    daily_state(1),
                    daily_state(2),
                    daily_state(
                        3,
                        s_p=None,
                        s_pc=None,
                        s_pct=None,
                        s_pcvt=None,
                        status=status,
                        reasons=(reason_code,),
                    ),
                ]
                daily = compute_daily_confirmations(rows, confirmation_k_values=(2,))
                intervals = [
                    item
                    for item in compute_confirmed_intervals(daily)
                    if item.state_name == "S_PCVT"
                ]
                self.assertEqual(len(intervals), 1)
                self.assertEqual(intervals[0].termination_reason, expected_reason)
                self.assertEqual(intervals[0].interval_end_date, "2026-0002")

    def test_confirmed_nested_invariant_and_raw_violation_guard(self) -> None:
        rows = [daily_state(1), daily_state(2)]
        results = compute_daily_confirmations(rows, confirmation_k_values=(2,))
        confirmed = {
            item.state_name: item.confirmed_state
            for item in results
            if item.trading_date == "2026-0002" and item.confirmation_k == 2
        }
        self.assertTrue(confirmed["S_PCVT"])
        self.assertTrue(confirmed["S_PCT"])
        self.assertTrue(confirmed["S_PC"])
        self.assertTrue(confirmed["S_P"])

        invalid = daily_state(3, s_p=True, s_pc=False, s_pct=False, s_pcvt=True)
        blocked = compute_daily_confirmations([invalid], confirmation_k_values=(2,))
        for item in blocked:
            self.assertEqual(item.validity_status, BLOCKED)
            self.assertIsNone(item.confirmed_state)
            self.assertIn("nested_raw_state_invariant_violation", item.reason_codes)

    def test_state_specific_validity_keeps_s_p_from_c_unknown_blocker(self) -> None:
        rows = [
            daily_state(
                day,
                s_p=True,
                s_pc=None,
                s_pct=None,
                s_pcvt=None,
                status=UNKNOWN,
                reasons=("c_unknown",),
                state_validity={
                    "S_P": VALID,
                    "S_PC": UNKNOWN,
                    "S_PCT": UNKNOWN,
                    "S_PCVT": UNKNOWN,
                },
                state_reasons={
                    "S_P": ("valid_no_blocker",),
                    "S_PC": ("c_unknown",),
                    "S_PCT": ("c_unknown",),
                    "S_PCVT": ("c_unknown",),
                },
            )
            for day in range(1, 4)
        ]

        results = compute_daily_confirmations(rows, confirmation_k_values=(2,))

        s_p_day2 = result_for(results, 2, "S_P", 2)
        self.assertTrue(s_p_day2.confirmed_state)
        self.assertEqual(s_p_day2.raw_streak, 2)
        self.assertEqual(s_p_day2.confirmation_date, "2026-0002")
        self.assertEqual(s_p_day2.validity_status, VALID)

        s_pc_day2 = result_for(results, 2, "S_PC", 2)
        self.assertIsNone(s_pc_day2.confirmed_state)
        self.assertIsNone(s_pc_day2.raw_streak)
        self.assertEqual(s_pc_day2.validity_status, UNKNOWN)
        self.assertIn("c_unknown", s_pc_day2.reason_codes)

    def test_invalid_k_values_are_rejected(self) -> None:
        for invalid_k in (0, 1, 4, 6):
            with self.subTest(invalid_k=invalid_k):
                with self.assertRaises(ValueError):
                    compute_daily_confirmations(
                        [daily_state(1)], confirmation_k_values=(invalid_k,)
                    )

    def test_interval_durations_use_observation_counts_across_calendar_gaps(
        self,
    ) -> None:
        rows = [
            daily_state(1, trading_date="2026-01-30"),
            daily_state(2, trading_date="2026-02-02"),
            daily_state(3, trading_date="2026-02-03"),
            daily_state(4, trading_date="2026-02-04", s_pcvt=False),
        ]
        daily = compute_daily_confirmations(rows, confirmation_k_values=(2, 3))
        intervals = [
            item
            for item in compute_confirmed_intervals(daily)
            if item.state_name == "S_PCVT"
        ]

        k2 = next(item for item in intervals if item.confirmation_k == 2)
        self.assertEqual(k2.raw_start_date, "2026-01-30")
        self.assertEqual(k2.confirmation_date, "2026-02-02")
        self.assertEqual(k2.interval_end_date, "2026-02-03")
        self.assertEqual(k2.last_observed_date, "2026-02-04")
        self.assertEqual(k2.duration_raw_days, 3)
        self.assertEqual(k2.duration_confirmed_days, 2)

        k3 = next(item for item in intervals if item.confirmation_k == 3)
        self.assertEqual(k3.confirmation_date, "2026-02-03")
        self.assertEqual(k3.duration_raw_days, 3)
        self.assertEqual(k3.duration_confirmed_days, 1)

    def test_forbidden_outputs_and_lineage_guards(self) -> None:
        forbidden = assert_no_forbidden_confirmation_outputs(
            {
                "future_return": 0.1,
                "future_label": "up",
                "breakout_direction": "up",
                "backtest": {},
                "portfolio": [],
                "formal_data_version": "v1",
            }
        )
        self.assertEqual(forbidden.validity_status, BLOCKED)
        self.assertIn("forbidden_output_field", forbidden.reason_codes)

        allowed = check_confirmation_lineage(["synthetic_in_memory_daily_states"])
        self.assertEqual(allowed.validity_status, VALID)

        for source in (
            "data/generated/r0/state.duckdb",
            "data/raw/vendor.csv",
            "MarketDB/prices",
            "SH000001.day",
        ):
            with self.subTest(source=source):
                result = check_confirmation_lineage([source])
                self.assertEqual(result.validity_status, BLOCKED)
                self.assertIn("direct_real_data_source_forbidden", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
