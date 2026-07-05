from __future__ import annotations

import unittest

from scripts.materialize_d2_tnskhdata_full_candidate import acceptance_decision


class D2T13ProviderErrorGateTest(unittest.TestCase):
    def _accepted_quality(self) -> dict[str, object]:
        return {
            "run_mode": "full",
            "sample_mode": False,
            "primary_provider_error_count": 0,
            "reconciliation_provider_error_count": 0,
            "pro_bar_reconciliation_warning_count": 0,
            "rate_limit_count": 0,
            "duplicate_key_count": 0,
            "null_ohlc_count": 0,
            "non_positive_price_count": 0,
            "high_low_violation_count": 0,
            "amount_unit_status": "resolved_thousand_yuan",
            "volume_unit_status": "resolved_lot",
            "missing_daily_count": 0,
            "unresolved_trading_status_count": 0,
            "unresolved_suspension_status_count": 0,
            "unresolved_st_status_count": 0,
            "unresolved_price_limit_status_count": 0,
            "unresolved_adjustment_factor_count": 0,
            "adjusted_price_row_count": 1,
            "daily_raw_row_count": 1,
        }

    def test_pro_bar_reconciliation_warning_does_not_block(self) -> None:
        quality = self._accepted_quality()
        quality["reconciliation_provider_error_count"] = 1
        quality["pro_bar_reconciliation_warning_count"] = 1
        self.assertEqual(
            acceptance_decision(quality), "accepted_for_d3_candidate_generation"
        )

    def test_primary_provider_error_blocks(self) -> None:
        quality = self._accepted_quality()
        quality["primary_provider_error_count"] = 1
        self.assertEqual(
            acceptance_decision(quality), "blocked_pending_provider_coverage"
        )

    def test_rate_limit_blocks(self) -> None:
        quality = self._accepted_quality()
        quality["rate_limit_count"] = 1
        self.assertEqual(
            acceptance_decision(quality), "blocked_pending_provider_coverage"
        )


if __name__ == "__main__":
    unittest.main()
