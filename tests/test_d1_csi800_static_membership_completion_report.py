from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/d1_csi800_static_membership_completion_report.schema.json"
CONFIG_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_completion_report.v1.json"
)
REFERENCE_PATH = ROOT / "configs/d1/csi800_static_2026_06_membership_reference.v1.json"
MEMBERSHIP_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"
)
OUTPUT_REPORT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_security_mapping_output_report.v1.json"
)

FAILURE_COUNTS = (
    "unmapped_member_count",
    "duplicate_membership_key_count",
    "duplicate_security_id_count",
    "invalid_security_id_format_count",
    "invalid_ticker_count",
    "invalid_exchange_count",
)
ARTIFACT_FLAGS = (
    "raw_bytes_committed",
    "duckdb_written",
    "run_manifest_created",
    "dataset_manifest_created",
)


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D1CSI800StaticMembershipCompletionReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.reference = load(REFERENCE_PATH)
        cls.membership_contract = load(MEMBERSHIP_CONTRACT_PATH)
        cls.output_report = load(OUTPUT_REPORT_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def validate(self, config: dict[str, object]) -> None:
        self.validator.validate(config)

    def test_schema_and_config_are_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validate(self.config)

    def test_report_aligns_with_contract_and_reference(self) -> None:
        universe = self.membership_contract["universe"]
        evidence = self.membership_contract["source_evidence"]
        self.assertEqual(self.config["universe_id"], universe["universe_id"])
        self.assertEqual(self.config["index_code"], universe["index_code"])
        self.assertEqual(
            self.config["source_snapshot_id"],
            evidence["source_snapshot_id"],
        )
        self.assertEqual(
            self.config["raw_evidence_sha256"],
            evidence["raw_evidence_sha256"],
        )
        self.assertEqual(
            self.config["membership_reference_artifact_id"],
            self.reference["artifact_id"],
        )
        self.assertEqual(
            self.config["member_count_observed"],
            self.reference["member_count"],
        )
        self.assertEqual(
            self.config["security_mapping_output_report_status"],
            self.output_report["report_status"],
        )

    def test_completion_status_and_d2_boundary_are_exact(self) -> None:
        self.assertEqual(self.config["d1_t04_status"], "completed")
        self.assertEqual(
            self.config["d2_readiness_decision"],
            "ready_for_d2_membership_alignment",
        )
        self.assertIn("D2 may use", self.config["d2_boundary"])
        self.assertIn("must not read G0 raw evidence", self.config["d2_boundary"])
        self.assertIn("not D2 execution", self.config["report_boundary"])

    def test_counts_are_clean(self) -> None:
        self.assertEqual(self.config["member_count_expected"], 800)
        self.assertEqual(self.config["member_count_observed"], 800)
        for field in FAILURE_COUNTS:
            with self.subTest(field=field):
                self.assertEqual(self.config[field], 0)

    def test_no_artifact_flags_are_false(self) -> None:
        for field in ARTIFACT_FLAGS:
            with self.subTest(field=field):
                self.assertFalse(self.config[field])

    def test_schema_rejects_bad_counts_or_failure_counts(self) -> None:
        changes = (
            ("member_count_expected", 799),
            ("member_count_observed", 799),
            ("unmapped_member_count", 1),
            ("duplicate_membership_key_count", 1),
            ("duplicate_security_id_count", 1),
            ("invalid_security_id_format_count", 1),
            ("invalid_ticker_count", 1),
            ("invalid_exchange_count", 1),
        )
        for field, value in changes:
            changed = deepcopy(self.config)
            changed[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_schema_rejects_d2_execution_or_artifacts(self) -> None:
        changes = (
            ("d2_readiness_decision", "ready_for_d2_execution"),
            ("d2_readiness_decision", "started_d2"),
            ("duckdb_written", True),
            ("dataset_manifest_created", True),
            ("run_manifest_created", True),
            ("raw_bytes_committed", True),
        )
        for field, value in changes:
            changed = deepcopy(self.config)
            changed[field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValidationError):
                    self.validate(changed)


if __name__ == "__main__":
    unittest.main()
