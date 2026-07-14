from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.common.canonical_io import write_json
from src.r3.r3_t01_protocol import (
    build_landmarks,
    build_production_rebuild_comparison,
    enumerate_exit_attempts,
)
from src.r3.r3_t01_result_analysis import analyze_run_dir
from src.r3.r3_t01_validator import (
    MUTATION_CODES,
    ReplayValidationError,
    _manifest_binding_errors,
    _validate_run_dir_core,
    _write_mutation_runner_snapshot,
    apply_mutation,
    compare_timestamps,
    validate_in_memory,
    validate_mutations,
    validate_timestamp_order,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r3/r3_t01_protocol_t0_analysis_unit.v1.json"
FIXTURE_PATH = ROOT / "tests/r3/fixtures/r3_t01/cases.json"


class R3T01RevisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.by_case = {item["case_id"]: item for item in cls.fixture["cases"]}

    def test_t0_does_not_require_current_membership_row(self) -> None:
        case = self.by_case["S21"]
        attempts, rejections = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        self.assertFalse(rejections)
        self.assertEqual(len(attempts), 1)
        self.assertFalse(attempts[0]["current_membership_row_present"])
        self.assertEqual(attempts[0]["exit_attempt_date"], "2024-01-02")

    def test_future_bridge_membership_does_not_delay_or_change_t0(self) -> None:
        case = copy.deepcopy(self.by_case["S01"])
        before, _ = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        case["membership_rows"][1]["membership_available_time"] = (
            "2024-02-15T15:00:00+08:00"
        )
        after, _ = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        self.assertEqual(before[0]["exit_attempt_date"], after[0]["exit_attempt_date"])
        self.assertEqual(before[0]["exit_attempt_id"], after[0]["exit_attempt_id"])

    def test_exit_attempt_id_uses_date_not_membership_available_time(self) -> None:
        case = copy.deepcopy(self.by_case["S01"])
        first, _ = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        case["membership_rows"][1]["membership_available_time"] = (
            "2024-12-31T15:00:00+08:00"
        )
        second, _ = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        self.assertEqual(first[0]["exit_attempt_id"], second[0]["exit_attempt_id"])
        self.assertEqual(
            self.config["analysis_unit_contract"]["exit_attempt_id_spec"]["namespace"],
            "r3_exit_attempt_v2",
        )

    def test_non_public_canonical_fields_fail_closed(self) -> None:
        fixture = copy.deepcopy(self.fixture)
        fixture["cases"][0]["membership_rows"][0][
            "component_qualification_" + "available_time"
        ] = None
        report = validate_in_memory(
            self.config, fixture, root=ROOT, check_upstream=False
        )
        self.assertIn(
            "NON_PUBLIC_CANONICAL_FIELD_REFERENCE",
            {item["code"] for item in report.errors},
        )

    def test_component_qualification_date_uses_public_daily_membership_fields(
        self,
    ) -> None:
        attempts, _ = enumerate_exit_attempts(
            self.by_case["S02"]["rows"],
            self.by_case["S02"]["event_zones"],
            self.by_case["S02"]["membership_rows"],
            self.config,
        )
        self.assertEqual(
            attempts[1]["source_component_qualification_date"], "2024-01-03"
        )
        self.assertTrue(attempts[1]["source_component_qualified"])

    def test_frozen_g_is_derived_from_state_version(self) -> None:
        attempts, _ = enumerate_exit_attempts(
            self.by_case["S01"]["rows"],
            self.by_case["S01"]["event_zones"],
            self.by_case["S01"]["membership_rows"],
            self.config,
        )
        self.assertEqual(attempts[0]["frozen_g"], 1)
        self.assertNotIn("g_used_as_of_exit", attempts[0])

    def test_landmarks_are_isolated_by_state_and_security(self) -> None:
        state_a = self.config["frozen_inputs"]["state_versions"][0]["state_version_id"]
        state_b = self.config["frozen_inputs"]["state_versions"][1]["state_version_id"]
        rows = [
            {
                "state_version_id": state_a,
                "security_id": "SEC_TARGET",
                "trade_date": "2024-01-02",
                "expected_row_present": True,
                "eligible_state": True,
                "quality_state": "valid",
            },
            {
                "state_version_id": state_a,
                "security_id": "SEC_OTHER",
                "trade_date": "2024-01-02",
                "expected_row_present": True,
                "eligible_state": True,
                "quality_state": "valid",
            },
            {
                "state_version_id": state_b,
                "security_id": "SEC_TARGET",
                "trade_date": "2024-01-02",
                "expected_row_present": True,
                "eligible_state": True,
                "quality_state": "valid",
            },
        ]
        landmark = build_landmarks(
            rows,
            state_version_id=state_a,
            security_id="SEC_TARGET",
            t0_date="2024-01-01",
        )
        self.assertEqual(landmark["state_version_id"], state_a)
        self.assertEqual(landmark["security_id"], "SEC_TARGET")
        self.assertEqual(landmark["T1"]["trade_date"], "2024-01-02")
        self.assertFalse(landmark["T2"]["available"])

    def test_other_security_cannot_supply_target_h30(self) -> None:
        state = self.config["frozen_inputs"]["state_versions"][0]["state_version_id"]
        rows = [
            {
                "state_version_id": state,
                "security_id": "SEC_TARGET",
                "trade_date": "2024-01-02",
                "expected_row_present": True,
                "eligible_state": True,
                "quality_state": "valid",
            },
            *[
                {
                    "state_version_id": state,
                    "security_id": "SEC_OTHER",
                    "trade_date": f"2024-02-{day:02d}",
                    "expected_row_present": True,
                    "eligible_state": True,
                    "quality_state": "valid",
                }
                for day in range(1, 32)
            ],
        ]
        landmark = build_landmarks(
            rows,
            state_version_id=state,
            security_id="SEC_TARGET",
            t0_date="2024-01-01",
        )
        self.assertFalse(landmark["H30"]["available"])

    def test_validator_rejects_empty_mutation_results(self) -> None:
        config, fixture, _ = apply_mutation(self.config, self.fixture, "M18")
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            _write_mutation_runner_snapshot(
                run_dir, config, fixture, artifact_mutation="EMPTY_MUTATION_RESULTS"
            )
            report = _validate_run_dir_core(
                run_dir,
                root=ROOT,
                execute_mutations=False,
                write_outputs=False,
                fixture_override=fixture,
            )
        self.assertIn(
            "EMPTY_MUTATION_RESULTS", {item["code"] for item in report.errors}
        )

    def test_validator_rejects_pending_artifacts(self) -> None:
        config, fixture, _ = apply_mutation(self.config, self.fixture, "M19")
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            _write_mutation_runner_snapshot(
                run_dir, config, fixture, artifact_mutation="PENDING_FORMAL_ARTIFACT"
            )
            report = _validate_run_dir_core(
                run_dir,
                root=ROOT,
                execute_mutations=False,
                write_outputs=False,
                fixture_override=fixture,
            )
        self.assertIn(
            "PENDING_FORMAL_ARTIFACT", {item["code"] for item in report.errors}
        )

    def test_validator_reads_and_compares_actual_synthetic_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            _write_mutation_runner_snapshot(run_dir, self.config, self.fixture)
            production = json.loads(
                (run_dir / "r3_t01_production_synthetic_results.json").read_text(
                    encoding="utf-8"
                )
            )
            production["cases"][0]["actual_attempts"] = []
            write_json(run_dir / "r3_t01_production_synthetic_results.json", production)
            report = _validate_run_dir_core(
                run_dir,
                root=ROOT,
                execute_mutations=False,
                write_outputs=False,
            )
        self.assertIn(
            "PRODUCTION_INDEPENDENT_REPLAY_MISMATCH",
            {item["code"] for item in report.errors},
        )

    def test_manifest_reconciles_actual_artifact_bytes(self) -> None:
        sha = "mutation" + "0" * 32
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            _write_mutation_runner_snapshot(run_dir, self.config, self.fixture)
            report = _validate_run_dir_core(
                run_dir, root=ROOT, execute_mutations=True, write_outputs=True
            )
            self.assertTrue(report.passed, report.errors)
            analyze_run_dir(
                run_dir,
                CONFIG_PATH,
                FIXTURE_PATH,
                reviewed_implementation_sha=sha,
                formal_execution_sha=sha,
                root=ROOT,
            )
            production = json.loads(
                (run_dir / "r3_t01_production_synthetic_results.json").read_text(
                    encoding="utf-8"
                )
            )
            production["case_count"] = 0
            write_json(run_dir / "r3_t01_production_synthetic_results.json", production)
            errors = _manifest_binding_errors(
                run_dir, json.loads((run_dir / "r3_t01_manifest.json").read_text())
            )
        self.assertIn(
            "MANIFEST_BINDING_HASH_MISMATCH", {item["code"] for item in errors}
        )

    def test_mutations_use_full_validation_entrypoint(self) -> None:
        results = validate_mutations(self.config, self.fixture)
        self.assertEqual({item["mutation_id"] for item in results}, set(MUTATION_CODES))
        self.assertTrue(all(item["status"] == "passed" for item in results))
        self.assertTrue(all(item["mutation_applied"] for item in results))

    def test_double_rebuild_executes_two_real_rebuilds(self) -> None:
        comparison = build_production_rebuild_comparison(CONFIG_PATH, FIXTURE_PATH)
        self.assertEqual(comparison["status"], "passed")
        self.assertEqual(comparison["mismatch_count"], 0)
        self.assertGreater(comparison["compared_artifact_count"], 0)
        self.assertNotEqual(
            id(comparison["rebuild_1_hashes"]), id(comparison["rebuild_2_hashes"])
        )

    def test_independent_timestamp_comparison_is_timezone_aware(self) -> None:
        self.assertTrue(
            compare_timestamps("2024-01-01T00:00:00+08:00", "2023-12-31T16:00:00Z")
        )
        self.assertFalse(
            compare_timestamps("2024-01-01T00:00:01+08:00", "2023-12-31T16:00:00Z")
        )
        with self.assertRaises(ReplayValidationError) as naive:
            compare_timestamps("2024-01-01T00:00:00", "2024-01-01T01:00:00+08:00")
        self.assertEqual(naive.exception.code, "TIMEZONE_REQUIRED")
        with self.assertRaises(ReplayValidationError) as invalid:
            compare_timestamps("not-a-timestamp", "2024-01-01T01:00:00+08:00")
        self.assertEqual(invalid.exception.code, "INVALID_TIME")
        with self.assertRaises(ReplayValidationError) as order:
            validate_timestamp_order(
                "2024-01-02T00:00:00+08:00", "2024-01-01T00:00:00+08:00"
            )
        self.assertEqual(order.exception.code, "TIME_ORDER_MISMATCH")

    def test_result_analysis_reads_actual_artifacts(self) -> None:
        sha = "mutation" + "0" * 32
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            _write_mutation_runner_snapshot(run_dir, self.config, self.fixture)
            report = _validate_run_dir_core(
                run_dir, root=ROOT, execute_mutations=True, write_outputs=True
            )
            self.assertTrue(report.passed, report.errors)
            production = json.loads(
                (run_dir / "r3_t01_production_synthetic_results.json").read_text(
                    encoding="utf-8"
                )
            )
            production["cases"][0]["actual_attempts"] = []
            write_json(run_dir / "r3_t01_production_synthetic_results.json", production)
            analysis_path = analyze_run_dir(
                run_dir,
                CONFIG_PATH,
                FIXTURE_PATH,
                reviewed_implementation_sha=sha,
                formal_execution_sha=sha,
                root=ROOT,
            )
            text = analysis_path.read_text(encoding="utf-8")
        self.assertIn("PRODUCTION_INDEPENDENT_REPLAY_MISMATCH", text)
        self.assertIn("R3-T02 recommendation", text)
        self.assertNotIn("Pending independent result review", text)


if __name__ == "__main__":
    unittest.main()
