from __future__ import annotations

import unittest

from scripts.materialize_d2_tnskhdata_full_candidate import acceptance_decision


class D2T13FullRunGateRequiresAllTasksTest(unittest.TestCase):
    def _quality(self) -> dict[str, object]:
        return {
            "run_mode": "full",
            "sample_mode": False,
            "all_tasks_completed": True,
            "primary_provider_error_count": 0,
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

    def test_full_acceptance_requires_all_endpoint_tasks_complete(self) -> None:
        quality = self._quality()
        quality["all_tasks_completed"] = False
        self.assertEqual(
            acceptance_decision(quality), "blocked_pending_provider_coverage"
        )

    def test_all_tasks_complete_can_accept_when_other_gates_pass(self) -> None:
        self.assertEqual(
            acceptance_decision(self._quality()), "accepted_for_d3_candidate_generation"
        )


if __name__ == "__main__":
    unittest.main()
