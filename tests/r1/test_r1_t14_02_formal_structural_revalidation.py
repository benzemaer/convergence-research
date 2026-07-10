from __future__ import annotations

import unittest

import numpy as np

from src.r1.r1_t14_02_formal_structural_revalidation import (
    _confirmed_coverage_fast,
    _step_metrics,
)


class R1T1402FormalStructuralRevalidationTests(unittest.TestCase):
    def test_confirmed_coverage_uses_k3_without_backfill(self) -> None:
        security = np.asarray([0, 0, 0, 0, 0, 1, 1, 1], dtype=np.int32)
        true_indices = np.asarray([0, 1, 2, 4, 5, 6, 7], dtype=np.int64)
        self.assertEqual(_confirmed_coverage_fast(true_indices, security, 8, 3), 2 / 8)

    def test_step_metrics_preserve_lift_delta_and_joint_excess_identities(self) -> None:
        result = _step_metrics(20, 30, 10, 40)
        self.assertAlmostEqual(result["retention"], 0.4)
        self.assertAlmostEqual(result["target_marginal"], 0.3)
        self.assertAlmostEqual(result["lift"], 4 / 3)
        self.assertAlmostEqual(result["delta"], 0.1)
        self.assertAlmostEqual(result["joint_excess"], 0.05)

    def test_zero_denominators_remain_unknown(self) -> None:
        result = _step_metrics(0, 0, 0, 0)
        self.assertIsNone(result["retention"])
        self.assertIsNone(result["lift"])
        self.assertIsNone(result["joint_excess"])


if __name__ == "__main__":
    unittest.main()
