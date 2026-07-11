import unittest

from src.r2.r2_t02_event_rule_contract import validate_risk_set_guard


class RiskSetTest(unittest.TestCase):
    def test_confirmed_only_and_bridge_excluded(self):
        legal = [
            {
                "confirmed_state": True,
                "available_at_evaluation_time": True,
                "risk_set_eligible": True,
                "is_bridged_gap": False,
                "event_zone_member": False,
            },
            {
                "confirmed_state": False,
                "available_at_evaluation_time": True,
                "risk_set_eligible": False,
                "is_bridged_gap": True,
                "event_zone_member": True,
            },
        ]
        self.assertEqual(validate_risk_set_guard(legal)["status"], "passed")
        legal[1]["risk_set_eligible"] = True
        self.assertEqual(validate_risk_set_guard(legal)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
