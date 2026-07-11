import unittest

from src.r2.r2_t02_event_rule_contract import metric_dictionary


class MetricDictionaryTest(unittest.TestCase):
    def test_required_definition_fields_and_metrics(self):
        rows = metric_dictionary()
        required = {
            "metric_id",
            "numerator",
            "denominator",
            "denominator_scope",
            "open_event_policy",
            "null_or_zero_denominator_policy",
        }
        self.assertTrue(all(required <= set(x) for x in rows))
        self.assertIn("confirmed_event_coverage", {x["metric_id"] for x in rows})
        self.assertGreaterEqual(len(rows), 38)


if __name__ == "__main__":
    unittest.main()
