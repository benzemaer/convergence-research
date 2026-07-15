from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from src.common.canonical_io import read_csv, write_csv, write_json
from src.r3.r3_t01_final_validator import validate_final_run_dir
from src.r3.r3_t01_protocol import (
    ProtocolContractError,
    authorize_formal_run,
    enumerate_exit_attempts,
)
from src.r3.r3_t01_result_analysis import analyze_run_dir
from src.r3.r3_t01_validator import (
    _validate_run_dir_core,
    _write_mutation_runner_snapshot,
    validate_in_memory,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/r3/r3_t01_protocol_t0_analysis_unit.v1.json"
FIXTURE_PATH = ROOT / "tests/r3/fixtures/r3_t01/cases.json"
TEST_SHA = "a" * 40
APPROVAL_ID = 1030000001
APPROVAL_BODY = "\n".join(
    [
        "task_id=R3-T01",
        "implementation_review_status=approved",
        f"reviewed_implementation_sha={TEST_SHA}",
        "formal_run_allowed=true",
        "approval_scope=R3-T01_formal_run_only",
    ]
)


class R3T01SecondRevisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.by_case = {item["case_id"]: item for item in cls.fixture["cases"]}
        cls.snapshot_tmp = tempfile.TemporaryDirectory(prefix="r3_t01_second_revision_")
        cls.clean_run_dir = Path(cls.snapshot_tmp.name) / "clean"
        _write_mutation_runner_snapshot(cls.clean_run_dir, cls.config, cls.fixture)
        report = _validate_run_dir_core(
            cls.clean_run_dir,
            root=ROOT,
            execute_mutations=True,
            write_outputs=True,
        )
        if not report.passed:
            raise AssertionError(report.errors)
        analyze_run_dir(
            cls.clean_run_dir,
            CONFIG_PATH,
            FIXTURE_PATH,
            reviewed_implementation_sha="mutation" + "0" * 32,
            formal_execution_sha="mutation" + "0" * 32,
            root=ROOT,
        )
        final = validate_final_run_dir(cls.clean_run_dir, root=ROOT)
        if final["status"] != "passed":
            raise AssertionError(final["errors"])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.snapshot_tmp.cleanup()

    @contextmanager
    def clean_copy(self):
        with tempfile.TemporaryDirectory(prefix="r3_t01_final_test_") as temp_dir:
            run_dir = Path(temp_dir) / "run"
            shutil.copytree(self.clean_run_dir, run_dir)
            yield run_dir

    @staticmethod
    def _comment(author: str = "benzemaer", body: str = APPROVAL_BODY) -> dict:
        return {
            "id": APPROVAL_ID,
            "html_url": (
                "https://github.com/benzemaer/convergence-research/"
                "pull/103#issuecomment-1030000001"
            ),
            "repository_url": (
                "https://api.github.com/repos/benzemaer/convergence-research"
            ),
            "user": {"login": author},
            "body": body,
            "created_at": "2026-07-15T00:00:00Z",
            "updated_at": "2026-07-15T00:00:00Z",
        }

    @classmethod
    def _gh_side_effect(cls, comment: dict):
        def respond(_root: Path, *args: str) -> dict:
            if args[0] == "api":
                return comment
            if args[0] == "pr":
                return {"state": "OPEN", "headRefOid": TEST_SHA}
            raise AssertionError(args)

        return respond

    def test_formal_authorization_does_not_require_tracked_config_mutation(
        self,
    ) -> None:
        before = copy.deepcopy(self.config["implementation_state"])
        with patch(
            "src.r3.r3_t01_protocol._gh_json",
            side_effect=self._gh_side_effect(self._comment()),
        ):
            approval = authorize_formal_run(
                self.config, TEST_SHA, APPROVAL_ID, root=ROOT
            )
        self.assertEqual(approval["approval_comment_id"], APPROVAL_ID)
        self.assertEqual(self.config["implementation_state"], before)
        self.assertFalse(self.config["implementation_state"]["formal_run_allowed"])

    def test_valid_github_approval_comment_authorizes_exact_sha(self) -> None:
        with patch(
            "src.r3.r3_t01_protocol._gh_json",
            side_effect=self._gh_side_effect(self._comment()),
        ) as gh:
            approval = authorize_formal_run(
                self.config, TEST_SHA, APPROVAL_ID, root=ROOT
            )
        self.assertEqual(approval["reviewed_implementation_sha"], TEST_SHA)
        self.assertEqual(approval["pr_head_sha"], TEST_SHA)
        self.assertEqual(
            gh.call_args_list[0].args[1:],
            (
                "api",
                f"repos/benzemaer/convergence-research/issues/comments/{APPROVAL_ID}",
            ),
        )

    def test_wrong_approval_comment_sha_fails_closed(self) -> None:
        body = APPROVAL_BODY.replace(TEST_SHA, "b" * 40)
        with patch(
            "src.r3.r3_t01_protocol._gh_json",
            side_effect=self._gh_side_effect(self._comment(body=body)),
        ):
            with self.assertRaises(ProtocolContractError) as raised:
                authorize_formal_run(self.config, TEST_SHA, APPROVAL_ID, root=ROOT)
        self.assertEqual(raised.exception.code, "FORMAL_APPROVAL_SHA_MISMATCH")

    def test_wrong_approval_comment_author_fails_closed(self) -> None:
        with patch(
            "src.r3.r3_t01_protocol._gh_json",
            side_effect=self._gh_side_effect(self._comment(author="someone_else")),
        ):
            with self.assertRaises(ProtocolContractError) as raised:
                authorize_formal_run(self.config, TEST_SHA, APPROVAL_ID, root=ROOT)
        self.assertEqual(raised.exception.code, "FORMAL_APPROVAL_AUTHOR_MISMATCH")

    def test_missing_approval_comment_fails_closed(self) -> None:
        with patch("src.r3.r3_t01_protocol._gh_json") as gh:
            with self.assertRaises(ProtocolContractError) as raised:
                authorize_formal_run(self.config, TEST_SHA, None, root=ROOT)
        self.assertEqual(raised.exception.code, "FORMAL_APPROVAL_RECORD_REQUIRED")
        gh.assert_not_called()

    def test_source_component_identity_uses_daily_and_event_zone_only(self) -> None:
        case = copy.deepcopy(self.by_case["S01"])
        baseline, _ = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        for row in case["membership_rows"]:
            row["component_member"] = False
            row["retrospective_component_member"] = True
            row["component_qualified_as_of"] = False
            row["membership_available_time"] = "2025-01-01T00:00:00+08:00"
        changed, _ = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        self.assertEqual(
            baseline[0]["source_component_id"], changed[0]["source_component_id"]
        )
        self.assertEqual(baseline[0]["exit_attempt_id"], changed[0]["exit_attempt_id"])

    def test_delayed_membership_does_not_change_primary_component(self) -> None:
        case = self.by_case["S27"]
        attempts, _ = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        self.assertEqual(attempts[0]["source_component_start_date"], "2024-01-01")
        self.assertEqual(
            attempts[0]["source_component_qualification_date"], "2024-01-01"
        )
        self.assertFalse(attempts[0]["current_membership_row_present"])

    def test_retrospective_membership_cannot_create_primary_component(self) -> None:
        case = self.by_case["S29"]
        attempts, rejections = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        self.assertEqual(attempts, [])
        self.assertEqual([item["code"] for item in rejections], ["PRIOR_NOT_CONFIRMED"])

    def test_membership_audit_fields_are_not_t0_features(self) -> None:
        field_specs = {
            item["field_name"]: item for item in self.config["field_semantics"]
        }
        for name in (
            "current_membership_row_present",
            "current_membership_available_time",
            "current_membership_availability_is_causal_for_t0",
            "membership_resolution_status",
            "last_observed_zone_revision_before_exit",
            "current_exit_membership_zone_revision",
        ):
            field = field_specs[name]
            self.assertEqual(field["availability_class"], "post_event_audit")
            self.assertFalse(field["allowed_at_T0"])
            self.assertTrue(field["audit_only"])
            self.assertTrue(field["forbidden_model_feature"])

    def test_first_component_uses_event_zone_start_and_qualification(self) -> None:
        case = copy.deepcopy(self.by_case["S01"])
        case["event_zones"][0]["first_component_start_date"] = "2023-12-29"
        case["event_zones"][0]["first_qualification_time"] = "2023-12-30T10:00:00+08:00"
        attempts, _ = enumerate_exit_attempts(
            case["rows"], case["event_zones"], case["membership_rows"], self.config
        )
        self.assertEqual(attempts[0]["source_component_start_date"], "2023-12-29")
        self.assertEqual(
            attempts[0]["source_component_qualification_date"], "2023-12-30"
        )

    def test_unqualified_reentry_ordinal_exceeds_qualified_count(self) -> None:
        attempts, _ = enumerate_exit_attempts(
            self.by_case["S31"]["rows"],
            self.by_case["S31"]["event_zones"],
            self.by_case["S31"]["membership_rows"],
            self.config,
        )
        self.assertEqual(attempts[1]["source_component_ordinal"], 2)
        self.assertEqual(attempts[1]["component_count_as_of_exit"], 1)
        self.assertFalse(attempts[1]["source_component_qualified"])

    def test_event_zone_primary_key_matches_r2_authority(self) -> None:
        event = next(
            item
            for item in self.config["canonical_public_interface_contract"]["tables"]
            if item["logical_table_name"] == "r2_canonical_event_zone"
        )
        self.assertEqual(event["primary_key"], ["state_version_id", "event_id"])
        self.assertEqual(
            self.config["canonical_interface_authority"]["interfaces"]["event"][
                "primary_key"
            ],
            event["primary_key"],
        )

    def test_all_canonical_interfaces_reconcile_to_r2_binding(self) -> None:
        report = validate_in_memory(
            self.config, self.fixture, root=ROOT, check_upstream=False
        )
        self.assertNotIn(
            "CANONICAL_INTERFACE_PRIMARY_KEY_MISMATCH",
            {item["code"] for item in report.errors},
        )
        self.assertNotIn(
            "CANONICAL_INTERFACE_ROW_COUNT_MISMATCH",
            {item["code"] for item in report.errors},
        )
        self.assertNotIn(
            "CANONICAL_INTERFACE_HASH_MISMATCH",
            {item["code"] for item in report.errors},
        )

    def test_analyzer_does_not_mark_completed_before_final_validation(self) -> None:
        manifest = json.loads(
            (self.clean_run_dir / "r3_t01_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["formal_run_status"],
            "analysis_complete_pending_final_validation",
        )
        self.assertNotEqual(manifest["formal_run_status"], "completed")

    def test_final_validator_passes_clean_closed_run(self) -> None:
        with self.clean_copy() as run_dir:
            result = validate_final_run_dir(run_dir, root=ROOT)
        self.assertEqual(result["status"], "passed", result["errors"])
        self.assertEqual(result["error_count"], 0)

    def _assert_final_tamper(self, filename: str, mutate) -> None:
        with self.clean_copy() as run_dir:
            path = run_dir / filename
            value = json.loads(path.read_text(encoding="utf-8"))
            mutate(value)
            write_json(path, value)
            result = validate_final_run_dir(run_dir, root=ROOT)
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("FINAL_VALIDATION_TAMPER_DETECTED", codes)
        self.assertEqual(result["status"], "failed")

    def test_final_validator_detects_analysis_tamper(self) -> None:
        with self.clean_copy() as run_dir:
            path = run_dir / "r3_t01_result_analysis.md"
            path.write_text(
                path.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8"
            )
            result = validate_final_run_dir(run_dir, root=ROOT)
        self.assertIn(
            "FINAL_VALIDATION_TAMPER_DETECTED",
            {item["code"] for item in result["errors"]},
        )

    def test_final_validator_detects_validator_result_tamper(self) -> None:
        self._assert_final_tamper(
            "r3_t01_validator_result.json",
            lambda value: value.update({"status": "failed"}),
        )

    def test_final_validator_detects_mutation_csv_tamper(self) -> None:
        with self.clean_copy() as run_dir:
            path = run_dir / "r3_t01_mutation_results.csv"
            rows = read_csv(path)
            rows[0]["status"] = "failed"
            write_csv(path, rows, list(rows[0]))
            result = validate_final_run_dir(run_dir, root=ROOT)
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("FINAL_VALIDATION_TAMPER_DETECTED", codes)
        self.assertIn("FINAL_VALIDATION_ANALYSIS_NOT_PASSED", codes)

    def test_final_validator_detects_runner_artifact_tamper(self) -> None:
        self._assert_final_tamper(
            "r3_t01_anchor_decision.json",
            lambda value: value.update({"tampered": True}),
        )

    def test_final_validation_sidecar_binds_manifest_sha(self) -> None:
        sidecar = json.loads(
            (self.clean_run_dir / "r3_t01_final_validation.json").read_text(
                encoding="utf-8"
            )
        )
        manifest_sha = hashlib.sha256(
            (self.clean_run_dir / "r3_t01_manifest.json").read_bytes()
        ).hexdigest()
        self.assertEqual(sidecar["validated_manifest_sha256"], manifest_sha)
        self.assertEqual(sidecar["tamper_check_status"], "passed")


if __name__ == "__main__":
    unittest.main()
