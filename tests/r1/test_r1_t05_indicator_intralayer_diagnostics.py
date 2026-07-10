from __future__ import annotations

import json
import unittest

from jsonschema import Draft202012Validator

from src.r1.r1_t05_indicator_intralayer_diagnostics import (
    CONFIG_PATH,
    SCHEMA_PATH,
    _validate_config,
)


class R1T05IndicatorIntralayerDiagnosticsTest(unittest.TestCase):
    def test_config_schema_exact_registry_and_grid(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(config)
        self.assertEqual(config["task_id"], "R1-T05")
        self.assertEqual(config["W"], [120, 250, 500])
        self.assertEqual(config["q"], [0.1, 0.2, 0.3])
        self.assertEqual(config["K"], "not_applicable")
        self.assertEqual(len(config["indicators"]), 8)
        self.assertEqual(len(config["layer_pairs"]), 4)
        self.assertEqual(
            {row["layer"] for row in config["layer_pairs"]}, {"P", "C", "T", "V"}
        )

    def test_v2_mapping_uses_log_amount_raw_source_without_repercentiling(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        v2 = next(
            row
            for row in config["indicators"]
            if row["indicator_id"] == "V2_AmountLevel20Pct"
        )
        self.assertEqual(v2["raw_source_indicator_id"], "V2_LogAmount20_base")
        self.assertEqual(v2["raw_metric_name"], "LogAmount20")
        forbidden = set(config["forbidden_tokens"])
        self.assertIn("optimized_q", forbidden)
        self.assertIn("best_indicator", forbidden)

    def test_extra_indicator_or_grid_change_is_rejected(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        extra = dict(config["indicators"][0])
        extra["indicator_id"] = "P3_Unexpected"
        config["indicators"] = config["indicators"] + [extra]
        config["W"] = [120, 250, 500, 750]
        errors = _validate_config(config, schema)
        self.assertTrue(any("config_schema" in error for error in errors))
        self.assertIn("indicator_registry_not_exactly_eight", errors)
        self.assertIn("grid_not_exact", errors)


if __name__ == "__main__":
    unittest.main()
