from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from src.r3.r3_t01_protocol import verify_remote_startup_binding
from src.r3.r3_t01_validator import (
    MUTATION_CODES,
    validate_in_memory,
    validate_independence,
    validate_mutations,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r3/r3_t01_protocol_t0_analysis_unit.v1.json"
FIXTURE_PATH = ROOT / "tests/r3/fixtures/r3_t01/cases.json"


class R3T01FailurePathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.by_case = {item["case_id"]: item for item in cls.fixture["cases"]}

    def test_all_negative_scenarios_have_specific_rejection_codes(self) -> None:
        report = validate_in_memory(self.config, self.fixture, root=ROOT)
        self.assertTrue(report.passed, report.errors)
        results = {item["case_id"]: item for item in report.synthetic_case_results}
        expected = {
            "S14": ["PREQUALIFICATION_EXIT"],
            "S15": ["QUALITY_INTERRUPTION"],
            "S16": ["CURRENT_INELIGIBLE"],
            "S17": ["PRIOR_NOT_CONFIRMED"],
            "S18": ["PRIOR_ROW_NOT_ELIGIBLE", "QUALITY_INTERRUPTION"],
            "S19": ["RIGHT_CENSORING"],
            "S20": ["EVENT_ID_CONFLICT"],
            "S21": [],
        }
        for case_id, codes in expected.items():
            self.assertEqual(
                results[case_id]["rejection_codes"], sorted(codes), case_id
            )

    def test_each_mutation_starts_from_a_passing_baseline_and_is_specific(self) -> None:
        baseline = validate_in_memory(self.config, self.fixture, root=ROOT)
        self.assertTrue(baseline.passed, baseline.errors)
        mutation_results = validate_mutations(self.config, self.fixture)
        self.assertEqual(len(mutation_results), 20)
        self.assertEqual(
            {item["mutation_id"] for item in mutation_results}, set(MUTATION_CODES)
        )
        for result in mutation_results:
            self.assertIn(result["expected_error_code"], result["actual_error_codes"])
            self.assertTrue(result["specific_error_detected"])
            self.assertFalse(result["unrelated_setup_failure"])
            self.assertEqual(result["status"], "passed")

    def test_mutation_error_codes_fail_closed_individually(self) -> None:
        results = {
            item["mutation_id"]: item
            for item in validate_mutations(self.config, self.fixture)
        }
        for mutation_id, expected_code in MUTATION_CODES.items():
            self.assertIn(expected_code, results[mutation_id]["actual_error_codes"])
            self.assertEqual(results[mutation_id]["status"], "passed")

    def test_validator_is_independent_from_production_protocol(self) -> None:
        source = (ROOT / "src/r3/r3_t01_validator.py").read_text(encoding="utf-8")
        self.assertIsNone(validate_independence(source))
        self.assertEqual(
            validate_independence(
                "from src.r3.r3_t01_protocol import enumerate_exit_attempts"
            ),
            "VALIDATOR_PRODUCTION_HELPER_REUSE",
        )

    def test_schema_and_contract_mutations_are_not_silently_accepted(self) -> None:
        mutated = copy.deepcopy(self.config)
        mutated["landmark_horizon_contract"]["primary_horizon"] = "H10"
        report = validate_in_memory(
            mutated, self.fixture, root=ROOT, check_upstream=False
        )
        codes = {item["code"] for item in report.errors}
        self.assertIn("SCHEMA_VALIDATION_FAILED", codes)

    def test_remote_startup_binding_requires_merged_reviewed_pr(self) -> None:
        responses = iter(
            [
                {
                    "state": "MERGED",
                    "mergeCommit": {
                        "oid": self.config["upstream_binding"]["r2_t08_merge_commit"]
                    },
                    "headRefOid": self.config["upstream_binding"][
                        "r2_t08_reviewed_head"
                    ],
                },
                {
                    "body": "scientific_review_status=passed",
                    "commit_id": self.config["upstream_binding"][
                        "r2_t08_reviewed_head"
                    ],
                },
            ]
        )

        class Completed:
            returncode = 0

            def __init__(self, payload: dict[str, object]) -> None:
                self.stdout = json.dumps(payload)

        def fake_run(*args: object, **kwargs: object) -> Completed:
            del args, kwargs
            return Completed(next(responses))

        with patch("src.r3.r3_t01_protocol.subprocess.run", side_effect=fake_run):
            result = verify_remote_startup_binding(self.config, ROOT)
        self.assertEqual(result["scientific_review_status"], "passed")

    def test_s22_duplicate_registry_marker_is_present_for_manual_replay(self) -> None:
        self.assertTrue(self.by_case["S22"]["duplicate_attempt_registry"])
        self.assertIn(
            "DUPLICATE_EXIT_ATTEMPT_ID",
            self.config["analysis_unit_contract"]["attempt_registry_fail_closed_codes"],
        )
        self.assertIn(
            "ORDINAL_NOT_CONTIGUOUS",
            self.config["analysis_unit_contract"]["attempt_registry_fail_closed_codes"],
        )


if __name__ == "__main__":
    unittest.main()
