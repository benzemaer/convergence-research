from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT / "schemas/d1_csi800_static_security_mapping_output_report.schema.json"
)
CONFIG_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_security_mapping_output_report.v1.json"
)
MEMBERSHIP_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"
)
FIELD_ALIAS_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_field_aliases.v1.json"
)
REFERENCE_CONTRACT_PATH = (
    ROOT
    / "configs/d1/csi800_static_2026_06_security_mapping_reference_contract.v1.json"
)
OUTPUT_CONTRACT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_security_mapping_output_contract.v1.json"
)

ROW_LEVEL_FIELDS = (
    "members",
    "member_rows",
    "rows",
    "tickers",
    "source_symbols",
    "security_ids",
)

ARTIFACT_FLAGS = (
    "row_level_detail_included",
    "output_rows_committed",
    "security_id_mapping_output_committed",
    "raw_bytes_committed",
    "member_rows_committed",
    "duckdb_written",
    "run_manifest_created",
    "dataset_manifest_created",
    "materialization_authorized",
    "member_rows_materialized",
)

FAILURE_COUNTS = (
    "unmapped_row_count",
    "duplicate_membership_key_count",
    "duplicate_security_id_count",
    "invalid_security_id_format_count",
    "invalid_mapping_method_count",
    "invalid_mapping_status_count",
)


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D1CSI800StaticSecurityMappingOutputReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.config = load(CONFIG_PATH)
        cls.membership_contract = load(MEMBERSHIP_CONTRACT_PATH)
        cls.field_alias_contract = load(FIELD_ALIAS_CONTRACT_PATH)
        cls.reference_contract = load(REFERENCE_CONTRACT_PATH)
        cls.output_contract = load(OUTPUT_CONTRACT_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def validate(self, config: dict[str, object]) -> None:
        self.validator.validate(config)

    def test_security_mapping_output_report_schema_and_config_are_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validate(self.config)

    def test_report_aligns_with_membership_contract(self) -> None:
        universe = self.membership_contract["universe"]
        evidence = self.membership_contract["source_evidence"]
        self.assertEqual(self.config["universe_id"], universe["universe_id"])
        self.assertEqual(self.config["index_code"], universe["index_code"])
        self.assertEqual(
            self.config["source_snapshot_id"],
            evidence["source_snapshot_id"],
        )
        self.assertEqual(
            self.config["raw_evidence_sha256_expected"],
            evidence["raw_evidence_sha256"],
        )

    def test_report_aligns_with_contract_chain(self) -> None:
        self.assertEqual(
            self.config["field_alias_contract_id"],
            self.field_alias_contract["contract_id"],
        )
        self.assertEqual(
            self.config["security_mapping_reference_contract_id"],
            self.reference_contract["contract_id"],
        )
        self.assertEqual(
            self.config["security_mapping_output_contract_id"],
            self.output_contract["contract_id"],
        )
        self.assertEqual(
            self.config["expected_row_count"],
            self.output_contract["expected_row_count"],
        )

    def test_passed_report_records_clean_aggregate_counts(self) -> None:
        self.assertEqual(
            self.config["report_status"],
            "passed",
        )
        self.assertEqual(self.config["observed_row_count"], 800)
        self.assertEqual(self.config["mapped_row_count"], 800)
        for field in FAILURE_COUNTS:
            with self.subTest(field=field):
                self.assertEqual(self.config[field], 0)
        self.assertEqual(
            self.config["downstream_decision"],
            "security_mapping_output_validated_but_membership_rows_not_materialized",
        )

    def test_no_artifact_or_materialization_flags_are_false(self) -> None:
        for field in ARTIFACT_FLAGS:
            with self.subTest(field=field):
                self.assertFalse(self.config[field])

    def test_passed_synthetic_report_requires_clean_aggregate_counts(self) -> None:
        changed = deepcopy(self.config)
        changed.update(
            {
                "report_status": "passed",
                "observed_row_count": 800,
                "mapped_row_count": 800,
                "downstream_decision": (
                    "security_mapping_output_validated_but_membership_rows_not_materialized"
                ),
            }
        )
        self.validate(changed)

    def test_blocked_synthetic_report_keeps_all_counts_zero(self) -> None:
        changed = deepcopy(self.config)
        changed.update(
            {
                "report_status": "blocked_missing_security_mapping_output",
                "observed_row_count": 0,
                "mapped_row_count": 0,
                "downstream_decision": "materialization_remains_blocked",
            }
        )
        self.validate(changed)

    def test_row_level_fields_are_rejected(self) -> None:
        for field in ROW_LEVEL_FIELDS:
            changed = deepcopy(self.config)
            changed[field] = []
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_artifact_or_materialization_flags_true_are_rejected(self) -> None:
        for field in ARTIFACT_FLAGS:
            changed = deepcopy(self.config)
            changed[field] = True
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_passed_report_with_bad_counts_is_rejected(self) -> None:
        changes = (
            ("observed_row_count", 799),
            ("mapped_row_count", 799),
            ("unmapped_row_count", 1),
            ("duplicate_membership_key_count", 1),
            ("duplicate_security_id_count", 1),
            ("invalid_security_id_format_count", 1),
            ("invalid_mapping_method_count", 1),
            ("invalid_mapping_status_count", 1),
        )
        for key, value in changes:
            changed = deepcopy(self.config)
            changed.update(
                {
                    "report_status": "passed",
                    "observed_row_count": 800,
                    "mapped_row_count": 800,
                    "downstream_decision": (
                        "security_mapping_output_validated_but_membership_rows_not_materialized"
                    ),
                }
            )
            changed[key] = value
            with self.subTest(key=key):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_non_passed_report_must_keep_blocked_downstream_decision(self) -> None:
        changed = deepcopy(self.config)
        changed["report_status"] = "failed_row_count"
        changed["downstream_decision"] = (
            "security_mapping_output_validated_but_membership_rows_not_materialized"
        )
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_blocked_report_with_observed_rows_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["observed_row_count"] = 1
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_ready_for_d2_decision_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["downstream_decision"] = "ready_for_d2"
        with self.assertRaises(ValidationError):
            self.validate(changed)


if __name__ == "__main__":
    unittest.main()
