from __future__ import annotations

import unittest

import src.r2.r2_t03_independent_validator as validator_module
from src.r2.r2_t03_independent_validator import (
    R2T03IndependentValidationError,
    compare_oracle_metric_targets,
    independent_strict_core_oracle,
    independent_window_oracle,
    source_timeline_oracle,
)


class R2T03SourceOracleTimelineTest(unittest.TestCase):
    def oracle(self, raw, *, d=1, g=0, qualities=None):
        qualities = qualities or ["valid"] * len(raw)
        rows = [
            {
                "security_id": "S1",
                "trade_date": f"2026-01-{index:02d}",
                "available_time": f"2026-01-{index:02d}T15:00:00+08:00",
                "eligible": quality == "valid",
                "quality_state": quality,
                "raw_state": value,
            }
            for index, (value, quality) in enumerate(zip(raw, qualities), start=1)
        ]
        return source_timeline_oracle(
            rows,
            expected_dates=[row["trade_date"] for row in rows],
            d=d,
            g=g,
        )

    def test_d1_single_component_closes_qualification_ledger(self) -> None:
        actual = self.oracle([True, True, True, False], d=1)
        self.assertEqual(actual["qualified_event_count"], 1)
        self.assertEqual(actual["transition_closure"]["qualification"], 1)
        self.assertEqual(actual["transition_closure"]["event_creation"], 1)
        self.assertEqual(actual["transition_closure"]["event_terminal"], 1)

    def test_d2_qualification_and_d3_prequalification_right_censor(self) -> None:
        qualified = self.oracle([True, True, True, True, False], d=2)
        self.assertEqual(len([c for c in qualified["components"] if c["qualified"]]), 1)
        censored = self.oracle([True, True, True, True], d=3)
        self.assertEqual(censored["qualified_event_count"], 0)
        self.assertEqual(
            censored["components"][0]["termination_reason"], "sample_end_censoring"
        )

    def test_g0_natural_exit_and_g1_g2_accepted_bridges(self) -> None:
        raw_g1 = [True, True, True, False, True, True, True, False]
        self.assertEqual(self.oracle(raw_g1, g=0)["qualified_event_count"], 2)
        accepted_g1 = self.oracle(raw_g1, g=1)
        self.assertEqual(accepted_g1["qualified_event_count"], 1)
        self.assertEqual(accepted_g1["bridge_count"], 1)
        raw_g2 = [True, True, True, False, False, True, True, True, False]
        self.assertEqual(self.oracle(raw_g2, g=2)["bridge_count"], 1)

    def test_g_plus_one_finalization_and_quality_break_never_bridge(self) -> None:
        g_plus_one = self.oracle(
            [True, True, True, False, False, True, True, True, False], g=1
        )
        self.assertEqual(g_plus_one["qualified_event_count"], 2)
        quality = self.oracle(
            [True, True, True, None, True, True, True, False],
            g=2,
            qualities=[
                "valid",
                "valid",
                "valid",
                "blocked",
                "valid",
                "valid",
                "valid",
                "valid",
            ],
        )
        self.assertEqual(quality["bridge_count"], 0)
        self.assertEqual(quality["zones"][0]["status"], "FINALIZED_WITH_QUALITY_BREAK")

    def test_unqualified_reentry_is_one_attempt_not_daily_rows(self) -> None:
        actual = self.oracle(
            [True, True, True, True, False, True, True, True, False], d=2, g=1
        )
        self.assertEqual(actual["unqualified_reentry_count"], 1)
        self.assertEqual(actual["transition_closure"]["rejected_reentry_paths"], 1)

    def test_right_censored_open_zone_and_multiple_events(self) -> None:
        open_zone = self.oracle([True, True, True], d=1)
        self.assertEqual(open_zone["zones"][0]["status"], "RIGHT_CENSORED")
        multiple = self.oracle(
            [True, True, True, False, False, False, True, True, True, False],
            d=1,
            g=1,
        )
        self.assertEqual(multiple["qualified_event_count"], 2)

    def test_trailing_quality_break_and_g_plus_one_are_terminal(self) -> None:
        quality = self.oracle(
            [True, True, True, None],
            d=1,
            g=2,
            qualities=["valid", "valid", "valid", "blocked"],
        )
        self.assertEqual(quality["zones"][0]["status"], "FINALIZED_WITH_QUALITY_BREAK")
        gap = self.oracle([True, True, True, False, False], d=1, g=1)
        self.assertEqual(gap["zones"][0]["status"], "FINALIZED")

    def test_expected_row_missing_fails_closed(self) -> None:
        rows = [
            {
                "security_id": "S1",
                "trade_date": "2026-01-01",
                "eligible": True,
                "quality_state": "valid",
                "raw_state": True,
            }
        ]
        with self.assertRaisesRegex(
            R2T03IndependentValidationError, "missing_expected_trading_row"
        ):
            source_timeline_oracle(
                rows,
                expected_dates=["2026-01-01", "2026-01-02"],
                d=1,
                g=0,
            )


class R2T03IndependentComparisonOracleTest(unittest.TestCase):
    def test_each_formal_metric_mutation_has_exact_failure_id(self) -> None:
        expected = {
            "confirmed_event_coverage": 0.25,
            "duration_q95_ratio": 2.0,
            "merge_ratio": 0.5,
            "short_interval_drop_rate": 0.1,
            "open_event_ratio": 0.2,
            "nonzero_years": 3,
            "bridged_day_ratio": 0.05,
            "unqualified_reentry_count": 4,
        }
        for metric, value in expected.items():
            production = dict(expected)
            production[metric] = value + 1
            self.assertEqual(
                compare_oracle_metric_targets(expected, production),
                [f"independent_metric_mismatch:{metric}"],
            )

    def test_oracle_does_not_import_production_scanner_metrics_or_t02_helpers(
        self,
    ) -> None:
        source = validator_module.__loader__.get_source(validator_module.__name__)
        self.assertNotIn("from src.r2.r2_t03_event_zone_scan", source)
        self.assertNotIn("from src.r2.r2_t03_metrics", source)
        self.assertNotIn("from src.r2.r2_t02_protocol_freeze", source)

    def test_oracle_strict_core_and_window_exact_values(self) -> None:
        primary_events = {"p": {("S1", "01"), ("S1", "02")}}
        strict_events = {"s": {("S1", "02")}}
        strict = independent_strict_core_oracle(
            primary_events,
            strict_events,
            {("S1", "01"), ("S1", "02")},
            {("S1", "02")},
        )
        self.assertEqual(strict["strict_core_event_share"], 1.0)
        self.assertEqual(strict["shell_only_confirmed_day_share"], 0.5)
        window = independent_window_oracle(
            {("S1", "01"), ("S1", "02")},
            {("S1", "02"), ("S1", "03")},
            {("S1", "01"), ("S1", "02")},
            {("S1", "02"), ("S1", "03")},
            primary_events,
            {"c": {("S1", "02"), ("S1", "03")}},
        )
        self.assertEqual(window["confirmed_day_jaccard"], 1 / 3)
        self.assertEqual(window["matched_event_count"], 1)


if __name__ == "__main__":
    unittest.main()
