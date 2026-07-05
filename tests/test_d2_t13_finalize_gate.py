from __future__ import annotations

import unittest

from scripts.materialize_d2_tnskhdata_full_candidate import acceptance_decision


class D2T13FinalizeGateTest(unittest.TestCase):
    def _quality(self) -> dict[str, object]:
        return {
            "run_mode": "full",
            "sample_mode": False,
            "fetch_stage_only": False,
            "fetch_completeness_decision": "complete",
            "all_tasks_completed": True,
            "artifact_hashes_complete": True,
            "primary_provider_error_count": 0,
            "rate_limit_count": 3,
            "timeout_count": 2,
            "unrecovered_rate_limit_count": 0,
            "unrecovered_timeout_count": 0,
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

    def test_historical_rate_limit_does_not_block_when_recovered(self) -> None:
        self.assertEqual(
            acceptance_decision(self._quality()), "accepted_for_d3_candidate_generation"
        )

    def test_unrecovered_rate_limit_blocks(self) -> None:
        quality = self._quality()
        quality["unrecovered_rate_limit_count"] = 1
        self.assertEqual(
            acceptance_decision(quality), "blocked_pending_provider_coverage"
        )

    def test_fetch_stage_or_missing_hashes_blocks(self) -> None:
        quality = self._quality()
        quality["fetch_stage_only"] = True
        self.assertEqual(
            acceptance_decision(quality),
            "blocked_pending_tnskhdata_full_materialization_run",
        )
        quality = self._quality()
        quality["artifact_hashes_complete"] = False
        self.assertEqual(acceptance_decision(quality), "blocked_pending_reconciliation")


if __name__ == "__main__":
    unittest.main()
