from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


class R1T08FormalExperimentContractTest(unittest.TestCase):
    def test_config_matches_schema_and_frozen_scope(self) -> None:
        config = json.loads(
            Path("configs/r1/r1_t08_global_nested_null_models.v1.json").read_text(
                encoding="utf-8"
            )
        )
        schema = json.loads(
            Path("schemas/r1/r1_t08_global_nested_null_models.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator(schema).validate(config)
        self.assertEqual(len(config["candidate_registry"]), 4)
        self.assertEqual(config["permutation"]["N_perm"], 2000)
        self.assertIn(10000, config["permutation"]["supported_N_perm"])
        self.assertIsNone(config["permutation"]["ten_thousand_trigger"])
        self.assertEqual(config["parallelism"]["duckdb_memory_limit"], "12GB")

    def test_readme_authorizes_only_r1_t08(self) -> None:
        text = Path("docs/tasks/README.md").read_text(encoding="utf-8")
        self.assertIn("current_task: R1-T08 S_PCT/S_PCVT 同步性与嵌套增量零模型", text)
        self.assertIn("R1-T08_allowed_to_start: true", text)
        self.assertIn("R1-T09_allowed_to_start: false", text)
        self.assertIn("R2_allowed_to_start: false", text)


if __name__ == "__main__":
    unittest.main()
