import unittest

from src.r2.r2_t04_freeze_decision import _dominates


class R2T04ParetoTest(unittest.TestCase):
    def test_dominance_has_no_weighted_score(self):
        objectives = [{"metric_id": "x", "direction": "max"}]
        self.assertTrue(
            _dominates(
                {"objective_values": {"x": 2}},
                {"objective_values": {"x": 1}},
                objectives,
            )
        )


if __name__ == "__main__":
    unittest.main()
