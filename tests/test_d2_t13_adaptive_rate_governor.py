from __future__ import annotations

import unittest

from scripts.materialize_d2_tnskhdata_full_candidate import AdaptiveRateGovernor


class D2T13AdaptiveRateGovernorTest(unittest.TestCase):
    def test_stable_minutes_increase_rpm_to_cap(self) -> None:
        governor = AdaptiveRateGovernor(
            initial_requests_per_minute=200,
            max_requests_per_minute=500,
            rate_increase_per_minute=100,
            enabled=False,
        )
        for expected in (300, 400, 500, 500):
            entry = governor.record_minute(
                successful_requests=10,
                failed_requests=0,
                rate_limit_count=0,
                timeout_count=0,
                provider_error_count=0,
            )
            self.assertEqual(entry["current_rpm"], expected)
        self.assertEqual(governor.rate_increase_events, 3)

    def test_rate_limit_or_provider_error_decreases_rpm(self) -> None:
        governor = AdaptiveRateGovernor(
            initial_requests_per_minute=400,
            max_requests_per_minute=500,
            rate_decrease_factor=0.5,
            enabled=False,
        )
        entry = governor.record_minute(
            successful_requests=5,
            failed_requests=1,
            rate_limit_count=1,
            timeout_count=0,
            provider_error_count=0,
        )
        self.assertEqual(entry["current_rpm"], 200)
        self.assertEqual(entry["backoff_events"], 1)
        self.assertEqual(governor.rate_decrease_events, 1)


if __name__ == "__main__":
    unittest.main()
