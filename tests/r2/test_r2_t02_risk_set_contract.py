import unittest

from src.r2.r2_t02_event_rule_contract import validate_risk_set_guard


class RiskSetTest(unittest.TestCase):
    def test_confirmed_only_and_bridge_excluded(self):
        legal = [
            {
                "confirmed_state": True,
                "eligible": True,
                "quality_state": "valid",
                "available_at_evaluation_time": True,
                "risk_set_eligible": True,
                "is_bridged_gap": False,
                "event_zone_member": False,
            },
            {
                "confirmed_state": False,
                "eligible": True,
                "quality_state": "valid",
                "available_at_evaluation_time": True,
                "risk_set_eligible": False,
                "is_bridged_gap": True,
                "event_zone_member": True,
            },
        ]
        self.assertEqual(validate_risk_set_guard(legal)["status"], "passed")
        legal[1]["risk_set_eligible"] = True
        self.assertEqual(validate_risk_set_guard(legal)["status"], "failed")

    def test_invalid_quality_confirmed_contradiction_fails_closed(self):
        row = {
            "confirmed_state": True,
            "eligible": True,
            "quality_state": "unknown",
            "available_at_evaluation_time": True,
            "risk_set_eligible": True,
            "is_bridged_gap": False,
            "event_zone_member": False,
        }
        result = validate_risk_set_guard([row])
        self.assertEqual(result["status"], "failed")
        self.assertIn("confirmed_quality_contradiction:0", result["errors"])


if __name__ == "__main__":
    unittest.main()
