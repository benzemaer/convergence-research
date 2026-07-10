from __future__ import annotations

import json
import unittest
from hashlib import sha256
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

    def test_readme_preserves_r1_t08_after_r1_t09_final_gate(self) -> None:
        text = Path("docs/tasks/README.md").read_text(encoding="utf-8")
        self.assertIn("R1-T08 completed via PR #84", text)
        self.assertIn("R1-T08_allowed_to_start: true", text)
        self.assertIn("R1-T09_allowed_to_start: true", text)

    def test_independent_review_is_bound_to_final_gate(self) -> None:
        root = Path.cwd()
        output = root / "data/generated/r1/r1_t08/R1-T08-20260710T1629Z"
        package = json.loads(
            (output / "r1_t08_result_package.json").read_text(encoding="utf-8")
        )
        review_path = output / "r1_t08_scientific_review.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        final = json.loads(
            (output / "r1_t08_final_gate_package_validation_result.json").read_text(
                encoding="utf-8"
            )
        )
        gate = package["gate_status"]
        self.assertEqual(review["scientific_review_status"], "passed")
        self.assertTrue(review["independence_attestation"])
        self.assertEqual(review["reviewer_identity"], "benzemaer")
        self.assertEqual(review["implementation_actor"], "codex")
        self.assertEqual(review["blocking_findings"], [])
        self.assertEqual(
            package["scientific_review_record_sha256"],
            sha256(review_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(gate["scientific_review_status"], "passed")
        self.assertEqual(gate["review_phase"], "independent_review_complete")
        self.assertEqual(gate["anomaly_resolution_status"], "passed")
        self.assertTrue(gate["readme_gate_updated"])
        self.assertTrue(package["downstream_gate_allowed"])
        self.assertEqual(final["author_package_validator_status"], "passed")
        self.assertTrue(final["formal_task_completed"])
        self.assertTrue(final["downstream_gate_allowed"])


if __name__ == "__main__":
    unittest.main()
