from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/d1_csi800_static_membership_validation_report.schema.json"
REPORT_PATH = (
    ROOT / "configs/d1/csi800_static_2026_06_membership_validation_report.v1.json"
)
CONTRACT_PATH = ROOT / "configs/d1/csi800_static_2026_06_membership_contract.v1.json"

ROW_LEVEL_FIELDS = (
    "member_rows",
    "members",
    "constituents",
    "rows",
    "tickers",
    "source_symbols",
)


def load(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class D1CSI800StaticMembershipValidationReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load(SCHEMA_PATH)
        cls.report = load(REPORT_PATH)
        cls.contract = load(CONTRACT_PATH)
        cls.validator = Draft202012Validator(cls.schema)

    def validate(self, report: dict[str, object]) -> None:
        self.validator.validate(report)

    def passed_report(self) -> dict[str, object]:
        report = deepcopy(self.report)
        report["validation_status"] = "passed"
        report["member_count_observed"] = 800
        report["downstream_decision"] = "evidence_validated_but_rows_not_materialized"
        report["mapping_readiness_summary"] = {
            "source_symbol_present": True,
            "ticker_present": True,
            "exchange_present": True,
            "security_id_mapping_reference_present": True,
            "row_level_detail_included": False,
        }
        return report

    def test_validation_report_schema_and_config_are_valid(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.validate(self.report)

    def test_report_matches_d1_t04_contract_source_identity(self) -> None:
        universe = self.contract["universe"]
        evidence = self.contract["source_evidence"]
        self.assertEqual(self.report["universe_id"], universe["universe_id"])
        self.assertEqual(self.report["index_code"], universe["index_code"])
        self.assertEqual(
            self.report["source_snapshot_id"],
            evidence["source_snapshot_id"],
        )
        self.assertEqual(
            self.report["raw_evidence_path"], evidence["raw_evidence_path"]
        )
        self.assertEqual(
            self.report["raw_evidence_sha256_expected"],
            evidence["raw_evidence_sha256"],
        )
        self.assertEqual(
            self.report["expected_member_count"],
            universe["expected_member_count"],
        )

    def test_failed_parse_report_keeps_materialization_blocked(self) -> None:
        self.assertEqual(self.report["validation_status"], "failed_parse")
        self.assertEqual(
            self.report["raw_evidence_sha256_actual"],
            self.report["raw_evidence_sha256_expected"],
        )
        self.assertEqual(self.report["member_count_observed"], 0)
        self.assertEqual(
            self.report["downstream_decision"],
            "materialization_remains_blocked",
        )
        self.assertIn("binary Excel", self.report["validation_reason"])

    def test_passed_report_requires_count_and_sha_match(self) -> None:
        report = self.passed_report()
        self.validate(report)
        self.assertEqual(report["member_count_observed"], 800)
        self.assertEqual(
            report["raw_evidence_sha256_actual"],
            report["raw_evidence_sha256_expected"],
        )

    def test_no_artifact_or_materialization_flags_are_false(self) -> None:
        for field in (
            "row_level_data_committed",
            "raw_bytes_committed",
            "duckdb_written",
            "run_manifest_created",
            "dataset_manifest_created",
            "materialization_authorized",
            "member_rows_materialized",
        ):
            with self.subTest(field=field):
                self.assertFalse(self.report[field])

    def test_report_contains_no_row_level_fields(self) -> None:
        self.assertTrue(set(ROW_LEVEL_FIELDS).isdisjoint(self.report))
        self.assertFalse(
            self.report["mapping_readiness_summary"]["row_level_detail_included"]
        )

    def test_static_cohort_and_report_boundary_are_explicit(self) -> None:
        self.assertIn(
            "static research cohort", self.report["static_cohort_bias_warning"]
        )
        self.assertIn(
            "not historical point-in-time CSI 800 membership",
            self.report["static_cohort_bias_warning"],
        )
        self.assertIn(
            "aggregate evidence validation report only", self.report["report_boundary"]
        )
        self.assertIn("not a materialization manifest", self.report["report_boundary"])

    def test_row_level_fields_are_rejected(self) -> None:
        for field in ROW_LEVEL_FIELDS:
            changed = deepcopy(self.report)
            changed[field] = []
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_materialization_or_artifact_flags_true_are_rejected(self) -> None:
        for field in (
            "materialization_authorized",
            "member_rows_materialized",
            "row_level_data_committed",
            "raw_bytes_committed",
            "duckdb_written",
            "run_manifest_created",
            "dataset_manifest_created",
        ):
            changed = deepcopy(self.report)
            changed[field] = True
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_prohibited_sources_are_rejected(self) -> None:
        for source_id in (
            "A_STOCK_DATA_RECON",
            "HITHINK_FINANCIAL_API",
            "BAOSTOCK",
        ):
            changed = deepcopy(self.report)
            changed["source_registry_id"] = source_id
            with self.subTest(source_id=source_id):
                with self.assertRaises(ValidationError):
                    self.validate(changed)

    def test_passed_status_with_wrong_member_count_is_rejected(self) -> None:
        changed = self.passed_report()
        changed["member_count_observed"] = 799
        with self.assertRaises(ValidationError):
            self.validate(changed)

    def test_passed_status_with_wrong_sha_is_rejected(self) -> None:
        changed = self.passed_report()
        changed["raw_evidence_sha256_actual"] = "0" * 64
        with self.assertRaises(ValidationError):
            self.validate(changed)


if __name__ == "__main__":
    unittest.main()
