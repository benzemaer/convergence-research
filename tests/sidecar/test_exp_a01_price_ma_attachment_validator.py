from __future__ import annotations

import copy
import math
import unittest
from datetime import date, timedelta
from pathlib import Path

from src.sidecar.exp_a01_price_ma_attachment import (
    A1_ID,
    A2_ID,
    A2B_ID,
    BOUNDARY_ULPS,
    INDEX_SOURCE_CONTRACT,
    compute_a01_metrics,
)
from src.sidecar.exp_a01_price_ma_attachment_validator import (
    RAW_TABLE_COLUMNS,
    _independent_gap,
    _independent_outside,
    _independent_row_reasons,
    _sampled_raw_row_compare,
    load_json,
    validate_metric_rows,
    validate_static_config,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/sidecar/exp_a01_price_ma_attachment_candidates.v1.json"


def dense_rows(count: int = 79) -> list[dict[str, object]]:
    return [
        {
            "security_id": "SEC001",
            "trading_date": (date(2020, 1, 1) + timedelta(days=index)).isoformat(),
            "observation_sequence": index,
            "expected_observation_status": "present",
            "adjusted_open": 100.0,
            "adjusted_close": 100.0,
            "trading_status": "normal_trading",
            "daily_status": "resolved",
            "effective_adj_factor": 1.0,
            "adjustment_factor_status": "resolved",
            "is_listing_pause": False,
            "row_provenance": f"d3-t07:SEC001:{index}",
            "source_contract": INDEX_SOURCE_CONTRACT,
            "source_ref": f"calendar-v1:SEC001:{index}",
        }
        for index in range(count)
    ]


class ExpA01ValidatorTest(unittest.TestCase):
    def test_independent_a2_and_a2b_boundary_semantics_match(self) -> None:
        body = math.log(2.0)
        history = [
            {
                "adjusted_open": 2.0,
                "adjusted_close": 2.0,
            }
        ]

        def shift(value: float, direction: float, steps: int) -> float:
            for _ in range(steps):
                value = math.nextafter(value, direction)
            return value

        for steps in (0, 1, 4, 8):
            with self.subTest(side="upper", steps=steps):
                cloud_high = shift(body, -math.inf, steps)
                self.assertFalse(_independent_outside(body, body - 1.0, cloud_high))
                self.assertEqual(
                    _independent_gap(history, 0, body, body - 1.0, cloud_high),
                    0.0,
                )
            with self.subTest(side="lower", steps=steps):
                cloud_low = shift(body, math.inf, steps)
                self.assertFalse(_independent_outside(body, cloud_low, body + 1.0))
                self.assertEqual(
                    _independent_gap(history, 0, body, cloud_low, body + 1.0),
                    0.0,
                )

        for side, cloud_low, cloud_high in (
            ("above", body - 1.0, shift(body, -math.inf, BOUNDARY_ULPS * 4)),
            ("below", shift(body, math.inf, BOUNDARY_ULPS * 4), body + 1.0),
        ):
            with self.subTest(side=side):
                self.assertTrue(_independent_outside(body, cloud_low, cloud_high))
                self.assertGreater(
                    _independent_gap(history, 0, body, cloud_low, cloud_high),
                    0.0,
                )

    def test_static_config_is_frozen_to_unique_d3_t07_route(self) -> None:
        config = load_json(CONFIG_PATH)
        self.assertEqual(validate_static_config(config), [])
        self.assertNotIn(
            "authoritative_contract", config["input_contract"]["artifacts"]
        )
        self.assertEqual(
            set(config["input_contract"]["artifacts"]),
            {
                "d3_t07_candidate_daily_observation",
                "d3_t07_handoff_report",
                "d3_t07_quality_report",
                "expected_price_observation_index",
            },
        )

    def test_valid_metric_rows_pass_independent_validation(self) -> None:
        metrics = compute_a01_metrics(dense_rows())
        errors = validate_metric_rows(metrics)
        self.assertEqual(errors, [])
        self.assertEqual(
            [row["indicator_id"] for row in metrics[-3:]],
            [
                "A1_LogBodyCenterToMACloudCenter_5_60",
                "A2_BodyCenterOutsideMACloudRate20_5_60",
                "A2b_BodyToMACloudGapMean20_5_60",
            ],
        )

    def test_independent_recomputation_accepts_d3_resolved_open_status(self) -> None:
        row = dense_rows()[40]
        row["trading_status"] = "listed_open_resolved_daily"
        self.assertNotIn("invalid_trading_status", _independent_row_reasons(row))

    def test_validator_rejects_forbidden_and_invalid_mutations(self) -> None:
        metrics = compute_a01_metrics(dense_rows())
        valid_row = next(
            row
            for row in metrics
            if row["indicator_id"] == A1_ID and row["validity_status"] == "valid"
        )

        forbidden = copy.deepcopy(valid_row)
        forbidden["future_return"] = 0.1
        errors = validate_metric_rows([forbidden])
        self.assertTrue(any("unexpected_fields" in error for error in errors))
        self.assertTrue(any("forbidden_fields" in error for error in errors))

        invalid_numeric = copy.deepcopy(valid_row)
        invalid_numeric["validity_status"] = "blocked"
        invalid_numeric["raw_value"] = 0.1
        errors = validate_metric_rows([invalid_numeric])
        self.assertIn("row_0_invalid_raw_value_present", errors)

        invalid_count = copy.deepcopy(valid_row)
        invalid_count["actual_valid_observation_count"] = 59
        self.assertIn(
            "row_0_valid_count_not_full_window",
            validate_metric_rows([invalid_count]),
        )

    def test_config_mutations_are_rejected(self) -> None:
        config = load_json(CONFIG_PATH)
        config["candidate_layer"] = "C"
        self.assertIn("config_candidate_layer_mismatch", validate_static_config(config))

        config = load_json(CONFIG_PATH)
        config["formal_run_allowed"] = True
        self.assertIn(
            "config_formal_run_allowed_mismatch", validate_static_config(config)
        )

        config = load_json(CONFIG_PATH)
        config["price_basis"]["raw_ohlc_forbidden"] = False
        self.assertIn("config_raw_ohlc_not_forbidden", validate_static_config(config))

        config = load_json(CONFIG_PATH)
        config["input_contract"]["artifacts"]["d3_t07_candidate_daily_observation"][
            "required_columns"
        ].append("adjustment_method")
        self.assertIn(
            "config_input_required_columns_mismatch", validate_static_config(config)
        )

    def test_sampled_numeric_tolerances_and_a2_integer_numerator(self) -> None:
        base = {
            "run_id": "EXP-A01-20260716T000000Z",
            "security_id": "SEC001",
            "trading_date": "2020-03-20",
            "observation_sequence": 79,
            "expected_observation_status": "present",
            "raw_metric_name": "metric",
            "validity_status": "valid",
            "reason_codes_json": '["valid_no_blocker"]',
            "input_window_start": "2020-01-02",
            "input_window_end": "2020-03-20",
            "required_observation_count": 79,
            "actual_valid_observation_count": 79,
            "metric_engine_version": "exp_a01_price_ma_attachment.v1",
            "source_ref": "ref",
        }

        def row(indicator: str, value: float) -> tuple[object, ...]:
            return tuple(
                base[field]
                if field != "indicator_id" and field != "raw_value"
                else indicator
                if field == "indicator_id"
                else value
                for field in RAW_TABLE_COLUMNS
            )

        for indicator in (A1_ID, A2B_ID):
            expected = {**base, "indicator_id": indicator, "raw_value": 1.0}
            self.assertEqual(
                _sampled_raw_row_compare(expected, row(indicator, 1.0 + 5e-11))[0],
                [],
            )
            self.assertIn(
                "raw_value",
                _sampled_raw_row_compare(expected, row(indicator, 1.0 + 5e-9))[0],
            )

        expected = {**base, "indicator_id": A2_ID, "raw_value": 0.15}
        self.assertEqual(
            _sampled_raw_row_compare(expected, row(A2_ID, 0.1500000000005))[0], []
        )
        self.assertIn(
            "raw_value",
            _sampled_raw_row_compare(expected, row(A2_ID, 0.20))[0],
        )


if __name__ == "__main__":
    unittest.main()
