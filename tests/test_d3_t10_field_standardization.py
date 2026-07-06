from __future__ import annotations

import unittest

from scripts.d3_t10_field_standardization import (
    combine_standardized_fields,
    forbidden_output_names,
    normalize_daily_basic_fields,
    normalize_daily_fields,
    provider_turnover_crosscheck,
)


class D3T10FieldStandardizationTest(unittest.TestCase):
    def test_daily_volume_amount_units_and_vwap(self) -> None:
        result = normalize_daily_fields({"vol": 100, "amount": 100})
        self.assertEqual(result["volume_unit"], "hand")
        self.assertEqual(result["volume_shares"], 10000)
        self.assertEqual(result["amount_unit"], "thousand_yuan")
        self.assertEqual(result["amount_yuan"], 100000)
        self.assertEqual(result["daily_vwap"], 10)

    def test_daily_basic_share_units(self) -> None:
        result = normalize_daily_basic_fields(
            {"total_share": 200, "float_share": 100, "free_share": 50}
        )
        self.assertEqual(result["total_share_unit"], "ten_thousand_shares")
        self.assertEqual(result["total_share_shares"], 2000000)
        self.assertEqual(result["float_share_shares"], 1000000)
        self.assertEqual(result["free_share_shares"], 500000)

    def test_turnover_float_free_and_provider_crosscheck(self) -> None:
        result = combine_standardized_fields(
            {"vol": 100, "amount": 100, "low": 9, "high": 11},
            {
                "total_share": 200,
                "float_share": 100,
                "free_share": 50,
                "turnover_rate": 1,
                "turnover_rate_f": 2,
            },
        )
        self.assertEqual(result["turnover_float"], 0.01)
        self.assertEqual(result["turnover_free"], 0.02)
        self.assertEqual(result["daily_vwap_range_status"], "valid")
        self.assertEqual(provider_turnover_crosscheck(result).status, "valid")

    def test_provider_turnover_crosscheck_detects_mismatch(self) -> None:
        result = combine_standardized_fields(
            {"vol": 100, "amount": 100, "low": 9, "high": 11},
            {
                "total_share": 200,
                "float_share": 100,
                "free_share": 50,
                "turnover_rate": 5,
                "turnover_rate_f": 2,
            },
        )
        check = provider_turnover_crosscheck(result)
        self.assertEqual(check.status, "fail")
        self.assertIn("turnover_rate_mismatch", check.reasons)

    def test_invalid_share_hierarchy_fails_share_status(self) -> None:
        result = combine_standardized_fields(
            {"vol": 100, "amount": 100, "low": 9, "high": 11},
            {
                "total_share": 100,
                "float_share": 200,
                "free_share": 300,
                "turnover_rate": 0.5,
                "turnover_rate_f": 0.333333,
            },
        )
        self.assertEqual(result["share_field_status"], "fail")

    def test_zero_volume_is_flag_not_low_participation(self) -> None:
        result = combine_standardized_fields(
            {"vol": 0, "amount": 0, "low": 9, "high": 11},
            {
                "total_share": 200,
                "float_share": 100,
                "free_share": 50,
                "turnover_rate": 0,
                "turnover_rate_f": 0,
            },
        )
        self.assertTrue(result["zero_volume_flag"])
        self.assertIsNone(result["daily_vwap"])
        self.assertEqual(
            result["daily_vwap_range_status"],
            "not_applicable_zero_or_missing_volume",
        )

    def test_forbidden_outputs_cover_research_and_formal_artifacts(self) -> None:
        forbidden = forbidden_output_names()
        self.assertTrue(
            {
                "pcvt_values",
                "pcvt_scores",
                "pcvt_states",
                "future_labels",
                "future_returns",
                "backtest",
                "portfolio",
                "formal_data_version",
            }.issubset(forbidden)
        )


if __name__ == "__main__":
    unittest.main()
