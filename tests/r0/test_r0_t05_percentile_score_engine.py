from __future__ import annotations

import unittest

from src.r0.percentile_score_engine import (
    ACTIVE_INDICATORS,
    BLOCKED,
    DIAGNOSTIC_REQUIRED,
    UNKNOWN,
    VALID,
    assert_no_forbidden_score_outputs,
    check_score_lineage,
    compute_common_eligible_samples,
    compute_dimension_scores,
    compute_indicator_scores,
)

INPUT_IDS = (
    "P1_NATR14",
    "P2_LogRange20",
    "C1_LogMASpread_5_60",
    "C2_AdjVWAPSpread_5_60",
    "T1_ER20",
    "T2_AbsTrendT20",
    "V1_TurnoverShrink20_60",
    "V2_LogAmount20_base",
)


def raw_row(
    day: int,
    indicator_id: str = "P1_NATR14",
    value: float = 1.0,
    security_id: str = "000001.SZ",
    status: str = VALID,
    reasons: tuple[str, ...] = ("valid_no_blocker",),
) -> dict[str, object]:
    return {
        "security_id": security_id,
        "trading_date": f"2026-{day:04d}",
        "indicator_id": indicator_id,
        "raw_metric_name": "LogAmount20"
        if indicator_id == "V2_LogAmount20_base"
        else indicator_id,
        "raw_value": value,
        "validity_status": status,
        "reason_codes": list(reasons),
        "required_observation_count": 20,
        "actual_valid_observation_count": 20,
        "source_field_names": ["synthetic"],
        "metric_engine_version": "r0_t04_raw_metric_engine.v1",
    }


def result_for(results, indicator_id: str, day: int, window: int):
    trading_date = f"2026-{day:04d}"
    for result in results:
        if (
            result.indicator_id == indicator_id
            and result.trading_date == trading_date
            and result.percentile_window_W == window
        ):
            return result
    raise AssertionError(f"missing result {indicator_id} {trading_date} W={window}")


def rows_for_indicator(
    indicator_id: str,
    count: int,
    security_id: str = "000001.SZ",
    start_value: float = 0.0,
) -> list[dict[str, object]]:
    return [
        raw_row(
            day=day,
            indicator_id=indicator_id,
            value=start_value + float(day),
            security_id=security_id,
        )
        for day in range(1, count + 1)
    ]


def rows_for_all_indicators(count: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for offset, indicator_id in enumerate(INPUT_IDS):
        rows.extend(
            raw_row(
                day=day,
                indicator_id=indicator_id,
                value=float(day + offset),
            )
            for day in range(1, count + 1)
        )
    return rows


class R0T05PercentileScoreEngineTest(unittest.TestCase):
    def test_strict_past_current_value_excluded_and_history_count_rules(self) -> None:
        rows = rows_for_indicator("P1_NATR14", 121)
        scores = compute_indicator_scores(rows, percentile_windows=(120,))

        day_120 = result_for(scores, "P1_NATR14", 120, 120)
        self.assertFalse(day_120.eligible)
        self.assertIsNone(day_120.percentile)
        self.assertIn("insufficient_strict_past_history", day_120.reason_codes)

        day_121 = result_for(scores, "P1_NATR14", 121, 120)
        self.assertTrue(day_121.eligible)
        self.assertEqual(day_121.reference_observation_count, 120)
        self.assertFalse(day_121.current_value_in_reference_set)
        self.assertEqual(day_121.reference_window_start, "2026-0001")
        self.assertEqual(day_121.reference_window_end, "2026-0120")
        self.assertEqual(day_121.percentile, 1.0)
        self.assertEqual(day_121.score, 0.0)

    def test_input_disorder_same_security_indicator_only_and_stable_output(
        self,
    ) -> None:
        rows = rows_for_indicator("P1_NATR14", 121)
        rows.extend(
            rows_for_indicator(
                "P1_NATR14", 121, security_id="000002.SZ", start_value=1000
            )
        )
        rows.extend(rows_for_indicator("P2_LogRange20", 121, start_value=1000))

        normal = compute_indicator_scores(rows, percentile_windows=(120,))
        shuffled = compute_indicator_scores(
            list(reversed(rows)), percentile_windows=(120,)
        )
        self.assertEqual(
            [item.as_dict() for item in normal], [item.as_dict() for item in shuffled]
        )

        target = result_for(normal, "P1_NATR14", 121, 120)
        self.assertEqual(target.percentile, 1.0)

    def test_midrank_ties_are_deterministic(self) -> None:
        rows = [raw_row(day=day, value=1.0) for day in range(1, 61)]
        rows.extend(raw_row(day=day, value=2.0) for day in range(61, 121))
        rows.append(raw_row(day=121, value=2.0))

        first = result_for(
            compute_indicator_scores(rows, percentile_windows=(120,)),
            "P1_NATR14",
            121,
            120,
        )
        second = result_for(
            compute_indicator_scores(rows, percentile_windows=(120,)),
            "P1_NATR14",
            121,
            120,
        )
        self.assertEqual(first.tie_method, "midrank")
        self.assertEqual(first.percentile, (60 + 0.5 * 60) / 120)
        self.assertEqual(first.as_dict(), second.as_dict())

    def test_score_boundaries_for_percentile_zero_half_and_one(self) -> None:
        low_current = [raw_row(day=day, value=2.0) for day in range(1, 121)]
        low_current.append(raw_row(day=121, value=1.0))
        low = result_for(
            compute_indicator_scores(low_current, percentile_windows=(120,)),
            "P1_NATR14",
            121,
            120,
        )
        self.assertEqual(low.percentile, 0.0)
        self.assertEqual(low.score, 1.0)

        equal_current = [raw_row(day=day, value=2.0) for day in range(1, 121)]
        equal_current.append(raw_row(day=121, value=2.0))
        equal = result_for(
            compute_indicator_scores(equal_current, percentile_windows=(120,)),
            "P1_NATR14",
            121,
            120,
        )
        self.assertEqual(equal.percentile, 0.5)
        self.assertEqual(equal.score, 0.5)

        high_current = [raw_row(day=day, value=2.0) for day in range(1, 121)]
        high_current.append(raw_row(day=121, value=3.0))
        high = result_for(
            compute_indicator_scores(high_current, percentile_windows=(120,)),
            "P1_NATR14",
            121,
            120,
        )
        self.assertEqual(high.percentile, 1.0)
        self.assertEqual(high.score, 0.0)

    def test_raw_metric_non_valid_propagates_upstream_reason(self) -> None:
        rows = rows_for_indicator("P1_NATR14", 121)
        rows[-1] = raw_row(
            day=121,
            status=DIAGNOSTIC_REQUIRED,
            reasons=("suspension_in_window",),
            value=121.0,
        )
        target = result_for(
            compute_indicator_scores(rows, percentile_windows=(120,)),
            "P1_NATR14",
            121,
            120,
        )
        self.assertFalse(target.eligible)
        self.assertIsNone(target.percentile)
        self.assertIsNone(target.score)
        self.assertEqual(target.validity_status, DIAGNOSTIC_REQUIRED)
        self.assertIn("raw_metric_not_valid", target.reason_codes)
        self.assertIn("suspension_in_window", target.reason_codes)

    def test_v2_amount_level_pct_is_generated_once_from_log_amount_base(self) -> None:
        rows = rows_for_indicator("V2_LogAmount20_base", 121)
        target = result_for(
            compute_indicator_scores(rows, percentile_windows=(120,)),
            "V2_AmountLevel20Pct",
            121,
            120,
        )
        self.assertEqual(target.raw_metric_name, "AmountLevel20Pct")
        self.assertEqual(target.percentile, 1.0)
        self.assertEqual(target.score, 0.0)

        repeated = rows + [
            raw_row(day=122, indicator_id="V2_AmountLevel20Pct", value=0.2)
        ]
        blocked = result_for(
            compute_indicator_scores(repeated, percentile_windows=(120,)),
            "V2_AmountLevel20Pct",
            122,
            120,
        )
        self.assertEqual(blocked.validity_status, BLOCKED)
        self.assertIn(
            "amount_level_repeated_percentile_forbidden", blocked.reason_codes
        )

    def test_dimension_scores_require_both_components_and_do_not_emit_state(
        self,
    ) -> None:
        rows = rows_for_all_indicators(121)
        indicator_scores = compute_indicator_scores(rows, percentile_windows=(120,))
        dimensions = compute_dimension_scores(indicator_scores)
        p_result = next(
            item
            for item in dimensions
            if item.dimension == "P"
            and item.trading_date == "2026-0121"
            and item.percentile_window_W == 120
        )
        self.assertTrue(p_result.eligible_dimension)
        self.assertIsNotNone(p_result.score_dimension)
        self.assertIsNotNone(p_result.score_dimension_min)
        self.assertNotIn("state_active", p_result.as_dict())

        rows = rows_for_all_indicators(121)
        for index, row in enumerate(rows):
            if (
                row["indicator_id"] == "P1_NATR14"
                and row["trading_date"] == "2026-0121"
            ):
                rows[index] = raw_row(
                    day=121,
                    indicator_id="P1_NATR14",
                    status=UNKNOWN,
                    reasons=("window_insufficient",),
                    value=121.0,
                )
                break
        else:
            self.fail("missing P1_NATR14 day 121 synthetic row")
        dimensions = compute_dimension_scores(
            compute_indicator_scores(rows, percentile_windows=(120,))
        )
        p_result = next(
            item
            for item in dimensions
            if item.dimension == "P"
            and item.trading_date == "2026-0121"
            and item.percentile_window_W == 120
        )
        self.assertFalse(p_result.eligible_dimension)
        self.assertIsNone(p_result.score_dimension)
        self.assertIsNone(p_result.score_dimension_min)
        self.assertIn("raw_metric_not_valid", p_result.reason_codes)

    def test_common_eligible_sample_requires_all_windows_and_all_indicators(
        self,
    ) -> None:
        full_scores = compute_indicator_scores(rows_for_all_indicators(501))
        common = next(
            item
            for item in compute_common_eligible_samples(full_scores)
            if item.trading_date == "2026-0501"
        )
        self.assertTrue(common.common_eligible_sample)
        self.assertEqual(common.common_eligible_windows, (120, 250, 500))

        short_scores = compute_indicator_scores(rows_for_all_indicators(251))
        common = next(
            item
            for item in compute_common_eligible_samples(short_scores)
            if item.trading_date == "2026-0251"
        )
        self.assertFalse(common.common_eligible_sample)
        self.assertEqual(common.common_eligible_windows, (120, 250))

        rows = rows_for_all_indicators(501)
        rows[-1] = raw_row(
            day=501,
            indicator_id="V2_LogAmount20_base",
            status=BLOCKED,
            reasons=("amount_volume_unit_status_fail",),
            value=501.0,
        )
        common = next(
            item
            for item in compute_common_eligible_samples(compute_indicator_scores(rows))
            if item.trading_date == "2026-0501"
        )
        self.assertFalse(common.common_eligible_sample)

    def test_forbidden_outputs_and_lineage_guards(self) -> None:
        forbidden = assert_no_forbidden_score_outputs(
            {"pcvt_state": "S_PCT", "future_return": 0.2, "portfolio": []}
        )
        self.assertEqual(forbidden.validity_status, BLOCKED)
        self.assertIn("forbidden_output_field", forbidden.reason_codes)

        allowed = assert_no_forbidden_score_outputs(
            {"percentile": 0.2, "score": 0.8, "dimension": "P"}
        )
        self.assertEqual(allowed.validity_status, VALID)

        lineage = check_score_lineage(["synthetic_in_memory_raw_metrics"])
        self.assertEqual(lineage.validity_status, VALID)
        direct = check_score_lineage(["data/raw/vendor.csv"])
        self.assertEqual(direct.validity_status, BLOCKED)
        self.assertIn("direct_real_data_source_forbidden", direct.reason_codes)

    def test_w_120_250_500_are_all_emitted(self) -> None:
        scores = compute_indicator_scores(rows_for_indicator("P1_NATR14", 501))
        windows = {
            result.percentile_window_W
            for result in scores
            if result.trading_date == "2026-0501"
        }
        self.assertEqual(windows, {120, 250, 500})

    def test_active_indicator_constant_matches_contract_count(self) -> None:
        self.assertEqual(len(ACTIVE_INDICATORS), 8)
        self.assertIn("V2_AmountLevel20Pct", ACTIVE_INDICATORS)
        self.assertNotIn("V2_LogAmount20_base", ACTIVE_INDICATORS)


if __name__ == "__main__":
    unittest.main()
