import json
import unittest
from pathlib import Path

from src.r2.r2_t04_freeze_decision import T04InputError, validate_phase_a

ROOT = Path(__file__).resolve().parents[2]
REAL_OUTPUT = ROOT / "data/generated/r2/r2_t04/R2-T04-20260713T120000Z"
PHASE_B_READY = REAL_OUTPUT / "r2_t04_freeze_plan_manifest.json"


class R2T04FreezePlanTest(unittest.TestCase):
    def test_missing_phase_a_artifact_is_blocking(self):
        with self.assertRaises(T04InputError):
            validate_phase_a(__import__("pathlib").Path("does-not-exist"))

    @unittest.skipUnless(
        PHASE_B_READY.exists(), "Phase B output is generated in the PR"
    )
    def test_phase_b_freeze_plan_contains_two_primary_versions(self):
        plan = json.loads(
            (REAL_OUTPUT / "r2_t04_freeze_plan_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(plan["planned_state_version_count"], 2)
        self.assertEqual({version["W"] for version in plan["planned_versions"]}, {120})
        self.assertTrue(
            all(version["strict_core_enabled"] for version in plan["planned_versions"])
        )
        self.assertNotEqual(
            plan["planned_versions"][0]["planned_state_version_id"],
            plan["planned_versions"][1]["planned_state_version_id"],
        )


if __name__ == "__main__":
    unittest.main()
