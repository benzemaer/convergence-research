from __future__ import annotations

import copy
import unittest
from datetime import date, timedelta
from pathlib import Path

from src.sidecar.exp_a01_price_ma_attachment import (
    A1_ID,
    INDEX_SOURCE_CONTRACT,
    compute_a01_metrics,
)
from src.sidecar.exp_a01_price_ma_attachment_validator import (
    _independent_row_reasons,
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


if __name__ == "__main__":
    unittest.main()
