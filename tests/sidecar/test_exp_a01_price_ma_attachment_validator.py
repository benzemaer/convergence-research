from __future__ import annotations

import copy
import unittest
from datetime import date, timedelta
from pathlib import Path

from src.sidecar.exp_a01_price_ma_attachment import A1_ID, compute_a01_metrics
from src.sidecar.exp_a01_price_ma_attachment_validator import (
    load_json,
    validate_metric_rows,
    validate_static_config,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/sidecar/exp_a01_price_ma_attachment_candidates.v1.json"


class ExpA01ValidatorTest(unittest.TestCase):
    def test_static_config_is_frozen_to_a01_boundary(self) -> None:
        config = load_json(CONFIG_PATH)
        self.assertEqual(validate_static_config(config), [])

    def test_valid_metric_rows_pass_independent_validation(self) -> None:
        rows = [
            {
                "security_id": "SEC001",
                "trading_date": (
                    date(2020, 1, 1) + timedelta(days=index - 1)
                ).isoformat(),
                "adjusted_open": 100.0,
                "adjusted_close": 100.0,
                "trading_status": "normal_trading",
            }
            for index in range(1, 61)
        ]
        metrics = compute_a01_metrics(rows)
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

    def test_validator_rejects_forbidden_and_invalid_mutations(self) -> None:
        rows = [
            {
                "security_id": "SEC001",
                "trading_date": (
                    date(2020, 1, 1) + timedelta(days=index - 1)
                ).isoformat(),
                "adjusted_open": 100.0,
                "adjusted_close": 100.0,
                "trading_status": "normal_trading",
            }
            for index in range(1, 61)
        ]
        metrics = compute_a01_metrics(rows)
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


if __name__ == "__main__":
    unittest.main()
