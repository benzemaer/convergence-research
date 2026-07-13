import unittest

from src.r2.r2_t04_freeze_decision import T04InputError, validate_phase_a


class R2T04FreezePlanTest(unittest.TestCase):
    def test_missing_phase_a_artifact_is_blocking(self):
        with self.assertRaises(T04InputError):
            validate_phase_a(__import__("pathlib").Path("does-not-exist"))


if __name__ == "__main__":
    unittest.main()
