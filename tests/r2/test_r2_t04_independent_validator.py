import unittest

from src.r2.r2_t04_independent_validator import validate_independently


class R2T04IndependentValidatorTest(unittest.TestCase):
    def test_validator_is_callable(self):
        self.assertTrue(callable(validate_independently))


if __name__ == "__main__":
    unittest.main()
