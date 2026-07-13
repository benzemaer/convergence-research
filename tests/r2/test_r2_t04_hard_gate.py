import unittest

from src.r2.r2_t04_freeze_decision import _evaluate_operator


class R2T04HardGateTest(unittest.TestCase):
    def test_operator_is_strict_and_null_fails_closed(self):
        self.assertTrue(_evaluate_operator(3, ">=", 3))
        self.assertFalse(_evaluate_operator(None, ">=", 3))
        self.assertFalse(_evaluate_operator(4, "<=", 3))


if __name__ == "__main__":
    unittest.main()
