from __future__ import annotations

import unittest

from scripts.run_d2_t12_provider_remediation_probe import (
    build_adj_factor_snapshot_revision,
)


class D2T12AdjFactorSnapshotRevisionTest(unittest.TestCase):
    def test_adj_factor_resolves_with_source_level_asof_and_snapshot_revision(
        self,
    ) -> None:
        result = build_adj_factor_snapshot_revision(
            trading_date="20260702",
            adj_factor_row={"adj_factor": "1.2345"},
            source_snapshot_id="snapshot-1",
            artifact_sha256="abc123",
        )
        self.assertEqual(result["adjustment_factor"], 1.2345)
        self.assertEqual(result["adjustment_factor_status"], "resolved")
        self.assertEqual(result["factor_as_of_time"], "20260702 09:20:00 Asia/Shanghai")
        self.assertEqual(result["adjustment_revision"], "snapshot-1")
        self.assertEqual(result["adjustment_revision_class"], "snapshot_level_revision")
        self.assertEqual(result["adjustment_revision_hash"], "abc123")
        self.assertEqual(
            result["point_in_time_eligibility_class"],
            "source_level_asof_snapshot_revision",
        )
        self.assertTrue(result["point_in_time_eligible_for_eod_research"])
        self.assertFalse(result["strict_provider_row_level_revision_eligible"])


if __name__ == "__main__":
    unittest.main()
