import unittest

from src.r2.r2_t02_event_rule_contract import metric_dictionary


class MetricDictionaryTest(unittest.TestCase):
    def test_required_definition_fields_and_metrics(self):
        rows = metric_dictionary()
        required = {
            "metric_id",
            "layer",
            "entity_level",
            "numerator_or_aggregation",
            "denominator",
            "deduplication_key",
            "included_rows",
            "excluded_rows",
            "censoring_policy",
            "denominator_scope",
            "open_event_policy",
            "expected_parameter_response",
            "hard_gate_usage",
            "null_or_zero_denominator_policy",
            "availability_basis",
        }
        self.assertTrue(all(required <= set(x) for x in rows))
        self.assertIn("confirmed_state_coverage", {x["metric_id"] for x in rows})
        self.assertIn(
            "prequalification_right_censored_count", {x["metric_id"] for x in rows}
        )
        self.assertIn("zone_revision_count", {x["metric_id"] for x in rows})
        self.assertGreaterEqual(len(rows), 38)
        serialized = str(rows)
        self.assertNotIn("metric-defined", serialized)
        self.assertNotIn("contract_defined", serialized)
        self.assertNotIn("registry_defined", serialized)
        self.assertGreater(len({row["deduplication_key"] for row in rows}), 5)
        self.assertGreater(len({row["open_event_policy"] for row in rows}), 5)


if __name__ == "__main__":
    unittest.main()
