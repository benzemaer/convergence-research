from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from src.r1.r1_t14_02_formal_structural_revalidation import (
    _confirmed_coverage_fast,
    _load_robust_envelopes,
    _security_hash,
    _sign,
    _step_metrics,
    _v_selectivity_retained,
)
from src.r1.r1_t14_02_formal_structural_revalidation_validator import (
    validate_r1_t14_02_formal_structural_revalidation,
)

ROOT = Path(__file__).resolve().parents[2]


class R1T1402FormalStructuralRevalidationTests(unittest.TestCase):
    def test_validator_fails_closed_for_raw_ratio_source(self) -> None:
        source = (
            Path(__file__).resolve().parents[2]
            / "data/generated/r1/r1_t14_02/R1-T14-02-20260711T0900Z"
        )
        with TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / source.name
            shutil.copytree(source, run_dir)
            result = validate_r1_t14_02_formal_structural_revalidation(run_dir=run_dir)
        self.assertEqual(result["status"], "failed")
        self.assertIn("v_selectivity_guard_contract", result["errors"])

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

    def test_sign_gate_uses_tolerance_and_detects_reversal(self) -> None:
        self.assertEqual(_sign(0.2), "positive")
        self.assertEqual(_sign(-0.2), "negative")
        self.assertEqual(_sign(1e-14), "zero")

    def test_security_group_ids_are_deterministically_pseudonymized(self) -> None:
        first = _security_hash("000001.SZ")
        self.assertEqual(first, _security_hash("000001.SZ"))
        self.assertNotIn("000001", first)
        self.assertTrue(first.startswith("security_sha256_"))

    def test_v_selectivity_guard_uses_complement_retention_formula(self) -> None:
        self.assertAlmostEqual(_v_selectivity_retained(0.35, 0.20), 0.8125)
        self.assertNotEqual(_v_selectivity_retained(0.35, 0.20), 0.35 / 0.20)
        self.assertIsNone(_v_selectivity_retained(0.35, 1.0))

    def test_scope_specific_robust_envelopes_are_loaded_from_t14_01(self) -> None:
        config = json.loads(
            (
                ROOT / "configs/r1/r1_t14_02_formal_structural_revalidation.v2.json"
            ).read_text(encoding="utf-8")
        )
        envelopes = _load_robust_envelopes(config)
        self.assertAlmostEqual(
            envelopes[(120, "S_PCVT", "confirmed_coverage")], 0.0005587316611579772
        )
        self.assertAlmostEqual(
            envelopes[(250, "V_GIVEN_PCT", "delta")], 0.04169739768175059
        )


if __name__ == "__main__":
    unittest.main()
