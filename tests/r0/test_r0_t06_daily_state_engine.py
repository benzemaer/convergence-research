from __future__ import annotations

import unittest

from src.r0.daily_state_engine import (
    BLOCKED,
    DIAGNOSTIC_REQUIRED,
    UNKNOWN,
    VALID,
    WEAK_DELTA,
    assert_no_forbidden_state_outputs,
    check_state_lineage,
    compute_dimension_weak_states,
    compute_indicator_active_states,
    compute_nested_daily_states,
)


def indicator_score(
    score: float | None,
    indicator_id: str = "P1_NATR14",
    eligible: bool = True,
    status: str = VALID,
    reasons: tuple[str, ...] = ("valid_no_blocker",),
) -> dict[str, object]:
    return {
        "security_id": "000001.SZ",
        "trading_date": "2026-0121",
        "percentile_window_W": 120,
        "indicator_id": indicator_id,
        "score": score,
        "eligible": eligible,
        "validity_status": status,
        "reason_codes": list(reasons),
    }


def dimension_score(
    dimension: str,
    score: float | None,
    score_min: float | None,
    eligible: bool = True,
    status: str = VALID,
    reasons: tuple[str, ...] = ("valid_no_blocker",),
) -> dict[str, object]:
    return {
        "security_id": "000001.SZ",
        "trading_date": "2026-0121",
        "percentile_window_W": 120,
        "dimension": dimension,
        "score_dimension": score,
        "score_dimension_min": score_min,
        "eligible_dimension": eligible,
        "validity_status": status,
        "reason_codes": list(reasons),
        "component_indicator_ids": [f"{dimension}1", f"{dimension}2"],
    }


def active_dimension(dimension: str) -> dict[str, object]:
    return dimension_score(dimension, 0.80, 0.70)


def inactive_dimension(dimension: str) -> dict[str, object]:
    return dimension_score(dimension, 0.79, 0.90)


def state_for_indicator(results, q: float = 0.20):
    return next(item for item in results if item.q == q)


def state_for_dimension(results, dimension: str, q: float = 0.20):
    return next(item for item in results if item.dimension == dimension and item.q == q)


def nested_for(results, q: float = 0.20):
    return next(item for item in results if item.q == q)


class R0T06DailyStateEngineTest(unittest.TestCase):
    def test_indicator_active_threshold_and_unknown_not_false(self) -> None:
        equal = state_for_indicator(
            compute_indicator_active_states([indicator_score(0.80)], q_values=(0.20,))
        )
        self.assertTrue(equal.indicator_active)
        self.assertEqual(equal.validity_status, VALID)

        below = state_for_indicator(
            compute_indicator_active_states([indicator_score(0.799)], q_values=(0.20,))
        )
        self.assertFalse(below.indicator_active)
        self.assertEqual(below.validity_status, VALID)

        missing = state_for_indicator(
            compute_indicator_active_states(
                [
                    indicator_score(
                        None,
                        eligible=False,
                        status=UNKNOWN,
                        reasons=("insufficient_strict_past_history",),
                    )
                ],
                q_values=(0.20,),
            )
        )
        self.assertIsNone(missing.indicator_active)
        self.assertEqual(missing.validity_status, UNKNOWN)
        self.assertIn("insufficient_strict_past_history", missing.reason_codes)

    def test_weak_dimension_rule_uses_mean_and_min_constraints(self) -> None:
        rows = [
            dimension_score("P", 0.80, 0.70),
            dimension_score("C", 0.80, 0.699),
            dimension_score("T", 0.799, 0.90),
        ]
        states = compute_dimension_weak_states(rows, q_values=(0.20,))
        self.assertTrue(state_for_dimension(states, "P").dimension_active_weak)
        self.assertFalse(state_for_dimension(states, "C").dimension_active_weak)
        self.assertFalse(state_for_dimension(states, "T").dimension_active_weak)

    def test_dimension_unknown_and_missing_min_do_not_become_false(self) -> None:
        rows = [
            dimension_score(
                "P",
                None,
                None,
                eligible=False,
                status=UNKNOWN,
                reasons=("missing_component_score",),
            ),
            dimension_score("C", 0.85, None),
        ]
        states = compute_dimension_weak_states(rows, q_values=(0.20,))
        unknown = state_for_dimension(states, "P")
        self.assertIsNone(unknown.dimension_active_weak)
        self.assertEqual(unknown.validity_status, UNKNOWN)
        self.assertIn("missing_component_score", unknown.reason_codes)

        missing_min = state_for_dimension(states, "C")
        self.assertIsNone(missing_min.dimension_active_weak)
        self.assertEqual(missing_min.validity_status, UNKNOWN)
        self.assertIn("score_dimension_min_missing", missing_min.reason_codes)

    def test_q_values_generate_all_candidates_and_thresholds(self) -> None:
        states = compute_dimension_weak_states(
            [dimension_score("P", 0.80, 0.70)], q_values=(0.10, 0.20, 0.30)
        )
        self.assertEqual({item.q for item in states}, {0.10, 0.20, 0.30})
        self.assertFalse(state_for_dimension(states, "P", 0.10).dimension_active_weak)
        self.assertTrue(state_for_dimension(states, "P", 0.20).dimension_active_weak)
        self.assertTrue(state_for_dimension(states, "P", 0.30).dimension_active_weak)
        self.assertEqual(WEAK_DELTA, 0.10)

    def test_invalid_q_and_weak_delta_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            compute_indicator_active_states([indicator_score(0.80)], q_values=(0.15,))

        with self.assertRaises(ValueError):
            compute_dimension_weak_states(
                [dimension_score("P", 0.80, 0.70)],
                q_values=(0.20,),
                weak_delta=0.05,
            )

    def test_nested_state_cases_and_exclusive_layers(self) -> None:
        cases = [
            (
                [
                    inactive_dimension("P"),
                    active_dimension("C"),
                    active_dimension("T"),
                    active_dimension("V"),
                ],
                (False, False, False, False),
                "NONE",
            ),
            (
                [
                    active_dimension("P"),
                    inactive_dimension("C"),
                    active_dimension("T"),
                    active_dimension("V"),
                ],
                (True, False, False, False),
                "P_ONLY",
            ),
            (
                [
                    active_dimension("P"),
                    active_dimension("C"),
                    inactive_dimension("T"),
                    active_dimension("V"),
                ],
                (True, True, False, False),
                "PC_ONLY",
            ),
            (
                [
                    active_dimension("P"),
                    active_dimension("C"),
                    active_dimension("T"),
                    inactive_dimension("V"),
                ],
                (True, True, True, False),
                "PCT_ONLY",
            ),
            (
                [
                    active_dimension("P"),
                    active_dimension("C"),
                    active_dimension("T"),
                    active_dimension("V"),
                ],
                (True, True, True, True),
                "PCVT",
            ),
        ]
        for rows, expected_states, expected_layer in cases:
            with self.subTest(expected_layer=expected_layer):
                dimensions = compute_dimension_weak_states(rows, q_values=(0.20,))
                nested = nested_for(compute_nested_daily_states(dimensions))
                self.assertEqual(
                    (
                        nested.S_P_raw,
                        nested.S_PC_raw,
                        nested.S_PCT_raw,
                        nested.S_PCVT_raw,
                    ),
                    expected_states,
                )
                self.assertEqual(nested.exclusive_state_layer, expected_layer)
                self.assertTrue(nested.eligible_state)

    def test_nested_unknown_propagation_does_not_emit_false(self) -> None:
        p_false_rows = [
            inactive_dimension("P"),
            dimension_score(
                "C",
                None,
                None,
                eligible=False,
                status=UNKNOWN,
                reasons=("missing_component_score",),
            ),
            dimension_score(
                "T",
                None,
                None,
                eligible=False,
                status=BLOCKED,
                reasons=("upstream_blocked",),
            ),
            active_dimension("V"),
        ]
        p_false = nested_for(
            compute_nested_daily_states(
                compute_dimension_weak_states(p_false_rows, q_values=(0.20,))
            )
        )
        self.assertEqual(
            (
                p_false.S_P_raw,
                p_false.S_PC_raw,
                p_false.S_PCT_raw,
                p_false.S_PCVT_raw,
            ),
            (False, False, False, False),
        )
        self.assertEqual(p_false.exclusive_state_layer, "NONE")
        self.assertTrue(p_false.eligible_state)
        self.assertEqual(p_false.validity_status, VALID)

        c_unknown_rows = [
            active_dimension("P"),
            dimension_score(
                "C",
                None,
                None,
                eligible=False,
                status=UNKNOWN,
                reasons=("missing_component_score",),
            ),
            active_dimension("T"),
            active_dimension("V"),
        ]
        c_unknown = nested_for(
            compute_nested_daily_states(
                compute_dimension_weak_states(c_unknown_rows, q_values=(0.20,))
            )
        )
        self.assertTrue(c_unknown.S_P_raw)
        self.assertIsNone(c_unknown.S_PC_raw)
        self.assertIsNone(c_unknown.S_PCT_raw)
        self.assertIsNone(c_unknown.S_PCVT_raw)
        self.assertEqual(c_unknown.exclusive_state_layer, "UNKNOWN")

        v_unknown_rows = [
            active_dimension("P"),
            active_dimension("C"),
            active_dimension("T"),
            dimension_score(
                "V",
                None,
                None,
                eligible=False,
                status=UNKNOWN,
                reasons=("missing_component_score",),
            ),
        ]
        v_unknown = nested_for(
            compute_nested_daily_states(
                compute_dimension_weak_states(v_unknown_rows, q_values=(0.20,))
            )
        )
        self.assertTrue(v_unknown.S_PCT_raw)
        self.assertIsNone(v_unknown.S_PCVT_raw)
        self.assertEqual(v_unknown.exclusive_state_layer, "UNKNOWN")

    def test_nested_blocked_and_diagnostic_layers(self) -> None:
        blocked_rows = [
            active_dimension("P"),
            dimension_score(
                "C",
                None,
                None,
                eligible=False,
                status=BLOCKED,
                reasons=("upstream_blocked",),
            ),
        ]
        blocked = nested_for(
            compute_nested_daily_states(
                compute_dimension_weak_states(blocked_rows, q_values=(0.20,))
            )
        )
        self.assertEqual(blocked.exclusive_state_layer, "BLOCKED")
        self.assertEqual(blocked.validity_status, BLOCKED)

        diagnostic_rows = [
            active_dimension("P"),
            active_dimension("C"),
            dimension_score(
                "T",
                None,
                None,
                eligible=False,
                status=DIAGNOSTIC_REQUIRED,
                reasons=("upstream_diagnostic_required",),
            ),
        ]
        diagnostic = nested_for(
            compute_nested_daily_states(
                compute_dimension_weak_states(diagnostic_rows, q_values=(0.20,))
            )
        )
        self.assertEqual(diagnostic.exclusive_state_layer, "DIAGNOSTIC_REQUIRED")
        self.assertEqual(diagnostic.validity_status, DIAGNOSTIC_REQUIRED)

    def test_nested_invariant_and_stable_output_for_disordered_input(self) -> None:
        rows = [
            active_dimension("V"),
            active_dimension("P"),
            active_dimension("T"),
            active_dimension("C"),
        ]
        normal = compute_nested_daily_states(
            compute_dimension_weak_states(rows, q_values=(0.10, 0.20, 0.30))
        )
        shuffled = compute_nested_daily_states(
            compute_dimension_weak_states(
                list(reversed(rows)), q_values=(0.10, 0.20, 0.30)
            )
        )
        self.assertEqual(
            [item.as_dict() for item in normal], [item.as_dict() for item in shuffled]
        )
        for item in normal:
            self.assertTrue(
                not item.S_PCVT_raw or item.S_PCT_raw and item.S_PC_raw and item.S_P_raw
            )

    def test_forbidden_outputs_and_lineage_guards(self) -> None:
        forbidden = assert_no_forbidden_state_outputs(
            {
                "confirmation": True,
                "streak": 3,
                "state_interval": {},
                "future_return": 0.2,
                "backtest": {},
                "portfolio": [],
            }
        )
        self.assertEqual(forbidden.validity_status, BLOCKED)
        self.assertIn("forbidden_output_field", forbidden.reason_codes)

        allowed = check_state_lineage(["synthetic_in_memory_scores"])
        self.assertEqual(allowed.validity_status, VALID)

        for source in (
            "data/generated/d3/foo.duckdb",
            "data/raw/vendor.csv",
            "MarketDB/prices",
            "SH000001.day",
        ):
            with self.subTest(source=source):
                result = check_state_lineage([source])
                self.assertEqual(result.validity_status, BLOCKED)
                self.assertIn("direct_real_data_source_forbidden", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
