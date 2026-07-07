from __future__ import annotations

import math
import unittest

from src.r0.raw_metric_engine import (
    BLOCKED,
    DIAGNOSTIC_REQUIRED,
    UNKNOWN,
    VALID,
    assert_no_forbidden_raw_metric_outputs,
    calculate_abs_trend_t20,
    calculate_adj_vwap_spread_5_60,
    calculate_er20,
    calculate_log_amount20_base,
    calculate_log_ma_spread_5_60,
    calculate_log_range20,
    calculate_natr14,
    calculate_turnover_shrink20_60,
    check_raw_metric_lineage,
    compute_raw_metrics,
)


def synthetic_rows(count: int = 90) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(count):
        close = 10.0 + index * 0.05 + math.sin(index / 3.0) * 0.02
        rows.append(
            {
                "security_id": "000001.SZ",
                "trading_date": f"2026-01-{index + 1:02d}",
                "adjusted_high": close * 1.01,
                "adjusted_low": close * 0.99,
                "adjusted_close": close,
                "daily_vwap": close,
                "volume_shares": 1000000 + index * 1000,
                "amount": close * (1000000 + index * 1000),
                "volume": 1000000 + index * 1000,
                "raw_low": close * 0.98,
                "raw_high": close * 1.02,
                "amount_unit": "yuan",
                "volume_unit": "shares",
                "amount_volume_unit_status": "pass",
                "daily_vwap_range_status": "pass",
                "adjusted_vwap_policy": "same_adjusted_basis",
                "trading_status": "normal_trading",
                "corporate_action_flag": False,
                "suspension_flag": False,
                "turnover_float": 0.02 if index < count - 20 else 0.01,
                "turnover_field_status": "pass",
                "share_field_status": "pass",
                "provider_turnover_crosscheck_status": "pass",
                "float_share_shares": 100000000,
                "corporate_action_types_in_window": [],
                "share_comparability_corporate_action_in_window": False,
                "common_share_basis_policy": "not_required",
                "volume_comparability_policy": "not_required",
                "amount_yuan": 1000000.0 + index * 1000.0,
                "zero_amount_flag": False,
                "price_limit_status": "none",
            }
        )
    return rows


def constant_close_rows(
    count: int = 90, close: float = 10.0
) -> list[dict[str, object]]:
    rows = synthetic_rows(count)
    for row in rows:
        row["adjusted_close"] = close
        row["adjusted_high"] = close * 1.01
        row["adjusted_low"] = close * 0.99
        row["daily_vwap"] = close
        row["raw_low"] = close * 0.98
        row["raw_high"] = close * 1.02
    return rows


def variable_true_range_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(21):
        true_range = float(index + 1)
        rows.append(
            {
                "security_id": "000001.SZ",
                "trading_date": f"2026-02-{index + 1:02d}",
                "adjusted_high": 100.0 + true_range / 2.0,
                "adjusted_low": 100.0 - true_range / 2.0,
                "adjusted_close": 100.0,
                "trading_status": "normal_trading",
                "corporate_action_flag": False,
                "suspension_flag": False,
            }
        )
    return rows


def manual_wilder_atr14(true_ranges: list[float]) -> float:
    atr = sum(true_ranges[:14]) / 14.0
    for true_range in true_ranges[14:]:
        atr = (atr * 13.0 + true_range) / 14.0
    return atr


def result_for(results, indicator_id: str, trading_date: str = "2026-01-90"):
    for result in results:
        if result.indicator_id == indicator_id and result.trading_date == trading_date:
            return result
    raise AssertionError(f"missing result {indicator_id} {trading_date}")


class R0T04RawMetricEngineTest(unittest.TestCase):
    def test_compute_raw_metrics_output_is_stable_for_disordered_input(self) -> None:
        rows = synthetic_rows()
        shuffled = list(reversed(rows))
        normal = compute_raw_metrics(rows)
        disordered = compute_raw_metrics(shuffled)
        self.assertEqual(
            [item.as_dict() for item in normal], [item.as_dict() for item in disordered]
        )
        last_ids = [
            item.indicator_id for item in normal if item.trading_date == "2026-01-90"
        ]
        self.assertEqual(
            last_ids,
            [
                "P1_NATR14",
                "P2_LogRange20",
                "C1_LogMASpread_5_60",
                "C2_AdjVWAPSpread_5_60",
                "T1_ER20",
                "T2_AbsTrendT20",
                "V1_TurnoverShrink20_60",
                "V2_LogAmount20_base",
            ],
        )

    def test_p_layer_metrics_compute_and_block_bad_inputs(self) -> None:
        rows = synthetic_rows()
        natr = calculate_natr14(rows, 89)
        self.assertEqual(natr.validity_status, VALID)
        self.assertGreater(natr.raw_value, 0)

        missing_previous = synthetic_rows()
        missing_previous[75]["adjusted_close"] = None
        result = calculate_natr14(missing_previous, 89)
        self.assertEqual(result.validity_status, UNKNOWN)
        self.assertIn("missing_required_field", result.reason_codes)

        insufficient = calculate_natr14(synthetic_rows(10), 9)
        self.assertEqual(insufficient.validity_status, UNKNOWN)
        self.assertIn("window_insufficient", insufficient.reason_codes)

        log_range = calculate_log_range20(rows, 89)
        highs = [row["adjusted_high"] for row in rows[-20:]]
        lows = [row["adjusted_low"] for row in rows[-20:]]
        self.assertEqual(log_range.validity_status, VALID)
        self.assertAlmostEqual(log_range.raw_value, math.log(max(highs) / min(lows)))

        anomaly = synthetic_rows()
        anomaly[89]["adjusted_low"] = anomaly[89]["adjusted_high"] * 2
        result = calculate_log_range20(anomaly, 89)
        self.assertEqual(result.validity_status, UNKNOWN)
        self.assertIn("high_low_anomaly", result.reason_codes)

    def test_natr14_uses_wilder_recursion_not_simple_moving_average(self) -> None:
        rows = variable_true_range_rows()
        result = calculate_natr14(rows, 20)
        true_ranges = [float(value) for value in range(2, 22)]
        expected_wilder = manual_wilder_atr14(true_ranges) / 100.0
        simple_moving_average = (sum(true_ranges[-14:]) / 14.0) / 100.0

        self.assertEqual(result.validity_status, VALID)
        self.assertAlmostEqual(result.raw_value, expected_wilder)
        self.assertNotAlmostEqual(result.raw_value, simple_moving_average)

    def test_c_layer_metrics_compute_and_propagate_c2_readiness(self) -> None:
        rows = synthetic_rows()
        ma = calculate_log_ma_spread_5_60(rows, 89)
        self.assertEqual(ma.validity_status, VALID)
        self.assertGreater(ma.raw_value, 0)
        self.assertIn(
            "window_insufficient", calculate_log_ma_spread_5_60(rows, 10).reason_codes
        )

        vwap = calculate_adj_vwap_spread_5_60(rows, 89)
        self.assertEqual(vwap.validity_status, VALID)
        self.assertGreaterEqual(vwap.raw_value, 0)

        unit_fail = synthetic_rows()
        unit_fail[89]["amount_volume_unit_status"] = "fail"
        result = calculate_adj_vwap_spread_5_60(unit_fail, 89)
        self.assertEqual(result.validity_status, BLOCKED)
        self.assertIn("amount_volume_unit_status_fail", result.reason_codes)

        zero_volume = synthetic_rows()
        zero_volume[89]["volume_shares"] = 0
        zero_volume[89]["volume"] = 0
        result = calculate_adj_vwap_spread_5_60(zero_volume, 89)
        self.assertEqual(result.validity_status, DIAGNOSTIC_REQUIRED)
        self.assertIn("zero_volume_in_window", result.reason_codes)

        corporate_action = synthetic_rows()
        corporate_action[89]["corporate_action_flag"] = True
        corporate_action[89].pop("adjusted_vwap_policy")
        result = calculate_adj_vwap_spread_5_60(corporate_action, 89)
        self.assertEqual(result.validity_status, UNKNOWN)
        self.assertIn("missing_required_field", result.reason_codes)
        self.assertIn("adjusted_vwap_policy_missing", result.reason_codes)
        self.assertIn(
            "corporate_action_window_without_common_basis", result.reason_codes
        )

    def test_window_level_readiness_is_not_masked_by_last_ready_row(self) -> None:
        rows = synthetic_rows()
        rows[50]["daily_vwap_range_status"] = "fail"
        self.assertEqual(rows[89]["daily_vwap_range_status"], "pass")
        result = calculate_adj_vwap_spread_5_60(rows, 89)
        self.assertEqual(result.validity_status, BLOCKED)
        self.assertIn("daily_vwap_range_fail", result.reason_codes)

        rows = synthetic_rows()
        rows[50]["amount_volume_unit_status"] = "fail"
        self.assertEqual(rows[89]["amount_volume_unit_status"], "pass")
        result = calculate_adj_vwap_spread_5_60(rows, 89)
        self.assertEqual(result.validity_status, BLOCKED)
        self.assertIn("amount_volume_unit_status_fail", result.reason_codes)

        rows = synthetic_rows()
        rows[50]["provider_turnover_crosscheck_status"] = "fail"
        self.assertEqual(rows[89]["provider_turnover_crosscheck_status"], "pass")
        result = calculate_turnover_shrink20_60(rows, 89)
        self.assertEqual(result.validity_status, BLOCKED)
        self.assertIn("provider_turnover_crosscheck_fail", result.reason_codes)

        rows = synthetic_rows()
        rows[50]["share_field_status"] = "invalid"
        self.assertEqual(rows[89]["share_field_status"], "pass")
        result = calculate_turnover_shrink20_60(rows, 89)
        self.assertEqual(result.validity_status, UNKNOWN)
        self.assertIn("share_field_status_invalid", result.reason_codes)

        rows = synthetic_rows()
        rows[50]["turnover_field_status"] = "invalid"
        self.assertEqual(rows[89]["turnover_field_status"], "pass")
        result = calculate_turnover_shrink20_60(rows, 89)
        self.assertEqual(result.validity_status, UNKNOWN)
        self.assertIn("turnover_field_status_invalid", result.reason_codes)

        rows = synthetic_rows()
        rows[75]["amount_volume_unit_status"] = "fail"
        self.assertEqual(rows[89]["amount_volume_unit_status"], "pass")
        result = calculate_log_amount20_base(rows, 89)
        self.assertEqual(result.validity_status, BLOCKED)
        self.assertIn("amount_volume_unit_status_fail", result.reason_codes)

        rows = synthetic_rows()
        rows[75]["zero_amount_flag"] = True
        self.assertFalse(rows[89]["zero_amount_flag"])
        result = calculate_log_amount20_base(rows, 89)
        self.assertEqual(result.validity_status, DIAGNOSTIC_REQUIRED)
        self.assertIn("zero_amount_in_window", result.reason_codes)

    def test_t_layer_metrics_cover_flat_and_degenerate_paths(self) -> None:
        rows = synthetic_rows()
        er = calculate_er20(rows, 89)
        self.assertEqual(er.validity_status, VALID)
        self.assertGreaterEqual(er.raw_value, 0)

        flat = constant_close_rows()
        er_flat = calculate_er20(flat, 89)
        self.assertEqual(er_flat.validity_status, VALID)
        self.assertEqual(er_flat.raw_value, 0.0)
        self.assertIn("denominator_zero_flat_path", er_flat.reason_codes)

        trend = calculate_abs_trend_t20(rows, 89)
        self.assertEqual(trend.validity_status, VALID)
        self.assertGreater(trend.raw_value, 0)

        flat_trend = calculate_abs_trend_t20(flat, 89)
        self.assertEqual(flat_trend.validity_status, VALID)
        self.assertEqual(flat_trend.raw_value, 0.0)
        self.assertIn("flat_path_residual_se_zero", flat_trend.reason_codes)

        perfect_nonzero_slope = synthetic_rows()
        for index, row in enumerate(perfect_nonzero_slope):
            close = math.exp(0.01 * index)
            row["adjusted_close"] = close
            row["adjusted_high"] = close * 1.01
            row["adjusted_low"] = close * 0.99
        result = calculate_abs_trend_t20(perfect_nonzero_slope, 89)
        self.assertEqual(result.validity_status, DIAGNOSTIC_REQUIRED)
        self.assertIsNone(result.raw_value)
        self.assertIn("residual_se_zero_slope_nonzero", result.reason_codes)

    def test_v_layer_turnover_shrink_uses_turnover_not_old_volume_shrink(self) -> None:
        rows = synthetic_rows()
        result = calculate_turnover_shrink20_60(rows, 89)
        self.assertEqual(result.validity_status, VALID)
        self.assertAlmostEqual(result.raw_value, 0.5)
        self.assertEqual(result.indicator_id, "V1_TurnoverShrink20_60")
        self.assertIn("turnover_float", result.source_field_names)
        self.assertNotIn("volume_unit", result.source_field_names)

        insufficient = calculate_turnover_shrink20_60(synthetic_rows(79), 78)
        self.assertEqual(insufficient.validity_status, UNKNOWN)
        self.assertIn("window_insufficient", insufficient.reason_codes)

        missing_turnover = synthetic_rows()
        missing_turnover[89].pop("turnover_float")
        result = calculate_turnover_shrink20_60(missing_turnover, 89)
        self.assertEqual(result.validity_status, UNKNOWN)
        self.assertIn("missing_required_field", result.reason_codes)

        provider_fail = synthetic_rows()
        provider_fail[89]["provider_turnover_crosscheck_status"] = "fail"
        result = calculate_turnover_shrink20_60(provider_fail, 89)
        self.assertEqual(result.validity_status, BLOCKED)
        self.assertIn("provider_turnover_crosscheck_fail", result.reason_codes)

        comparability_missing = synthetic_rows()
        comparability_missing[89].pop("common_share_basis_policy")
        result = calculate_turnover_shrink20_60(comparability_missing, 89)
        self.assertNotEqual(result.validity_status, VALID)
        self.assertIn("missing_required_field", result.reason_codes)

        suspension = synthetic_rows()
        suspension[89]["suspension_flag"] = True
        result = calculate_turnover_shrink20_60(suspension, 89)
        self.assertEqual(result.validity_status, DIAGNOSTIC_REQUIRED)
        self.assertIn("suspension_in_window", result.reason_codes)

    def test_v2_log_amount_base_does_not_generate_amount_level_percentile(self) -> None:
        rows = synthetic_rows()
        result = calculate_log_amount20_base(rows, 89)
        self.assertEqual(result.validity_status, VALID)
        self.assertEqual(result.indicator_id, "V2_LogAmount20_base")
        self.assertEqual(result.raw_metric_name, "LogAmount20")
        expected = math.log(sum(row["amount_yuan"] for row in rows[-20:]) / 20)
        self.assertAlmostEqual(result.raw_value, expected)

        unit_fail = synthetic_rows()
        unit_fail[89]["amount_volume_unit_status"] = "fail"
        result = calculate_log_amount20_base(unit_fail, 89)
        self.assertEqual(result.validity_status, BLOCKED)
        self.assertIn("amount_volume_unit_status_fail", result.reason_codes)

        zero_amount = synthetic_rows()
        zero_amount[89]["zero_amount_flag"] = True
        result = calculate_log_amount20_base(zero_amount, 89)
        self.assertEqual(result.validity_status, DIAGNOSTIC_REQUIRED)
        self.assertIn("zero_amount_in_window", result.reason_codes)

        missing_flag = synthetic_rows()
        missing_flag[89].pop("zero_amount_flag")
        result = calculate_log_amount20_base(missing_flag, 89)
        self.assertEqual(result.validity_status, UNKNOWN)
        self.assertIn("missing_required_field", result.reason_codes)

    def test_forbidden_output_lineage_and_unknown_guards(self) -> None:
        forbidden = assert_no_forbidden_raw_metric_outputs(
            {"pcvt_percentiles": {"P1_NATR14": 0.1}, "pcvt_states": ["S_PCT"]}
        )
        self.assertEqual(forbidden.validity_status, BLOCKED)
        self.assertIn("forbidden_output_field", forbidden.reason_codes)

        allowed = assert_no_forbidden_raw_metric_outputs(
            {"raw_metrics": [{"indicator_id": "P1_NATR14", "raw_value": 0.1}]}
        )
        self.assertEqual(allowed.validity_status, VALID)

        lineage = check_raw_metric_lineage(
            ["d3_t11_volume_amount_share_turnover_candidate"]
        )
        self.assertEqual(lineage.validity_status, VALID)
        synthetic_lineage = check_raw_metric_lineage(["synthetic_in_memory_rows"])
        self.assertEqual(synthetic_lineage.validity_status, VALID)
        direct = check_raw_metric_lineage(["d2.adjusted_market_prices"])
        self.assertEqual(direct.validity_status, BLOCKED)
        self.assertIn("direct_d1_d2_bypass_detected", direct.reason_codes)

        first_day = result_for(
            compute_raw_metrics(synthetic_rows()), "P1_NATR14", "2026-01-01"
        )
        self.assertEqual(first_day.validity_status, UNKNOWN)
        self.assertIsNone(first_day.raw_value)
        self.assertNotEqual(first_day.raw_value, 0)
        self.assertIn("window_insufficient", first_day.reason_codes)


if __name__ == "__main__":
    unittest.main()
